#!/usr/bin/env bash
set -euo pipefail

# --- config ---
ABT_TOOLS="/rbt/abtv2-tools/abt-tools.py"
WORKSPACE="/rbt/run-planet"
SCHEMA="/rbt/rbt-schema"
JOBS=12
PROVIDER="env"
KIND="planet"
ZOOM=13

export PGHOST=127.0.0.1
export PGPORT=5432
export PGUSER=rbt
export PGPASSWORD=rbt
export PGDATABASE=rbt

echo "[1/5] download"
python "$ABT_TOOLS" download -w "$WORKSPACE" -s "$SCHEMA" -d all -k "$KIND" -n "$JOBS"

echo "[2/5] import"
python "$ABT_TOOLS" import -w "$WORKSPACE" -s "$SCHEMA" -d all -n "$JOBS" -p "$PROVIDER" -k "$KIND" -c

echo "[3/5] carto"
python "$ABT_TOOLS" carto -w "$WORKSPACE" -s "$SCHEMA" -p "$PROVIDER"

echo "[4/5] export"
python "$ABT_TOOLS" export -w "$WORKSPACE" -s "$SCHEMA" -n "$JOBS" -p "$PROVIDER" -z "$ZOOM"

echo "[5/5] bundler"
python "$ABT_TOOLS" bundler -w "$WORKSPACE" -s "$SCHEMA" -p "$PROVIDER"

echo "done."