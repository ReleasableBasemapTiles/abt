"""
exporter.py

Runs the two-step tile export for a TileLayer: PostGIS -> FlatGeobuf
(ogr2ogr), then FlatGeobuf -> MBTiles (tippecanoe), so a re-run resumes
where an earlier one stopped. The FlatGeobuf step is skipped if its output
exists; the MBTiles step only if its output is a *finished* tileset, since
tippecanoe leaves a stub behind when it fails -- see is_complete_tileset.
"""

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


def export_to_fgb(layer: TileLayer) -> None:
    if not layer.ogr_export_filename.exists():
        run_subprocess(
            cmd=layer.ogr_cmd,
            layer=layer.layer_id,
            process_stage="export_to_fgb",
            log_dir=layer.log_dir,
            tool_name="ogr2ogr",
        )


def export_to_mbtiles(layer: TileLayer) -> None:
    # Completeness, not existence: an interrupted earlier run leaves a
    # tile-less output file behind (see is_complete_tileset), and skipping
    # that would ship an empty layer.
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
        run_subprocess(
            cmd=layer.tippecanoe_cmd,
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
            bounds, center = crs_area_of_use_bounds(layer.projection_override_epsg_code)
            write_mbtiles_metadata(layer.mbtiles_export_filename, {
                "bounds": ",".join(str(v) for v in bounds),
                "center": ",".join(str(v) for v in center),
                "crs": layer.projection_override,
            })
            delete_mbtiles_metadata(layer.mbtiles_export_filename, list(OVERRIDE_ONLY_DROPPED_METADATA_KEYS))
