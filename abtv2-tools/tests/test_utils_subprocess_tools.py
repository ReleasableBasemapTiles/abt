"""Tests for abt.utils.subprocess_tools.run_subprocess. Uses the real
`sys.executable` as the subprocess rather than mocking subprocess.Popen,
since the function's entire job is streaming a real process's output into
a log file -- a real (tiny, fast) child process exercises that faithfully
without pinning to Popen's internal call shape.

Every real call site (abt/vundler.py, export/exporter.py, export/bundler.py,
importer/importer.py, download/downloader.py) pre-creates `log_dir` before
calling run_subprocess -- neither it nor abt.utils.logger.get_logger
create it themselves (see docs/code-review-findings.md), so these tests
do the same rather than exercising an unrealistic call pattern.
"""

import subprocess
import sys

import pytest

from abt.utils.subprocess_tools import redact_secrets, run_subprocess


def test_run_subprocess_success_streams_output_to_log_file(tmp_path):
    log_dir = tmp_path / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    run_subprocess(
        cmd=[sys.executable, "-c", "print('hello from subprocess')"],
        layer="successlayer",
        process_stage="successstage",
        log_dir=log_dir,
        tool_name="python",
    )

    log_file = log_dir / "successlayer_successstage.log"
    assert log_file.exists()
    content = log_file.read_text()
    assert "hello from subprocess" in content
    assert "finished with exit code 0" in content


def test_run_subprocess_raises_on_nonzero_exit(tmp_path):
    log_dir = tmp_path / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    with pytest.raises(subprocess.CalledProcessError) as exc_info:
        run_subprocess(
            cmd=[sys.executable, "-c", "import sys; sys.exit(7)"],
            layer="faillayer",
            process_stage="failstage",
            log_dir=log_dir,
            tool_name="python",
        )
    assert exc_info.value.returncode == 7

    log_file = log_dir / "faillayer_failstage.log"
    assert log_file.exists()
    assert "failed" in log_file.read_text().lower()


def test_run_subprocess_raises_for_a_command_that_does_not_exist(tmp_path):
    log_dir = tmp_path / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    with pytest.raises(Exception):
        run_subprocess(
            cmd=["definitely-not-a-real-executable-abt-test"],
            layer="missinglayer",
            process_stage="missingstage",
            log_dir=log_dir,
            tool_name="ghost",
        )


# --- redaction and decoding ----------------------------------------------------

@pytest.mark.parametrize("text, expected", [
    ("PG:postgresql://rbt:s3cr%40t@localhost:5432/rbt",
     "PG:postgresql://rbt:***@localhost:5432/rbt"),
    ("-connection postgis://rbt:hunter2@db.internal:5432/rbt",
     "-connection postgis://rbt:***@db.internal:5432/rbt"),
    ("host=h port=5432 user='u' password='it\\'s' dbname='d'",
     "host=h port=5432 user='u' password=*** dbname='d'"),
    ("PASSWORD=plain next", "PASSWORD=*** next"),
    # Nothing that isn't a credential is touched.
    ("https://planet.openstreetmap.org/pbf/planet-latest.osm.pbf",
     "https://planet.openstreetmap.org/pbf/planet-latest.osm.pbf"),
    ("https://example.com:8443/a@b", "https://example.com:8443/a@b"),
])
def test_redact_secrets(text, expected):
    assert redact_secrets(text) == expected


def test_run_subprocess_keeps_passwords_out_of_the_log_and_the_error(tmp_path):
    log_dir = tmp_path / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "-c", "import sys; print(sys.argv[1]); sys.exit(3)",
           "PG:postgresql://rbt:hunter2@localhost:5432/rbt"]
    with pytest.raises(subprocess.CalledProcessError) as exc_info:
        run_subprocess(cmd=cmd, layer="redactlayer", process_stage="redactstage",
                       log_dir=log_dir, tool_name="python")
    assert "hunter2" not in str(exc_info.value)
    log_text = (log_dir / "redactlayer_redactstage.log").read_text()
    assert "hunter2" not in log_text
    assert "postgresql://rbt:***@localhost" in log_text


def test_run_subprocess_survives_non_utf8_output(tmp_path):
    # Regression test: text=True without errors= made one undecodable byte
    # raise UnicodeDecodeError and abort the whole run.
    log_dir = tmp_path / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    run_subprocess(
        cmd=[sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'caf\\xe9 ok\\n')"],
        layer="bytelayer", process_stage="bytestage", log_dir=log_dir, tool_name="python",
    )
    content = (log_dir / "bytelayer_bytestage.log").read_text()
    assert "caf\ufffd ok" in content
    assert "finished with exit code 0" in content
