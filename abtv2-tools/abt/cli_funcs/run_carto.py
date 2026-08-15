"""
run_carto.py

A command-line interface (CLI) script to execute a series of SQL scripts
against a PostgreSQL database. This process transforms imported data into a
format suitable for the final tile export process.
"""

import typer
from typing import Annotated, List, Union
from pathlib import Path

from .cli_helpers import get_pg_config
from ..schema import DataSchema, ProcessingDirectorySchema
from ..carto_processing_model import CartoProcessingModel
from ..utils.run_reporter import RunReporter
from ..utils.fields import (
    working_dir_field,
    schema_dir_field,
    data_type_field,
    pg_config_field,
    num_workers_field
)

def init_carto_runer(working_dir: Path, schema_dir: Path, pg_config_type: str):
    """Initializes and runs the SQL processing scripts.

    This function orchestrates the execution of SQL scripts defined in the data
    schema. It sets up the necessary directory structures, establishes a database
    connection, and then runs the SQL commands to transform the data.

    Args:
        working_dir: The root directory for all data processing and storage.
        schema_dir: The directory containing the data schema definitions.
        pg_config_type: The method for obtaining the PostgreSQL config ('env' or path).
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
        log_dir=processing_directory.carto_log_dir
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
    pg_config: Annotated[str, pg_config_field] = 'env'
):
    """CLI command to run SQL data transformation scripts.

    This command executes predefined SQL scripts to process and transform data
    within the PostgreSQL database, preparing it for the tile export step.

    Args:
        working_dir: The root directory for all processing tasks.
        schema_dir: The directory where schema definitions are located.
        pg_config: Specifies how to get the PG connection string ('env' or file path).
    """
    try:
        init_carto_runer(
            working_dir=working_dir,
            schema_dir=schema_dir,
            pg_config_type=pg_config
        )
    except Exception as e:
        typer.echo(f"Error in Carto SQL Runner: {e}. Check logs for details.", err=True)
        raise typer.Exit(code=1)
    return 1

if __name__ == "__main__":
    app()
