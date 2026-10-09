import typer
from datetime import datetime, timezone
from typing import Annotated, List, Optional
from pathlib import Path
import importlib.util

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
    optional_max_zoom_field,
    data_version_field,
    check_data_version,
)


def _load_metadata(schema_dir: Path) -> dict:
    metadata_path = schema_dir / "tile-metadata" / "metadata.py"
    if not metadata_path.exists():
        raise FileNotFoundError(f"No metadata.py found at {metadata_path}")
    spec = importlib.util.spec_from_file_location("tile_metadata", metadata_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.metadata


def resolve_data_version(data_version: Optional[str] = None, now: Optional[datetime] = None) -> str:
    """The version stamped on the bundle: `data_version` if given (after
    checking its form), else the UTC date of `now` -- by default the current
    time -- with a build counter of 0.

    UTC rather than local time, so every machine, and every projection's
    bundler, names a given moment's day the same way. `now` should be
    timezone-aware.
    """
    if data_version is not None:
        return check_data_version(data_version)
    now = now or datetime.now(timezone.utc)
    return f"{now.astimezone(timezone.utc):%Y-%m-%d}.0"


def init_bundler(
    working_dir: Path,
    schema_dir: Path,
    pg_config_type: str = 'env',
    additional_mbtiles: Optional[List[Path]] = None,
    output_name: Optional[str] = None,
    max_zoom: Optional[int] = None,
    data_version: Optional[str] = None,
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
            joined.mbtiles.
        max_zoom: Optional zoom cap for the bundled output (e.g. for an RBT
            Small package). Omit for no cap (full resolution).
        data_version: Optional version to stamp on the bundle, as
            YYYY-MM-DD.N. Defaults to the UTC date this run starts on, with
            a counter of 0. See resolve_data_version.

    Raises:
        ValueError: If data_version is not of the form YYYY-MM-DD.N.
    """
    # First, so a malformed version fails before anything is created.
    version = resolve_data_version(data_version)
    data_schema = DataSchema(base_schema_dir=schema_dir)
    processing_directory = ProcessingDirectorySchema.init_working_directories(working_dir=working_dir)
    reporter = RunReporter(run_id=processing_directory.run_id, command="abt bundler")
    # The data version is the bundler's to set: whatever tile-metadata/metadata.py
    # says (it no longer has a version) is replaced.
    joined_metadata = {**_load_metadata(schema_dir), "version": version}
    print(f"--- Data version: {version} ---")

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
        max_zoom=max_zoom,
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
    max_zoom: Annotated[Optional[int], optional_max_zoom_field] = None,
    data_version: Annotated[Optional[str], data_version_field] = None,
):
    """Join the per-layer MBTiles into one bundle with tile-join.

    Writes <working-dir>/bundled/joined.mbtiles (or --output-name) with the
    metadata from <schema-dir>/tile-metadata/metadata.py, and with the data
    version from --data-version as its version.
    \f
    Args:
        working_dir: Root directory for all processing and output files.
        schema_dir: Directory containing the data schema definitions.
        pg_config: How to connect to PostgreSQL ('env' or "host,port,user,password,dbname").
            Defaults to 'env'.
        additional_mbtiles: Paths to externally-produced mbtiles files (e.g.
            contours) to fold into the bundle. Repeatable.
        output_name: Optional filename for the bundled output.
        max_zoom: Optional zoom cap for the bundle. Omit for no cap.
        data_version: Version to stamp on the bundle, as YYYY-MM-DD.N. Defaults
            to the UTC date the bundler starts on, with .0.
    """
    try:
        reporter = init_bundler(
            working_dir=working_dir,
            schema_dir=schema_dir,
            pg_config_type=pg_config,
            additional_mbtiles=additional_mbtiles,
            output_name=output_name,
            max_zoom=max_zoom,
            data_version=data_version,
        )
    except Exception as e:
        typer.echo(f"Error during bundler process: {e}. Check logs for details.", err=True)
        raise typer.Exit(code=1)
    if reporter.overall_status != "SUCCESS":
        typer.echo(f"Bundler finished with status {reporter.overall_status}. See summary for details.", err=True)
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
