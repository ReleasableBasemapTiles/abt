"""setup_ubuntu.sh keeps its run log readable by its owner only: the log holds
everything the script and its tools print. LOG_FILE is the operator's to set,
though, and the script is often run under sudo, so tightening the log must
never change the mode of something that isn't a log: LOG_FILE=/dev/null as
root would take /dev/null away from every other user on the host.

private_log is the function in setup_ubuntu.sh that prepares the log. It is
lifted out of the script and called on its own here, since the script itself
reconfigures the host it runs on.
"""

import shutil
import stat
import subprocess
from pathlib import Path

import pytest

SETUP_SH = Path(__file__).resolve().parents[1] / "setup_ubuntu.sh"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")


def _private_log(path: Path) -> None:
    script = 'umask 022; eval "$(sed -n \'/^private_log() {$/,/^}$/p\' "$1")"; private_log "$2"'
    result = subprocess.run(
        ["bash", "-c", script, "_", str(SETUP_SH), str(path)],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_a_new_log_is_created_readable_by_its_owner_only(tmp_path):
    log = tmp_path / "setup.log"

    _private_log(log)

    assert _mode(log) == 0o600


def test_an_existing_log_is_tightened(tmp_path):
    log = tmp_path / "setup.log"
    log.write_text("an earlier run\n")
    log.chmod(0o644)

    _private_log(log)

    assert _mode(log) == 0o600
    assert log.read_text() == "an earlier run\n"


def test_a_log_reached_through_a_symlink_is_tightened(tmp_path):
    log = tmp_path / "real.log"
    log.write_text("")
    log.chmod(0o644)
    link = tmp_path / "setup.log"
    link.symlink_to(log)

    _private_log(link)

    assert _mode(log) == 0o600


def test_a_path_that_is_not_a_regular_file_keeps_its_mode(tmp_path):
    # Stands in for LOG_FILE=/dev/null: a test can't chmod a device, and must
    # not try. A directory is the other thing a mistyped LOG_FILE can name.
    not_a_log = tmp_path / "not-a-log"
    not_a_log.mkdir()
    not_a_log.chmod(0o755)

    _private_log(not_a_log)

    assert _mode(not_a_log) == 0o755
