#!/usr/bin/env python3
"""Stamp the real CRS onto mbtiles built through the reprojected path.

Those tiles hold coordinates in TARGET_SRS but are labelled EPSG:3857 so
tippecanoe passes them through untouched -- nothing in the file says what the
coordinates actually are. Downstream needs that, plus bounds/center matching the
CRS rather than the whole-world defaults tippecanoe computes.

  ./tag_crs.py 4087 building_polygon_4087.mbtiles contours_4087.mbtiles

Env: ABT_TOOLS -- checkout holding abt.export (default /raid/rbt/abtv2-tools)
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, os.environ.get("ABT_TOOLS", "/raid/rbt/abtv2-tools"))

from abt.export.mbtiles_metadata import crs_area_of_use_bounds, write_mbtiles_metadata


def main(argv):
    if len(argv) < 3:
        sys.exit("usage: {} <epsg> <file.mbtiles> [file.mbtiles ...]".format(argv[0]))

    epsg = int(argv[1])
    files = [Path(a) for a in argv[2:]]

    # Check every path up front; a half-tagged set is worse than none.
    missing = [str(f) for f in files if not f.is_file()]
    if missing:
        sys.exit("not found: " + ", ".join(missing))

    bounds, center = crs_area_of_use_bounds(epsg)

    for f in files:
        write_mbtiles_metadata(f, {
            "bounds": ",".join(str(v) for v in bounds),
            "center": ",".join(str(v) for v in center),
            "crs": "EPSG:{}".format(epsg),
        })
        print("tagged {} as EPSG:{}".format(f, epsg))


if __name__ == "__main__":
    main(sys.argv)
