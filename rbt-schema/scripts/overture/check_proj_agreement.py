#!/usr/bin/env python3
"""Check that every PROJ build touching this pipeline agrees on non-3857
reprojections, before hours of --overture/--projections work run on
possibly-wrong coordinates.

Background: PROJ 9.8.0 added the ellipsoidal Equidistant Cylindrical method
(EPSG:1028) -- see https://github.com/OSGeo/PROJ/issues/4654 -- and older
PROJ silently keeps using the spherical method (EPSG:1029) instead. The two
disagree by tens of kilometers in northing for EPSG:4087-style codes. DuckDB
(as of duckdb 1.5.5) still bundles PROJ 9.1.1, well before that fix, which is
exactly why shard.sh no longer lets DuckDB reproject non-4326 targets itself
-- see this directory's README.md. Whatever GDAL/PROJ this script's own
pyproj and Postgres's PostGIS extension link against may or may not be new
enough either, especially since they're typically installed through
completely different channels (a conda env vs. the OS package manager) that
drift independently. This script transforms a handful of fixed control
points through every engine it can reach and fails loudly if any of them
disagree, rather than letting the mismatch surface only as misaligned tiles
hours into a planet build.

Requires pyproj and psycopg2 (both abtv2-tools env dependencies -- run this
under that environment's python, same as the rest of abtv2-tools, e.g. via
`micromamba run -n abtv2`). The DuckDB and PostGIS checks are each skipped,
with a printed note, when that engine isn't reachable (duckdb not on PATH,
or the standard PG* environment variables aren't set / the database refuses
the connection) -- deliberately not a hard dependency on either, so this
still runs standalone against just pyproj's own PROJ.

  ./check_proj_agreement.py 4087 [3395 ...]

Env:
  PROJ_AGREEMENT_TOLERANCE_M  max allowed disagreement in metres (default 0.001)
"""

import csv
import io
import os
import shutil
import subprocess
import sys
from typing import Dict, List, Optional, Tuple

import psycopg2
import pyproj
from pyproj import Transformer

# Longitude is fixed at 0 -- eqc-style projections have zero easting there at
# every latitude, so any nonzero easting a broken engine reports is itself a
# tell (see the axis-order trap noted in duckdb_values below). Latitudes span
# equator to near-polar, since the ellipsoidal-vs-spherical divergence this
# guards against is latitude-dependent (zero at the equator, largest around
# 50-60 degrees -- see README.md).
CONTROL_LATITUDES: Tuple[float, ...] = (0.0, 30.0, 45.0, 60.0, 84.0)
CONTROL_LONGITUDE = 0.0
DEFAULT_TOLERANCE_M = 0.001

# lat -> (x, y)
PointMap = Dict[float, Tuple[float, float]]
# (points, engine's own PROJ version string, reason this engine was skipped)
# -- exactly one of (points, version) or reason is populated.
EngineResult = Tuple[Optional[PointMap], Optional[str], Optional[str]]


def pyproj_reference(epsg: int) -> PointMap:
    """Transforms every control point via this process's own pyproj/PROJ."""
    transformer = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True)
    return {
        lat: transformer.transform(CONTROL_LONGITUDE, lat)
        for lat in CONTROL_LATITUDES
    }


def _run_duckdb(sql: str) -> Optional[List[Tuple[str, ...]]]:
    """Runs `sql` via the duckdb CLI, returning parsed CSV rows of raw string
    fields (callers convert whichever columns they expect to be numeric), or
    None if the binary is missing, times out, or exits non-zero."""
    try:
        proc = subprocess.run(
            ["duckdb", "-csv", "-noheader", "-c", sql],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"    duckdb invocation failed: {exc}", file=sys.stderr)
        return None
    if proc.returncode != 0:
        print(f"    duckdb exited {proc.returncode}: {proc.stderr.strip()}", file=sys.stderr)
        return None
    return [tuple(row) for row in csv.reader(io.StringIO(proc.stdout)) if row]


def duckdb_values(epsg: int) -> EngineResult:
    """Transforms every control point via the `duckdb` CLI's bundled spatial/PROJ.

    Kept as a regression trip-wire for shard.sh's own reprojection path --
    see this module's docstring -- rather than because DuckDB still does any
    reprojection in production today.
    """
    if shutil.which("duckdb") is None:
        return None, None, "duckdb not found on PATH"

    values_sql = ", ".join(f"({lat})" for lat in CONTROL_LATITUDES)
    # geometry_always_xy=true is not optional here: without it, DuckDB takes
    # ST_Point(lon, lat)'s two arguments as EPSG:4326's own officially-defined
    # (latitude, longitude) axis order instead of (x, y) -- silently swapping
    # every point's lat/lon before it ever reaches PROJ. Same setting shard.sh
    # itself sets, for the same reason.
    query = f"""
LOAD spatial;
SET geometry_always_xy = true;
SELECT lat,
       ST_X(ST_Transform(ST_Point({CONTROL_LONGITUDE}, lat), 'EPSG:4326', 'EPSG:{epsg}')) AS x,
       ST_Y(ST_Transform(ST_Point({CONTROL_LONGITUDE}, lat), 'EPSG:4326', 'EPSG:{epsg}')) AS y
FROM (VALUES {values_sql}) AS t(lat);
"""
    rows = _run_duckdb(query)
    if rows is None:
        return None, None, "duckdb query failed (see stderr above)"
    points = {float(lat): (float(x), float(y)) for lat, x, y in rows}

    version_rows = _run_duckdb("LOAD spatial; SELECT DuckDB_Proj_Version();")
    version = version_rows[0][0] if version_rows else "unknown"
    return points, version, None


