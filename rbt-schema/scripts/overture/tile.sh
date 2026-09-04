#!/usr/bin/env bash

#./tile.sh /path/to/data_dir [srs]   srs: 3857 (default) | any reprojected code, e.g. 3395, 4087
# See README.md for what the reprojected path does.
# Env: CLEAN_PARTS (default false -- delete this projection's .fgb shards once
#      tiling succeeds), PYTHON (interpreter used for tag_crs.py)

set -euo pipefail
cd "$(dirname "$0")"
source ./lock.sh

OUTDIR="${1:-./data}"
SRS="${2:-3857}"

if [[ "$SRS" != "3857" && ! "$SRS" =~ ^[0-9]+$ ]]; then
  echo "ERROR: srs must be 3857 or a numeric EPSG code (e.g. 3395, 4087), got '$SRS'" >&2
  exit 1
fi

# Shared, not exclusive: two tile.sh runs for different projections read
# disjoint parts_<srs> dirs and write disjoint outputs (see PARTSDIR/OUT
# below), so running them concurrently has always been safe -- and is
# exactly what README.md documents doing. A shared lock still blocks any
# overlap with fetch.sh's exclusive lock, which is the actual hazard.
acquire_overture_lock "$OUTDIR" shared

OUT="$OUTDIR/building_polygon_$SRS.mbtiles"
if [[ "$SRS" == "3857" ]]; then
  PARTSDIR="$OUTDIR/parts"
  PROJ_FLAG=()
else
  # Parts were already reprojected to EPSG:$SRS by shard.sh and tagged 3857;
  # --projection=EPSG:3857 tells tippecanoe to take them as-is.
  PARTSDIR="$OUTDIR/parts_$SRS"
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

# Opt-in: drop the .fgb shards this build just consumed. A planet parts dir runs
# to hundreds of GB and there is one per projection, so they are usually the
# pipeline's dominant disk cost once the .mbtiles exists. Deliberately the
# last thing here: under set -e a failed tippecanoe or tag_crs.py never reaches
# it, leaving the shards in place to retry from. Nothing regenerates them, so a
# later re-run of this projection has to re-shard (fetch.sh / shard.sh) first.
if [[ "${CLEAN_PARTS:-false}" == true && -d "$PARTSDIR" ]]; then
  echo "cleaning $PARTSDIR"
  rm -rf "$PARTSDIR"
fi
