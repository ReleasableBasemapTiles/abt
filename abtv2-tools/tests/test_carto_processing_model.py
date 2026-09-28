"""Tests for abt.carto_processing_model: CartoExecutionPlan.load,
CartoProcessingModel's plan/disk drift detection (_validate_plan_covers_all_files,
_resolve), the weighted per-group GUC sizing (group_guc_values,
_group_pg_configs), and the per-script timings (ScriptRun). No live Postgres:
the timing tests replace PGConfig's SQL execution with a recorder."""

from pathlib import Path

import pytest
import yaml

from abt.carto_processing_model import (
    MAX_DISSOLVE_SHARDS,
    MAX_PARALLEL_WORKERS_PER_GATHER,
    CartoExecutionPlan,
    CartoGroup,
    CartoProcessingModel,
    group_guc_values,
)
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


# --- weights and per-group GUCs --------------------------------------------

def _old_heuristic(cpu_count, running):
    """The single shared (shards, workers) pair carto computed before weights."""
    budget = max(cpu_count - 4, cpu_count // 2)
    per_group = max(1, budget // max(running, 1))
    return (max(2, per_group), max(2, per_group // 4))


@pytest.mark.parametrize("cpu_count,concurrency", [(48, 8), (16, 2), (32, 5), (64, 10), (8, 3)])
def test_unweighted_groups_get_the_old_shared_values(cpu_count, concurrency):
    values = group_guc_values(weights=[1] * 29, concurrency=concurrency, cpu_count=cpu_count)
    assert values == [_old_heuristic(cpu_count, min(29, concurrency))] * 29


def test_weighted_groups_split_the_budget_of_the_groups_that_start_together():
    # 48 vCPU: budget 44. The first 8 groups start at once with total weight
    # 2 + 2 + 6 = 10, so a weight-2 group gets 8 and a weight-1 group 4.
    weights = [2, 2] + [1] * 27
    values = group_guc_values(weights=weights, concurrency=8, cpu_count=48)
    assert values[0] == values[1] == (8, 2)
    assert set(values[2:]) == {(4, 2)}


def test_a_later_group_gets_the_share_its_weight_had_among_the_first_groups():
    # Only the first two groups start at once (total weight 2); the third,
    # weighted 2, starts later and gets what a weight-2 group would have.
    values = group_guc_values(weights=[1, 1, 2], concurrency=2, cpu_count=24)
    budget = 20
    assert values[0] == (budget // 2, max(2, budget // 2 // 4))
    assert values[2] == (16, 5)  # budget * 2 // 2 = 20 shards, capped at 16


def test_values_are_capped_at_the_scripts_sequential_defaults():
    values = group_guc_values(weights=[1], concurrency=4, cpu_count=128)
    assert values == [(MAX_DISSOLVE_SHARDS, MAX_PARALLEL_WORKERS_PER_GATHER)]


def test_values_never_drop_below_two():
    assert group_guc_values(weights=[1] * 8, concurrency=8, cpu_count=4) == [(2, 2)] * 8


def test_load_parses_weights_and_group_weight_takes_the_heaviest_script(tmp_path):
    path = tmp_path / "execution_plan.yml"
    path.write_text(yaml.safe_dump({
        "groups": [["005a.sql", "005b.sql"], ["003.sql"]],
        "weights": {"005a.sql": 2},
    }))
    plan = CartoExecutionPlan.load(path)
    assert plan.weights == {"005a.sql": 2}
    assert plan.group_weight(["005a.sql", "005b.sql"]) == 2
    assert plan.group_weight(["003.sql"]) == 1


def test_load_treats_an_empty_weights_key_as_no_weights(tmp_path):
    path = tmp_path / "execution_plan.yml"
    path.write_text("groups: [[a.sql]]\nweights:\n")
    assert CartoExecutionPlan.load(path).weights == {}


@pytest.mark.parametrize("bad", [0, -1, "heavy"])
def test_load_rejects_weights_that_are_not_positive_integers(tmp_path, bad):
    path = tmp_path / "execution_plan.yml"
    path.write_text(yaml.safe_dump({"groups": [["a.sql"]], "weights": {"a.sql": bad}}))
    with pytest.raises(ValueError):
        CartoExecutionPlan.load(path)


def test_validate_plan_rejects_weights_for_scripts_outside_the_groups(tmp_path):
    files = [tmp_path / "a.sql", tmp_path / "b.sql"]
    model = make_model(tmp_path, files)
    plan = CartoExecutionPlan(prefix=["a.sql"], groups=[["b.sql"]], weights={"a.sql": 2, "ghost.sql": 3})
    with pytest.raises(ValueError, match=r"weights for scripts that aren't in any group: \['a.sql', 'ghost.sql'\]"):
        model._validate_plan_covers_all_files(plan)


def test_group_pg_configs_pass_each_groups_gucs_as_connection_options(tmp_path, monkeypatch):
    monkeypatch.setattr("abt.carto_processing_model.os.cpu_count", lambda: 48)
    model = make_model(tmp_path, [])
    model.concurrency = 8
    plan = CartoExecutionPlan(groups=[["009.sql"]] + [[f"{i}.sql"] for i in range(9)], weights={"009.sql": 2})
    configs = model._group_pg_configs(plan)
    assert len(configs) == 10
    # 8 groups start together with total weight 9: 44 * 2 // 9 = 9, 44 // 9 = 4.
    assert configs[0].extra_options == "-c abt.dissolve_shards=9 -c abt.parallel_workers_per_gather=2"
    assert configs[1].extra_options == "-c abt.dissolve_shards=4 -c abt.parallel_workers_per_gather=2"
    assert model.pg_config.extra_options == ""


# --- per-script timings ----------------------------------------------------

@pytest.fixture
def ran_scripts(monkeypatch):
    """Replaces PGConfig's SQL execution with a recorder. Scripts whose names
    start with "bad" raise."""
    ran = []

    def run_script(self, sql_script):
        ran.append(sql_script.name)
        if sql_script.name.startswith("bad"):
            raise RuntimeError(f"{sql_script.name}: syntax error")

    monkeypatch.setattr(PGConfig, "runSQLScript", run_script)
    monkeypatch.setattr(PGConfig, "execute_sql", lambda self, sql, description: None)
    return ran


def _plan_model(tmp_path, names, **plan):
    model = make_model(tmp_path, [tmp_path / name for name in names])
    model.execution_plan_path = tmp_path / "execution_plan.yml"
    model.execution_plan_path.write_text(yaml.safe_dump(plan))
    model.concurrency = 2
    return model


def test_group_records_each_script_up_to_and_including_the_one_that_failed(tmp_path, ran_scripts):
    scripts = [tmp_path / "a.sql", tmp_path / "bad.sql", tmp_path / "c.sql"]
    group = CartoGroup(scripts=scripts, pg_config=make_pg_config(tmp_path))
    with pytest.raises(RuntimeError, match="syntax error"):
        group.run()
    assert ran_scripts == ["a.sql", "bad.sql"]
    assert [(r.script, r.status) for r in group.runs] == [("a.sql", "SUCCESS"), ("bad.sql", "FAILED")]
    assert group.runs[1].error == "bad.sql: syntax error"
    assert all(r.seconds >= 0 for r in group.runs)


def test_sequential_mode_times_every_script(tmp_path, ran_scripts):
    model = make_model(tmp_path, [tmp_path / "a.sql", tmp_path / "b.sql"])
    model.process_sql()
    assert [(r.script, r.status) for r in model.script_runs] == [("a.sql", "SUCCESS"), ("b.sql", "SUCCESS")]


def test_plan_mode_lists_prefix_groups_and_suffix_in_plan_order(tmp_path, ran_scripts):
    names = ["p.sql", "a1.sql", "a2.sql", "b.sql", "s.sql"]
    model = _plan_model(tmp_path, names, prefix=["p.sql"], groups=[["a1.sql", "a2.sql"], ["b.sql"]], suffix=["s.sql"])
    model.process_sql()
    assert [r.script for r in model.script_runs] == names
    assert {r.status for r in model.script_runs} == {"SUCCESS"}


def test_plan_mode_keeps_the_timings_of_a_failed_run(tmp_path, ran_scripts):
    names = ["p.sql", "bad.sql", "a2.sql", "b.sql", "s.sql"]
    model = _plan_model(tmp_path, names, prefix=["p.sql"], groups=[["bad.sql", "a2.sql"], ["b.sql"]], suffix=["s.sql"])
    with pytest.raises(RuntimeError, match="1 of 2 carto group"):
        model.process_sql()
    # a2.sql never started (its group had already failed), nor did the suffix.
    assert [(r.script, r.status) for r in model.script_runs] == [
        ("p.sql", "SUCCESS"), ("bad.sql", "FAILED"), ("b.sql", "SUCCESS"),
    ]
