"""Tests for abt.export.mbtiles_metadata: metadata table read/write/delete
helpers and the CRS area-of-use lookup. Uses real (tiny) sqlite files on
disk -- these functions are thin sqlite wrappers, so faking sqlite3 would
just re-test the fakes rather than the actual SQL."""

import json
import sqlite3
from pathlib import Path

import pytest

from abt.export.mbtiles_metadata import (
    crs_area_of_use_bounds,
    delete_mbtiles_metadata,
    is_complete_tileset,
    read_mbtiles_crs,
    resolve_crs_from_files,
    strip_json_tilestats,
    write_mbtiles_metadata,
)


def make_mbtiles(path: Path, rows=()) -> None:
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE metadata (name TEXT, value TEXT)")
    con.execute("CREATE UNIQUE INDEX name ON metadata (name)")
    for name, value in rows:
        con.execute("INSERT INTO metadata (name, value) VALUES (?, ?)", (name, value))
    con.commit()
    con.close()


def add_tiles_table(path: Path, tiles: int = 0) -> None:
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE tiles "
        "(zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_data BLOB)"
    )
    for i in range(tiles):
        con.execute("INSERT INTO tiles VALUES (0, 0, ?, ?)", (i, b"tile"))
    con.commit()
    con.close()


def read_all_metadata(path: Path) -> dict:
    con = sqlite3.connect(path)
    try:
        return dict(con.execute("SELECT name, value FROM metadata").fetchall())
    finally:
        con.close()


def test_crs_area_of_use_bounds_for_wgs84():
    bounds, center = crs_area_of_use_bounds(4326)
    assert bounds == [-180.0, -90.0, 180.0, 90.0]
    assert center == [0.0, 0.0, 2]


def test_write_mbtiles_metadata_inserts_string_values_verbatim(tmp_path):
    path = tmp_path / "test.mbtiles"
    make_mbtiles(path)
    write_mbtiles_metadata(path, {"name": "My Package", "crs": "EPSG:3395"})
    rows = read_all_metadata(path)
    assert rows["name"] == "My Package"
    assert rows["crs"] == "EPSG:3395"


def test_write_mbtiles_metadata_json_encodes_non_string_values(tmp_path):
    path = tmp_path / "test.mbtiles"
    make_mbtiles(path)
    write_mbtiles_metadata(path, {"bounds": [1.0, 2.0, 3.0, 4.0], "count": 42})
    rows = read_all_metadata(path)
    assert rows["bounds"] == json.dumps([1.0, 2.0, 3.0, 4.0])
    assert rows["count"] == json.dumps(42)


def test_write_mbtiles_metadata_replaces_existing_row(tmp_path):
    path = tmp_path / "test.mbtiles"
    make_mbtiles(path, rows=[("name", "Old Name")])
    write_mbtiles_metadata(path, {"name": "New Name"})
    assert read_all_metadata(path)["name"] == "New Name"


def test_delete_mbtiles_metadata_removes_given_keys_only(tmp_path):
    path = tmp_path / "test.mbtiles"
    make_mbtiles(path, rows=[("keep", "1"), ("drop_me", "2"), ("also_drop", "3")])
    delete_mbtiles_metadata(path, ["drop_me", "also_drop"])
    assert read_all_metadata(path) == {"keep": "1"}


def test_delete_mbtiles_metadata_is_a_noop_for_absent_keys(tmp_path):
    path = tmp_path / "test.mbtiles"
    make_mbtiles(path, rows=[("keep", "1")])
    delete_mbtiles_metadata(path, ["never_existed"])
    assert read_all_metadata(path) == {"keep": "1"}


def test_strip_json_tilestats_removes_only_tilestats_key(tmp_path):
    path = tmp_path / "test.mbtiles"
    raw_json = json.dumps({"vector_layers": [{"id": "roads"}], "tilestats": {"layerCount": 1}})
    make_mbtiles(path, rows=[("json", raw_json)])

    strip_json_tilestats(path)

    updated = json.loads(read_all_metadata(path)["json"])
    assert "tilestats" not in updated
    assert updated["vector_layers"] == [{"id": "roads"}]


def test_strip_json_tilestats_is_a_noop_when_absent(tmp_path):
    path = tmp_path / "test.mbtiles"
    raw_json = json.dumps({"vector_layers": []})
    make_mbtiles(path, rows=[("json", raw_json)])

    strip_json_tilestats(path)

    assert json.loads(read_all_metadata(path)["json"]) == {"vector_layers": []}


