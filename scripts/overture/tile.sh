#!/usr/bin/env bash

#./tile.sh /path/to/data_dir

set -euo pipefail
cd "$(dirname "$0")"

OUTDIR="${1:-./data}"

mkdir -p "$OUTDIR/tippe_temp"

tippecanoe \
  -o "$OUTDIR/building_polygon.mbtiles" \
  -l building_polygon \
  -P \
  --temporary-directory "$OUTDIR/tippe_temp" \
  -y area -y subtype -y has_parts \
  -T area:int -T has_parts:bool \
  --minimum-zoom=11 \
  --maximum-zoom=13 \
  --simplify-only-low-zooms \
  --no-tiny-polygon-reduction-at-maximum-zoom \
  --no-feature-limit \
  --no-tile-size-limit \
  -j '{"*":["any",
        ["all",[">=","$zoom",11],[">=","area",40000]],
        ["all",[">=","$zoom",12],[">=","area",6400]],
        [">=","$zoom",13]]}' \
  --force \
  "$OUTDIR"/parts/*.fgb
