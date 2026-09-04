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
  # .btis, not .mbtiles: the file is sqlite in the usual layout, but the tiles are
  # not web mercator, so the extension keeps it from being consumed as one.
  PARTSDIR="$OUTDIR/parts_$SRS"
  OUT="$OUTDIR/building_polygon_$SRS.btis"
  PROJ_FLAG=(--projection=EPSG:3857)
fi

mkdir -p "$OUTDIR/tippe_temp"

tippecanoe \
  -o "$OUT" \
  -l building_polygon \
  -n "Releasable Basemap Tiles (RBT) - Buildings" \
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

# Reprojected builds claim EPSG:3857 in the mbtiles header, so nothing downstream
# can tell what the coordinates really are. Stamp the true CRS plus bounds/center
# for it. Invoked via the interpreter so a missing exec bit can't break the build.
if [[ "$SRS" != "3857" ]]; then
  "${PYTHON:-python3}" tag_crs.py "$SRS" "$OUT"
fi
