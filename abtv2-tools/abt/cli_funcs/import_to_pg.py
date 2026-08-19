import typer
from typing import Annotated, List, Optional, Tuple
from pathlib import Path
from itertools import chain

from .cli_helpers import get_pg_config
from ..schema import DataSchema, ProcessingDirectorySchema
from ..aux_data_model import AuxDataLayer
from ..osm_data_model import prep_osm, get_osm_bbox
from ..parallel import ParallelExecutor
from ..utils.run_reporter import RunReporter
from ..importer.importer import Importer
from ..utils.fields import (
    working_dir_field,
    schema_dir_field,
    data_type_field,
    CliDataType,
    pg_config_field,
    num_workers_field,
    osm_key_field,
    force_field,
    clip_aux_field,
    default_num_workers,
)


class OSMAlreadyPopulatedError(Exception):
    """Raised when OSM import is attempted against an already-populated schema without --force."""

def prep_aux(
    data_schema: DataSchema,
    processing_directory: ProcessingDirectorySchema,
    pg_string: str,
    bbox: Optional[Tuple[float, float, float, float]] = None
) -> tuple[List[Importer], List[AuxDataLayer]]:
    """Prepares auxiliary data layers for database import.

    This function reads the auxiliary data files specified in the data schema,
    initializes an Importer object for each layer, and configures it with
    the database connection string.

    Args:
        data_schema: The data schema configuration containing paths to auxiliary data files.
        processing_directory: The schema for processing directories.
        pg_string: The PostgreSQL connection string for the database.
        bbox: Optional WGS84 (xmin, ymin, xmax, ymax) filter applied to every
            aux layer's import, for fast test builds.

    Returns:
        A tuple containing:
        - A flattened list of configured Importer instances for all auxiliary data.
        - A list of the AuxDataLayer instances.
    """
    aux_layers = list(
        map(
            AuxDataLayer.from_file, data_schema.aux_files
        )
    )

    aux_importer_groups = map(
        lambda a: a.init_importer(
            output_directory=processing_directory.aux_download_dir,
            log_dir=processing_directory.import_log_dir,
            pg_string=pg_string,
            bbox=bbox
        ),
        aux_layers
    )

    flat_aux_importers = list(chain.from_iterable(aux_importer_groups))

    return flat_aux_importers, aux_layers

def init_importer(
    working_dir: Path,
    schema_dir: Path,
    data_type: CliDataType,
    num_workers: int,
    pg_config_type: str,
    osm_key: Optional[str] = "planet",
    force: bool = False,
    clip_aux: bool = False
):
    """Initializes and runs the data import process into the database.

    Orchestrates the import of OpenStreetMap (OSM) data, auxiliary data, or both,
    into a PostgreSQL database. It handles sequential imports for OSM and parallel
    imports for auxiliary files.

    Args:
        working_dir: The root directory where data is stored.
        schema_dir: The directory containing data schema definitions.
        data_type: The type of data to import (OSM, AUX, or ALL).
        num_workers: The number of parallel workers for importing auxiliary data.
        pg_config_type: The method for obtaining the PostgreSQL config ('env' or path).
        osm_key: The key for selecting the OSM extract from the GeoFabrik index. Defaults to "planet".
        force: Re-import OSM data even if the schema is already populated.
        clip_aux: Clip auxiliary data imports to the osm_key extract's bounding box.

    Raises:
        ValueError: If an unsupported data_type is provided.
        OSMAlreadyPopulatedError: If OSM data already exists and force is False.
    """
    data_schema = DataSchema(base_schema_dir=schema_dir)
    processing_directory = ProcessingDirectorySchema.init_working_directories(working_dir=working_dir)
    reporter = RunReporter(run_id=processing_directory.run_id, command="abt import")
    pg_config = get_pg_config(
        cli_input=pg_config_type,
        log_dir=processing_directory.carto_log_dir
    )

    if data_type in [CliDataType.OSM, CliDataType.ALL]:
        print("--- Preparing OSM data for import ---")

        if pg_config.osm_populated and not force:
            raise OSMAlreadyPopulatedError(
                "OSM schema already contains data. Re-importing will overwrite it "
                "and can take 24+ hours. Pass --force to proceed."
            )

        osm_processing = prep_osm(
            data_schema=data_schema,
            processing_directory=processing_directory,
            osm_index=osm_key
        )
        print("--- Importing OSM data ---")
        try:
            osm_importer = osm_processing.init_import(
                pg_uri=pg_config.pguri,
                pg_schema=pg_config.osm_schema,
                diff=False
            )
            osm_importer.import_to_pg()
            reporter.record(stage="import", task=osm_processing.osm_data.filename, status="SUCCESS")
            print("--- OSM import complete ---")
        except Exception as e:
            reporter.record(stage="import", task=osm_processing.osm_data.filename, status="FAILED", error=str(e))
            print(f"--- OSM import failed: {e} ---")

    if data_type in [CliDataType.AUX, CliDataType.ALL]:
        print("--- Preparing auxiliary data for import ---")
        aux_bbox = get_osm_bbox(osm_key) if clip_aux else None
        if clip_aux and aux_bbox is None:
            print(f"--- --clip-aux has no effect: '{osm_key}' has no bounding box ---")
        aux_import_list, _ = prep_aux(
            data_schema=data_schema,
            processing_directory=processing_directory,
            pg_string=pg_config.uri,
            bbox=aux_bbox
        )

        aux_import_task = ParallelExecutor(
            log_dir=processing_directory.download_log_dir,
            max_workers=num_workers,
            instance='import_to_pg'
        )

        print("--- Importing auxiliary data ---")
        print("--- Resetting auxiliary schema ---")
        pg_config.reset_aux_schema()

        print("--- Importing in parallel ---")
        aux_import_task.run(
            objects=aux_import_list,
            action=Importer.import_to_pg,
            reporter=reporter,
            stage="import"
        )
        print("--- Auxiliary data import complete ---")

    if data_type not in [CliDataType.OSM, CliDataType.AUX, CliDataType.ALL]:
        raise ValueError(f"Invalid data_type specified: {data_type}")

    reporter.write_summary(processing_directory.summary_file)
    print(f"Run summary: {processing_directory.summary_file}")
    return reporter

app = typer.Typer()

@app.command("import")
def cli_impoter(
    working_dir: Annotated[Path, working_dir_field],
    schema_dir: Annotated[Path, schema_dir_field],
    data_type: Annotated[CliDataType, data_type_field],
    num_workers: Annotated[int, num_workers_field] = default_num_workers(divisor=2),
    pg_config: Annotated[str, pg_config_field] = 'env',
    osm_key: Annotated[str, osm_key_field] = "planet",
    force: Annotated[bool, force_field] = False,
    clip_aux: Annotated[bool, clip_aux_field] = False
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
        force: Re-import OSM data even if the schema is already populated.
        clip_aux: Clip auxiliary data imports to the osm_key extract's bounding box.
    """
    try:
        reporter = init_importer(
            working_dir=working_dir,
            schema_dir=schema_dir,
            data_type=data_type,
            num_workers=num_workers,
            pg_config_type=pg_config,
            osm_key=osm_key,
            force=force,
            clip_aux=clip_aux
        )
    except Exception as e:
        typer.echo(f"Error during import process: {e}. Check logs for details.", err=True)
        raise typer.Exit(code=1)
    if reporter.overall_status != "SUCCESS":
        typer.echo(f"Import finished with status {reporter.overall_status}. See summary for details.", err=True)
        raise typer.Exit(code=1)

if __name__ == "__main__":
    app()