def postgis_values(epsg: int) -> EngineResult:
    """Transforms every control point via Postgres/PostGIS's own ST_Transform.

    Reads the standard PG* environment variables directly (matching init.sh's
    own exports) rather than importing abtv2-tools' PGConfig, keeping this
    pipeline's scripts independent of it -- see tag_crs.py's own "no
    abtv2-tools" note.
    """
    env_vars = {
        "host": os.environ.get("PGHOST"),
        "port": os.environ.get("PGPORT"),
        "user": os.environ.get("PGUSER"),
        "password": os.environ.get("PGPASSWORD"),
        "dbname": os.environ.get("PGDATABASE"),
    }
    missing = [k.upper() for k, v in env_vars.items() if not v]
    if missing:
        return None, None, f"PG* environment variables not set: {', '.join(missing)}"

    try:
        conn = psycopg2.connect(connect_timeout=5, **env_vars)
    except psycopg2.OperationalError as exc:
        return None, None, f"could not connect to Postgres: {exc}".strip()

    try:
        with conn, conn.cursor() as cur:
            cur.execute("SELECT postgis_proj_version();")
            version = cur.fetchone()[0]
            cur.execute(
                "SELECT lat, ST_X(pt), ST_Y(pt) FROM ("
                "  SELECT lat, ST_Transform(ST_SetSRID(ST_MakePoint(%s, lat), 4326), %s) AS pt"
                "  FROM unnest(%s::float8[]) AS lat"
                ") sub;",
                (CONTROL_LONGITUDE, epsg, list(CONTROL_LATITUDES)),
            )
            points = {lat: (x, y) for lat, x, y in cur.fetchall()}
        return points, version, None
    except psycopg2.Error as exc:
        return None, None, f"query failed: {exc}".strip()
    finally:
        conn.close()


def compare(reference: PointMap, other: PointMap, tolerance: float) -> List[Tuple[float, float, float]]:
    """Returns (lat, dx, dy) for every control point where `other` differs
    from `reference` by more than `tolerance` metres in either axis."""
    mismatches = []
    for lat, (rx, ry) in reference.items():
        ox, oy = other[lat]
        dx, dy = ox - rx, oy - ry
        if abs(dx) > tolerance or abs(dy) > tolerance:
            mismatches.append((lat, dx, dy))
    return mismatches


def check_epsg(epsg: int, tolerance: float) -> bool:
    """Checks one EPSG code across every reachable engine against pyproj.
    Returns True if every reachable engine agrees within `tolerance`."""
    print(f"[check_proj_agreement] EPSG:{epsg} (pyproj/PROJ {pyproj.proj_version_str}, tolerance {tolerance}m)")
    reference = pyproj_reference(epsg)
    ok = True

    for engine_name, fetch in (("duckdb", duckdb_values), ("postgis", postgis_values)):
        points, version, skip_reason = fetch(epsg)
        if skip_reason is not None:
            print(f"  {engine_name}: skipped ({skip_reason})")
            continue
        mismatches = compare(reference, points, tolerance)
        if mismatches:
            ok = False
            print(f"  {engine_name} (PROJ {version}): MISMATCH vs pyproj/PROJ {pyproj.proj_version_str}")
            for lat, dx, dy in mismatches:
                print(f"    lat={lat:>5.1f}  dx={dx:+.3f}m  dy={dy:+.3f}m")
            print(
                "    PROJ 9.8.0 added the ellipsoidal Equidistant Cylindrical method "
                "(EPSG:1028) -- https://github.com/OSGeo/PROJ/issues/4654 -- one of "
                "these two engines is likely older than that."
            )
        else:
            print(f"  {engine_name} (PROJ {version}): OK")

    return ok


def main(argv: List[str]) -> int:
    if len(argv) < 2:
        sys.exit(f"usage: {argv[0]} <epsg> [epsg ...]")

    try:
        epsg_codes = [int(a) for a in argv[1:]]
    except ValueError:
        sys.exit(f"epsg codes must be numeric, got: {' '.join(argv[1:])}")

    tolerance = float(os.environ.get("PROJ_AGREEMENT_TOLERANCE_M", DEFAULT_TOLERANCE_M))

    all_ok = True
    for epsg in epsg_codes:
        if not check_epsg(epsg, tolerance):
            all_ok = False

    if not all_ok:
        print("ERROR: PROJ disagreement detected -- see MISMATCH lines above.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
