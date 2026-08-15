"""
logger.py

Builds a `logging.Logger` that writes to a per-task log file within a run's
log directory.
"""

from pathlib import Path
import logging
import threading

_handler_lock = threading.Lock()


def get_logger(name: str, directory: Path, process_stage: str, level: str = "INFO") -> logging.Logger:
    """
    Returns a logger that writes to directory/{name}_{process_stage}.log.

    Keyed on `process_stage.name` so different stages touching the
    same-named task (e.g. a layer exported to both FlatGeobuf and MBTiles)
    never share a cached logger/file handle. `directory` is expected to
    already be scoped to a single run (see ProcessingDirectorySchema).
    """
    logger = logging.getLogger(f"{process_stage}.{name}")
    logger.setLevel(level)
    with _handler_lock:
        if not logger.handlers:
            handler = logging.FileHandler(str(directory / f"{name}_{process_stage}.log"), mode="w")
            handler.setFormatter(logging.Formatter("[%(asctime)s | %(levelname)s | %(processName)s %(process)s] %(message)s"))
            handler.setLevel(level)
            logger.addHandler(handler)
    return logger
