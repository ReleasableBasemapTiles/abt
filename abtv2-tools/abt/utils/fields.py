"""
cli_fields.py

This module centralizes the definition of command-line interface (CLI)
enums and `typer.Option` fields used across the Army Basemap Tiles (ABT) CLI.
It ensures consistent argument definitions, help text, and type annotations
for various commands related to data processing.
"""

from typing import Annotated, Optional
from enum import Enum
from pathlib import Path
import os
import re
import typer


def default_num_workers(divisor: int = 3, floor: int = 4) -> int:
    """Computes a parallelism default scaled to the host's core count.

    Returns `floor` on small hosts -- matching this tool's historical fixed
    default of 4, tuned for the 8 vCPU tier documented in the READMEs -- and
    scales up on larger hosts, so a big single-host server doesn't need an
    explicit -n/--num-workers just to make use of its cores. `divisor` lets
    each call site leave more headroom for tasks that already spawn their
    own multi-threaded subprocess per worker (e.g. tippecanoe in `export`).
    Always overridable via -n/--num-workers.
    """
    cpu_count = os.cpu_count() or floor
    return max(floor, cpu_count // divisor)


class CliDataType(str, Enum):
    """Enumeration for specifying the type of data to process in CLI commands."""
    OSM = 'osm'
    AUX = 'aux'
    ALL = 'all'


# --- Field Aliases ---
# These define the short and long form command-line flags for each option.
working_dir_aliases = ['-w', '--working-dir']
schema_dir_aliases = ['-s', '--schema-dir']
pg_config_aliases = ['-p', '--pg-config']
max_zoom_aliases = ['-z', '--max-zoom']
additional_mbtiles_aliases = ['-q', '--additional-mbtiles']
num_workers_aliases = ['-n', '--num-workers']
data_type_aliases = ['-d', '--data-type']
osm_key_aliases = ['-k', '--osm-key']
force_aliases = ['-f', '--force']
clip_aux_aliases = ['-c', '--clip-aux']

### Debug Options
single_aux_file_aliases = ['-a', '--aux-file']

projection_override_aliases = ['--projection-override']
output_name_aliases = ['-o', '--output-name']
vundler_input_aliases = ['-i', '--input-path']
vundler_output_dir_aliases = ['-o', '--output-dir']

# --- Field Options ---
# These define the actual Typer options with their help text and default values.

working_dir_field = typer.Option(
    ...,  # Indicates this option is required
    *working_dir_aliases,
    help="Specifies the path to the directory for downloading, extracting, and building datasets. If the directory does not exist, it will be created automatically."
)

schema_dir_field = typer.Option(
    ...,
    *schema_dir_aliases,
    help="Points to the directory that contains all necessary schemas and processing instructions. This directory must be set up with the required subdirectories and data files before running the app. Please consult the API documentation for setup details.",
)

pg_config_field = typer.Option(
    ..., # Default value 'env'
    *pg_config_aliases,
    help='Defines the PostgreSQL/PostGIS connection. You can either use "env" to connect using environment variables (PGHOST, PGPORT, PGUSER, PGPASSWORD, PGDATABASE) or provide a connection string in the format: "<host>,<port>,<username>,<password>,<database_name>"',
)

max_zoom_field = typer.Option(
    ..., # Default value 13
    *max_zoom_aliases,
    help="Sets the maximum zoom level for processing exports. The default value is 13",
)

additional_mbtiles_field = typer.Option(
    ..., # Default value [], making it optional
    *additional_mbtiles_aliases,
    help="(Optional, repeatable) Path to an externally-produced mbtiles file to fold into "
         "the bundle -- e.g. contours. Pass multiple times to include more than one.",
)

num_workers_field = typer.Option(
    ..., # Default computed per-command by default_num_workers(); see each command
    *num_workers_aliases,
    help="Determines the number of parallel processes for the download, import, and export commands. This setting is disregarded by the carto and bundler commands. Defaults to a value scaled to this host's CPU count (minimum 4); pass explicitly to override.",
)

data_type_field = typer.Option(
    ..., # Required, as there's no default given CliDataType
    *data_type_aliases,
    help=(
        "Specifies the type of data for the download and import commands. "
        "Allowed values are 'osm', 'aux', or 'all'.\n"
        "  osm: Uses the Imposm method to import data.\n"
        "  aux: Uses Ogr2Ogr methods to import data in parallel, respecting the --num-workers setting.\n"
        "  all: A convenience option to run both aux and osm. It first processes aux data in parallel, "
        "then dedicates all workers to the osm import."
    ),
)

osm_key_field = typer.Option(
    ...,
    *osm_key_aliases,
    help="Extracts OSM Data based on either planet or GeoFabrik key.",
)

force_field = typer.Option(
    ...,
    *force_aliases,
    help="Re-import OSM data even if the schema is already populated. Without this, "
         "import aborts rather than silently overwriting an existing OSM import "
         "(a full re-import can take 24+ hours).",
)

clip_aux_field = typer.Option(
    ...,
    *clip_aux_aliases,
    help="Clip auxiliary (global) data imports to the bounding box of the "
         "--osm-key GeoFabrik extract, for fast test builds. Ignored when "
         "--osm-key is 'planet' or omitted.",
)


single_aux_file_field = typer.Option(
    ...,
    *single_aux_file_aliases,
    help="Specifies the path to a single auxiliary data file to import.",
)


def validate_projection_override(value: Optional[str]) -> Optional[str]:
    """Ensures --projection-override is either unset or a strict 'EPSG:<code>' string."""
    if value is None:
        return None
    if not re.fullmatch(r"EPSG:\d+", value):
        raise typer.BadParameter('Must be in the form "EPSG:<code>", e.g. "EPSG:3395"')
    return value


projection_override_field = typer.Option(
    ...,
    *projection_override_aliases,
    callback=validate_projection_override,
    help=(
        "ADVANCED / NON-STANDARD: Overrides the CRS tippecanoe assumes for exported "
        "geometry (default: WGS84 -> Web Mercator). Data is reprojected to the given "
        "EPSG code in PostGIS, then tippecanoe is told (falsely) that it is already "
        "receiving EPSG:3857 data, skipping its normal reprojection. This is an "
        "undocumented tippecanoe compatibility trick -- see "
        "github.com/mapbox/tippecanoe/issues/422. NOTE: this only makes sense for a "
        "target projection that uses meters as its unit (like EPSG:3857 itself) -- "
        "e.g. EPSG:3395, 5041, 5042. This is NOT enforced/validated; passing a "
        "degrees-based or otherwise incompatible EPSG code will silently produce "
        "garbled tiles. Output tiles will NOT conform to the MBTiles 1.3 spec and are "
        "saved with a .btis extension instead of .mbtiles, with 'crs' (and, for "
        "bundled output, 'btp_schema_version'/'changelog_url') metadata rows added "
        "per the BTIS convention. Must be given as \"EPSG:<code>\", e.g. \"EPSG:3395\"."
    ),
)

output_name_field = typer.Option(
    ...,
    *output_name_aliases,
    help="Filename for the bundled output. Defaults to joined.mbtiles (joined.btis under --projection-override).",
)

vundler_input_field = typer.Option(
    ...,
    *vundler_input_aliases,
    help="Path to the source .mbtiles/.btis file. Defaults to <working-dir>/bundled/joined.mbtiles or joined.btis.",
)

vundler_output_dir_field = typer.Option(
    ...,
    *vundler_output_dir_aliases,
    help="Output package directory. Defaults to <working-dir>/bundled/vundled/p12.",
)

