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
