"""Tests for the metadata export_bundled writes into the joined file: the BTIS
rows on a reprojected bundle (changelog_url empty, not a placeholder), their
absence on plain Web Mercator output, and the schema's descriptive metadata.
tile-join is replaced by a copy of one input."""

import shutil
import sqlite3
from pathlib import Path

import abt.export.bundler as bundler_module
from abt.export.bundler import export_bundled
from abt.export.bundler_model import Bundler


def _make_input(path: Path, crs=None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE tiles (zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_data BLOB)")
    con.execute("INSERT INTO tiles VALUES (0, 0, 0, x'00')")
    con.execute("CREATE TABLE metadata (name TEXT, value TEXT)")
    con.execute("CREATE UNIQUE INDEX name ON metadata (name)")
    if crs is not None:
        con.execute("INSERT INTO metadata (name, value) VALUES ('crs', ?)", (crs,))
    con.commit()
    con.close()


def _bundle_with_fake_tile_join(tmp_path: Path, monkeypatch, crs=None) -> Bundler:
    src = tmp_path / "in" / "a.mbtiles"
    _make_input(src, crs)
    bundle = Bundler(
        bundled_dir=tmp_path / "bundled",
        tile_layers=[],
        additional_mbtiles=[src],
        metadata={"name": "Test", "version": "2026-10-08.0"},
    )
    bundle.bundled_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        bundler_module, "run_subprocess",
        lambda **kwargs: shutil.copy(src, bundle.bundled_mbtiles_path),
    )
    return bundle


def _read_metadata(path: Path) -> dict:
    con = sqlite3.connect(path)
    try:
        return dict(con.execute("SELECT name, value FROM metadata").fetchall())
    finally:
        con.close()


def test_reprojected_bundle_gets_btis_rows_with_an_empty_changelog_url(tmp_path, monkeypatch):
    bundle = _bundle_with_fake_tile_join(tmp_path, monkeypatch, crs="EPSG:3395")

    export_bundled(bundle)

    metadata = _read_metadata(bundle.bundled_mbtiles_path)
    assert metadata["crs"] == "EPSG:3395"
    assert metadata["btp_schema_version"] == "1.0.0"
    assert metadata["changelog_url"] == ""  # present, but not a placeholder like TBD


def test_web_mercator_bundle_has_no_btis_rows(tmp_path, monkeypatch):
    bundle = _bundle_with_fake_tile_join(tmp_path, monkeypatch)

    export_bundled(bundle)

    metadata = _read_metadata(bundle.bundled_mbtiles_path)
    assert "crs" not in metadata
    assert "btp_schema_version" not in metadata
    assert "changelog_url" not in metadata


def test_bundle_carries_the_version_it_was_given(tmp_path, monkeypatch):
    bundle = _bundle_with_fake_tile_join(tmp_path, monkeypatch)

    export_bundled(bundle)

    assert _read_metadata(bundle.bundled_mbtiles_path)["version"] == "2026-10-08.0"
