#!/usr/bin/env bash
# Export ONE Overture parquet file to ONE FlatGeobuf.
# Called once per input file by xargs/parallel.
#
# bash shard.sh <partsdir> <infile>
# Env: SHARD_THREADS, SHARD_MEM, SHARD_TMP, TARGET_SRS (4326 | any projected EPSG code, e.g. 3395, 4087) -- see README.md
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
tmp="${partsdir}/.${name}.$$.tmp"

# Idempotent restart: skip anything already finished.
if [[ -s "$out" ]]; then
  echo "skip  $out"
  exit 0
fi
rm -rf "$tmp"
# PIDs get reused across separate runs, so a same-named leftover from a much
# earlier crash is still possible even though this run's own $tmp can't
# collide with a concurrent one. Cleans up on any exit (normal or error) so
# a failed/interrupted worker doesn't leave debris for the next run to trip
# over.
trap 'rm -rf "$tmp"' EXIT

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
if [[ "$TARGET_SRS" == "4326" ]]; then
  geom_expr="geometry"
  out_srs="EPSG:4326"
else
  geom_expr="ST_Transform(geometry, 'EPSG:4326', 'EPSG:${TARGET_SRS}')"
  # Deliberate mislabel: the coords really are EPSG:${TARGET_SRS} metres, but tagging
  # them 3857 stops tippecanoe (run with --projection=EPSG:3857) reprojecting again.
  out_srs="EPSG:3857"
fi

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
            ST_Multi(${geom_expr})      AS geometry             -- uniform MultiPolygon, possibly reprojected
        FROM read_parquet('${infile}')
    )
    SELECT * FROM b
    WHERE area >= 1                                      -- drop degenerate sub-meter polygons
) TO '${tmp}'
WITH (FORMAT GDAL, DRIVER 'FlatGeobuf', SRS '${out_srs}', LAYER_CREATION_OPTIONS 'SPATIAL_INDEX=NO');
"

# DuckDB's GDAL FlatGeobuf writer creates $tmp as a directory containing the
# real single-layer .fgb (nested one level down). Pull that inner file up to a
# flat $out so tippecanoe can mmap it directly. 
if [[ -d "$tmp" ]]; then
  inner="$(find "$tmp" -maxdepth 1 -type f | head -n1)"
  [[ -n "$inner" ]] || { echo "ERROR: no file inside $tmp" >&2; exit 1; }
  mv -f "$inner" "$out"      # same-filesystem move = atomic
  rm -rf "$tmp"
else
  mv -f "$tmp" "$out"
fi
echo "done  $out"