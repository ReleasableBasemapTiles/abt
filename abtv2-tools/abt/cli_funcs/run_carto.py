"""
run_carto.py

A command-line interface (CLI) script to execute a series of SQL scripts
against a PostgreSQL database. This process transforms imported data into a
format suitable for the final tile export process.
"""

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
        pg_config_type: The method for obtaining the PostgreSQL config ('env' or path).
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
    try:
        carto.process_sql()
        reporter.record(stage="carto", task="process_sql", status="SUCCESS")
        print("--- SQL processing complete ---")
    except Exception as e:
        reporter.record(stage="carto", task="process_sql", status="FAILED", error=str(e))
        raise
    finally:
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
    """CLI command to run SQL data transformation scripts.

    This command executes predefined SQL scripts to process and transform data
    within the PostgreSQL database, preparing it for the tile export step.

    Args:
        working_dir: The root directory for all processing tasks.
        schema_dir: The directory where schema definitions are located.
        pg_config: Specifies how to get the PG connection string ('env' or file path).
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
