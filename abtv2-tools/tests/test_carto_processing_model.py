"""Tests for abt.carto_processing_model: CartoExecutionPlan.load and
CartoProcessingModel's plan/disk drift detection (_validate_plan_covers_all_files,
_resolve). No live Postgres -- process_sql/_process_with_plan (which
actually run SQL) are out of scope."""

from pathlib import Path

import pytest
import yaml

from abt.carto_processing_model import CartoExecutionPlan, CartoProcessingModel
from abt.utils.pg_config import PGConfig


def make_pg_config(tmp_path: Path) -> PGConfig:
    return PGConfig(
        host="localhost", port=5432, user="u", password="p", database="d",
        log_path=tmp_path,
    )


def make_model(tmp_path: Path, sql_files) -> CartoProcessingModel:
    return CartoProcessingModel(
        sql_files=sql_files, pg_config=make_pg_config(tmp_path), log_dir=tmp_path,
    )


# --- CartoExecutionPlan.load ----------------------------------------------

def test_load_returns_none_when_file_does_not_exist(tmp_path):
    assert CartoExecutionPlan.load(tmp_path / "execution_plan.yml") is None


def test_load_parses_a_full_plan(tmp_path):
    path = tmp_path / "execution_plan.yml"
    path.write_text(yaml.safe_dump({
        "custom_schemas": ["custom"],
        "extensions": ["dblink"],
        "prefix": ["000_update_aux_geom.sql"],
        "groups": [["003_road.sql"], ["004_railway.sql", "005a_water_polygon.sql"]],
        "suffix": ["099_update_geometry.sql"],
    }))
    plan = CartoExecutionPlan.load(path)
    assert plan.custom_schemas == ["custom"]
    assert plan.extensions == ["dblink"]
    assert plan.prefix == ["000_update_aux_geom.sql"]
    assert plan.groups == [["003_road.sql"], ["004_railway.sql", "005a_water_polygon.sql"]]
    assert plan.suffix == ["099_update_geometry.sql"]


def test_load_defaults_missing_fields_to_empty_lists(tmp_path):
    path = tmp_path / "execution_plan.yml"
    path.write_text(yaml.safe_dump({"prefix": ["a.sql"]}))
    plan = CartoExecutionPlan.load(path)
    assert plan.prefix == ["a.sql"]
    assert plan.groups == []
    assert plan.custom_schemas == []


def test_load_handles_an_empty_file(tmp_path):
    path = tmp_path / "execution_plan.yml"
    path.write_text("")
    plan = CartoExecutionPlan.load(path)
    assert plan.prefix == []
    assert plan.groups == []


# --- CartoProcessingModel._validate_plan_covers_all_files -----------------

def test_validate_plan_covers_all_files_passes_when_in_sync(tmp_path):
    files = [tmp_path / "a.sql", tmp_path / "b.sql"]
    model = make_model(tmp_path, files)
    plan = CartoExecutionPlan(prefix=["a.sql"], groups=[["b.sql"]])
    model._validate_plan_covers_all_files(plan)  # should not raise


def test_validate_plan_covers_all_files_detects_file_missing_from_plan(tmp_path):
    files = [tmp_path / "a.sql", tmp_path / "b.sql"]
    model = make_model(tmp_path, files)
    plan = CartoExecutionPlan(prefix=["a.sql"])  # b.sql on disk, absent from plan
    with pytest.raises(ValueError, match="missing from execution_plan.yml"):
        model._validate_plan_covers_all_files(plan)


def test_validate_plan_covers_all_files_detects_file_missing_from_disk(tmp_path):
    files = [tmp_path / "a.sql"]
    model = make_model(tmp_path, files)
    plan = CartoExecutionPlan(prefix=["a.sql", "ghost.sql"])
    with pytest.raises(ValueError, match="not found on disk"):
        model._validate_plan_covers_all_files(plan)


def test_validate_plan_covers_all_files_detects_duplicates_across_sections(tmp_path):
    files = [tmp_path / "a.sql"]
    model = make_model(tmp_path, files)
    plan = CartoExecutionPlan(prefix=["a.sql"], groups=[["a.sql"]])
    with pytest.raises(ValueError, match="listed more than once"):
        model._validate_plan_covers_all_files(plan)


def test_resolve_maps_filenames_to_paths_in_the_requested_order(tmp_path):
    a, b = tmp_path / "a.sql", tmp_path / "b.sql"
    model = make_model(tmp_path, [a, b])
    assert model._resolve(["b.sql", "a.sql"]) == [b, a]


def test_resolve_raises_for_unknown_filename(tmp_path):
    model = make_model(tmp_path, [tmp_path / "a.sql"])
    with pytest.raises(FileNotFoundError, match="not found among"):
        model._resolve(["ghost.sql"])
