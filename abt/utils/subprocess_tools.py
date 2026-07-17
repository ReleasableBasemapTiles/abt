"""
subprocess_tools.py

Runs an external command-line tool (ogr2ogr, imposm, tippecanoe) as a
subprocess, streaming its output into a per-task log file in real time.
"""

import subprocess
from pathlib import Path
from typing import List

from .logger import get_logger


def run_subprocess(cmd: List[str], layer: str, process_stage: str, log_dir: Path, tool_name: str) -> None:
    """Runs `cmd`, logging its output under `layer`/`process_stage` in `log_dir`.

    Raises subprocess.CalledProcessError on a non-zero exit code.
    """
    logger = get_logger(name=layer, directory=log_dir, process_stage=process_stage)
    logger.info(f"Running {tool_name} for '{layer}': {' '.join(cmd)}")
    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
        )
        for line in iter(process.stdout.readline, ''):
            logger.info(line.strip())
        process.wait()
        if process.returncode != 0:
            logger.error(f"{tool_name} failed for '{layer}' with exit code {process.returncode}.")
            raise subprocess.CalledProcessError(process.returncode, cmd)
    except Exception as e:
        logger.error(f"An exception occurred while running {tool_name} for '{layer}': {e}", exc_info=True)
        raise
    logger.info(f"{tool_name} for '{layer}' finished with exit code {process.returncode}.")
