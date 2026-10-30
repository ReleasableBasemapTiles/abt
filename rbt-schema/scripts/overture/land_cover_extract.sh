#!/usr/bin/env bash

# ./land_cover_extract.sh /path/to/data_dir [jobs]
#
# One-off extraction of the Overture land cover slice that
# import/aux_data/overture_land_cover.json describes, run outside the
# pipeline. The zip it writes is meant to be hosted, the way the old project
# hosted its MODIS land cover, so builds download a few GB instead of reading
# the whole release. It reads and writes only data_dir, never a build.
#
# Why not let `download -d aux` read it from S3: base/land_cover is 128
# parquet files, ~109 GB per release, and the rows we keep (the z0-z7 band
# plus the detailed urban areas, ~4% of rows) are spread through every row
# group, so DuckDB fetches nearly all of the geometry anyway. Streaming it
# with DuckDB's ranged reads ran at ~7 MB/s (hours); `aws s3 sync` of the
# same files saturates the link, and the query on local files takes minutes.
#
# Writes, in data_dir:
#   overture_land_cover.fgb            the extract (same rows and columns the
#   overture_land_cover.fgb.release    pipeline's Overture download writes)
#   overture_land_cover_<release>.zip  the two above, ready to host
#
# Env:
#   KEEP_PARQUET=1  keep the downloaded parquet (data_dir/overture-land-cover-
#                   <release>/) instead of deleting it after a good extract.
#
# Needs: aws (CLI), python3 with the duckdb module (the abtv2 env has both).

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG="$SCRIPT_DIR/../../import/aux_data/overture_land_cover.json"

DATA_DIR="${1:?usage: $0 /path/to/data_dir [jobs]}"
JOBS="${2:-32}"
PYTHON="${PYTHON:-python3}"

# The release, filter and columns come from the aux config, so the hosted
# extract matches what the pipeline would have extracted itself.
RELEASE="$("$PYTHON" -c 'import json,sys; print(json.load(open(sys.argv[1]))["overture_params"]["release"])' "$CONFIG")"
PARQUET_DIR="$DATA_DIR/overture-land-cover-$RELEASE"
OUT="$DATA_DIR/overture_land_cover.fgb"
ZIP="$DATA_DIR/overture_land_cover_$RELEASE.zip"
echo "release: $RELEASE"
mkdir -p "$PARQUET_DIR"

# aws s3 sync defaults to 10 concurrent requests. A throwaway config file
# raises that without touching the operator's own ~/.aws/config.
AWS_CONFIG_FILE="$(mktemp)"
export AWS_CONFIG_FILE
trap 'rm -f "$AWS_CONFIG_FILE"' EXIT
printf '[default]\ns3 =\n  max_concurrent_requests = %s\n  multipart_chunksize = 64MB\n' "$JOBS" > "$AWS_CONFIG_FILE"

echo "downloading -> $PARQUET_DIR"
aws s3 sync --no-sign-request --only-show-errors \
  "s3://overturemaps-us-west-2/release/$RELEASE/theme=base/type=land_cover/" \
  "$PARQUET_DIR/"

echo "extracting -> $OUT"
"$PYTHON" - "$CONFIG" "$PARQUET_DIR" "$OUT" <<'EOF'
import json, os, sys, time
from pathlib import Path
import duckdb

config, parquet_dir, out = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
p = json.load(open(config))["overture_params"]
lit = lambda s: "'" + str(s).replace("'", "''") + "'"
# GDAL's FlatGeobuf driver treats a name not ending in .fgb as a directory,
# so the staging file keeps the final name, one directory down.
staging = out.parent / ".partial" / out.name
staging.parent.mkdir(parents=True, exist_ok=True)
staging.unlink(missing_ok=True)

sql = (f"COPY (SELECT {', '.join([*p.get('columns', []), 'geometry'])}\n"
       f"FROM read_parquet({lit(parquet_dir / '*.parquet')})"
       + (f"\nWHERE {p['where']}" if p.get("where") else "")
       + f")\nTO {lit(staging)} WITH (FORMAT GDAL, DRIVER 'FlatGeobuf')")
print(sql, flush=True)
con = duckdb.connect()
con.execute("INSTALL spatial")
con.execute("LOAD spatial")
try:
    # See DownloadOverture.optional_statements: newer DuckDB warns about
    # latitude/longitude order without it; older versions reject it.
    con.execute("SET geometry_always_xy = true")
except Exception as e:
    print(f"skipping geometry_always_xy: {e}")
t = time.time()
con.execute(sql)
con.close()
os.replace(staging, out)
print(f"done in {time.time() - t:.0f}s, {out.stat().st_size / 1e9:.2f} GB")
EOF
echo "$RELEASE" > "$OUT.release"

echo "zipping -> $ZIP"
"$PYTHON" - "$ZIP" "$OUT" "$OUT.release" <<'EOF'
import sys, zipfile
from pathlib import Path
with zipfile.ZipFile(sys.argv[1], "w", zipfile.ZIP_DEFLATED, allowZip64=True) as z:
    for f in sys.argv[2:]:
        z.write(f, Path(f).name)
EOF
ls -l "$OUT" "$ZIP"

if [[ "${KEEP_PARQUET:-0}" != "1" ]]; then
  rm -rf "$PARQUET_DIR"
  echo "removed $PARQUET_DIR"
fi
