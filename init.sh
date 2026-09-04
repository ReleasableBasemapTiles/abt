#!/usr/bin/env bash
set -euo pipefail

# --- args ---
# --overture also fetches+tiles Overture buildings in the background (see
# rbt-schema/scripts/overture/README.md) and folds the result into each of
# the bundler runs below via -q/--additional-mbtiles.
# --overture-clean additionally deletes each projection's .fgb shards as soon
# as that projection is tiled, trading re-shard work on a later re-run for a
# much smaller disk footprint.
# --projections overrides which EPSG codes [4/6]-[6/6] run for (space-
# separated, default "3857 3395 4087"). 3857 is the one case every derived
# path below special-cases (see workspace_for and friends); any other value
# is assumed metres-based and run through --projection-override, same as
# 3395/4087 always were.
# --contours folds contours_<srs>.mbtiles from the given directory into each
# projection's bundle via -q, alongside Overture buildings if also enabled.
RUN_OVERTURE=false
CLEAN_OVERTURE_PARTS=false
PROJECTIONS=(3857 3395 4087)
CONTOURS_DIR=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --overture)
            RUN_OVERTURE=true
            shift
            ;;
        --overture-clean)
            # Implies --overture: cleaning up after a pipeline that didn't run
            # would be a no-op, so this is accepted on its own.
            RUN_OVERTURE=true
            CLEAN_OVERTURE_PARTS=true
            shift
            ;;
        --projections)
            read -r -a PROJECTIONS <<< "$2"
            shift 2
            ;;
        --contours)
            CONTOURS_DIR="$2"
            shift 2
            ;;
        *)
            echo "unknown option: $1" >&2
            exit 1
            ;;
    esac
done

if [[ "${#PROJECTIONS[@]}" -eq 0 ]]; then
    echo "ERROR: --projections must list at least one EPSG code" >&2
    exit 1
fi
for srs in "${PROJECTIONS[@]}"; do
    if [[ ! "$srs" =~ ^[0-9]+$ ]]; then
        echo "ERROR: --projections entries must be numeric EPSG codes (e.g. 3857 3395 4087), got '$srs'" >&2
        exit 1
    fi
done

# --- config ---
ABT_TOOLS="/rbt/abtv2-tools/abt-tools.py"
WORKSPACE="/rbt/run-planet"
SCHEMA="/rbt/rbt-schema"
JOBS=12
PROVIDER="env"
KIND="planet"
ZOOM=13
# Destination prefix for [6/6] -- each projection uploads to
# $S3_BUCKET_PREFIX/<srs>/, e.g. .../3857/RBT.mbtiles.
S3_BUCKET_PREFIX="s3://data-478728046499-us-east-1-an"
# Only read when --overture is passed.
OVERTURE_DIR="/rbt/overture"
OVERTURE_SCRIPTS="$SCHEMA/scripts/overture"

# Per-projection paths, derived by convention from the EPSG code instead of
# one hardcoded variable per projection. 3857 (Web Mercator, the default) is
# the case each of these special-cases: its workspace keeps the unsuffixed
# $WORKSPACE (the box's already-populated default must keep working), and
# its outputs stay real .mbtiles instead of the BTIS .btis convention every
# other projection's output follows -- see the note above [5/6] below for
# why getting that extension wrong would fail silently rather than loudly.
workspace_for() {
    if [[ "$1" == 3857 ]]; then echo "$WORKSPACE"; else echo "$WORKSPACE-$1"; fi
}

overture_for() {
    if [[ "$1" == 3857 ]]; then
        echo "$OVERTURE_DIR/building_polygon_3857.mbtiles"
    else
        echo "$OVERTURE_DIR/building_polygon_$1.btis"
    fi
}

contours_for() {
    echo "$CONTOURS_DIR/contours_$1.mbtiles"
}

upload_name_for() {
    if [[ "$1" == 3857 ]]; then echo "RBT.mbtiles"; else echo "RBT.btis"; fi
}

export PGHOST=127.0.0.1
export PGPORT=5432
export PGUSER=rbt
export PGPASSWORD=rbt
export PGDATABASE=rbt

# Region for the S3_BUCKET_PREFIX bucket above.
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

