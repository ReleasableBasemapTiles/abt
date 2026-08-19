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
# Destination folders for [6/6] -- trailing slash optional, stripped below.
S3_BUCKET_3857="s3://data-478728046499-us-east-1-an/3857/"
S3_BUCKET_3395="s3://data-478728046499-us-east-1-an/3395/"

export PGHOST=127.0.0.1
export PGPORT=5432
export PGUSER=rbt
export PGPASSWORD=rbt
export PGDATABASE=rbt

# Region for the S3_BUCKET_* buckets above -- hardcoded since both live in
# the same region; only the credentials below are expected to vary per run.
export AWS_DEFAULT_REGION="us-east-1"

# Fail fast on missing AWS credentials now, before hours of download/import/
# export work, rather than discovering it only at the [6/6] upload step.
# The AWS CLI picks up AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY/
# AWS_SESSION_TOKEN from the environment automatically (these look like STS
# temporary credentials, given the session token) -- this script only
# checks they're present, it doesn't fetch or refresh them, so export
# current ones before running.
: "${AWS_ACCESS_KEY_ID:?AWS_ACCESS_KEY_ID must be exported for the aws s3 cp step}"
: "${AWS_SECRET_ACCESS_KEY:?AWS_SECRET_ACCESS_KEY must be exported for the aws s3 cp step}"
: "${AWS_SESSION_TOKEN:?AWS_SESSION_TOKEN must be exported for the aws s3 cp step}"

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

# Resolves the bundler's output file for a workspace. bundler names it
# joined.mbtiles by default, but renames it joined.btis whenever it detects
# a non-default CRS among the input layers -- which the 3395 workspace
# always will, since export runs with --projection-override below. Same
# lookup order as resolve_input() in abt/cli_funcs/vundler.py.
resolve_bundled() {
    local workspace="$1" candidate
    for candidate in "$workspace/bundled/joined.mbtiles" "$workspace/bundled/joined.btis"; do
        if [[ -f "$candidate" ]]; then
            echo "$candidate"
            return 0
        fi
    done
    echo "No joined.mbtiles or joined.btis found in $workspace/bundled" >&2
    return 1
}

echo "[1/6] download"
python "$ABT_TOOLS" download -w "$WORKSPACE" -s "$SCHEMA" -d all -k "$KIND" -n "$JOBS"

echo "[2/6] import"
python "$ABT_TOOLS" import -w "$WORKSPACE" -s "$SCHEMA" -d all -n "$JOBS" -p "$PROVIDER" -k "$KIND" -c

echo "[3/6] carto"
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
echo "[4/6] export (3857 + 3395, in parallel)"
python "$ABT_TOOLS" export -w "$WORKSPACE" -s "$SCHEMA" -n "$JOBS" -p "$PROVIDER" -z "$ZOOM" &
pid_3857=$!
python "$ABT_TOOLS" export -w "$WORKSPACE_3395" -s "$SCHEMA" -n "$JOBS" -p "$PROVIDER" -z "$ZOOM" --projection-override "$PROJECTION_3395" &
pid_3395=$!
wait_jobs "3857:$pid_3857" "3395:$pid_3395"

echo "[5/6] bundler (3857 + 3395, in parallel)"
python "$ABT_TOOLS" bundler -w "$WORKSPACE" -s "$SCHEMA" -p "$PROVIDER" &
pid_3857=$!
python "$ABT_TOOLS" bundler -w "$WORKSPACE_3395" -s "$SCHEMA" -p "$PROVIDER" &
pid_3395=$!
wait_jobs "3857:$pid_3857" "3395:$pid_3395"

echo "[6/6] upload bundles to S3 (3857 + 3395, in parallel)"
bundled_3857="$(resolve_bundled "$WORKSPACE")"
bundled_3395="$(resolve_bundled "$WORKSPACE_3395")"
# "${VAR%/}" strips a trailing slash (if any) so S3_BUCKET_* works whether
# or not the operator included one, then the target filename is fixed
# here rather than left as whatever resolve_bundled found on disk.
aws s3 cp "$bundled_3857" "${S3_BUCKET_3857%/}/RBT.mbtiles" &
pid_3857=$!
aws s3 cp "$bundled_3395" "${S3_BUCKET_3395%/}/RBT.btis" &
pid_3395=$!
wait_jobs "3857:$pid_3857" "3395:$pid_3395"

echo "done."