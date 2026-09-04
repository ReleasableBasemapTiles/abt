"""Tests for abt.export.exporter's skip logic -- specifically that
export_to_mbtiles resumes a tileset an earlier run left unfinished instead
of mistaking it for completed work.

run_subprocess is replaced with a recorder rather than actually invoking
ogr2ogr/tippecanoe: what's under test is the decision to run at all, and
the real tools' own behaviour is covered in test_utils_subprocess_tools.py.
Layers stay on the default projection so the --projection-override metadata
rewrite (which needs a real tippecanoe output to edit) stays out of the
picture.
"""

import sqlite3
from pathlib import Path

import pytest

from abt.export import exporter
from abt.export.exporter import export_to_fgb, export_to_mbtiles
from abt.export.tile_layer_model import (
    GeometryTypes,
    OGRExportOptions,
    TileLayer,
    TippecanoeOptions,
)
from abt.utils.pg_config import PGConfig


def make_layer(tmp_path: Path, **overrides) -> TileLayer:
    defaults = dict(
        geometry_type=GeometryTypes.LINESTRING,
        pg_config=PGConfig(
            host="localhost", port=5432, user="u", password="p", database="d",
            log_path=tmp_path,
        ),
        flatgeobuf_dir=tmp_path / "flatgeobuf",
        mbtiles_dir=tmp_path / "mbtiles",
        tmp_dir=tmp_path / "tmp",
        log_dir=tmp_path / "logs",
        tippecanoe_options=TippecanoeOptions(minimum_zoom=8, maximum_zoom=13, max_detail_const=13),
        ogr_export_options=OGRExportOptions(),
    )
    defaults.update(overrides)
    layer = TileLayer(**defaults)
    # run_subprocess and get_logger both expect their directories to exist
    # already -- every real call site pre-creates them via
    # ProcessingDirectorySchema.init_working_directories.
    for directory in (layer.flatgeobuf_dir, layer.mbtiles_dir, layer.tmp_dir, layer.log_dir):
        directory.mkdir(parents=True, exist_ok=True)
    return layer


@pytest.fixture
def layer(tmp_path, request) -> TileLayer:
    """A TileLayer whose layer_id is unique to the requesting test.

    get_logger caches its FileHandler on a module-level logging.Logger
    keyed by stage and layer name, so tests sharing a layer_id would all
    write into whichever tmp_path happened to run first.
    """
    return make_layer(tmp_path, layer_id=request.node.name)


@pytest.fixture
def recorded_runs(monkeypatch):
    """Replaces run_subprocess with a recorder, returning the call list."""
    calls = []
    monkeypatch.setattr(exporter, "run_subprocess", lambda **kwargs: calls.append(kwargs))
    return calls


def write_tileset(path: Path, tiles: int) -> None:
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE metadata (name TEXT, value TEXT)")
    con.execute(
        "CREATE TABLE tiles "
        "(zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_data BLOB)"
    )
    for i in range(tiles):
        con.execute("INSERT INTO tiles VALUES (8, 0, ?, ?)", (i, b"tile"))
    con.commit()
    con.close()


def test_export_to_mbtiles_runs_when_no_output_exists(layer, recorded_runs):
    export_to_mbtiles(layer)
    assert len(recorded_runs) == 1
    assert recorded_runs[0]["tool_name"] == "tippecanoe"


def test_export_to_mbtiles_skips_a_finished_tileset(layer, recorded_runs):
    write_tileset(layer.mbtiles_export_filename, tiles=1)
    export_to_mbtiles(layer)
    assert recorded_runs == []


def test_export_to_mbtiles_reruns_on_a_tile_less_stub(layer, recorded_runs):
    write_tileset(layer.mbtiles_export_filename, tiles=0)
    export_to_mbtiles(layer)
    assert len(recorded_runs) == 1


def test_export_to_mbtiles_reruns_on_a_zero_byte_output(layer, recorded_runs):
    layer.mbtiles_export_filename.touch()
    export_to_mbtiles(layer)
    assert len(recorded_runs) == 1


def test_export_to_mbtiles_removes_the_stub_before_rerunning(layer, monkeypatch):
    # tippecanoe exits EXIT_EXISTS rather than overwriting, so retrying is
    # only useful if the stub is gone by the time it runs.
    write_tileset(layer.mbtiles_export_filename, tiles=0)
    existed_at_run_time = []
    monkeypatch.setattr(
        exporter,
        "run_subprocess",
        lambda **kwargs: existed_at_run_time.append(layer.mbtiles_export_filename.exists()),
    )
    export_to_mbtiles(layer)
    assert existed_at_run_time == [False]


def test_export_to_mbtiles_logs_that_it_discarded_a_stub(layer, recorded_runs):
    write_tileset(layer.mbtiles_export_filename, tiles=0)
    export_to_mbtiles(layer)
    log_text = (layer.log_dir / f"{layer.layer_id}_export_to_mbtiles.log").read_text()
    assert f"Discarding incomplete {layer.mbtiles_export_filename.name}" in log_text


def test_export_to_mbtiles_says_nothing_about_stubs_on_a_first_run(layer, recorded_runs):
    export_to_mbtiles(layer)
    log_file = layer.log_dir / f"{layer.layer_id}_export_to_mbtiles.log"
    assert not log_file.exists()


def test_export_to_fgb_still_skips_on_existence_alone(layer, recorded_runs):
    # ogr2ogr streams its FlatGeobuf output rather than opening a database
    # up front, so existence remains the right check there; this pins that
    # the mbtiles change didn't leak into it.
    layer.ogr_export_filename.touch()
    export_to_fgb(layer)
    assert recorded_runs == []
