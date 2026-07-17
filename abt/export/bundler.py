"""
bundler.py

Runs the tile-join bundling step for a Bundler: joins all per-layer mbtiles
into one package and writes BTIS/descriptive metadata into the result.
"""

from pathlib import Path
import sqlite3

from .bundler_model import Bundler
from ..utils.subprocess_tools import run_subprocess
from .mbtiles_metadata import (
    BTIS_SCHEMA_VERSION,
    BTIS_CHANGELOG_URL_PLACEHOLDER,
    TOOL_COMPUTED_METADATA_KEYS,
    OVERRIDE_ONLY_DROPPED_METADATA_KEYS,
    crs_area_of_use_bounds,
    resolve_crs_from_files,
    write_mbtiles_metadata,
    delete_mbtiles_metadata,
)


def set_pragma_options(bundle: Bundler) -> None:
    """Applies SQLite PRAGMA tuning to the finished bundle."""
    con = sqlite3.connect(bundle.bundled_mbtiles_path)
    cursor = con.cursor()
    cursor.execute("PRAGMA cache_size = -2000000;")
    con.execute(f"PRAGMA temp_store_directory = '{str(bundle.bundled_mbtiles_tmp)}'")
    con.commit()
    con.close()


def export_bundled(bundle: Bundler) -> None:
    """Runs tile-join and writes BTIS/descriptive metadata into the joined output."""

    # Determine up front whether every input agrees on a projection (or
    # all default to Web Mercator); if it's a non-default CRS, the joined
    # output is renamed .btis before tile_join_cmd/bundled_mbtiles_path
    # are built from bundle.package_name. Skipped for an explicit
    # package_name -- the caller's chosen extension is left alone.
    crs = resolve_crs_from_files(bundle.tile_list)
    if crs is not None and not bundle.package_name_explicit:
        bundle.package_name = Path(bundle.package_name).with_suffix(".btis").name

    # Remove any stale output file so tile-join doesn't prompt to overwrite
    if bundle.bundled_mbtiles_path.exists():
        bundle.bundled_mbtiles_path.unlink()

    run_subprocess(
        cmd=bundle.tile_join_cmd,
        layer="joined",
        process_stage="bundler",
        log_dir=bundle.bundled_dir,
        tool_name="tile-join",
    )

    set_pragma_options(bundle)

    if crs is not None:
        # tile-join's own computed bounds/center (and
        # antimeridian_adjusted_bounds) are only meaningful for real Web
        # Mercator output -- see crs_area_of_use_bounds. Under
        # --projection-override, tile-join's math is provably wrong, so
        # replace bounds/center with the target CRS's actual area of use
        # and drop the non-spec-required antimeridian field entirely. With
        # no override, tile-join's own bounds/center are legitimate (real
        # Web Mercator math on real Web Mercator data) and are left alone.
        epsg_code = int(crs.split(":")[1])
        bounds, center = crs_area_of_use_bounds(epsg_code)
        write_mbtiles_metadata(bundle.bundled_mbtiles_path, {
            "bounds": ",".join(str(v) for v in bounds),
            "center": ",".join(str(v) for v in center),
            "crs": crs,
            "btp_schema_version": BTIS_SCHEMA_VERSION,
            "changelog_url": BTIS_CHANGELOG_URL_PLACEHOLDER,
        })
        delete_mbtiles_metadata(bundle.bundled_mbtiles_path, list(OVERRIDE_ONLY_DROPPED_METADATA_KEYS))

    # tile-join only accepts a -n name via its CLI; everything else in
    # `metadata` (description, attribution, tags, license, etc.) has to be
    # written directly. bounds/center/format are excluded here since
    # they're either handled above (bounds/center) or left to tile-join
    # itself (format).
    if bundle.metadata:
        descriptive_metadata = {
            k: v for k, v in bundle.metadata.items()
            if k not in TOOL_COMPUTED_METADATA_KEYS
        }
        write_mbtiles_metadata(bundle.bundled_mbtiles_path, descriptive_metadata)
