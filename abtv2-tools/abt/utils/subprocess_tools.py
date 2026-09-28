"""
subprocess_tools.py

Runs an external command-line tool (ogr2ogr, imposm, tippecanoe) as a
subprocess, streaming its output into a per-task log file in real time.
"""

import re
import subprocess
from pathlib import Path
from typing import List

from .logger import get_logger

# user:password@ in a connection URI (postgresql://, postgis://, ...)
_URI_CREDENTIALS = re.compile(r"(?P<prefix>\b[A-Za-z][A-Za-z0-9+.-]*://[^:/@\s]*):[^@/\s]*@")
# password=... in a libpq key=value connection string, quoted or not
_KEYWORD_PASSWORD = re.compile(r"(?P<prefix>\bpassword\s*=\s*)(?:'(?:[^'\\]|\\.)*'|[^\s']+)", re.IGNORECASE)


def redact_secrets(text: str) -> str:
    """Replaces database passwords in `text` with ***.

    Commands carry the connection string (ogr2ogr's PG:postgresql://...,
    imposm's -connection postgis://...), and both the command log line and
    the CalledProcessError message (which ends up in summary.json) would
    otherwise record the password in plain text.
    """
    text = _URI_CREDENTIALS.sub(r"\g<prefix>:***@", text)
    return _KEYWORD_PASSWORD.sub(r"\g<prefix>***", text)


def run_subprocess(cmd: List[str], layer: str, process_stage: str, log_dir: Path, tool_name: str) -> None:
    """Runs `cmd`, logging its output under `layer`/`process_stage` in `log_dir`.

    Passwords are redacted from everything logged, and from the raised
    error's command (see redact_secrets).

    Raises subprocess.CalledProcessError on a non-zero exit code.
    """
    logger = get_logger(name=layer, directory=log_dir, process_stage=process_stage)
    logger.info(f"Running {tool_name} for '{layer}': {redact_secrets(' '.join(cmd))}")
    try:
        # Popen as a context manager guarantees stdout/stdin/stderr get
        # closed and the child is waited on even if something in the read
        # loop below raises something other than the CalledProcessError
        # handled explicitly here.
        with subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            # One undecodable byte in a multi-hour tool's output (a
            # non-UTF-8 name in an error message, say) must not kill the
            # read loop and, with it, the run.
            encoding="utf-8",
            errors="replace",
        ) as process:
            for line in iter(process.stdout.readline, ''):
                logger.info(redact_secrets(line.strip()))
            process.wait()
            if process.returncode != 0:
                logger.error(f"{tool_name} failed for '{layer}' with exit code {process.returncode}.")
                raise subprocess.CalledProcessError(process.returncode, [redact_secrets(c) for c in cmd])
    except Exception as e:
        logger.error(f"An exception occurred while running {tool_name} for '{layer}': {e}", exc_info=True)
        raise
    logger.info(f"{tool_name} for '{layer}' finished with exit code {process.returncode}.")
