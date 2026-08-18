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

# Waits for each given "label:pid" background job and reports its outcome.
# Always waits for every one of them -- even after an earlier failure --
# so a fast failure never leaves a still-running sibling job unreported or
# orphaned. Returns non-zero (aborting the script, via set -e, once every
# job has finished) if any job failed. A bare `wait` with no arguments
# can't be used here since it discards individual jobs' exit statuses.
wait_jobs() {
    local status=0 entry label pid
    for entry in "$@"; do
        label="${entry%%:*}"
        pid="${entry#*:}"
        if wait "$pid"; then
            echo "  ok:     $label"
        else
            echo "  FAILED: $label" >&2
            status=1
        fi
    done
    return "$status"
}

echo "[1/5] download"
python "$ABT_TOOLS" download -w "$WORKSPACE" -s "$SCHEMA" -d all -k "$KIND" -n "$JOBS"

echo "[2/5] import"
python "$ABT_TOOLS" import -w "$WORKSPACE" -s "$SCHEMA" -d all -n "$JOBS" -p "$PROVIDER" -k "$KIND" -c

echo "[3/5] carto"
python "$ABT_TOOLS" carto -w "$WORKSPACE" -s "$SCHEMA" -p "$PROVIDER"

# 3857 (default) and 3395 (World Mercator, via --projection-override) both
# only read the carto'd `export` schema and write to their own workspace
# ($WORKSPACE vs $WORKSPACE_3395 -- required, not just tidy: export's
# intermediate .fgb filenames don't encode projection, so sharing a
# workspace would make one run silently skip regenerating .fgb files the
# other already produced, instead of reprojecting them to 3395). Nothing
# about the two conflicts, so run them concurrently instead of back to
# back. NOTE: each still fans out its own $JOBS-worker pool, so this briefly
# runs up to 2x $JOBS worker processes at once -- lower $JOBS if that would
# oversubscribe this host's CPU/IO/Postgres connections.
echo "[4/5] export (3857 + 3395, in parallel)"
python "$ABT_TOOLS" export -w "$WORKSPACE" -s "$SCHEMA" -n "$JOBS" -p "$PROVIDER" -z "$ZOOM" &
pid_3857=$!
python "$ABT_TOOLS" export -w "$WORKSPACE_3395" -s "$SCHEMA" -n "$JOBS" -p "$PROVIDER" -z "$ZOOM" --projection-override "$PROJECTION_3395" &
pid_3395=$!
wait_jobs "3857:$pid_3857" "3395:$pid_3395"

echo "[5/5] bundler (3857 + 3395, in parallel)"
python "$ABT_TOOLS" bundler -w "$WORKSPACE" -s "$SCHEMA" -p "$PROVIDER" &
pid_3857=$!
python "$ABT_TOOLS" bundler -w "$WORKSPACE_3395" -s "$SCHEMA" -p "$PROVIDER" &
pid_3395=$!
wait_jobs "3857:$pid_3857" "3395:$pid_3395"

echo "done."