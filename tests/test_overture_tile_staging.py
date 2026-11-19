"""rbt-schema/scripts/overture/tile.sh must never leave an unfinished tileset
at building_polygon_<srs>.mbtiles.

init.sh skips the Overture pipeline when that file exists, kills tile.sh
whenever another stage fails, and then passes the file to `bundler -q`. So a
tileset that tippecanoe was still writing, or that tag_crs.py hadn't yet
labelled, would be bundled and shipped by the next run.

Runs the real script with a stand-in tippecanoe on PATH. flock is replaced
only where the host has none (macOS): locking isn't what these tests check.
"""

import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

TILE_SH = Path(__file__).resolve().parents[1] / "rbt-schema" / "scripts" / "overture" / "tile.sh"

# Writes to whatever -o names, as tippecanoe does. STUB_TIPPECANOE says how
# the run ends: "ok" leaves a small mbtiles, "no_metadata" leaves a file
# tag_crs.py rejects, "die" leaves half a file and exits non-zero.
STUB_TIPPECANOE = """#!/usr/bin/env bash
out=""
while (( $# )); do
  if [[ "$1" == "-o" ]]; then out="$2"; shift; fi
  shift
done
case "${STUB_TIPPECANOE:-ok}" in
  die) printf 'half a tileset' > "$out"; exit 1 ;;
  no_metadata) printf 'not an mbtiles' > "$out" ;;
  ok)
    rm -f "$out"
    "$PYTHON" -c 'import sqlite3, sys
con = sqlite3.connect(sys.argv[1])
con.execute("CREATE TABLE metadata (name TEXT, value TEXT)")
con.execute("INSERT INTO metadata VALUES (?, ?)", ("name", "stub"))
con.execute("CREATE TABLE tiles (zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_data BLOB)")
con.executemany("INSERT INTO tiles VALUES (0, ?, 0, ?)", ((i, b"B" * 700) for i in range(50)))
con.commit()' "$out"
    ;;
esac
"""

PREVIOUS_TILESET = b"the last good tileset"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")


def _run_tile_sh(tmp_path: Path, srs: str, outcome: str) -> subprocess.CompletedProcess:
    stub_dir = tmp_path / "bin"
    stub_dir.mkdir(exist_ok=True)
    stubs = {"tippecanoe": STUB_TIPPECANOE}
    if shutil.which("flock") is None:
        stubs["flock"] = "#!/bin/sh\nexit 0\n"
    for name, body in stubs.items():
        (stub_dir / name).write_text(body)
        (stub_dir / name).chmod(0o755)

    data_dir = tmp_path / "data"
    parts_dir = data_dir / ("parts" if srs == "3857" else f"parts_{srs}")
    parts_dir.mkdir(parents=True, exist_ok=True)
    (parts_dir / "part-0.fgb").write_bytes(b"")

    # PYTHON is tile.sh's own knob for the interpreter that runs tag_crs.py;
    # the stand-in tippecanoe borrows it.
    env = dict(
        os.environ,
        PATH=f"{stub_dir}{os.pathsep}{os.environ['PATH']}",
        PYTHON=sys.executable,
        STUB_TIPPECANOE=outcome,
    )
    env.pop("CLEAN_PARTS", None)
    return subprocess.run(
        ["bash", str(TILE_SH), str(data_dir), srs], env=env, capture_output=True, text=True, timeout=60,
    )


def _tileset(tmp_path: Path, srs: str) -> Path:
    return tmp_path / "data" / f"building_polygon_{srs}.mbtiles"


def _metadata(path: Path) -> dict:
    con = sqlite3.connect(path)
    try:
        return dict(con.execute("SELECT name, value FROM metadata").fetchall())
    finally:
        con.close()


def test_a_failed_tippecanoe_leaves_no_tileset_for_a_rerun_to_skip_on(tmp_path):
    result = _run_tile_sh(tmp_path, "3857", "die")

    assert result.returncode != 0
    assert not _tileset(tmp_path, "3857").exists()


def test_a_failed_tippecanoe_leaves_the_previous_tileset_untouched(tmp_path):
    (tmp_path / "data").mkdir()
    _tileset(tmp_path, "3857").write_bytes(PREVIOUS_TILESET)

    result = _run_tile_sh(tmp_path, "3857", "die")

    assert result.returncode != 0
    assert _tileset(tmp_path, "3857").read_bytes() == PREVIOUS_TILESET


def test_a_reprojected_tileset_that_could_not_be_tagged_is_not_published(tmp_path):
    # Until tag_crs.py has run, a reprojected tileset still claims EPSG:3857.
    result = _run_tile_sh(tmp_path, "3395", "no_metadata")

    assert result.returncode != 0
    assert not _tileset(tmp_path, "3395").exists()


def test_a_finished_tileset_is_moved_into_place(tmp_path):
    result = _run_tile_sh(tmp_path, "3857", "ok")

    assert result.returncode == 0, result.stderr
    assert _metadata(_tileset(tmp_path, "3857")) == {"name": "stub"}
    assert list((tmp_path / "data" / ".partial").iterdir()) == []


def test_a_finished_reprojected_tileset_arrives_already_tagged(tmp_path):
    result = _run_tile_sh(tmp_path, "3395", "ok")

    assert result.returncode == 0, result.stderr
    assert _metadata(_tileset(tmp_path, "3395"))["crs"] == "EPSG:3395"


def test_a_journal_a_killed_run_left_does_not_corrupt_the_new_tileset(tmp_path):
    # tippecanoe killed while it wrote building_polygon_<srs>.mbtiles in
    # place, as tile.sh ran it before it staged, leaves <name>-journal, and
    # an operator clearing up may delete only the .mbtiles. SQLite replays a
    # journal into whichever database it next finds beside it, so the
    # finished tileset would be rolled back into on its first open.
    tileset = _tileset(tmp_path, "3857")
    tileset.parent.mkdir()
    journal = tileset.with_name(tileset.name + "-journal")
    con = sqlite3.connect(tileset, isolation_level=None)
    con.execute("PRAGMA synchronous=OFF")  # as tippecanoe sets it
    con.execute("CREATE TABLE tiles (zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_data BLOB)")
    con.executemany("INSERT INTO tiles VALUES (1, ?, 0, ?)", ((i, b"A" * 700) for i in range(300)))
    con.execute("BEGIN IMMEDIATE")
    con.execute("UPDATE tiles SET tile_data = zeroblob(700)")
    on_disk_at_the_kill = journal.read_bytes()
    con.execute("ROLLBACK")
    con.close()
    journal.write_bytes(on_disk_at_the_kill)
    tileset.unlink()

    result = _run_tile_sh(tmp_path, "3857", "ok")

    assert result.returncode == 0, result.stderr
    con = sqlite3.connect(tileset)
    try:
        assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        intact = con.execute("SELECT count(*) FROM tiles WHERE tile_data = ?", (b"B" * 700,)).fetchone()[0]
        assert intact == 50  # the stand-in tippecanoe's tiles, not the killed run's
    finally:
        con.close()


def test_a_rerun_replaces_a_partial_left_by_a_killed_run(tmp_path):
    assert _run_tile_sh(tmp_path, "3857", "die").returncode != 0

    result = _run_tile_sh(tmp_path, "3857", "ok")

    assert result.returncode == 0, result.stderr
    assert _metadata(_tileset(tmp_path, "3857")) == {"name": "stub"}
