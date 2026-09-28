"""
run_reporter.py

Provides RunReporter, a thread-safe collector for per-task pass/fail results
across a single pipeline invocation ("run"). Stages executed via
ParallelExecutor (or any other concurrent worker) record results as they
complete, each with its wall-clock duration where known; at the end of the
run, everything collected is flushed to one consolidated JSON summary file.
"""

import json
import threading
import datetime
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

STATUS_SUCCESS = "SUCCESS"
STATUS_FAILED = "FAILED"
STATUS_PARTIAL_FAILURE = "PARTIAL_FAILURE"


def format_duration(seconds: float) -> str:
    """Formats a duration as e.g. '42.0s', '3m 07s' or '2h 05m 09s'."""
    if round(seconds, 1) < 60:
        return f"{seconds:.1f}s"
    minutes, secs = divmod(int(round(seconds)), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes:02d}m {secs:02d}s"
    return f"{minutes}m {secs:02d}s"


class RunReporter:
    """
    Collects pass/fail results for every task across every stage of a single
    pipeline invocation, and writes them out as one consolidated JSON summary.

    `.record()` is safe to call concurrently from multiple threads (e.g. from
    workers inside a `ParallelExecutor`).
    """

    def __init__(self, run_id: str, command: str):
        self.run_id = run_id
        self.command = command
        self.started_at = datetime.datetime.now()
        self._lock = threading.Lock()
        self._stages: Dict[str, List[Dict[str, Any]]] = {}

    def record(
        self,
        stage: str,
        task: str,
        status: str,
        log_file: Optional[Path] = None,
        error: Optional[str] = None,
        duration_s: Optional[float] = None,
    ) -> None:
        """Records the outcome of one task within one stage, and optionally
        how long it took in seconds. Thread-safe."""
        if status not in (STATUS_SUCCESS, STATUS_FAILED):
            raise ValueError(f"Unknown status '{status}', expected SUCCESS or FAILED")
        entry: Dict[str, Any] = {"task": task, "status": status}
        if duration_s is not None:
            entry["duration_s"] = round(duration_s, 3)
        if log_file is not None:
            entry["log_file"] = str(log_file)
        if error is not None:
            entry["error"] = error
        with self._lock:
            self._stages.setdefault(stage, []).append(entry)

    def slowest(self, stage: str, limit: int = 10) -> List[Tuple[str, float]]:
        """The `limit` longest-running tasks of `stage` that recorded a
        duration, as (task, seconds), slowest first."""
        with self._lock:
            timed = [(t["task"], t["duration_s"]) for t in self._stages.get(stage, []) if "duration_s" in t]
        return sorted(timed, key=lambda item: item[1], reverse=True)[:limit]

    def print_slowest(self, stage: str, title: str, limit: int = 10) -> None:
        """Prints `slowest(stage, limit)` under a `--- title ---` header, or
        nothing if no task of `stage` recorded a duration."""
        slowest = self.slowest(stage, limit)
        if not slowest:
            return
        print(f"--- {title} ---")
        for task, seconds in slowest:
            print(f"  {format_duration(seconds):>10}  {task}")

    @staticmethod
    def _stage_status(tasks: List[Dict[str, Any]]) -> str:
        statuses = {t["status"] for t in tasks}
        if statuses == {STATUS_SUCCESS}:
            return STATUS_SUCCESS
        if statuses == {STATUS_FAILED}:
            return STATUS_FAILED
        return STATUS_PARTIAL_FAILURE

    @property
    def overall_status(self) -> str:
        with self._lock:
            stage_task_lists = list(self._stages.values())
        if not stage_task_lists:
            return STATUS_SUCCESS
        stage_statuses = {self._stage_status(tasks) for tasks in stage_task_lists}
        if stage_statuses == {STATUS_SUCCESS}:
            return STATUS_SUCCESS
        if stage_statuses == {STATUS_FAILED}:
            return STATUS_FAILED
        return STATUS_PARTIAL_FAILURE

    def write_summary(self, path: Path) -> Dict[str, Any]:
        """Serializes all recorded results to `path` as JSON and returns the summary dict."""
        with self._lock:
            stages = [
                {"stage": stage, "status": self._stage_status(tasks), "tasks": tasks}
                for stage, tasks in self._stages.items()
            ]
        summary = {
            "run_id": self.run_id,
            "invoked_command": self.command,
            "started_at": self.started_at.isoformat(),
            "finished_at": datetime.datetime.now().isoformat(),
            "overall_status": self.overall_status,
            "stages": stages,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w") as f:
            json.dump(summary, f, indent=2)
        return summary


def run_stages(task: str, stages: List[Tuple[str, Callable[[], Any]]], reporter: RunReporter) -> None:
    """Runs one task's dependent steps in order, recording each into
    `reporter` under its own stage name, with its duration.

    When a step raises, it is recorded FAILED, every later step is recorded
    FAILED as "not attempted (<stage> failed)" without being run, and the
    exception propagates -- so a task run by a ParallelExecutor still counts
    as failed there, and each stage's summary still lists every task.
    """
    for index, (stage, step) in enumerate(stages):
        started = time.monotonic()
        try:
            step()
        except Exception as e:
            reporter.record(
                stage=stage, task=task, status=STATUS_FAILED, error=str(e), duration_s=time.monotonic() - started
            )
            for later_stage, _ in stages[index + 1:]:
                reporter.record(
                    stage=later_stage, task=task, status=STATUS_FAILED, error=f"not attempted ({stage} failed)"
                )
            raise
        reporter.record(stage=stage, task=task, status=STATUS_SUCCESS, duration_s=time.monotonic() - started)
