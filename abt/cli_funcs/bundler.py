import typer
from typing import Annotated, List, Optional
from pathlib import Path
import importlib.util
import pathlib

from .cli_helpers import get_pg_config, get_tile_layers_for_bundler

from ..schema import DataSchema, ProcessingDirectorySchema
from ..export.bundler_model import Bundler
from ..export.bundler import export_bundled
from ..utils.run_reporter import RunReporter

from ..utils.fields import (
    working_dir_field,
    schema_dir_field,
    pg_config_field,
    additional_mbtiles_field,
    output_name_field,
)


def _load_metadata():
    spec = importlib.util.spec_from_file_location(
        "abt_metadata",
        pathlib.Path(__file__).parents[3] / "abtv2-schema-rbt" / "tile-metadata" / "abt_metadata.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.metadata

joined_metadata = _load_metadata()


def init_bundler(
    working_dir: Path,
    schema_dir: Path,
    pg_config_type: str = 'env',
    additional_mbtiles: Optional[List[Path]] = None,
    output_name: Optional[str] = None
):
    """Bundles exported tile layers into a single MBTiles file via tile-join.

    Args:
        working_dir: Root directory for all processing and output files.
        schema_dir: Directory containing the data schema definitions.
        pg_config_type: PostgreSQL connection method. Use 'env' to read from
            environment variables, or pass a comma-separated connection string.
            Defaults to 'env'.
        additional_mbtiles: Paths to externally-produced mbtiles files (e.g.
            contours) to fold into the bundle. Defaults to none.
        output_name: Optional filename for the bundled output. Defaults to
            joined.mbtiles (joined.btis under --projection-override).
    """
    data_schema = DataSchema(base_schema_dir=schema_dir)
    processing_directory = ProcessingDirectorySchema.init_working_directories(working_dir=working_dir)
    reporter = RunReporter(run_id=processing_directory.run_id, command="abt bundler")

    pg_config = get_pg_config(cli_input=pg_config_type, log_dir=processing_directory.carto_log_dir)

    tile_layers = get_tile_layers_for_bundler(
        data_schema=data_schema,
        processing_directory=processing_directory,
        pg_config=pg_config
    )

    bundle = Bundler(
        bundled_dir=processing_directory.bundled_dir,
        tile_layers=tile_layers,
        additional_mbtiles=additional_mbtiles or [],
        metadata=joined_metadata,
        package_name=output_name or "joined.mbtiles",
        package_name_explicit=output_name is not None
    )
    print("--- Bundling tile layers ---")
    print(f"--- Log directory: {bundle.bundled_dir} ---")
    try:
        export_bundled(bundle)
        reporter.record(stage="bundle", task="tile_join", status="SUCCESS")
        print("--- Bundler complete ---")
    except Exception as e:
        reporter.record(stage="bundle", task="tile_join", status="FAILED", error=str(e))
        raise
    finally:
        reporter.write_summary(processing_directory.summary_file)
        print(f"Run summary: {processing_directory.summary_file}")

    return reporter


app = typer.Typer()

@app.command("bundler")
def cli_bundler(
    working_dir: Annotated[Path, working_dir_field],
    schema_dir: Annotated[Path, schema_dir_field],
    pg_config: Annotated[str, pg_config_field] = 'env',
    additional_mbtiles: Annotated[List[Path], additional_mbtiles_field] = None,
    output_name: Annotated[str, output_name_field] = None,
):
    """CLI command to bundle exported tile layers into a single MBTiles file via tile-join.

    Args:
        working_dir: Root directory for all processing and output files.
        schema_dir: Directory containing the data schema definitions.
        pg_config: PostgreSQL connection method ('env' or connection string).
            Defaults to 'env'.
        additional_mbtiles: Paths to externally-produced mbtiles files (e.g.
            contours) to fold into the bundle. Repeatable.
        output_name: Optional filename for the bundled output.
    """
    try:
        reporter = init_bundler(
            working_dir=working_dir,
            schema_dir=schema_dir,
            pg_config_type=pg_config,
            additional_mbtiles=additional_mbtiles,
            output_name=output_name
        )
    except Exception as e:
        typer.echo(f"Error during bundler process: {e}. Check logs for details.", err=True)
        raise typer.Exit(code=1)
    if reporter.overall_status != "SUCCESS":
        typer.echo(f"Bundler finished with status {reporter.overall_status}. See summary for details.", err=True)
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
