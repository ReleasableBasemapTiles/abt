import typer
from functools import partial
from typing import Annotated, Optional
from pathlib import Path

from .cli_helpers import get_pg_config
from ..schema import DataSchema, ProcessingDirectorySchema
from ..export.tile_layer_model import TileLayer
from ..export.exporter import export_layer, order_largest_first
from ..parallel import ParallelExecutor
from ..utils.run_reporter import RunReporter
from ..utils.fields import (
    working_dir_field,
    schema_dir_field,
    pg_config_field,
    num_workers_field,
    max_zoom_field,
    projection_override_field,
    default_num_workers,
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
    It reads layer definitions from the schema and runs up to `num_workers`
    layers at a time, largest first. Each layer is exported from PostgreSQL
    to a FlatGeobuf (FGB) file and then converted straight on to MBTiles, so
    no layer's conversion waits for every other layer's export.

    Args:
        working_dir: The root directory for all data processing and storage.
        schema_dir: The directory containing the data schema definitions.
        num_workers: The number of parallel workers to use for export tasks.
        pg_config_type: How to connect to PostgreSQL ('env' or "host,port,user,password,dbname").
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
        log_dir=processing_directory.fgb_log_dir
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

    # export_layer records each layer's two steps into the reporter itself,
    # so the executor gets none: it would record every layer a second time.
    tile_layers = order_largest_first(tile_layers, pg_config)
    print(f"--- Exporting {len(tile_layers)} layer(s) to FlatGeobuf, then MBTiles, largest first ---")
    ParallelExecutor(
        log_dir=processing_directory.log_dir,
        max_workers=num_workers,
        instance='export'
    ).run(objects=tile_layers, action=partial(export_layer, reporter=reporter))

    print("--- Export complete ---")
    reporter.print_slowest("export_to_fgb", title="Slowest FlatGeobuf exports")
    reporter.print_slowest("export_to_mbtiles", title="Slowest MBTiles conversions")
    reporter.write_summary(processing_directory.summary_file)
    print(f"Run summary: {processing_directory.summary_file}")
    return reporter

app = typer.Typer()

@app.command("export")
def cli_export(
    working_dir: Annotated[Path, working_dir_field],
    schema_dir: Annotated[Path, schema_dir_field],
    num_workers: Annotated[int, num_workers_field] = default_num_workers(divisor=3),
    pg_config: Annotated[str, pg_config_field] = 'env',
    max_zoom: Annotated[int, max_zoom_field] = 13,
    projection_override: Annotated[str, projection_override_field] = None
):
    """Export each export.* layer to FlatGeobuf, then to per-layer MBTiles.

    ogr2ogr writes <working-dir>/flatgeobuf/<layer>.fgb and tippecanoe turns
    it into <working-dir>/mbtiles/<layer>.mbtiles, per the layer's
    <schema-dir>/export/*.json. Finished outputs from an earlier run are
    skipped.
    \f
    Args:
        working_dir: The root directory for all processing tasks.
        schema_dir: The directory where schema definitions are located.
        num_workers: The number of concurrent workers for the export process.
        pg_config: How to connect to PostgreSQL ('env' or "host,port,user,password,dbname").
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
