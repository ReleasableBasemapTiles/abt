"""Tests for abt.cli_funcs.export_tiles.init_exporter: layers run largest
first, each straight on from FlatGeobuf to MBTiles, and each layer's two
steps are recorded once in the run summary. The connection check, the
table-size query and the tools themselves are replaced, so neither
Postgres, ogr2ogr nor tippecanoe is needed."""

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from abt.cli_funcs import export_tiles
from abt.export import exporter
from abt.utils.pg_config import PGConfig

TABLE_SIZES = {"poi": 20, "road": 500, "water_polygon": 900}


@pytest.fixture
def tools(monkeypatch):
    """Stubs out Postgres and the tools. `tools.runs` lists each (tool,
    layer) run in order; ogr2ogr fails for the layers in `tools.failing`."""
    tools = SimpleNamespace(runs=[], failing=set())

    def run_subprocess(**kwargs):
        tools.runs.append((kwargs["tool_name"], kwargs["layer"]))
        cmd = kwargs["cmd"]
        if kwargs["tool_name"] == "tippecanoe":
            con = sqlite3.connect(cmd[cmd.index("--output") + 1])
            con.execute("CREATE TABLE tiles (zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_data BLOB)")
            con.execute("INSERT INTO tiles VALUES (0, 0, 0, x'00')")
            con.commit()
            con.close()
        elif kwargs["layer"] in tools.failing:
            raise RuntimeError("ogr2ogr exit 1")
        else:
            Path(cmd[-2]).write_bytes(b"fgb")

    monkeypatch.setattr(exporter, "run_subprocess", run_subprocess)
    monkeypatch.setattr(PGConfig, "table_sizes", lambda self, schema: TABLE_SIZES)
    monkeypatch.setattr(export_tiles, "get_pg_config", lambda cli_input, log_dir: PGConfig(
        host="localhost", port=5432, user="u", password="p", database="d", log_path=log_dir,
    ))
    return tools


def run_export(tmp_path):
    """Runs init_exporter on one worker over the TABLE_SIZES layers and
    returns the summary's overall status and {stage: tasks}."""
    schema_dir = tmp_path / "schema"
    for sub in ("import/osm", "import/aux_data", "export", "carto_sql"):
        (schema_dir / sub).mkdir(parents=True)
    for layer_id in TABLE_SIZES:
        (schema_dir / "export" / f"{layer_id}.json").write_text(
            json.dumps({"layer_id": layer_id, "geometry_type": "point"})
        )
    reporter = export_tiles.init_exporter(
        working_dir=tmp_path / "work", schema_dir=schema_dir, num_workers=1, pg_config_type="env", max_zoom=13,
    )
    summary = reporter.write_summary(tmp_path / "summary.json")
    return summary["overall_status"], {stage["stage"]: stage["tasks"] for stage in summary["stages"]}


def test_each_layer_goes_straight_on_to_mbtiles_largest_first(tmp_path, tools):
    status, stages = run_export(tmp_path)
    assert tools.runs == [
        ("ogr2ogr", "water_polygon"), ("tippecanoe", "water_polygon"),
        ("ogr2ogr", "road"), ("tippecanoe", "road"),
        ("ogr2ogr", "poi"), ("tippecanoe", "poi"),
    ]
    assert status == "SUCCESS"
    for stage in ("export_to_fgb", "export_to_mbtiles"):
        assert sorted(task["task"] for task in stages[stage]) == sorted(TABLE_SIZES)


def test_a_failed_fgb_export_skips_only_that_layers_mbtiles(tmp_path, tools):
    tools.failing.add("road")
    status, stages = run_export(tmp_path)
    assert ("tippecanoe", "road") not in tools.runs
    assert ("tippecanoe", "poi") in tools.runs
    assert status == "PARTIAL_FAILURE"
    mbtiles = {task["task"]: task for task in stages["export_to_mbtiles"]}
    assert len(stages["export_to_mbtiles"]) == 3
    assert mbtiles["road"]["error"] == "not attempted (export_to_fgb failed)"
    assert mbtiles["poi"]["status"] == "SUCCESS"
