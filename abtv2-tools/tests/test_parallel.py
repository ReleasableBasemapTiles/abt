"""Tests for abt.parallel: run_action_on_instance and ParallelExecutor.
Uses plain in-memory objects and callables -- no subprocess/network/DB, so
no mocking framework is needed."""

import logging

from abt.parallel import ParallelExecutor, run_action_on_instance
from abt.utils.run_reporter import RunReporter, STATUS_PARTIAL_FAILURE


class _Obj:
    def __init__(self, name):
        self.name = name


def _raise_boom(_obj):
    raise ValueError("boom")


def _make_executor(tmp_path, **kwargs):
    # ParallelExecutor.logger (like run_subprocess) never creates its own
    # log_dir -- every real caller pre-creates it (see
    # docs/code-review-findings.md) -- so tests do the same.
    log_dir = tmp_path / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return ParallelExecutor(log_dir=log_dir, **kwargs)


def test_run_action_on_instance_success():
    logger = logging.getLogger("test_run_action_on_instance_success")
    name, status, data = run_action_on_instance(_Obj("x"), lambda o: o.name.upper(), logger)
    assert name == "x"
    assert status == "SUCCESS"
    assert data == "X"


def test_run_action_on_instance_captures_exception_as_failure():
    logger = logging.getLogger("test_run_action_on_instance_failure")
    name, status, data = run_action_on_instance(_Obj("y"), _raise_boom, logger)
    assert name == "y"
    assert status == "FAILURE"
    assert "boom" in data


def test_run_action_on_instance_falls_back_to_str_when_no_name_attribute():
    logger = logging.getLogger("test_run_action_on_instance_no_name")
    name, status, data = run_action_on_instance("plain-string", lambda o: o.upper(), logger)
    assert name == "plain-string"
    assert status == "SUCCESS"
    assert data == "PLAIN-STRING"


def test_parallel_executor_aggregates_success_and_failure(tmp_path):
    executor = _make_executor(tmp_path, instance="unittest", max_workers=2)

    def action(obj):
        if obj.name == "bad":
            raise RuntimeError("boom")
        return f"ok-{obj.name}"

    objects = [_Obj("good1"), _Obj("bad"), _Obj("good2")]
    results = executor.run(objects, action)

    by_name = {name: (status, data) for name, status, data in results}
    assert by_name["good1"] == ("SUCCESS", "ok-good1")
    assert by_name["good2"] == ("SUCCESS", "ok-good2")
    assert by_name["bad"][0] == "FAILURE"
    assert "boom" in by_name["bad"][1]


def test_parallel_executor_records_into_reporter(tmp_path):
    executor = _make_executor(tmp_path, instance="unittest2", max_workers=2)
    reporter = RunReporter(run_id="r1", command="test")

    def action(obj):
        if obj.name == "bad":
            raise RuntimeError("boom")
        return "ok"

    executor.run([_Obj("good"), _Obj("bad")], action, reporter=reporter, stage="mystage")

    assert reporter.overall_status == STATUS_PARTIAL_FAILURE


def test_parallel_executor_returns_empty_list_for_no_objects(tmp_path):
    executor = _make_executor(tmp_path, instance="unittest3")
    assert executor.run([], lambda o: o) == []
