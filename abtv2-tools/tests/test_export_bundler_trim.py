"""Tests for abt.export.bundler: the max_zoom pre-trim helper
(_trim_mbtiles) and its cleanup behavior in export_bundled. Uses real
(tiny) sqlite files on disk rather than mocking sqlite3 -- _trim_mbtiles's
whole job is a real ATTACH+SELECT against a real mbtiles file, so faking
sqlite3 would just re-test the fakes."""

import sqlite3
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import abt.export.bundler as bundler_module
from abt.export.bundler import _trim_mbtiles, export_bundled
from abt.export.bundler_model import Bundler


def _make_mbtiles(path: Path, tiles=(), metadata_rows=None) -> None:
    """Writes a minimal mbtiles file. `metadata_rows=None` omits the
    metadata table entirely (as a source lacking one, e.g. a hand-built
    --additional-mbtiles file, would); pass {} for an empty-but-present
    table."""
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE tiles (zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_data BLOB)"
    )
    con.executemany(
        "INSERT INTO tiles VALUES (?, ?, ?, ?)",
        [(z, x, y, b"\x00") for z, x, y in tiles],
    )
    if metadata_rows is not None:
        con.execute("CREATE TABLE metadata (name TEXT, value TEXT)")
        con.execute("CREATE UNIQUE INDEX name ON metadata (name)")
        con.executemany(
            "INSERT INTO metadata (name, value) VALUES (?, ?)",
            list(metadata_rows.items()),
        )
    con.commit()
    con.close()


def _read_tiles(path: Path):
    con = sqlite3.connect(path)
    try:
        return sorted(con.execute("SELECT zoom_level, tile_column, tile_row FROM tiles").fetchall())
    finally:
        con.close()


def _read_metadata(path: Path) -> dict:
    con = sqlite3.connect(path)
    try:
        return dict(con.execute("SELECT name, value FROM metadata").fetchall())
    finally:
        con.close()


# --- _trim_mbtiles --------------------------------------------------------

def test_trim_mbtiles_drops_tiles_above_max_zoom_keeps_at_or_below(tmp_path):
    src = tmp_path / "src.mbtiles"
    _make_mbtiles(src, tiles=[(0, 0, 0), (5, 1, 1), (8, 2, 2), (9, 3, 3)], metadata_rows={})

    dst = tmp_path / "dst.mbtiles"
    _trim_mbtiles(src, dst, max_zoom=8)

    assert _read_tiles(dst) == [(0, 0, 0), (5, 1, 1), (8, 2, 2)]


def test_trim_mbtiles_sets_maxzoom_metadata_and_keeps_other_rows(tmp_path):
    src = tmp_path / "src.mbtiles"
    _make_mbtiles(src, tiles=[(0, 0, 0)], metadata_rows={"minzoom": "0", "maxzoom": "13"})

    dst = tmp_path / "dst.mbtiles"
    _trim_mbtiles(src, dst, max_zoom=8)

    metadata = _read_metadata(dst)
    assert metadata["maxzoom"] == "8"
    assert metadata["minzoom"] == "0"


def test_trim_mbtiles_sets_maxzoom_when_source_has_no_maxzoom_row(tmp_path):
    src = tmp_path / "src.mbtiles"
    _make_mbtiles(src, tiles=[(0, 0, 0)], metadata_rows={"minzoom": "0"})

    dst = tmp_path / "dst.mbtiles"
    _trim_mbtiles(src, dst, max_zoom=8)

    # An UPDATE would silently no-op here since there's no existing row --
    # the trimmed copy's maxzoom must still end up set.
    assert _read_metadata(dst)["maxzoom"] == "8"


def test_trim_mbtiles_succeeds_when_source_has_no_metadata_table(tmp_path):
    src = tmp_path / "src.mbtiles"
    _make_mbtiles(src, tiles=[(0, 0, 0), (9, 1, 1)], metadata_rows=None)

    dst = tmp_path / "dst.mbtiles"
    _trim_mbtiles(src, dst, max_zoom=8)  # would raise "no such table: src.metadata" without the guard

    assert _read_tiles(dst) == [(0, 0, 0)]
    assert _read_metadata(dst) == {"maxzoom": "8"}


def test_trim_mbtiles_handles_source_path_containing_a_quote(tmp_path):
    src_dir = tmp_path / "o'brien"
    src = src_dir / "src.mbtiles"
    _make_mbtiles(src, tiles=[(0, 0, 0), (9, 1, 1)], metadata_rows={})

    dst = tmp_path / "dst.mbtiles"
    # An f-string-interpolated ATTACH ("ATTACH DATABASE '{src}'") would
    # break here on the unescaped quote; the bound parameter must not.
    _trim_mbtiles(src, dst, max_zoom=8)

    assert _read_tiles(dst) == [(0, 0, 0)]


