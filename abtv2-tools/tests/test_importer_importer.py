"""Tests for abt.importer.importer.Importer.import_to_pg's dispatch: an
ImportOGR's optional pre-conversion step runs first, inside the same task,
and a prep-time failure is raised by that layer's task alone.
run_subprocess is replaced with a recorder."""

from pathlib import Path

import pytest

from abt.importer import importer as importer_module
from abt.importer.importer import Importer, ImportImposm, ImportOGR


@pytest.fixture
def recorded_runs(monkeypatch):
    calls = []
    monkeypatch.setattr(importer_module, "run_subprocess", lambda **kwargs: calls.append(kwargs))
    return calls


def test_plain_ogr_import_runs_one_command(tmp_path, recorded_runs):
    Importer(importer=ImportOGR(cmd=["ogr2ogr", "x"]), layer="lsib", log_dir=tmp_path).import_to_pg()
    assert [c["cmd"] for c in recorded_runs] == [["ogr2ogr", "x"]]
    assert recorded_runs[0]["tool_name"] == "ogr2ogr"


def test_pre_conversion_runs_first_after_clearing_its_output(tmp_path, monkeypatch):
    stale = tmp_path / "MirtaLocations.fgb"
    stale.write_bytes(b"from an earlier run")
    seen = []

    def record(**kwargs):
        seen.append((kwargs["cmd"], stale.exists()))

    monkeypatch.setattr(importer_module, "run_subprocess", record)
    Importer(
        importer=ImportOGR(cmd=["import"], pre_cmd=["convert"], pre_output=stale),
        layer="MirtaLocations",
        log_dir=tmp_path,
    ).import_to_pg()
    assert seen == [(["convert"], False), (["import"], False)]


def test_prep_error_fails_only_when_the_task_runs(tmp_path, recorded_runs):
    task = Importer(importer=ImportOGR(prep_error="no layer matched"), layer="lsib", log_dir=tmp_path)
    with pytest.raises(RuntimeError, match="no layer matched"):
        task.import_to_pg()
    assert recorded_runs == []


def test_imposm_import_is_dispatched_as_imposm(tmp_path, recorded_runs):
    imposm = ImportImposm(
        mapping=Path("m.yaml"), pbf=Path("p.pbf"), pg_uri="postgis://u:p@h:5432/d",
        pg_schema="osm", cache_directory=tmp_path,
    )
    Importer(importer=imposm, layer="planet", log_dir=tmp_path).import_to_pg()
    assert recorded_runs[0]["tool_name"] == "imposm"
    assert recorded_runs[0]["cmd"][:2] == ["imposm", "import"]
