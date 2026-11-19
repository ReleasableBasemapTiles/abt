"""Tests that export_bundled builds the bundle under bundled/.partial/ and
moves it to its final name only once tile-join and every metadata edit have
succeeded, so a failed or killed bundler run never costs the previous bundle
or leaves a half-labelled one for vundler and the upload to pick up.
tile-join is replaced by a fake that writes to the command's --output."""

import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest

import abt.export.bundler as bundler_module
from abt.export.bundler import export_bundled
from abt.export.bundler_model import Bundler

PREVIOUS_BUNDLE = b"the last good bundle"


def _make_input(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE tiles (zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_data BLOB)")
    con.execute("INSERT INTO tiles VALUES (0, 0, 0, x'00')")
    con.execute("CREATE TABLE metadata (name TEXT, value TEXT)")
    con.execute("CREATE UNIQUE INDEX name ON metadata (name)")
    con.commit()
    con.close()


def _output_of(cmd) -> Path:
    return Path(cmd[cmd.index("--output") + 1])


def _bundle_over_a_previous_one(tmp_path: Path) -> Bundler:
    src = tmp_path / "in" / "a.mbtiles"
    _make_input(src)
    bundle = Bundler(
        bundled_dir=tmp_path / "bundled",
        tile_layers=[],
        additional_mbtiles=[src],
        metadata={"name": "Test"},
    )
    bundle.bundled_dir.mkdir(parents=True, exist_ok=True)
    bundle.bundled_mbtiles_path.write_bytes(PREVIOUS_BUNDLE)
    return bundle


def _tile_join_that_succeeds(bundle: Bundler):
    return lambda **kwargs: shutil.copy(bundle.additional_mbtiles[0], _output_of(kwargs["cmd"]))


def _leave_a_killed_writers_journal(database: Path) -> Path:
    """Leaves `database` as a writer killed mid-transaction would: the file,
    and beside it the hot rollback journal SQLite replays on the next open."""
    journal = database.with_name(database.name + "-journal")
    database.unlink(missing_ok=True)
    con = sqlite3.connect(database, isolation_level=None)
    con.execute("PRAGMA synchronous=OFF")  # as tippecanoe and tile-join set it
    con.execute("CREATE TABLE tiles (zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_data BLOB)")
    con.executemany("INSERT INTO tiles VALUES (1, ?, 0, ?)", ((i, b"A" * 700) for i in range(300)))
    con.execute("BEGIN IMMEDIATE")
    con.execute("UPDATE tiles SET tile_data = zeroblob(700)")
    on_disk_at_the_kill = journal.read_bytes()
    con.execute("ROLLBACK")
    con.close()
    journal.write_bytes(on_disk_at_the_kill)
    return journal


def test_a_failed_tile_join_leaves_the_previous_bundle_untouched(tmp_path, monkeypatch):
    bundle = _bundle_over_a_previous_one(tmp_path)

    def tile_join_that_dies(**kwargs):
        _output_of(kwargs["cmd"]).write_bytes(b"half a bundle")
        raise subprocess.CalledProcessError(1, kwargs["cmd"])

    monkeypatch.setattr(bundler_module, "run_subprocess", tile_join_that_dies)

    with pytest.raises(subprocess.CalledProcessError):
        export_bundled(bundle)

    assert bundle.bundled_mbtiles_path.read_bytes() == PREVIOUS_BUNDLE


def test_a_failed_metadata_edit_leaves_the_previous_bundle_untouched(tmp_path, monkeypatch):
    # tile-join's output isn't a finished bundle until its metadata is
    # rewritten; a failure there must not publish the unlabelled join.
    bundle = _bundle_over_a_previous_one(tmp_path)
    monkeypatch.setattr(bundler_module, "run_subprocess", _tile_join_that_succeeds(bundle))

    def metadata_write_that_dies(path, rows):
        raise sqlite3.OperationalError("database or disk is full")

    monkeypatch.setattr(bundler_module, "write_mbtiles_metadata", metadata_write_that_dies)

    with pytest.raises(sqlite3.OperationalError):
        export_bundled(bundle)

    assert bundle.bundled_mbtiles_path.read_bytes() == PREVIOUS_BUNDLE


def test_a_finished_bundle_replaces_the_previous_one_and_leaves_no_partial(tmp_path, monkeypatch):
    bundle = _bundle_over_a_previous_one(tmp_path)
    monkeypatch.setattr(bundler_module, "run_subprocess", _tile_join_that_succeeds(bundle))

    export_bundled(bundle)

    con = sqlite3.connect(bundle.bundled_mbtiles_path)
    try:
        assert dict(con.execute("SELECT name, value FROM metadata").fetchall())["name"] == "Test"
    finally:
        con.close()
    assert list((bundle.bundled_dir / ".partial").iterdir()) == []


def test_a_journal_a_killed_run_left_does_not_corrupt_the_new_bundle(tmp_path, monkeypatch):
    # A run killed while it wrote joined.mbtiles in place, as the bundler did
    # before it staged, leaves joined.mbtiles-journal. SQLite replays a
    # journal into whichever database it next finds beside it, so one left
    # there would be rolled back into the finished bundle on its first open.
    bundle = _bundle_over_a_previous_one(tmp_path)
    _leave_a_killed_writers_journal(bundle.bundled_mbtiles_path)
    monkeypatch.setattr(bundler_module, "run_subprocess", _tile_join_that_succeeds(bundle))

    export_bundled(bundle)

    con = sqlite3.connect(bundle.bundled_mbtiles_path)
    try:
        assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert con.execute("SELECT count(*) FROM tiles").fetchone()[0] == 1
        assert dict(con.execute("SELECT name, value FROM metadata").fetchall())["name"] == "Test"
    finally:
        con.close()


def test_tile_join_never_writes_to_the_final_path(tmp_path, monkeypatch):
    bundle = _bundle_over_a_previous_one(tmp_path)
    outputs = []

    def tile_join(**kwargs):
        outputs.append(_output_of(kwargs["cmd"]))
        shutil.copy(bundle.additional_mbtiles[0], outputs[-1])

    monkeypatch.setattr(bundler_module, "run_subprocess", tile_join)

    export_bundled(bundle)

    assert outputs == [bundle.bundled_dir / ".partial" / "joined.mbtiles"]


def test_a_partial_left_by_an_interrupted_run_is_cleared_before_tile_join(tmp_path, monkeypatch):
    # tile-join refuses to write over an existing output, so a leftover
    # partial would fail every later run until someone deleted it by hand.
    bundle = _bundle_over_a_previous_one(tmp_path)
    stale = bundle.bundled_dir / ".partial" / "joined.mbtiles"
    stale.parent.mkdir()
    stale.write_bytes(b"half a bundle")
    seen = []

    def tile_join(**kwargs):
        output = _output_of(kwargs["cmd"])
        seen.append((output, output.exists()))
        shutil.copy(bundle.additional_mbtiles[0], output)

    monkeypatch.setattr(bundler_module, "run_subprocess", tile_join)

    export_bundled(bundle)

    assert seen == [(stale, False)]