# Same fail-fast rationale as the AWS credential checks above, for the
# Overture pipeline's own dependencies. setup_ubuntu.sh doesn't provision
# duckdb -- only this pipeline needs it -- and the pipeline runs in the
# background (see below), so a missing binary would otherwise only surface
# in $OVERTURE_DIR/overture.log at the [5/6] wait_jobs join instead of here.
if [[ "$RUN_OVERTURE" == true ]]; then
    command -v duckdb >/dev/null 2>&1 || { echo "duckdb is required for --overture but was not found on PATH" >&2; exit 1; }
    command -v aws >/dev/null 2>&1 || { echo "aws CLI is required for --overture but was not found on PATH" >&2; exit 1; }
fi

# Same fail-fast rationale again, for --contours: checked (and, for
# reprojected projections, tagged) here rather than left to the bundler.
# Bundler.tile_list silently *drops* a -q path that doesn't exist rather than
# erroring, so a missing/misnamed contours file would otherwise ship a bundle
# with no contours instead of failing loudly; and an untagged reprojected
# contours file would otherwise only surface as a bundler ValueError at
# [5/6], hours in. 3857 contours must carry no crs row, matching the
# convention Overture/export output already follow for the default
# projection; non-3857 contours get tagged in place if bare, or rejected if
# already tagged with some other EPSG code than requested.
if [[ -n "$CONTOURS_DIR" ]]; then
    command -v sqlite3 >/dev/null 2>&1 || { echo "sqlite3 is required for --contours but was not found on PATH" >&2; exit 1; }
    for srs in "${PROJECTIONS[@]}"; do
        contours_file="$(contours_for "$srs")"
        if [[ ! -f "$contours_file" ]]; then
            echo "ERROR: no contours file at $contours_file" >&2
            exit 1
        fi
        current_crs="$(sqlite3 "$contours_file" "SELECT value FROM metadata WHERE name = 'crs';")"
        if [[ "$srs" == 3857 ]]; then
            if [[ -n "$current_crs" ]]; then
                echo "ERROR: $contours_file claims crs=$current_crs but 3857 inputs must carry no crs row" >&2
                exit 1
            fi
        elif [[ -z "$current_crs" ]]; then
            echo "[contours] tagging $contours_file as EPSG:$srs"
            "${PYTHON:-python3}" "$OVERTURE_SCRIPTS/tag_crs.py" "$srs" "$contours_file"
        elif [[ "$current_crs" != "EPSG:$srs" ]]; then
            echo "ERROR: $contours_file claims crs=$current_crs, cannot bundle it as EPSG:$srs" >&2
            exit 1
        fi
    done
fi

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
# a non-default CRS among the input layers -- which every non-3857 workspace
# will, since export runs with --projection-override for those below. Same
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

# Overture buildings pipeline (rbt-schema/scripts/overture/) is entirely
# independent of the Postgres-based stages below -- DuckDB reads Overture's
# GeoParquet straight from S3 and tippecanoe tiles it, no import/carto
# involved. Started here, in the background, so its multi-hour fetch+shard
# time overlaps with [1/6]-[4/6] instead of adding to the critical path.
# Output is redirected to a log file rather than the console: shard.sh emits
# one done/skip line per input file (there are thousands), which would
# otherwise bury the [n/6] progress markers below. Joined via wait_jobs just
# before [5/6] -- the first stage that actually needs its output -- so a
# failed Overture run aborts the script there instead of silently bundling
# without buildings.
if [[ "$RUN_OVERTURE" == true ]]; then
    echo "[overture] starting in background (log: $OVERTURE_DIR/overture.log)"
    mkdir -p "$OVERTURE_DIR"
    # With --overture-clean, each tile.sh drops its own parts dir as it finishes,
    # so every shard set is gone well before [5/6]/[6/6] need room for the
    # bundles. Note it does not lower the *peak*: fetch.sh shards every listed
    # projection before any tiling starts, so all of them still coexist during
    # that phase. Interleaving fetch and tile per projection would be the fix
    # if peak, not tail, is what's tight.
    (
        SRS_LIST="${PROJECTIONS[*]}" bash "$OVERTURE_SCRIPTS/fetch.sh" "$OVERTURE_DIR" "$JOBS"
        for srs in "${PROJECTIONS[@]}"; do
            CLEAN_PARTS="$CLEAN_OVERTURE_PARTS" bash "$OVERTURE_SCRIPTS/tile.sh" "$OVERTURE_DIR" "$srs"
        done
    ) > "$OVERTURE_DIR/overture.log" 2>&1 &
    pid_overture=$!