def test_trim_mbtiles_overwrites_a_stale_dst(tmp_path):
    src = tmp_path / "src.mbtiles"
    _make_mbtiles(src, tiles=[(0, 0, 0)], metadata_rows={})

    dst = tmp_path / "dst.mbtiles"
    dst.write_bytes(b"not a real sqlite file")

    _trim_mbtiles(src, dst, max_zoom=8)

    assert _read_tiles(dst) == [(0, 0, 0)]


# --- export_bundled: max_zoom pre-trim integration -----------------------

def make_bundler(tmp_path: Path, **overrides) -> Bundler:
    defaults = dict(bundled_dir=tmp_path / "bundled", tile_layers=[])
    defaults.update(overrides)
    bundler = Bundler(**defaults)
    bundler.bundled_dir.mkdir(parents=True, exist_ok=True)
    return bundler


def test_export_bundled_cleans_up_trimmed_temporaries_when_tile_join_raises(tmp_path, monkeypatch):
    mbtiles_dir = tmp_path / "mbtiles"
    a = mbtiles_dir / "a.mbtiles"
    b = mbtiles_dir / "b.mbtiles"
    _make_mbtiles(a, tiles=[(0, 0, 0)], metadata_rows={})
    _make_mbtiles(b, tiles=[(0, 0, 0)], metadata_rows={})

    bundler = make_bundler(tmp_path, additional_mbtiles=[a, b], max_zoom=5)

    monkeypatch.setattr(
        bundler_module,
        "run_subprocess",
        MagicMock(side_effect=subprocess.CalledProcessError(1, ["tile-join"])),
    )

    with pytest.raises(subprocess.CalledProcessError):
        export_bundled(bundler)

    tmp_dir = bundler.bundled_dir / "_tmp"
    assert list(tmp_dir.glob("*.mbtiles")) == []


def test_export_bundled_trims_same_named_inputs_without_collision(tmp_path, monkeypatch):
    # tile_list can combine per-layer files from different directories with
    # additional_mbtiles -- two inputs sharing a basename must not overwrite
    # each other's trimmed copy in _tmp. run_subprocess is mocked to raise
    # (rather than actually run tile-join) purely so export_bundled stops
    # right after building the command -- its later steps assume a real
    # tile-join output file exists, which is a separate concern from what
    # this test is checking.
    dir_a = tmp_path / "layer_a"
    dir_b = tmp_path / "layer_b"
    a = dir_a / "joined.mbtiles"
    b = dir_b / "joined.mbtiles"
    _make_mbtiles(a, tiles=[(0, 0, 0)], metadata_rows={})
    _make_mbtiles(b, tiles=[(0, 0, 0), (1, 0, 0)], metadata_rows={})

    bundler = make_bundler(tmp_path, additional_mbtiles=[a, b], max_zoom=5)

    mock_run = MagicMock(side_effect=subprocess.CalledProcessError(1, ["tile-join"]))
    monkeypatch.setattr(bundler_module, "run_subprocess", mock_run)

    with pytest.raises(subprocess.CalledProcessError):
        export_bundled(bundler)

    # Filter to args actually inside _tmp -- bundler.package_name also
    # defaults to "joined.mbtiles", so a plain suffix match on the full
    # cmd would also catch the unrelated --output path.
    tmp_dir = bundler.bundled_dir / "_tmp"
    cmd = mock_run.call_args.kwargs["cmd"]
    trimmed_paths = [Path(arg) for arg in cmd if Path(arg).parent == tmp_dir]

    assert len(trimmed_paths) == 2
    assert trimmed_paths[0].name != trimmed_paths[1].name


def test_export_bundled_keeps_mbtiles_extension_for_crs_tagged_inputs(tmp_path, monkeypatch):
    # A CRS-tagged input (e.g. from a --projection-override export) used to
    # trigger an automatic rename to joined.btis; that auto-rename is gone,
    # so package_name/bundled_mbtiles_path must stay joined.mbtiles even
    # when every input carries a non-default crs metadata row. run_subprocess
    # is mocked to raise for the same reason as the tests above -- stop
    # export_bundled right after it decides the package name, before it
    # reaches post-tile-join steps that assume a real output file exists.
    mbtiles_dir = tmp_path / "mbtiles"
    a = mbtiles_dir / "a.mbtiles"
    _make_mbtiles(a, tiles=[(0, 0, 0)], metadata_rows={"crs": "EPSG:3395"})

    bundler = make_bundler(tmp_path, additional_mbtiles=[a])

    monkeypatch.setattr(
        bundler_module,
        "run_subprocess",
        MagicMock(side_effect=subprocess.CalledProcessError(1, ["tile-join"])),
    )

    with pytest.raises(subprocess.CalledProcessError):
        export_bundled(bundler)

    assert bundler.package_name == "joined.mbtiles"
    assert bundler.bundled_mbtiles_path == tmp_path / "bundled" / "joined.mbtiles"
