"""Tests for abt.export.bundler_model.Bundler: tile_join_cmd, _has_tiles,
and the tile_list discovery/skip-empty logic. Uses real (tiny) sqlite
files on disk rather than mocking sqlite3 -- these are the actual
mechanics _has_tiles checks."""

import re
import sqlite3
from pathlib import Path

from abt.export.bundler_model import Bundler
from abt.export.tile_layer_model import GeometryTypes, TileLayer
from abt.utils.pg_config import PGConfig


def _write_populated_mbtiles(path: Path) -> None:
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE tiles (zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_data BLOB)"
    )
    con.execute("INSERT INTO tiles VALUES (0, 0, 0, X'00')")
    con.commit()
    con.close()


def _write_empty_schema_mbtiles(path: Path) -> None:
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE tiles (zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_data BLOB)"
    )
    con.commit()
    con.close()


def make_bundler(tmp_path: Path, **overrides) -> Bundler:
    defaults = dict(bundled_dir=tmp_path, tile_layers=[])
    defaults.update(overrides)
    return Bundler(**defaults)


def make_pg_config(tmp_path: Path) -> PGConfig:
    return PGConfig(
        host="localhost", port=5432, user="u", password="p", database="d",
        log_path=tmp_path,
    )


def make_tile_layer(tmp_path: Path, layer_id: str, mbtiles_dir: Path) -> TileLayer:
    return TileLayer(
        layer_id=layer_id,
        geometry_type=GeometryTypes.LINESTRING,
        pg_config=make_pg_config(tmp_path),
        flatgeobuf_dir=tmp_path / "fgb",
        mbtiles_dir=mbtiles_dir,
        tmp_dir=tmp_path / "tmp",
        log_dir=tmp_path / "logs",
    )


# --- tile_join_cmd ----------------------------------------------------

def test_tile_join_cmd_uses_default_name_with_todays_date_when_no_metadata(tmp_path):
    cmd = make_bundler(tmp_path).tile_join_cmd
    assert cmd[0] == "tile-join"
    assert "-pk" in cmd
    name = cmd[cmd.index("-n") + 1]
    assert re.fullmatch(r"Army Basemap Tiles \(Build: \d{4}-\d{2}-\d{2}\)", name)
    assert "--output" in cmd
    assert str(tmp_path / "joined.mbtiles") in cmd


def test_tile_join_cmd_uses_metadata_name_when_present(tmp_path):
    bundler = make_bundler(tmp_path, metadata={"name": "Custom Package Name"})
    cmd = bundler.tile_join_cmd
    assert cmd[cmd.index("-n") + 1] == "Custom Package Name"


def test_tile_join_cmd_includes_tile_list_paths(tmp_path):
    mbtiles_dir = tmp_path / "mbtiles"
    mbtiles_dir.mkdir()
    extra = mbtiles_dir / "contours.mbtiles"
    _write_populated_mbtiles(extra)

    bundler = make_bundler(tmp_path, additional_mbtiles=[extra])
    assert str(extra) in bundler.tile_join_cmd


# --- _has_tiles ---------------------------------------------------------

def test_has_tiles_true_for_populated_table(tmp_path):
    path = tmp_path / "populated.mbtiles"
    _write_populated_mbtiles(path)
    assert Bundler._has_tiles(path) is True


def test_has_tiles_false_for_schema_only_no_rows(tmp_path):
    path = tmp_path / "empty_schema.mbtiles"
    _write_empty_schema_mbtiles(path)
    assert Bundler._has_tiles(path) is False


def test_has_tiles_false_when_tiles_table_absent(tmp_path):
    path = tmp_path / "no_tiles_table.mbtiles"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE metadata (name TEXT, value TEXT)")
    con.commit()
    con.close()
    assert Bundler._has_tiles(path) is False


def test_has_tiles_false_for_nonexistent_file(tmp_path):
    assert Bundler._has_tiles(tmp_path / "does_not_exist.mbtiles") is False


def test_has_tiles_true_for_a_view_named_tiles(tmp_path):
    # Real tippecanoe/tile-join output defines `tiles` as a VIEW over
    # map/images, not a plain TABLE -- _has_tiles explicitly checks both.
    path = tmp_path / "view_schema.mbtiles"
    con = sqlite3.connect(path)
    con.executescript(
        "CREATE TABLE map (zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_id TEXT);"
        "CREATE TABLE images (zoom_level INTEGER, tile_data BLOB, tile_id TEXT);"
        "CREATE VIEW tiles AS SELECT map.zoom_level AS zoom_level, map.tile_column AS tile_column, "
        "map.tile_row AS tile_row, images.tile_data AS tile_data FROM map "
        "JOIN images ON images.tile_id = map.tile_id AND images.zoom_level = map.zoom_level;"
    )
    con.execute("INSERT INTO images VALUES (0, X'00', '0')")
    con.execute("INSERT INTO map VALUES (0, 0, 0, '0')")
    con.commit()
    con.close()
    assert Bundler._has_tiles(path) is True


# --- tile_list ------------------------------------------------------------

def test_tile_list_finds_mbtiles_extension(tmp_path):
    mbtiles_dir = tmp_path / "mbtiles"
    mbtiles_dir.mkdir()
    _write_populated_mbtiles(mbtiles_dir / "roads.mbtiles")
    layer = make_tile_layer(tmp_path, "roads", mbtiles_dir)

    bundler = make_bundler(tmp_path, tile_layers=[layer])
    assert bundler.tile_list == [mbtiles_dir / "roads.mbtiles"]


def test_tile_list_falls_back_to_btis_extension(tmp_path):
    mbtiles_dir = tmp_path / "mbtiles"
    mbtiles_dir.mkdir()
    _write_populated_mbtiles(mbtiles_dir / "roads.btis")
    layer = make_tile_layer(tmp_path, "roads", mbtiles_dir)

    bundler = make_bundler(tmp_path, tile_layers=[layer])
    assert bundler.tile_list == [mbtiles_dir / "roads.btis"]


def test_tile_list_skips_empty_layers_and_prints_a_note(tmp_path, capsys):
    mbtiles_dir = tmp_path / "mbtiles"
    mbtiles_dir.mkdir()
    _write_populated_mbtiles(mbtiles_dir / "roads.mbtiles")
    _write_empty_schema_mbtiles(mbtiles_dir / "empty_layer.mbtiles")

    roads = make_tile_layer(tmp_path, "roads", mbtiles_dir)
    empty_layer = make_tile_layer(tmp_path, "empty_layer", mbtiles_dir)

    bundler = make_bundler(tmp_path, tile_layers=[roads, empty_layer])
    assert bundler.tile_list == [mbtiles_dir / "roads.mbtiles"]
    assert "empty_layer.mbtiles" in capsys.readouterr().out


def test_tile_list_ignores_layers_with_no_file_on_disk_at_all(tmp_path):
    mbtiles_dir = tmp_path / "mbtiles"
    mbtiles_dir.mkdir()
    missing_layer = make_tile_layer(tmp_path, "never_exported", mbtiles_dir)

    bundler = make_bundler(tmp_path, tile_layers=[missing_layer])
    assert bundler.tile_list == []
