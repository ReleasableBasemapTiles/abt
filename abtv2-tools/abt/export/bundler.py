"""
bundler.py

Runs the tile-join bundling step for a Bundler: joins all per-layer mbtiles
into one package and writes BTIS/descriptive metadata into the result.
"""

from pathlib import Path
from typing import List
import sqlite3

from .bundler_model import Bundler
from ..utils.logger import get_logger
from ..utils.subprocess_tools import run_subprocess
from .mbtiles_metadata import (
    BTIS_SCHEMA_VERSION,
    BTIS_CHANGELOG_URL_PLACEHOLDER,
    TOOL_COMPUTED_METADATA_KEYS,
    OVERRIDE_ONLY_DROPPED_METADATA_KEYS,
    TIPPECANOE_BUILD_METADATA_KEYS,
    crs_area_of_use_bounds,
    resolve_crs_from_files,
    write_mbtiles_metadata,
    delete_mbtiles_metadata,
    strip_json_tilestats,
)


def _trim_mbtiles(src: Path, dst: Path, max_zoom: int) -> None:
    """Copies tiles with zoom_level <= max_zoom from src into a new dst mbtiles.

    Uses ATTACH + INSERT INTO ... SELECT so the transfer stays inside
    SQLite's C layer with no Python row iteration overhead. `src` is bound
    as a query parameter rather than interpolated into the ATTACH
    statement, so a source path containing a quote can't break it.
    """
    if dst.exists():
        dst.unlink()
    con = sqlite3.connect(dst)
    try:
        con.execute("PRAGMA synchronous = OFF")
        con.execute("PRAGMA journal_mode = MEMORY")
        con.execute("ATTACH DATABASE ? AS src", (str(src),))
        try:
            con.execute(
                "CREATE TABLE tiles "
                "(zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_data BLOB)"
            )
            con.execute(
                "INSERT INTO tiles "
                "SELECT zoom_level, tile_column, tile_row, tile_data "
                "FROM src.tiles WHERE zoom_level <= ?",
                (max_zoom,),
            )
            con.execute(
                "CREATE UNIQUE INDEX tiles_idx ON tiles (zoom_level, tile_column, tile_row)"
            )

            # Not every input has a metadata table -- a user-supplied
            # --additional-mbtiles file may not have one at all -- so check
            # before copying rather than assuming it's always present.
            has_metadata = con.execute(
                "SELECT count(*) FROM src.sqlite_master WHERE name = 'metadata' AND type = 'table'"
            ).fetchone()[0] == 1
            con.execute("CREATE TABLE metadata (name TEXT, value TEXT)")
            con.execute("CREATE UNIQUE INDEX metadata_name_idx ON metadata (name)")
            if has_metadata:
                con.execute(
                    "INSERT OR REPLACE INTO metadata (name, value) "
                    "SELECT name, value FROM src.metadata"
                )
            # OR REPLACE (backed by the unique index above) rather than an
            # UPDATE, which would silently no-op when the source has no
            # maxzoom row at all -- the trimmed copy's own maxzoom should
            # always reflect the cap just applied, regardless of source.
            con.execute(
                "INSERT OR REPLACE INTO metadata (name, value) VALUES ('maxzoom', ?)",
                (str(max_zoom),),
            )
            con.commit()
        finally:
            con.execute("DETACH DATABASE src")
    finally:
        con.close()


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

    # When max_zoom is set (e.g. for an RBT Small package), pre-trim every
    # input to a zoom-capped copy using SQLite (fast indexed read), then
    # tile-join the small trimmed files instead of the full-resolution
    # originals. This avoids tile-join scanning the full dataset just to
    # filter by zoom. Trimmed copies are named with a positional prefix,
    # not just src.name -- tile_list can combine per-layer files from
    # different directories with additional_mbtiles, so two inputs could
    # otherwise share a basename and overwrite each other in _tmp.
    tile_files = bundle.tile_list
    trimmed_files: List[Path] = []
    try:
        if bundle.max_zoom is not None:
            logger = get_logger("trim", bundle.bundled_dir, "bundler")
            tmp_dir = bundle.bundled_mbtiles_tmp
            for i, src in enumerate(tile_files):
                dst = tmp_dir / f"{i:03d}_{src.name}"
                trimmed_files.append(dst)
                logger.info(f"Trimming {src.name} to z{bundle.max_zoom} ({i + 1}/{len(tile_files)})")
                _trim_mbtiles(src, dst, bundle.max_zoom)
            tile_files = trimmed_files

        run_subprocess(
            cmd=bundle.build_tile_join_cmd(tile_files),
            layer="joined",
            process_stage="bundler",
            log_dir=bundle.bundled_dir,
            tool_name="tile-join",
        )
    finally:
        for f in trimmed_files:
            f.unlink(missing_ok=True)

    set_pragma_options(bundle)

    # tile-join always writes its own build-provenance rows (generator,
    # generator_options -- its full command line, one path per input layer,
    # which can run into the megabytes -- and strategies) into the joined
    # output. None of it is useful in a shipped package, so it's stripped
    # unconditionally here rather than left for a manual cleanup pass.
    delete_mbtiles_metadata(bundle.bundled_mbtiles_path, list(TIPPECANOE_BUILD_METADATA_KEYS))
    strip_json_tilestats(bundle.bundled_mbtiles_path)

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
    elif bundle.metadata and "center" in bundle.metadata:
        # No projection override, so tile-join's own bounds are legitimate
        # Web Mercator math and are left alone. Its computed *center*,
        # though, is just wherever the densest tile content happened to
        # land (e.g. a random z13 tile) -- not a meaningful default view for
        # a released package. When the schema declares one, it wins.
        declared_center = ",".join(str(v) for v in bundle.metadata["center"])
        write_mbtiles_metadata(bundle.bundled_mbtiles_path, {"center": declared_center})

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
