import typer
from typing import Annotated, List, Optional, Union
from pathlib import Path
from tqdm import tqdm

from .cli_helpers import get_pg_config
from ..schema import DataSchema, ProcessingDirectorySchema
from ..export.tile_layer_model import TileLayer
from ..export.exporter import export_to_fgb, export_to_mbtiles
from ..parallel import ParallelExecutor
from ..utils.run_reporter import RunReporter
from ..utils.fields import (
    working_dir_field,
    schema_dir_field,
    data_type_field,
    pg_config_field,
    num_workers_field,
    max_zoom_field,
    projection_override_field
)

def init_exporter(
    working_dir: Path,
    schema_dir: Path,
    num_workers: int,
    pg_config_type: str,
    max_zoom: int,
    projection_override: Optional[str] = None
):
    """Initializes and runs the tile export process.

    This function orchestrates the end-to-end process of exporting vector tiles.
    It reads layer definitions from the schema, exports data from PostgreSQL to
    FlatGeobuf (FGB) files in parallel, and then converts those FGB files into
    MBTiles format, also in parallel.

    Args:
        working_dir: The root directory for all data processing and storage.
        schema_dir: The directory containing the data schema definitions.
        num_workers: The number of parallel workers to use for export tasks.
        pg_config_type: The method for obtaining the PostgreSQL config ('env' or path).
        max_zoom: The maximum zoom level to generate tiles for.
        projection_override: Advanced/non-standard override of the CRS tippecanoe
            assumes for exported geometry (e.g. "EPSG:3395"). See
            projection_override_field's help text for details.

    Returns:
        The RunReporter for this invocation, with the summary already written.
    """
    data_schema = DataSchema(base_schema_dir=schema_dir)
    processing_directory = ProcessingDirectorySchema.init_working_directories(working_dir=working_dir)
    reporter = RunReporter(run_id=processing_directory.run_id, command="abt export")
    pg_config = get_pg_config(
        cli_input=pg_config_type,
        log_dir=processing_directory.carto_log_dir
    )

    # Initialize TileLayer objects from schema definitions
    tile_layers = list(
        map(
            lambda t: TileLayer.from_file(
                path=t,
                pg_config=pg_config,
                flatgeobuf_dir=processing_directory.flatgeobuf_dir,
                mbtiles_dir=processing_directory.mbtiles_dir,
                tmp_dir=processing_directory.tmp_dir,
                log_dir=processing_directory.log_dir,
                max_detail_const=max_zoom,
                projection_override=projection_override
            ),
            data_schema.export_layers
        )
    )
    
    # Run parallel export from PostGIS to FlatGeobuf
    tile_fgb_export_tasks = ParallelExecutor(
        log_dir=processing_directory.log_dir,
        max_workers=num_workers,
        instance='export_fgb'
    )
    print("--- Exporting to FlatGeobuf ---")
    fgb_results = tile_fgb_export_tasks.run(
        action=export_to_fgb,
        objects=tile_layers,
        reporter=reporter,
        stage='export_to_fgb'
    )

    # Run parallel conversion from FlatGeobuf to MBTiles
    print("--- Converting to MBTiles ---")
    tile_mbtile_export_tasks = ParallelExecutor(
        log_dir=processing_directory.log_dir,
        max_workers=num_workers,
        instance='export_mbtiles'
    )
    mbtile_results = tile_mbtile_export_tasks.run(
        objects=tile_layers,
        action=export_to_mbtiles,
        reporter=reporter,
        stage='export_to_mbtiles'
    )

    print("--- Export complete ---")
    reporter.write_summary(processing_directory.summary_file)
    print(f"Run summary: {processing_directory.summary_file}")
    return reporter

app = typer.Typer()

@app.command("export")
def cli_export(
    working_dir: Annotated[Path, working_dir_field],
    schema_dir: Annotated[Path, schema_dir_field],
    num_workers: Annotated[int, num_workers_field] = 4,
    pg_config: Annotated[str, pg_config_field] = 'env',
    max_zoom: Annotated[int, max_zoom_field] = 13,
    projection_override: Annotated[str, projection_override_field] = None
):
    """CLI command to export vector tiles from the database.

    This command orchestrates the process of converting data from a PostgreSQL
    database into MBTiles files, ready for use in web maps.

    Args:
        working_dir: The root directory for all processing tasks.
        schema_dir: The directory where schema definitions are located.
        num_workers: The number of concurrent workers for the export process.
        pg_config: Specifies how to get the PG connection string ('env' or file path).
        max_zoom: The maximum zoom level to include in the exported tiles.
        projection_override: Advanced/non-standard CRS override -- see the
            --projection-override help text.
    """
    try:
        reporter = init_exporter(
            working_dir=working_dir,
            schema_dir=schema_dir,
            num_workers=num_workers,
            pg_config_type=pg_config,
            max_zoom=max_zoom,
            projection_override=projection_override
        )
    except Exception as e:
        typer.echo(f"Error during tile export process: {e}. Check logs for details.", err=True)
        raise typer.Exit(code=1)
    if reporter.overall_status != "SUCCESS":
        typer.echo(f"Tile export finished with status {reporter.overall_status}. See summary for details.", err=True)
        raise typer.Exit(code=1)
    return 1

if __name__ == "__main__":
    app()
