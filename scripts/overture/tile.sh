#!/usr/bin/env bash

#./tile.sh /path/to/data_dir [srs]   srs: 3857 (default) | any reprojected code, e.g. 3395, 4087
# See README.md for what the reprojected path does.

set -euo pipefail
cd "$(dirname "$0")"

OUTDIR="${1:-./data}"
SRS="${2:-3857}"

if [[ "$SRS" == "3857" ]]; then
  PARTSDIR="$OUTDIR/parts"
  OUT="$OUTDIR/building_polygon_3857.mbtiles"
  PROJ_FLAG=()
else
  # Parts were already reprojected to EPSG:$SRS by shard.sh and tagged 3857;
  # --projection=EPSG:3857 tells tippecanoe to take them as-is.
  PARTSDIR="$OUTDIR/parts_$SRS"
  OUT="$OUTDIR/building_polygon_$SRS.mbtiles"
  PROJ_FLAG=(--projection=EPSG:3857)
fi

mkdir -p "$OUTDIR/tippe_temp"

tippecanoe \
  -o "$OUT" \
  -l building_polygon \
  -P \
  --temporary-directory "$OUTDIR/tippe_temp" \
  -y area -y subtype -y class -y has_parts -y height \
  -T area:int -T has_parts:bool -T height:int \
  --minimum-zoom=11 \
  --maximum-zoom=13 \
  --extra-detail=14 \
  --no-tiny-polygon-reduction-at-maximum-zoom \
  --no-feature-limit \
  --no-tile-size-limit \
  -j '{"*":["any",
        ["all",[">=","$zoom",11],[">=","area",40000]],
        ["all",[">=","$zoom",12],[">=","area",6400]],
        [">=","$zoom",13]]}' \
  --force \
  "${PROJ_FLAG[@]}" \
  "$PARTSDIR"/*.fgb