def test_read_mbtiles_crs_returns_none_for_nonexistent_file(tmp_path):
    assert read_mbtiles_crs(tmp_path / "does_not_exist.mbtiles") is None


def test_read_mbtiles_crs_returns_none_when_row_absent(tmp_path):
    path = tmp_path / "test.mbtiles"
    make_mbtiles(path)
    assert read_mbtiles_crs(path) is None


def test_read_mbtiles_crs_returns_the_stored_value(tmp_path):
    path = tmp_path / "test.mbtiles"
    make_mbtiles(path, rows=[("crs", "EPSG:3395")])
    assert read_mbtiles_crs(path) == "EPSG:3395"


def test_resolve_crs_from_files_returns_none_when_all_default_web_mercator(tmp_path):
    a, b = tmp_path / "a.mbtiles", tmp_path / "b.mbtiles"
    make_mbtiles(a)
    make_mbtiles(b)
    assert resolve_crs_from_files([a, b]) is None


def test_resolve_crs_from_files_returns_the_shared_crs(tmp_path):
    a, b = tmp_path / "a.mbtiles", tmp_path / "b.mbtiles"
    make_mbtiles(a, rows=[("crs", "EPSG:3395")])
    make_mbtiles(b, rows=[("crs", "EPSG:3395")])
    assert resolve_crs_from_files([a, b]) == "EPSG:3395"


def test_resolve_crs_from_files_raises_on_disagreement(tmp_path):
    a, b = tmp_path / "a.mbtiles", tmp_path / "b.mbtiles"
    make_mbtiles(a, rows=[("crs", "EPSG:3395")])
    make_mbtiles(b)  # defaults to Web Mercator (no crs row)
    with pytest.raises(ValueError):
        resolve_crs_from_files([a, b])


# --- is_complete_tileset -------------------------------------------------

def test_is_complete_tileset_is_false_for_a_nonexistent_file(tmp_path):
    assert is_complete_tileset(tmp_path / "never_written.mbtiles") is False


def test_is_complete_tileset_is_false_for_a_metadata_only_stub(tmp_path):
    # The shape tippecanoe leaves behind when it dies before reading input:
    # its database is initialized, but no tiles table was ever created.
    path = tmp_path / "stub.mbtiles"
    make_mbtiles(path, rows=[("name", "roads")])
    assert is_complete_tileset(path) is False


def test_is_complete_tileset_is_false_when_the_tiles_table_is_empty(tmp_path):
    path = tmp_path / "empty.mbtiles"
    make_mbtiles(path)
    add_tiles_table(path, tiles=0)
    assert is_complete_tileset(path) is False


def test_is_complete_tileset_is_true_with_at_least_one_tile(tmp_path):
    path = tmp_path / "good.mbtiles"
    make_mbtiles(path)
    add_tiles_table(path, tiles=1)
    assert is_complete_tileset(path) is True


def test_is_complete_tileset_is_true_for_the_deduplicated_view_schema(tmp_path):
    # The spec also permits `tiles` to be a view over map/images rather
    # than a table of its own.
    path = tmp_path / "dedup.mbtiles"
    make_mbtiles(path)
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE map (zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_id TEXT)")
    con.execute("CREATE TABLE images (tile_data BLOB, tile_id TEXT)")
    con.execute(
        "CREATE VIEW tiles AS SELECT map.zoom_level, map.tile_column, map.tile_row, "
        "images.tile_data FROM map JOIN images ON images.tile_id = map.tile_id"
    )
    con.execute("INSERT INTO map VALUES (0, 0, 0, 'a')")
    con.execute("INSERT INTO images VALUES (?, 'a')", (b"tile",))
    con.commit()
    con.close()
    assert is_complete_tileset(path) is True


def test_is_complete_tileset_is_false_for_a_zero_byte_file(tmp_path):
    path = tmp_path / "truncated.mbtiles"
    path.touch()
    assert is_complete_tileset(path) is False


def test_is_complete_tileset_is_false_for_a_file_that_is_not_a_database(tmp_path):
    path = tmp_path / "garbage.mbtiles"
    path.write_bytes(b"not sqlite, just bytes")
    assert is_complete_tileset(path) is False


def test_is_complete_tileset_does_not_create_or_alter_the_file(tmp_path):
    path = tmp_path / "garbage.mbtiles"
    path.write_bytes(b"not sqlite, just bytes")
    is_complete_tileset(path)
    assert path.read_bytes() == b"not sqlite, just bytes"
    assert not (tmp_path / "absent.mbtiles").exists()
    is_complete_tileset(tmp_path / "absent.mbtiles")
    assert not (tmp_path / "absent.mbtiles").exists()
