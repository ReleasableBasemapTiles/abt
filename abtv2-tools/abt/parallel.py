"""
parallel.py

Provides a reusable framework for running an action against multiple objects
in parallel using a thread pool. This is particularly useful for I/O-bound
operations like downloading files or running external subprocesses, where
threads can efficiently wait for operations to complete without blocking the
entire program.
"""

import concurrent.futures
import logging
from pathlib import Path
from typing import Any, Callable, List, Optional

from pydantic import BaseModel, ConfigDict

from .utils.logger import get_logger
from .utils.run_reporter import RunReporter


def run_action_on_instance(instance: Any, action: Callable[[Any], Any], logger: logging.Logger) -> tuple:
    """
    A worker function designed to be run in a separate thread.

    It safely calls `action(instance)`, logs the progress, and captures any
    exception that occurs.

    Args:
        instance: The object instance to pass to `action`.
        action: A callable taking one argument (the instance) that performs the task.
        logger: The logger object to use for recording task progress and errors.

    Returns:
        A tuple containing the instance name, the execution status ('SUCCESS' or
        'FAILURE'), and the result or error message.
    """
    instance_name = getattr(instance, 'name', str(instance))
    try:
        logger.info(f"Starting task for instance '{instance_name}'.")
        result = action(instance)
        logger.info(f"Task for '{instance_name}' completed successfully.")
        return (instance_name, "SUCCESS", result)
    except Exception as e:
        logger.error(f"Task for '{instance_name}' failed with an exception: {e}", exc_info=True)
        return (instance_name, "FAILURE", str(e))


class ParallelExecutor(BaseModel):
    """
    A Pydantic model to run a specific method on a list of objects in parallel.

    This class simplifies the process of using a `ThreadPoolExecutor` for
    running I/O-bound tasks concurrently. It manages the thread pool,
    logging, and result collection.

    Attributes:
        log_dir: The directory where log files will be stored.
        max_workers: The maximum number of threads to use in the pool.
        instance: A unique name for this executor instance, used for logging.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)

    log_dir: Path
    max_workers: int = 5
    instance: str

    @property
    def logger(self) -> logging.Logger:
        """Returns the logger for this executor instance."""
        return get_logger(
            name=f"ParallelExecutor_{self.instance}",
            directory=self.log_dir,
            process_stage=self.instance,
        )

    def run(
        self,
        objects: List[Any],
        action: Callable[[Any], Any],
        reporter: Optional[RunReporter] = None,
        stage: Optional[str] = None,
    ) -> List[tuple]:
        """
        Runs `action(obj)` for each object in the provided list, in parallel.

        This method sets up a `ThreadPoolExecutor`, submits a task for each
        object, and collects the results as they are completed.

        Args:
            objects: A list of object instances.
            action: A callable taking one argument (an object from `objects`)
                that performs the task.
            reporter: Optional `RunReporter` to record each task's pass/fail
                outcome into the run's consolidated summary. `.record()` is
                thread-safe, so it can be called directly as each future
                completes without additional synchronization here.
            stage: Label used when recording into `reporter` (defaults to
                `self.instance`).

        Returns:
            A list of tuples, where each tuple contains the result from one task,
            formatted as (instance_name, status, data).
        """
        logger = self.logger
        logger.info(f"Creating parallel executor for '{self.instance}' with {self.max_workers} workers.")
        stage_name = stage or self.instance

        all_results = []
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=self.max_workers, thread_name_prefix=f"{self.instance}_Worker"
        ) as executor:
            future_to_obj = {
                executor.submit(run_action_on_instance, obj, action, logger): obj
                for obj in objects
            }

            # Process futures as they complete.
            for future in concurrent.futures.as_completed(future_to_obj):
                try:
                    name, status, data = future.result()
                    logger.info(f"Future completed for '{name}' with status '{status}'.")
                    all_results.append((name, status, data))
                    if reporter is not None:
                        reporter.record(
                            stage=stage_name,
                            task=name,
                            status="SUCCESS" if status == "SUCCESS" else "FAILED",
                            error=None if status == "SUCCESS" else str(data),
                        )
                except Exception as e:
                    # This is a fallback for errors that might occur outside the worker function
                    obj_name = getattr(future_to_obj[future], 'name', 'Unknown')
                    logger.error(f"An unexpected error occurred while processing the future for '{obj_name}': {e}", exc_info=True)
                    all_results.append((obj_name, "EXCEPTION", str(e)))
                    if reporter is not None:
                        reporter.record(stage=stage_name, task=obj_name, status="FAILED", error=str(e))

        logger.info("All parallel tasks are complete.")
        return all_results