fi

echo "[1/6] download"
python "$ABT_TOOLS" download -w "$WORKSPACE" -s "$SCHEMA" -d all -k "$KIND" -n "$JOBS"

echo "[2/6] import"
python "$ABT_TOOLS" import -w "$WORKSPACE" -s "$SCHEMA" -d all -n "$JOBS" -p "$PROVIDER" -k "$KIND" -c

echo "[3/6] carto"
python "$ABT_TOOLS" carto -w "$WORKSPACE" -s "$SCHEMA" -p "$PROVIDER"

# Every listed projection -- 3857 (Web Mercator, no override) plus any others
# via --projection-override -- only reads the carto'd `export` schema and
# writes to its own workspace (workspace_for above -- required, not just
# tidy: export's intermediate .fgb filenames don't encode projection, so
# sharing a workspace would make one run silently skip regenerating .fgb
# files another projection already produced, instead of reprojecting them).
# Nothing about the projections conflicts, so run them all concurrently
# instead of back to back. NOTE: each still fans out its own $JOBS-worker
# pool, so this briefly runs up to len(PROJECTIONS)x $JOBS worker processes
# at once -- lower $JOBS if that would oversubscribe this host's CPU/IO/
# Postgres connections.
echo "[4/6] export (${PROJECTIONS[*]}, in parallel)"
pids=()
for srs in "${PROJECTIONS[@]}"; do
    proj_flag=()
    if [[ "$srs" != 3857 ]]; then
        proj_flag=(--projection-override "EPSG:$srs")
    fi
    python "$ABT_TOOLS" export -w "$(workspace_for "$srs")" -s "$SCHEMA" -n "$JOBS" -p "$PROVIDER" -z "$ZOOM" "${proj_flag[@]}" &
    pids+=("$srs:$!")
done
wait_jobs "${pids[@]}"

if [[ "$RUN_OVERTURE" == true ]]; then
    echo "[overture] waiting for background fetch+tile pipeline"
    wait_jobs "overture:$pid_overture"
fi

# Overture buildings / contours (when --overture / --contours were passed)
# get folded into each projection's bundle below via -q/--additional-mbtiles
# -- an empty q array otherwise, so this loop is identical either way.
# Extensions matter: 3857's Overture output stays real .mbtiles but every
# other projection's is .btis (non-web-mercator BTIS convention -- see
# rbt-schema/scripts/overture/README.md); contours' extension was already
# verified by the --contours preflight above. Bundler.tile_list silently
# *drops* any -q path that doesn't exist rather than erroring, so a wrong
# extension or path here would produce a bundle silently missing a layer
# instead of failing loudly.
echo "[5/6] bundler (${PROJECTIONS[*]}, in parallel)"
pids=()
for srs in "${PROJECTIONS[@]}"; do
    q=()
    if [[ "$RUN_OVERTURE" == true ]]; then
        q+=(-q "$(overture_for "$srs")")
    fi
    if [[ -n "$CONTOURS_DIR" ]]; then
        q+=(-q "$(contours_for "$srs")")
    fi
    python "$ABT_TOOLS" bundler -w "$(workspace_for "$srs")" -s "$SCHEMA" -p "$PROVIDER" "${q[@]}" &
    pids+=("$srs:$!")
done
wait_jobs "${pids[@]}"

echo "[6/6] upload bundles to S3 (${PROJECTIONS[*]}, in parallel)"
# Resolved for every projection up front, before any upload starts (rather
# than interleaved with the background aws s3 cp loop below), so one
# workspace's bundle being missing/misnamed aborts here -- before any partial
# set of uploads begins -- same fail-fast intent as the checks earlier in
# this script.
declare -A bundled_paths
for srs in "${PROJECTIONS[@]}"; do
    bundled_paths["$srs"]="$(resolve_bundled "$(workspace_for "$srs")")"
done
pids=()
for srs in "${PROJECTIONS[@]}"; do
    aws s3 cp "${bundled_paths[$srs]}" "$S3_BUCKET_PREFIX/$srs/$(upload_name_for "$srs")" &
    pids+=("$srs:$!")
done
wait_jobs "${pids[@]}"

echo "done."
