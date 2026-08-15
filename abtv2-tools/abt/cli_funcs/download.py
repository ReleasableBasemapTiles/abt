import typer
from typing import Annotated, List, Union, Optional
from pathlib import Path

from ..schema import DataSchema, ProcessingDirectorySchema
from ..aux_data_model import AuxDataLayer
from ..osm_data_model import prep_osm
from ..parallel import ParallelExecutor
from ..utils.run_reporter import RunReporter
from ..download.downloader import Downloader
from ..utils.fields import (
    working_dir_field,
    schema_dir_field,
    data_type_field,
    CliDataType,
    pg_config_field,
    num_workers_field,
    osm_key_field,
    default_num_workers,
)

def prep_aux(
    data_schema: DataSchema, 
    processing_directory: ProcessingDirectorySchema,
) -> tuple[List[Downloader], List[AuxDataLayer]]:
    """Prepares auxiliary data layers for downloading.

    This function reads the auxiliary data files specified in the data schema,
    initializes an AuxDataLayer object for each, and creates a corresponding
    Downloader instance configured with the correct output and log directories.

    Args:
        data_schema: The data schema configuration containing paths to auxiliary data files.
        processing_directory: The schema for processing directories where auxiliary
                              data will be downloaded.

    Returns:
        A tuple containing:
        - A list of configured Downloader instances for the auxiliary data.
        - A list of the AuxDataLayer instances.
    """
    aux_layers = list(
        map(
            AuxDataLayer.from_file, data_schema.aux_files
        )
    )
    
    aux_downloaders = [
        a.init_download(
            output_directory=processing_directory.aux_download_dir,
            log_dir=processing_directory.download_log_dir
        )
        for a in aux_layers
        if not a.is_local
    ]

    return aux_downloaders, aux_layers

def init_downloader(working_dir: Path, schema_dir: Path, data_type: CliDataType, num_workers: int, osm_key: str):
    """Initializes and runs the data download process.

    Orchestrates the download of OpenStreetMap (OSM) data, auxiliary data, or both,
    based on the specified data_type. It handles sequential downloads for OSM and
    parallel downloads and extractions for auxiliary files.

    Args:
        working_dir: The root directory for all data processing and storage.
        schema_dir: The directory containing the data schema definitions.
        data_type: The type of data to download (OSM, AUX, or ALL).
        num_workers: The number of parallel workers for downloading auxiliary data.

    Raises:
        ValueError: If an unsupported data_type is provided.
    """
    data_schema = DataSchema(base_schema_dir=schema_dir)
    processing_directory = ProcessingDirectorySchema.init_working_directories(working_dir=working_dir)
    reporter = RunReporter(run_id=processing_directory.run_id, command="abt download")

    if data_type in [CliDataType.OSM, CliDataType.ALL]:
        print("--- Preparing OSM data ---")
        osm_processing = prep_osm(
            data_schema=data_schema,
            processing_directory=processing_directory,
            osm_index=osm_key
        )
        print("--- Downloading OSM data ---")
        try:
            osm_downloader = osm_processing.init_download()
            osm_downloader.download()
            reporter.record(stage="download", task=osm_processing.osm_data.filename, status="SUCCESS")
            print("--- OSM download complete ---")
        except Exception as e:
            reporter.record(stage="download", task=osm_processing.osm_data.filename, status="FAILED", error=str(e))
            print(f"--- OSM download failed: {e} ---")

    if data_type in [CliDataType.AUX, CliDataType.ALL]:
        print("--- Preparing auxiliary data ---")
        aux_download_list, aux_layers = prep_aux(
            data_schema=data_schema,
            processing_directory=processing_directory
        )

        aux_download_task = ParallelExecutor(
            log_dir=processing_directory.download_log_dir,
            max_workers=num_workers,
            instance='download'
        )

        print("--- Downloading auxiliary data ---")
        aux_download_task.run(
            objects=aux_download_list,
            action=Downloader.download,
            reporter=reporter,
            stage="download"
        )

        # Filter for zipped layers and prepare for extraction
        extraction_list = map(
            lambda a: a.init_extraction(processing_directory.aux_download_dir),
            [layer for layer in aux_layers if layer.zipped]
        )

        # Run extractions, continuing past individual failures
        for extractor in extraction_list:
            task_name = str(extractor.filename)
            try:
                extractor.extract()
                reporter.record(stage="aux_extraction", task=task_name, status="SUCCESS")
            except Exception as e:
                reporter.record(stage="aux_extraction", task=task_name, status="FAILED", error=str(e))

        print("--- Auxiliary data download complete ---")

    if data_type not in [CliDataType.OSM, CliDataType.AUX, CliDataType.ALL]:
        raise ValueError(f"Invalid data_type specified: {data_type}")

    reporter.write_summary(processing_directory.summary_file)
    print(f"Run summary: {processing_directory.summary_file}")
    return reporter

app = typer.Typer()

@app.command("download")
def cli_download(
    working_dir: Annotated[Path, working_dir_field],
    schema_dir: Annotated[Path, schema_dir_field],
    data_type: Annotated[CliDataType, data_type_field],
    num_workers: Annotated[int, num_workers_field] = default_num_workers(divisor=4),
    osm_key: Annotated[str, osm_key_field]="planet"
):
    """CLI command to download and prepare geographic data.

    This command serves as the entry point for the data download process,
    allowing users to specify working directories, data types, and
    concurrency settings from the command line.

    Args:
        working_dir: The root directory for all processing tasks.
        schema_dir: The directory where schema definitions are located.
        data_type: The type of data to download (OSM, AUX, or ALL).
        num_workers: The number of concurrent workers for downloading.
    """
    try:
        reporter = init_downloader(
            working_dir=working_dir,
            schema_dir=schema_dir,
            data_type=data_type,
            num_workers=num_workers,
            osm_key=osm_key
        )
    except Exception as e:
        typer.echo(f"Error during download process: {e}. Check logs for details.", err=True)
        raise typer.Exit(code=1)
    if reporter.overall_status != "SUCCESS":
        typer.echo(f"Download finished with status {reporter.overall_status}. See summary for details.", err=True)
        raise typer.Exit(code=1)

if __name__ == "__main__":
    app()
