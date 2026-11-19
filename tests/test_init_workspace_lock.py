"""init.sh must refuse to start while another run holds the same run directory.

Two runs sharing a run directory download to the same files and write the
same flatgeobuf/, mbtiles/ and bundled/, and no stage notices. init.sh takes
a flock on <run directory>/.init.lock before it starts any work, and a
second run must stop there, naming the first. The lock is in the run
directory ($ABT_RUN_DIR, by default $ABT_WORKSPACE_DIR/run-planet) because
that is where a run writes: the data root need not exist when ABT_RUN_DIR
points elsewhere.

Runs the real script with a stand-in for $PYTHON that records each stage it
is asked to run instead of running it. Where the host has no flock(1)
(macOS), a stand-in makes the same flock(2) call on the inherited descriptor.
"""

import fcntl
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

INIT_SH = Path(__file__).resolve().parents[1] / "init.sh"

# Stands in for `$PYTHON $ABT_TOOLS <stage> ...`: logs the stage, and leaves
# the bundle init.sh looks for after the bundler.
STUB_PYTHON = """#!/usr/bin/env bash
echo "$2" >> "$STUB_LOG"
if [[ "$2" == bundler ]]; then
  while (( $# )); do
    if [[ "$1" == "-w" ]]; then mkdir -p "$2/bundled"; : > "$2/bundled/joined.mbtiles"; fi
    shift
  done
fi
"""

STUB_FLOCK = f"""#!{sys.executable}
import fcntl, sys
operation, descriptor = fcntl.LOCK_EX, None
for arg in sys.argv[1:]:
    if arg == "-n":
        operation |= fcntl.LOCK_NB
    elif arg == "-s":
        operation = (operation & fcntl.LOCK_NB) | fcntl.LOCK_SH
    elif arg != "-x":
        descriptor = int(arg)
try:
    fcntl.flock(descriptor, operation)
except OSError:
    sys.exit(1)
"""

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")


def _run_init(tmp_path: Path, **overrides: str) -> subprocess.CompletedProcess:
    """Runs init.sh with the data root at tmp_path/rbt; `overrides` are
    environment variables set on top, such as ABT_RUN_DIR."""
    stub_dir = tmp_path / "bin"
    stub_dir.mkdir(exist_ok=True)
    stubs = {"python-stub": STUB_PYTHON}
    if shutil.which("flock") is None:
        stubs["flock"] = STUB_FLOCK
    for name, body in stubs.items():
        (stub_dir / name).write_text(body)
        (stub_dir / name).chmod(0o755)
    (tmp_path / "schema" / "export").mkdir(parents=True, exist_ok=True)
    (tmp_path / "abt-tools.py").touch()

    env = dict(
        os.environ,
        PATH=f"{stub_dir}{os.pathsep}{os.environ['PATH']}",
        PYTHON=str(stub_dir / "python-stub"),
        ABT_TOOLS=str(tmp_path / "abt-tools.py"),
        ABT_SCHEMA_DIR=str(tmp_path / "schema"),
        ABT_WORKSPACE_DIR=str(tmp_path / "rbt"),
        STUB_LOG=str(tmp_path / "stages.log"),
    )
    for name in ("ABT_RUN_DIR", "ABT_OVERTURE_DIR", "ABT_JOBS"):
        env.pop(name, None)
    env.update(overrides)
    return subprocess.run(
        ["bash", str(INIT_SH), "--no-upload", "--projections", "3857"],
        env=env, capture_output=True, text=True, timeout=60,
    )


def _stages_run(tmp_path: Path) -> list:
    log = tmp_path / "stages.log"
    return log.read_text().split() if log.exists() else []


ALL_STAGES = ["download", "import", "carto", "export", "bundler"]


def _hold_lock(run_dir: Path):
    """Takes the lock a running init.sh would hold on `run_dir`, as PID 4242."""
    lock_file = run_dir / ".init.lock"
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    lock_file.write_text("4242\n")
    held = lock_file.open("r+")
    fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
    return held


def test_a_second_run_on_the_same_run_directory_stops_before_any_stage(tmp_path):
    with _hold_lock(tmp_path / "rbt" / "run-planet"):
        result = _run_init(tmp_path)

    assert result.returncode != 0
    assert _stages_run(tmp_path) == []
    assert "4242" in result.stderr  # names the run that holds the lock


def test_runs_given_one_run_directory_collide_whatever_their_data_roots(tmp_path):
    shared_run_dir = tmp_path / "volume" / "run"
    with _hold_lock(shared_run_dir):
        result = _run_init(tmp_path, ABT_RUN_DIR=str(shared_run_dir),
                           ABT_WORKSPACE_DIR=str(tmp_path / "another-root"))

    assert result.returncode != 0
    assert _stages_run(tmp_path) == []
    assert "4242" in result.stderr


def test_a_run_with_its_own_run_directory_needs_nothing_at_the_data_root(tmp_path):
    # A host whose data lives on a volume and that never had /rbt: the data
    # root here can't even be created, because its parent is a file.
    (tmp_path / "not-a-directory").write_text("")
    data_root = tmp_path / "not-a-directory" / "rbt"

    result = _run_init(tmp_path, ABT_RUN_DIR=str(tmp_path / "volume" / "run"),
                       ABT_WORKSPACE_DIR=str(data_root))

    assert result.returncode == 0, result.stderr
    assert _stages_run(tmp_path) == ALL_STAGES


def test_a_run_records_its_pid_and_releases_the_lock_when_it_exits(tmp_path):
    result = _run_init(tmp_path)

    assert result.returncode == 0, result.stderr
    assert _stages_run(tmp_path) == ALL_STAGES
    lock_file = tmp_path / "rbt" / "run-planet" / ".init.lock"
    assert lock_file.read_text().strip().isdigit()
    with lock_file.open("r+") as free:
        fcntl.flock(free, fcntl.LOCK_EX | fcntl.LOCK_NB)  # raises if still held


def test_a_run_can_follow_one_that_has_finished(tmp_path):
    assert _run_init(tmp_path).returncode == 0

    result = _run_init(tmp_path)

    assert result.returncode == 0, result.stderr
