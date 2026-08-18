#!/usr/bin/env bash
set -euo pipefail

# --- config ---
ABT_TOOLS="/rbt/abtv2-tools/abt-tools.py"
WORKSPACE="/rbt/run-planet"
WORKSPACE_3395="/rbt/run-planet-3395"
SCHEMA="/rbt/rbt-schema"
JOBS=12
PROVIDER="env"
KIND="planet"
ZOOM=13
PROJECTION_3395="EPSG:3395"

export PGHOST=127.0.0.1
export PGPORT=5432
export PGUSER=rbt
export PGPASSWORD=rbt
export PGDATABASE=rbt

echo "[1/7] download"
python "$ABT_TOOLS" download -w "$WORKSPACE" -s "$SCHEMA" -d all -k "$KIND" -n "$JOBS"

echo "[2/7] import"
python "$ABT_TOOLS" import -w "$WORKSPACE" -s "$SCHEMA" -d all -n "$JOBS" -p "$PROVIDER" -k "$KIND" -c

echo "[3/7] carto"
python "$ABT_TOOLS" carto -w "$WORKSPACE" -s "$SCHEMA" -p "$PROVIDER"

echo "[4/7] export"
python "$ABT_TOOLS" export -w "$WORKSPACE" -s "$SCHEMA" -n "$JOBS" -p "$PROVIDER" -z "$ZOOM"

echo "[5/7] bundler"
python "$ABT_TOOLS" bundler -w "$WORKSPACE" -s "$SCHEMA" -p "$PROVIDER"

# EPSG:3395 (World Mercator) variant, built from the same carto'd `export`
# schema -- no need to redo download/import/carto. Uses its own workspace
# because export's intermediate .fgb files are named the same regardless of
# projection; reusing $WORKSPACE would make export silently skip
# regenerating them instead of reprojecting to 3395 (both steps skip work
# whose output file already exists).
echo "[6/7] export (EPSG:3395)"
python "$ABT_TOOLS" export -w "$WORKSPACE_3395" -s "$SCHEMA" -n "$JOBS" -p "$PROVIDER" -z "$ZOOM" --projection-override "$PROJECTION_3395"

echo "[7/7] bundler (EPSG:3395)"
python "$ABT_TOOLS" bundler -w "$WORKSPACE_3395" -s "$SCHEMA" -p "$PROVIDER"

echo "done."