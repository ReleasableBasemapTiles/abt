"""
run_reporter.py

Provides RunReporter, a thread-safe collector for per-task pass/fail results
across a single pipeline invocation ("run"). Stages executed via
ParallelExecutor (or any other concurrent worker) record results as they
complete; at the end of the run, everything collected is flushed to one
consolidated JSON summary file.
"""

import json
import threading
import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List

STATUS_SUCCESS = "SUCCESS"
STATUS_FAILED = "FAILED"
STATUS_PARTIAL_FAILURE = "PARTIAL_FAILURE"


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
    ) -> None:
        """Records the outcome of one task within one stage. Thread-safe."""
        if status not in (STATUS_SUCCESS, STATUS_FAILED):
            raise ValueError(f"Unknown status '{status}', expected SUCCESS or FAILED")
        entry: Dict[str, Any] = {"task": task, "status": status}
        if log_file is not None:
            entry["log_file"] = str(log_file)
        if error is not None:
            entry["error"] = error
        with self._lock:
            self._stages.setdefault(stage, []).append(entry)

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
