"""Tests for abt.utils.run_reporter.RunReporter -- pure in-memory
set-logic, durations and JSON serialization, no I/O beyond the final
write_summary call (which uses tmp_path) -- and format_duration."""

import json

import pytest

from abt.utils.run_reporter import (
    RunReporter,
    STATUS_FAILED,
    STATUS_PARTIAL_FAILURE,
    STATUS_SUCCESS,
    format_duration,
)


def test_stage_status_all_success():
    tasks = [{"task": "a", "status": STATUS_SUCCESS}, {"task": "b", "status": STATUS_SUCCESS}]
    assert RunReporter._stage_status(tasks) == STATUS_SUCCESS


def test_stage_status_all_failed():
    tasks = [{"task": "a", "status": STATUS_FAILED}, {"task": "b", "status": STATUS_FAILED}]
    assert RunReporter._stage_status(tasks) == STATUS_FAILED


def test_stage_status_mixed_is_partial_failure():
    tasks = [{"task": "a", "status": STATUS_SUCCESS}, {"task": "b", "status": STATUS_FAILED}]
    assert RunReporter._stage_status(tasks) == STATUS_PARTIAL_FAILURE


def test_overall_status_with_no_recorded_stages_is_success():
    reporter = RunReporter(run_id="r1", command="cmd")
    assert reporter.overall_status == STATUS_SUCCESS


def test_overall_status_all_stages_succeed():
    reporter = RunReporter(run_id="r1", command="cmd")
    reporter.record(stage="s1", task="t1", status=STATUS_SUCCESS)
    reporter.record(stage="s2", task="t2", status=STATUS_SUCCESS)
    assert reporter.overall_status == STATUS_SUCCESS


def test_overall_status_all_stages_fail():
    reporter = RunReporter(run_id="r1", command="cmd")
    reporter.record(stage="s1", task="t1", status=STATUS_FAILED)
    reporter.record(stage="s2", task="t2", status=STATUS_FAILED)
    assert reporter.overall_status == STATUS_FAILED


def test_overall_status_mixed_stage_outcomes_is_partial_failure():
    reporter = RunReporter(run_id="r1", command="cmd")
    reporter.record(stage="s1", task="t1", status=STATUS_SUCCESS)
    reporter.record(stage="s2", task="t2", status=STATUS_FAILED)
    assert reporter.overall_status == STATUS_PARTIAL_FAILURE


def test_overall_status_partial_failure_within_one_stage_propagates():
    reporter = RunReporter(run_id="r1", command="cmd")
    reporter.record(stage="s1", task="t1", status=STATUS_SUCCESS)
    reporter.record(stage="s1", task="t2", status=STATUS_FAILED)
    assert reporter.overall_status == STATUS_PARTIAL_FAILURE


def test_record_rejects_unknown_status():
    reporter = RunReporter(run_id="r1", command="cmd")
    with pytest.raises(ValueError):
        reporter.record(stage="s1", task="t1", status="NOT_A_REAL_STATUS")


def test_write_summary_serializes_expected_shape(tmp_path):
    reporter = RunReporter(run_id="run-123", command="abt export")
    reporter.record(stage="export", task="roads", status=STATUS_SUCCESS)
    reporter.record(
        stage="export", task="rivers", status=STATUS_FAILED,
        log_file="/logs/rivers.log", error="tippecanoe exit 1",
    )

    out_path = tmp_path / "summary.json"
    summary = reporter.write_summary(out_path)

    assert summary["run_id"] == "run-123"
    assert summary["invoked_command"] == "abt export"
    assert summary["overall_status"] == STATUS_PARTIAL_FAILURE
    assert len(summary["stages"]) == 1
    stage = summary["stages"][0]
    assert stage["stage"] == "export"
    assert stage["status"] == STATUS_PARTIAL_FAILURE
    tasks_by_name = {t["task"]: t for t in stage["tasks"]}
    assert tasks_by_name["roads"]["status"] == STATUS_SUCCESS
    assert "error" not in tasks_by_name["roads"]
    assert tasks_by_name["rivers"]["error"] == "tippecanoe exit 1"
    assert tasks_by_name["rivers"]["log_file"] == "/logs/rivers.log"

    assert out_path.exists()
    on_disk = json.loads(out_path.read_text())
    assert on_disk == summary


def test_write_summary_creates_parent_directories(tmp_path):
    reporter = RunReporter(run_id="r1", command="cmd")
    out_path = tmp_path / "nested" / "dir" / "summary.json"
    reporter.write_summary(out_path)
    assert out_path.exists()


def test_record_stores_a_rounded_duration_only_when_given(tmp_path):
    reporter = RunReporter(run_id="r1", command="cmd")
    reporter.record(stage="s1", task="timed", status=STATUS_SUCCESS, duration_s=1.23456)
    reporter.record(stage="s1", task="untimed", status=STATUS_SUCCESS)
    summary = reporter.write_summary(tmp_path / "summary.json")
    tasks = {t["task"]: t for t in summary["stages"][0]["tasks"]}
    assert tasks["timed"]["duration_s"] == 1.235
    assert "duration_s" not in tasks["untimed"]


def test_slowest_sorts_one_stages_timed_tasks_and_skips_untimed_ones():
    reporter = RunReporter(run_id="r1", command="cmd")
    for task, seconds in [("a", 3.0), ("b", 30.0), ("c", None), ("d", 12.5)]:
        reporter.record(stage="s1", task=task, status=STATUS_SUCCESS, duration_s=seconds)
    reporter.record(stage="s2", task="e", status=STATUS_SUCCESS, duration_s=99.0)
    assert reporter.slowest("s1") == [("b", 30.0), ("d", 12.5), ("a", 3.0)]
    assert reporter.slowest("s1", limit=2) == [("b", 30.0), ("d", 12.5)]
    assert reporter.slowest("not-a-stage") == []


def test_print_slowest_lists_tasks_slowest_first_under_the_title(capsys):
    reporter = RunReporter(run_id="r1", command="cmd")
    reporter.record(stage="s1", task="026_places.sql", status=STATUS_FAILED, duration_s=42.0)
    reporter.record(stage="s1", task="005a_water_polygon.sql", status=STATUS_SUCCESS, duration_s=4000.0)
    reporter.print_slowest("s1", title="Slowest carto scripts")
    assert capsys.readouterr().out.splitlines() == [
        "--- Slowest carto scripts ---",
        "  1h 06m 40s  005a_water_polygon.sql",
        "       42.0s  026_places.sql",
    ]


def test_print_slowest_prints_nothing_without_durations(capsys):
    reporter = RunReporter(run_id="r1", command="cmd")
    reporter.record(stage="s1", task="a", status=STATUS_SUCCESS)
    reporter.print_slowest("s1", title="Slowest")
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("seconds,expected", [
    (0, "0.0s"),
    (42.04, "42.0s"),
    (59.96, "1m 00s"),
    (187, "3m 07s"),
    (7509, "2h 05m 09s"),
])
def test_format_duration(seconds, expected):
    assert format_duration(seconds) == expected
