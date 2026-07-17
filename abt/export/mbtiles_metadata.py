"""
mbtiles_metadata.py

Reads and writes rows in an mbtiles/btis file's `metadata` table, and looks
up a CRS's real-world area of use. Used by TileLayer/Bundler in
tile_layer_model.py to keep BTIS metadata (crs, bounds, center) correct under
--projection-override -- see crs_area_of_use_bounds for why tippecanoe/
tile-join's own computed bounds/center can't be trusted in that case.
"""

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pyproj import CRS

# BTIS (Basemap Tile Package) metadata per NGA.IS.0081-1
BTIS_SCHEMA_VERSION = "1.0.0"
BTIS_CHANGELOG_URL_PLACEHOLDER = "TBD"

TOOL_COMPUTED_METADATA_KEYS = {"bounds", "center", "format"}
OVERRIDE_ONLY_DROPPED_METADATA_KEYS = {"antimeridian_adjusted_bounds"}

DEFAULT_CENTER_ZOOM = 2


def crs_area_of_use_bounds(epsg_code: int) -> Tuple[List[float], List[float]]:
    """
    Looks up the full area-of-use extent for an EPSG code via pyproj/PROJ, and
    returns (bounds, center) in mbtiles-metadata format
    ([west, south, east, north], [lon, lat, zoom]).
    """
    area_of_use = CRS.from_epsg(epsg_code).area_of_use
    west, south, east, north = area_of_use.bounds
    center = [(west + east) / 2, (south + north) / 2, DEFAULT_CENTER_ZOOM]
    return [west, south, east, north], center


def read_mbtiles_crs(path: Path) -> Optional[str]:
    """
    Reads the `crs` metadata row from an mbtiles/btis file
    """
    if not path.exists():
        return None
    con = sqlite3.connect(path)
    try:
        row = con.execute("SELECT value FROM metadata WHERE name = 'crs'").fetchone()
        return row[0] if row else None
    finally:
        con.close()


def resolve_crs_from_files(paths: List[Path]) -> Optional[str]:
    """
    Determines the CRS shared by every given mbtiles/btis file, by reading
    each one's own `crs` metadata row rather than requiring
    --projection-override to be passed again (export and bundling are often
    separate invocations). Returns None when every input is plain Web
    Mercator. Raises if inputs disagree, since treating tiles built with
    different projections as one dataset would be geographically broken.
    """
    crs_by_file = {p.name: read_mbtiles_crs(p) for p in paths}
    distinct = set(crs_by_file.values())
    if len(distinct) > 1:
        details = ", ".join(
            f"{name}={crs or 'EPSG:3857 (default)'}" for name, crs in crs_by_file.items()
        )
        raise ValueError(f"Files were built with different projections: {details}")
    return next(iter(distinct), None)


def write_mbtiles_metadata(mbtiles_path: Path, metadata: Dict[str, Any]) -> None:
    """
    Writes (or overwrites) rows in an mbtiles/btis file's `metadata` table.
    """
    con = sqlite3.connect(mbtiles_path)
    try:
        rows = [
            (k, v if isinstance(v, str) else json.dumps(v))
            for k, v in metadata.items()
        ]
        con.executemany(
            "INSERT OR REPLACE INTO metadata (name, value) VALUES (?, ?)",
            rows,
        )
        con.commit()
    finally:
        con.close()


def delete_mbtiles_metadata(mbtiles_path: Path, keys: List[str]) -> None:
    """Removes the given rows from an mbtiles/btis file's `metadata` table, if present."""
    con = sqlite3.connect(mbtiles_path)
    try:
        con.executemany("DELETE FROM metadata WHERE name = ?", [(k,) for k in keys])
        con.commit()
    finally:
        con.close()
