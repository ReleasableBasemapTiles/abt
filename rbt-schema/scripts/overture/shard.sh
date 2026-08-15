#!/usr/bin/env bash
# Export ONE Overture parquet file to ONE FlatGeobuf.
# Called once per input file by xargs/parallel.
#
# bash shard.sh <partsdir> <infile>
# Env: SHARD_THREADS, TARGET_SRS (4326|3395) -- see README.md
set -euo pipefail

partsdir="${1:-parts}"
infile="$2"
name="$(basename "$infile" .zstd.parquet)"
out="${partsdir}/${name}.fgb"
tmp="${partsdir}/.${name}.tmp"

# Idempotent restart: skip anything already finished.
if [[ -s "$out" ]]; then
  echo "skip  $out"
  exit 0
fi
rm -rf "$tmp"

TARGET_SRS="${TARGET_SRS:-4326}"
if [[ "$TARGET_SRS" == "3395" ]]; then
  geom_expr="ST_Transform(geometry, 'EPSG:4326', 'EPSG:3395')"
  out_srs="EPSG:3857"
else
  geom_expr="geometry"
  out_srs="EPSG:4326"
fi

duckdb -bail -dark-mode -c "
INSTALL spatial; LOAD spatial;
SET enable_progress_bar = false;        -- silence per-worker progress bars under xargs -P
SET geometry_always_xy = true;          -- correct axis order for ST_Area_Spheroid + GDAL
SET threads = ${SHARD_THREADS:-4};      -- per-process; keep small since many run at once
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