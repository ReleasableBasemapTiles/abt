#!/usr/bin/env python3
"""Stamp the real CRS onto mbtiles built through the reprojected path.

Those tiles hold coordinates in TARGET_SRS but are labelled EPSG:3857 so
tippecanoe passes them through untouched -- nothing in the file says what the
coordinates actually are. Writes only the `crs` key; bounds/center are left as
tippecanoe computed them.

  ./tag_crs.py 4087 building_polygon_4087.mbtiles [more ...]

Standard library only -- no abtv2-tools, no pyproj.
"""

import sqlite3
import sys
from pathlib import Path


def tag(path, epsg):
    con = sqlite3.connect(path)
    try:
        exists = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'metadata'"
        ).fetchone()
        if exists is None:
            sys.exit("{}: no metadata table -- not an mbtiles?".format(path))

        # DELETE then INSERT, not INSERT OR REPLACE: the latter only replaces when
        # metadata.name carries a UNIQUE constraint, and silently appends a second
        # row when it doesn't. This leaves exactly one crs row either way.
        with con:
            con.execute("DELETE FROM metadata WHERE name = 'crs'")
            con.execute(
                "INSERT INTO metadata (name, value) VALUES ('crs', ?)",
                ("EPSG:{}".format(epsg),),
            )
    finally:
        con.close()


def main(argv):
    if len(argv) < 3:
        sys.exit("usage: {} <epsg> <file.mbtiles> [file.mbtiles ...]".format(argv[0]))

    try:
        epsg = int(argv[1])
    except ValueError:
        sys.exit("epsg must be a number, got: {}".format(argv[1]))

    files = [Path(a) for a in argv[2:]]

    # Check every path up front; a half-tagged set is worse than none.
    missing = [str(f) for f in files if not f.is_file()]
    if missing:
        sys.exit("not found: " + ", ".join(missing))

    for f in files:
        tag(f, epsg)
        print("tagged {} as EPSG:{}".format(f, epsg))


if __name__ == "__main__":
    main(sys.argv)
