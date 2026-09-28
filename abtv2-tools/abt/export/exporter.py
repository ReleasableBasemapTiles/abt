"""
exporter.py

Runs the two-step tile export for a TileLayer: PostGIS -> FlatGeobuf
(ogr2ogr), then FlatGeobuf -> MBTiles (tippecanoe), so a re-run resumes
where an earlier one stopped.

Both steps write into a .partial/ subdirectory and move their output to the
final path only after the tool exits successfully, so a file at the final
path is always finished work. Neither tool's own output can be trusted
after an interruption: ogr2ogr streams a no-index FlatGeobuf, so a killed
run leaves a truncated file whose header still reads as valid (and
tippecanoe tiles whatever features are there, exiting 0); tippecanoe writes
tiles zoom by zoom, so a killed run leaves a tileset missing its top zooms.
The FlatGeobuf step is skipped if its output exists; the MBTiles step only
if its output is a finished tileset, which also discards a stub an earlier
version left at the final path -- see is_complete_tileset.
"""

import os
from pathlib import Path

from .tile_layer_model import TileLayer
from ..utils.logger import get_logger
from ..utils.subprocess_tools import run_subprocess
from .mbtiles_metadata import (
    crs_area_of_use_bounds,
    is_complete_tileset,
    write_mbtiles_metadata,
    delete_mbtiles_metadata,
    OVERRIDE_ONLY_DROPPED_METADATA_KEYS,
)


def _prepare_partial(partial: Path) -> Path:
    """Clears a partial output left by an interrupted run: neither tool can
    overwrite one (FlatGeobuf has no DeleteLayer, and tippecanoe exits
    EXIT_EXISTS without --force)."""
    partial.parent.mkdir(parents=True, exist_ok=True)
    partial.unlink(missing_ok=True)
    return partial


def export_to_fgb(layer: TileLayer) -> None:
    if layer.ogr_export_filename.exists():
        return
    partial = _prepare_partial(layer.ogr_partial_filename)
    run_subprocess(
        cmd=layer.ogr_cmd_for(partial),
        layer=layer.layer_id,
        process_stage="export_to_fgb",
        log_dir=layer.log_dir,
        tool_name="ogr2ogr",
    )
    os.replace(partial, layer.ogr_export_filename)


def export_to_mbtiles(layer: TileLayer) -> None:
    # Completeness, not existence: before outputs were staged in .partial/,
    # a failed run left a tile-less stub at the final path (see
    # is_complete_tileset), and skipping that would ship an empty layer.
    if not is_complete_tileset(layer.mbtiles_export_filename):
        if layer.mbtiles_export_filename.exists():
            # tippecanoe refuses to write to an existing output at all
            # (EXIT_EXISTS) unless --force, so the stub has to go before
            # there's any point retrying.
            get_logger(
                name=layer.layer_id,
                directory=layer.log_dir,
                process_stage="export_to_mbtiles",
            ).warning(
                f"Discarding incomplete {layer.mbtiles_export_filename.name} left by an "
                "earlier run and re-exporting it."
            )
            layer.mbtiles_export_filename.unlink()
        partial = _prepare_partial(layer.mbtiles_partial_filename)
        run_subprocess(
            cmd=layer.tippecanoe_cmd_for(partial),
            layer=layer.layer_id,
            process_stage="export_to_mbtiles",
            log_dir=layer.log_dir,
            tool_name="tippecanoe",
        )

        if layer.is_projection_override_active:
            # tippecanoe's own computed bounds/center (and
            # antimeridian_adjusted_bounds) are only meaningful for real
            # Web Mercator output -- see crs_area_of_use_bounds. When
            # overridden, tippecanoe's math is provably wrong, so replace
            # bounds/center with the target CRS's actual area of use and
            # drop the non-spec-required antimeridian field entirely.
            # Edited before the move, so the final path never holds a
            # tileset with tippecanoe's wrong bounds.
            bounds, center = crs_area_of_use_bounds(layer.projection_override_epsg_code)
            write_mbtiles_metadata(partial, {
                "bounds": ",".join(str(v) for v in bounds),
                "center": ",".join(str(v) for v in center),
                "crs": layer.projection_override,
            })
            delete_mbtiles_metadata(partial, list(OVERRIDE_ONLY_DROPPED_METADATA_KEYS))
        os.replace(partial, layer.mbtiles_export_filename)
