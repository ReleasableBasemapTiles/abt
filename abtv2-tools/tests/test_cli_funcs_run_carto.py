"""Tests for abt.cli_funcs.run_carto.init_carto_runer's run summary: the
carto stage's outcome, plus a carto_scripts stage with each script's
duration, written even when carto fails. The connection check and
CartoProcessingModel.process_sql are replaced, so no Postgres is needed."""

import json

import pytest

from abt.carto_processing_model import CartoProcessingModel, ScriptRun
from abt.cli_funcs import run_carto as run_carto_module
from abt.cli_funcs.run_carto import init_carto_runer
from abt.utils.pg_config import PGConfig


def run_carto(tmp_path, monkeypatch, runs, error=None):
    """Runs init_carto_runer with a process_sql that reports `runs` and then
    raises RuntimeError(error) if one is given."""
    def process_sql(self):
        self.script_runs.extend(runs)
        if error:
            raise RuntimeError(error)

    monkeypatch.setattr(CartoProcessingModel, "process_sql", process_sql)
    monkeypatch.setattr(run_carto_module, "get_pg_config", lambda cli_input, log_dir: PGConfig(
        host="localhost", port=5432, user="u", password="p", database="d", log_path=log_dir,
    ))
    schema_dir = tmp_path / "schema"
    for sub in ("import/osm", "import/aux_data", "export", "carto_sql"):
        (schema_dir / sub).mkdir(parents=True)
    (schema_dir / "carto_sql" / "000_update_aux_geom.sql").write_text("SELECT 1;")
    init_carto_runer(
        working_dir=tmp_path / "work", schema_dir=schema_dir, pg_config_type="env",
    )


def read_stages(tmp_path):
    (summary_file,) = (tmp_path / "work").glob("**/summary.json")
    return {stage["stage"]: stage for stage in json.loads(summary_file.read_text())["stages"]}


def test_summary_records_each_scripts_duration(tmp_path, monkeypatch, capsys):
    run_carto(tmp_path, monkeypatch, [
        ScriptRun(script="000_update_aux_geom.sql", status="SUCCESS", seconds=12.5),
        ScriptRun(script="005a_water_polygon.sql", status="SUCCESS", seconds=4000.0),
    ])
    stages = read_stages(tmp_path)
    (carto_task,) = stages["carto"]["tasks"]
    assert carto_task["status"] == "SUCCESS"
    assert carto_task["duration_s"] >= 0
    assert stages["carto_scripts"]["tasks"] == [
        {"task": "000_update_aux_geom.sql", "status": "SUCCESS", "duration_s": 12.5},
        {"task": "005a_water_polygon.sql", "status": "SUCCESS", "duration_s": 4000.0},
    ]
    out = capsys.readouterr().out
    assert "--- Slowest carto scripts ---" in out
    assert out.index("005a_water_polygon.sql") < out.index("000_update_aux_geom.sql")


def test_a_failed_run_still_records_the_scripts_that_ran(tmp_path, monkeypatch):
    runs = [
        ScriptRun(script="003_road.sql", status="SUCCESS", seconds=60.0),
        ScriptRun(script="026_places.sql", status="FAILED", seconds=2.0, error="syntax error"),
    ]
    with pytest.raises(RuntimeError, match="1 of 29"):
        run_carto(tmp_path, monkeypatch, runs, error="1 of 29 carto group(s) failed")
    stages = read_stages(tmp_path)
    assert stages["carto"]["status"] == "FAILED"
    assert stages["carto"]["tasks"][0]["error"] == "1 of 29 carto group(s) failed"
    assert stages["carto_scripts"]["tasks"][1] == {
        "task": "026_places.sql", "status": "FAILED", "duration_s": 2.0, "error": "syntax error",
    }
