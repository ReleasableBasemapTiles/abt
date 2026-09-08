#!/usr/bin/env bash
# Export ONE Overture parquet file to ONE FlatGeobuf.
# Called once per input file by xargs/parallel.
#
# bash shard.sh <partsdir> <infile>
# Env: SHARD_THREADS, SHARD_MEM, SHARD_TMP, TARGET_SRS (4326 | any projected EPSG code, e.g. 3395, 4087) -- see README.md.
# TARGET_SRS != 4326 also requires ogr2ogr on PATH: DuckDB always writes plain
# WGS84 here, and the system GDAL/PROJ reprojects from there -- see the
# "Other projections" section of README.md for why DuckDB itself never
# reprojects.
set -euo pipefail

partsdir="${1:-parts}"
infile="$2"
name="$(basename "$infile" .zstd.parquet)"
out="${partsdir}/${name}.fgb"
# Suffixed with this process's PID: two concurrent workers can land on the
# same input file across two separate fetch.sh invocations (e.g. an
# orphaned run left over from an aborted init.sh), and without the PID both
# would target the identical temp path and destroy each other's in-progress
# output via the rm -rf below. fetch.sh's own lock (see lock.sh) is meant to
# prevent two invocations from running at all; this is the fallback if it
# doesn't.
duck_tmp="${partsdir}/.${name}.$$.tmp"          # DuckDB's raw COPY output (a directory -- see below)
wgs84_tmp="${partsdir}/.${name}.$$.wgs84.fgb"   # flattened WGS84 .fgb; the finished output when TARGET_SRS=4326
reproj_tmp="${partsdir}/.${name}.$$.reproj.fgb" # ogr2ogr's reprojected output, only used when TARGET_SRS != 4326

# Idempotent restart: skip anything already finished.
if [[ -s "$out" ]]; then
  echo "skip  $out"
  exit 0
fi
rm -rf "$duck_tmp" "$wgs84_tmp" "$reproj_tmp"
# PIDs get reused across separate runs, so a same-named leftover from a much
# earlier crash is still possible even though this run's own temp paths can't
# collide with a concurrent one. Cleans up on any exit (normal or error) so
# a failed/interrupted worker doesn't leave debris for the next run to trip
# over.
trap 'rm -rf "$duck_tmp" "$wgs84_tmp" "$reproj_tmp"' EXIT

# DuckDB spill space. Defaults alongside the parts dir (i.e. the data dir) rather
# than $PWD, so it lands on the big volume no matter where xargs was invoked from.
# Concurrent workers can share one directory; duckdb namespaces its temp files.
SHARD_TMP="${SHARD_TMP:-$(dirname "$partsdir")/duck_tmp}"
mkdir -p "$SHARD_TMP"

TARGET_SRS="${TARGET_SRS:-4326}"
if [[ "$TARGET_SRS" != "4326" && ! "$TARGET_SRS" =~ ^[0-9]+$ ]]; then
  echo "ERROR: TARGET_SRS must be 4326 or a numeric EPSG code (e.g. 3395, 4087), got '$TARGET_SRS'" >&2
  exit 1
fi
if [[ "$TARGET_SRS" != "4326" ]]; then
  command -v ogr2ogr >/dev/null 2>&1 || { echo "ERROR: ogr2ogr is required to reproject to EPSG:$TARGET_SRS but was not found on PATH" >&2; exit 1; }
fi

# DuckDB always writes plain WGS84 here, regardless of TARGET_SRS: its bundled
# PROJ predates PROJ 9.8's ellipsoidal +proj=eqc formulas (EPSG method 1028),
# so letting it reproject an EPSG:4087-style target itself disagrees with
# PostGIS's ST_Transform (used by the export path's --projection-override) by
# tens of kilometers -- see README.md. Reprojection for TARGET_SRS != 4326
# happens below instead, via the system ogr2ogr/PROJ -- the same engine
# family PostGIS runs on, so both paths agree.
duckdb -bail -dark-mode -c "
INSTALL spatial; LOAD spatial;
SET enable_progress_bar = false;        -- silence per-worker progress bars under xargs -P
SET geometry_always_xy = true;          -- correct axis order for ST_Area_Spheroid + GDAL
SET threads = ${SHARD_THREADS:-4};      -- per-process; keep small since many run at once
SET memory_limit = '${SHARD_MEM:-8GB}';  -- per-process ceiling; default is ~80% of SYSTEM ram,
                                        -- which N concurrent workers would each claim in full
SET temp_directory = '${SHARD_TMP}';   -- spill here instead of duckdb's default
SET preserve_insertion_order = false;
COPY (
    WITH b AS (
        SELECT
            id,
            names.primary               AS name,
            subtype,
            class,
            has_parts,
            height,
            ST_Area_Spheroid(geometry)  AS area,               -- true ground area, m^2 (always from source WGS84 geometry)
            ST_Multi(geometry)          AS geometry             -- uniform MultiPolygon, WGS84 -- see comment above
        FROM read_parquet('${infile}')
    )
    SELECT * FROM b
    WHERE area >= 1                                      -- drop degenerate sub-meter polygons
) TO '${duck_tmp}'
WITH (FORMAT GDAL, DRIVER 'FlatGeobuf', SRS 'EPSG:4326', LAYER_CREATION_OPTIONS 'SPATIAL_INDEX=NO');
"

# DuckDB's GDAL FlatGeobuf writer creates $duck_tmp as a directory containing
# the real single-layer .fgb (nested one level down). Pull that inner file up
# to a flat $wgs84_tmp so both ogr2ogr below and tippecanoe (in the
# TARGET_SRS=4326 case, once moved onto $out) can mmap it directly.
if [[ -d "$duck_tmp" ]]; then
  inner="$(find "$duck_tmp" -maxdepth 1 -type f | head -n1)"
  [[ -n "$inner" ]] || { echo "ERROR: no file inside $duck_tmp" >&2; exit 1; }
  mv -f "$inner" "$wgs84_tmp"      # same-filesystem move = atomic
  rm -rf "$duck_tmp"
else
  mv -f "$duck_tmp" "$wgs84_tmp"
fi

if [[ "$TARGET_SRS" == "4326" ]]; then
  mv -f "$wgs84_tmp" "$out"      # already the target projection; same-filesystem move = atomic
else
  # -t_srs writes the honest EPSG:$TARGET_SRS header (tippecanoe ignores a
  # FlatGeobuf's header CRS regardless -- see README.md -- so this is purely
  # for any other tool, e.g. ogrinfo, that reads these shards directly).
  ogr2ogr -f FlatGeobuf -s_srs EPSG:4326 -t_srs "EPSG:${TARGET_SRS}" \
    -lco SPATIAL_INDEX=NO "$reproj_tmp" "$wgs84_tmp"
  mv -f "$reproj_tmp" "$out"     # same-filesystem move = atomic
  rm -f "$wgs84_tmp"
fi
echo "done  $out"
