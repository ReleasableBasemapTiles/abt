#!/usr/bin/env bash

#./fetch.sh /path/to/data_dir [jobs] [shard_threads]
# See README.md for pipeline order and tuning guidance.

set -euo pipefail
cd "$(dirname "$0")"

RELEASE="$(aws s3 ls --no-sign-request s3://overturemaps-us-west-2/release/ | awk '{print $2}' | tr -d '/' | sort | tail -1)"
OUTDIR="${1:-./data}"
JOBS="${2:-128}"
export SHARD_THREADS="${3:-1}"

echo "release: $RELEASE"
mkdir -p "$OUTDIR"
echo "$RELEASE" > "$OUTDIR/RELEASE"

aws s3 cp --no-sign-request --recursive \
  s3://overturemaps-us-west-2/release/$RELEASE/theme=buildings/type=building/ \
  "$OUTDIR/overture-buildings/"

mkdir -p "$OUTDIR/parts"
ls "$OUTDIR"/overture-buildings/*.parquet | xargs -P "$JOBS" -n 1 bash shard.sh "$OUTDIR/parts"
