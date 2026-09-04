#!/usr/bin/env bash

#./fetch.sh /path/to/data_dir [jobs] [shard_threads]
# See README.md for pipeline order and tuning guidance.
# Env:
#   SRS_LIST         space-separated output projections to shard, e.g.
#                    "3857 3395 4087" (default: "3857"). One shard.sh pass
#                    over every parquet file per entry -- see README.md.
#   OVERTURE_RELEASE  pin a specific release instead of always taking the
#                    newest on S3 (also skips the `aws s3 ls` lookup below).

set -euo pipefail
cd "$(dirname "$0")"
source ./lock.sh

RELEASE="${OVERTURE_RELEASE:-$(aws s3 ls --no-sign-request s3://overturemaps-us-west-2/release/ | awk '{print $2}' | tr -d '/' | sort | tail -1)}"
OUTDIR="${1:-./data}"
JOBS="${2:-128}"
export SHARD_THREADS="${3:-1}"

echo "release: $RELEASE"
mkdir -p "$OUTDIR"

# Exclusive: this is the only writer to the shared parts dirs below, and a
# second concurrent writer (e.g. a run started twice, or an orphaned job
# left over from an aborted init.sh) is what corrupts shard.sh's temp files
# -- see lock.sh and shard.sh. Fails fast rather than blocking.
acquire_overture_lock "$OUTDIR" exclusive

# `aws s3 sync` below only adds/updates files for $RELEASE -- it won't remove
# a *different*, previously-fetched release's parquet already sitting in
# $OUTDIR/overture-buildings/. Re-running into a data_dir last populated from
# another release would silently shard a mix of both. Fail instead of
# guessing which one the operator wants; RELEASE is written only after this
# check passes.
if [[ -s "$OUTDIR/RELEASE" ]]; then
  PREV_RELEASE="$(cat "$OUTDIR/RELEASE")"
  if [[ "$PREV_RELEASE" != "$RELEASE" ]]; then
    echo "ERROR: $OUTDIR/RELEASE was built from release $PREV_RELEASE, but this run resolved $RELEASE." >&2
    echo "       Re-run with OVERTURE_RELEASE=$PREV_RELEASE to keep using it, or clear $OUTDIR to start over." >&2
    exit 1
  fi
fi
echo "$RELEASE" > "$OUTDIR/RELEASE"

aws s3 sync --no-sign-request \
  s3://overturemaps-us-west-2/release/$RELEASE/theme=buildings/type=building/ \
  "$OUTDIR/overture-buildings/"

# One shard.sh pass per requested projection. "3857" means shard.sh's own
# identity path (no reprojection, TARGET_SRS left at its 4326 default) into
# parts/; anything else reprojects into parts_<srs>/ -- matching the
# vocabulary tile.sh's own $SRS argument expects (see tile.sh).
for srs in ${SRS_LIST:-3857}; do
  if [[ "$srs" == "3857" ]]; then
    partsdir="$OUTDIR/parts"
    shard_target_srs=4326
  else
    partsdir="$OUTDIR/parts_$srs"
    shard_target_srs="$srs"
  fi
  mkdir -p "$partsdir"
  # Safe only because acquire_overture_lock above guarantees we're the only
  # writer: sweeps any half-written temp left by a prior run that was
  # killed mid-shard, before shard.sh's own per-process paths existed (or
  # before this run's own PID reused one), rather than leaving it as
  # permanent debris.
  find "$partsdir" -maxdepth 1 -name '.*.tmp' -exec rm -rf {} +
  echo "sharding -> $partsdir (TARGET_SRS=$shard_target_srs)"
  ls "$OUTDIR"/overture-buildings/*.parquet \
    | TARGET_SRS="$shard_target_srs" xargs -P "$JOBS" -n 1 bash shard.sh "$partsdir"
done
