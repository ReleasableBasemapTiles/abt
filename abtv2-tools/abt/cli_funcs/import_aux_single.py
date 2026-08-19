import typer
from typing import Annotated
from pathlib import Path

from .cli_helpers import get_pg_config
from ..schema import DataSchema, ProcessingDirectorySchema
from ..aux_data_model import AuxDataLayer
from ..utils.fields import (
    working_dir_field,
    schema_dir_field,
    pg_config_field,
    single_aux_file_field
    
)



app = typer.Typer()

@app.command("debug_aux_import")
def cli_impoter(
    working_dir: Annotated[Path, working_dir_field],
    schema_dir: Annotated[Path, schema_dir_field],
    aux_file: Annotated[str, single_aux_file_field],
    pg_config: Annotated[str, pg_config_field]="env",
    
):
    """CLI command to import geographic data into the database.

    This command serves as the entry point for the data import process,
    allowing users to specify data sources, database connections, and
    concurrency settings from the command line.

    Args:
        working_dir: The root directory where processed data is located.
        schema_dir: The directory where schema definitions are located.
        data_type: The type of data to import (OSM, AUX, or ALL).
        num_workers: The number of concurrent workers for the import process.
        pg_config: Specifies how to get the PG connection string ('env' or file path).
    """
    try:
        data_schema = DataSchema(base_schema_dir=schema_dir)
        
        
        
        processing_directory = ProcessingDirectorySchema.init_working_directories(working_dir)
        

        pg_config = get_pg_config(
            cli_input=pg_config,
            log_dir=processing_directory.carto_log_dir
        )
       
        aux_file_path = data_schema.aux_import_dir / f"{aux_file}.json"
        
        if not aux_file_path.exists():
            raise ValueError(f"Specified auxiliary file does not exist: {aux_file_path}")
        print(f"--- Preparing auxiliary data for import from {aux_file_path} ---")
        a = AuxDataLayer.from_file(f=aux_file_path)

        print(f"Extraction folder: {a.extraction_folder(output_directory=processing_directory.aux_download_dir)}")

        importer = a.init_importer(
            output_directory=processing_directory.aux_download_dir,
            log_dir=processing_directory.import_log_dir,
            pg_string=pg_config.uri
        )
        
        for imp in importer:
            imp.import_to_pg()
        print(f"--- Auxiliary data import complete for {aux_file} ---")
    except Exception as e:
        typer.echo(f"Error during import process: {e}. Check logs for details.", err=True)
        raise typer.Exit(code=1)

if __name__ == "__main__":
    app()
