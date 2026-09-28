"""
run_carto.py

A command-line interface (CLI) script to execute a series of SQL scripts
against a PostgreSQL database. This process transforms imported data into a
format suitable for the final tile export process.
"""

import time
import typer
from typing import Annotated
from pathlib import Path

from .cli_helpers import get_pg_config
from ..schema import DataSchema, ProcessingDirectorySchema
from ..carto_processing_model import CartoProcessingModel
from ..utils.run_reporter import RunReporter
from ..utils.fields import (
    working_dir_field,
    schema_dir_field,
    pg_config_field,
    carto_concurrency_field,
    default_num_workers,
)

def init_carto_runer(working_dir: Path, schema_dir: Path, pg_config_type: str, carto_concurrency: int = 1):
    """Initializes and runs the SQL processing scripts.

    This function orchestrates the execution of SQL scripts defined in the data
    schema. It sets up the necessary directory structures, establishes a database
    connection, and then runs the SQL commands to transform the data.

    Args:
        working_dir: The root directory for all data processing and storage.
        schema_dir: The directory containing the data schema definitions.
        pg_config_type: How to connect to PostgreSQL ('env' or "host,port,user,password,dbname").
        carto_concurrency: Number of independent carto_sql groups to run
            concurrently (see rbt-schema/carto_sql/execution_plan.yml). 1
            reproduces today's fully sequential behavior.
    """
    data_schema = DataSchema(base_schema_dir=schema_dir)
    processing_directory = ProcessingDirectorySchema.init_working_directories(working_dir=working_dir)
    reporter = RunReporter(run_id=processing_directory.run_id, command="abt carto")
    pg_config = get_pg_config(
        cli_input=pg_config_type,
        log_dir=processing_directory.carto_log_dir
    )

    carto = CartoProcessingModel(
        sql_files=data_schema.carto_sql_layers,
        pg_config=pg_config,
        log_dir=processing_directory.carto_log_dir,
        execution_plan_path=data_schema.carto_execution_plan_path,
        concurrency=carto_concurrency
    )

    print("--- Processing SQL files ---")
    started = time.monotonic()
    try:
        carto.process_sql()
        reporter.record(stage="carto", task="process_sql", status="SUCCESS", duration_s=time.monotonic() - started)
        print("--- SQL processing complete ---")
    except Exception as e:
        reporter.record(
            stage="carto", task="process_sql", status="FAILED", error=str(e), duration_s=time.monotonic() - started
        )
        raise
    finally:
        # Per-script timings, for tuning execution_plan.yml's group order and weights.
        for run in carto.script_runs:
            reporter.record(
                stage="carto_scripts", task=run.script, status=run.status, error=run.error, duration_s=run.seconds
            )
        reporter.print_slowest("carto_scripts", title="Slowest carto scripts")
        reporter.write_summary(processing_directory.summary_file)
        print(f"Run summary: {processing_directory.summary_file}")

    return reporter

app = typer.Typer()

@app.command("carto")
def cli_carto_runner(
    working_dir: Annotated[Path, working_dir_field],
    schema_dir: Annotated[Path, schema_dir_field],
    pg_config: Annotated[str, pg_config_field] = 'env',
    carto_concurrency: Annotated[int, carto_concurrency_field] = default_num_workers(divisor=6, floor=1),
):
    """Run the carto_sql scripts that build the export.* layers.

    The scripts in <schema-dir>/carto_sql turn the imported osm and aux_data
    tables into the export schema that the export command reads. Script
    groups that carto_sql/execution_plan.yml marks independent run
    concurrently, up to -n at a time.
    \f
    Args:
        working_dir: The root directory for all processing tasks.
        schema_dir: The directory where schema definitions are located.
        pg_config: How to connect to PostgreSQL ('env' or "host,port,user,password,dbname").
        carto_concurrency: Number of independent carto_sql groups to run concurrently.
    """
    try:
        init_carto_runer(
            working_dir=working_dir,
            schema_dir=schema_dir,
            pg_config_type=pg_config,
            carto_concurrency=carto_concurrency
        )
    except Exception as e:
        typer.echo(f"Error in Carto SQL Runner: {e}. Check logs for details.", err=True)
        raise typer.Exit(code=1)
    return 1

if __name__ == "__main__":
    app()
