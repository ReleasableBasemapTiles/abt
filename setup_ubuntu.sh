#!/usr/bin/env bash
#
# setup_ubuntu.sh
#
# Idempotent bootstrap script for a fresh Ubuntu 26.04 host to run the ABT
# (Army/Releasable Basemap Tiles) pipeline. This automates README.md
# section 3 (system dependencies), section 3.2's Postgres role/database/
# tuning, and section 4's repo checkout. See README.md for the manual
# walkthrough this codifies, and for the full planet run this leaves you
# ready to execute (section 6 covers a smaller single-extract variant).
#
# imposm3 and tippecanoe are compiled from source (from their "master"/
# "main" branches by default, see IMPOSM_REF/TIPPECANOE_REF below) rather
# than installed from a pinned release. Python/GDAL dependencies are
# managed with micromamba rather than a full Miniforge/conda install.
# PostgreSQL's own cluster is initialized directly with initdb/pg_ctl rather
# than Debian's postgresql-common tooling (pg_createcluster/pg_ctlcluster),
# and runs under a small custom systemd unit; see section 3 below.
#
# Usage:
#   ./setup_ubuntu.sh
#
# All configuration is via environment variables; every one has a default
# matching README.md. Re-running this script is safe: each stage checks
# whether its work is already done before repeating it.

set -euo pipefail

# --- Logging -------------------------------------------------------------------
#
# Mirrors all stdout/stderr to a local log file (in addition to the
# terminal) via process substitution rather than a literal `| tee` pipe, so
# the script's own exit code -- not tee's -- is what `set -e` and the caller
# see. One log file per run by default; override LOG_FILE to reuse/append to
# a fixed path instead.

LOG_FILE="${LOG_FILE:-$HOME/setup_ubuntu-$(date +%Y%m%d-%H%M%S).log}"
mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || true
exec > >(tee -a "$LOG_FILE") 2>&1
echo "Logging full output to ${LOG_FILE}"

# --- Configuration (env vars, all overridable) ------------------------------

# Everything the pipeline touches -- the monorepo checkout (abtv2-tools/ and
# rbt-schema/ as subdirectories) and the working/data directories used for
# download+import+export runs -- lives under this one root rather than being
# split across $HOME and wherever this script happens to live. Override to
# relocate the whole tree, e.g. onto a dedicated data disk mounted elsewhere.
ABT_WORKSPACE_DIR="${ABT_WORKSPACE_DIR:-/rbt}"
ABT_RUN_DIR="${ABT_RUN_DIR:-$ABT_WORKSPACE_DIR/run-planet}"

# Separate workspace for the EPSG:3395 (World Mercator) `export`/`bundler`
# variant -- see init.sh's own comments for why this needs to be a distinct
# directory from ABT_RUN_DIR rather than a subdirectory of it (the
# intermediate .fgb filenames don't encode projection, so sharing a
# workspace would make a --projection-override export silently reuse the
# default build's Web Mercator .fgb files instead of reprojecting to 3395).
ABT_RUN_DIR_3395="${ABT_RUN_DIR_3395:-${ABT_RUN_DIR}-3395}"

ABT_MONOREPO_DIR="${ABT_MONOREPO_DIR:-$ABT_WORKSPACE_DIR/rbt}"

# This is a private repo, cloned over SSH using a deploy key rather than
# HTTPS. The hostname below ("abt") is not github.com itself -- it's expected
# to be a Host alias in ~/.ssh/config that points at ssh.github.com with its
# own IdentityFile, e.g.:
#
#   Host abt
#       HostName ssh.github.com
#       Port 443
#       User git
#       IdentityFile ~/.ssh/id_ed25519_abt
#       IdentitiesOnly yes
#
# Cloning via git@github.com:... directly would skip that alias and fall
# back to your default SSH identity, which a deploy key can't authenticate
# as. Override to a plain https://github.com/... URL instead if this becomes
# public, or if you're not using a deploy key.
ABT_REPO="${ABT_REPO:-git@abt:ReleaseableBasemapTiles/abt.git}"
CLONE_REPO="${CLONE_REPO:-true}"

# The non-root user (and its primary group) that should own ABT_WORKSPACE_DIR/
# ABT_RUN_DIR and everything cloned/written into them, since the script itself
# runs plain `git clone`/`python` as this user but needs sudo to first create
# a root-level directory like /rbt.
PIPELINE_USER="${PIPELINE_USER:-${SUDO_USER:-$(id -un)}}"
PIPELINE_GROUP="${PIPELINE_GROUP:-$(id -gn "$PIPELINE_USER")}"

PG_DB="${PG_DB:-rbt}"
PG_USER="${PG_USER:-rbt}"
PG_PASSWORD="${PG_PASSWORD:-rbt}"
PG_PORT="${PG_PORT:-5432}"

# This script bypasses Debian's postgresql-common cluster tooling
# (pg_createcluster/pg_ctlcluster/pg_lsclusters) entirely and instead
# initializes and runs the cluster with the raw upstream initdb/pg_ctl
# binaries, wrapped in a small systemd unit named PG_SERVICE_NAME.
PG_SERVICE_NAME="${PG_SERVICE_NAME:-postgresql-rbt}"

# Data directory for the cluster, initialized via a plain `initdb`. Defaults
# to /var/lib/postgresql/<major>/main (the standard Debian/Ubuntu path, just
# not populated by Debian's own tooling) once the installed major version is
# known; override PG_DATA_DIR to use a different path, e.g. a mount point
# for a dedicated NVMe device.
PG_DATA_DIR="${PG_DATA_DIR:-}"

# Set to "true" to allow wiping a non-empty PG_DATA_DIR before running
# initdb fresh. Left "false" by default so the script fails loudly instead
# of silently deleting data that happens to already live at that path.
FORCE_REINIT_POSTGRES="${FORCE_REINIT_POSTGRES:-false}"

# Defaults below target the 8 vCPU / 32 GB "small extract" tier documented
# in README.md section 2 (Sizing). For a large single host (e.g. 48 vCPU /
# 384 GB), override all of these -- README.md's Sizing section has a
# copy-pasteable `export` block sized for that tier.
PG_SHARED_BUFFERS="${PG_SHARED_BUFFERS:-96GB}"
PG_EFFECTIVE_CACHE_SIZE="${PG_EFFECTIVE_CACHE_SIZE:-192GB}"
PG_MAINTENANCE_WORK_MEM="${PG_MAINTENANCE_WORK_MEM:-8GB}"
PG_MAX_WORKER_PROCESSES="${PG_MAX_WORKER_PROCESSES:-44}"
PG_MAX_PARALLEL_WORKERS="${PG_MAX_PARALLEL_WORKERS:-40}"
PG_MAX_PARALLEL_WORKERS_PER_GATHER="${PG_MAX_PARALLEL_WORKERS_PER_GATHER:-8}"
PG_MAX_FILES_PER_PROCESS="${PG_MAX_FILES_PER_PROCESS:-4096}"

# Postgres's own factory default (100) is too low once carto runs multiple
# concurrent script groups (see abt carto --carto-concurrency), each able to
# open up to ~16 additional dblink worker connections for the water/land-cover
# dissolves -- raised here unconditionally since headroom is cheap and a
# too-low ceiling fails hard ("FATAL: sorry, too many clients already") deep
# into a run rather than at startup.
PG_MAX_CONNECTIONS="${PG_MAX_CONNECTIONS:-400}"

# Set to "false" to skip the /etc/sysctl.d, /etc/security/limits.d, and
# systemd LimitNOFILE tuning below entirely.
KERNEL_TUNE="${KERNEL_TUNE:-true}"

# vm.swappiness: how aggressively the kernel moves process memory to swap
# (0-200, Ubuntu default 60). Kept above 0 rather than fully disabling swap,
# since an outright swap-averse kernel makes the OOM killer more likely to
# strike instead; low-but-nonzero is the standard PostgreSQL recommendation.
VM_SWAPPINESS="${VM_SWAPPINESS:-1}"

# vm.overcommit_memory=2 makes the kernel do strict accounting (deny
# allocations up front) instead of the default heuristic overcommit, which
# is what PostgreSQL's own docs recommend to keep the OOM killer from
# targeting the postmaster. overcommit_ratio caps allocations at
# swap + this percentage of RAM; lower it if this host has little/no swap.
VM_OVERCOMMIT_MEMORY="${VM_OVERCOMMIT_MEMORY:-2}"
VM_OVERCOMMIT_RATIO="${VM_OVERCOMMIT_RATIO:-80}"

# Flush dirty pages earlier and in smaller batches (Ubuntu defaults are 10%/
# 20% of RAM) so large COPY/import bursts and checkpoints don't build up a
# huge backlog that then stalls everything during synchronous writeback.
VM_DIRTY_BACKGROUND_RATIO="${VM_DIRTY_BACKGROUND_RATIO:-3}"
VM_DIRTY_RATIO="${VM_DIRTY_RATIO:-10}"

# System-wide ceilings: fs.file-max bounds total open file descriptors
# across all processes, fs.aio-max-nr bounds in-flight async I/O requests
# (relevant to PostgreSQL 18's io_uring support). Both need to comfortably
# exceed the per-process NOFILE_LIMIT below.
FS_FILE_MAX="${FS_FILE_MAX:-2097152}"
FS_AIO_MAX_NR="${FS_AIO_MAX_NR:-1048576}"

# Per-process/user open-file and process limits ("ulimit -n" / "ulimit -u").
NOFILE_LIMIT="${NOFILE_LIMIT:-1048576}"
NPROC_LIMIT="${NPROC_LIMIT:-65536}"

# imposm3 and tippecanoe are built from source at these git refs (branch,
# tag, or commit) rather than installed from a pinned release, so "master"/
# "main" always pull in the latest upstream code.
IMPOSM_REF="${IMPOSM_REF:-master}"
TIPPECANOE_REF="${TIPPECANOE_REF:-main}"

# Set to "true" to rebuild even if a binary is already installed. Useful
# since building from a moving branch has no fixed version to compare
# against for the usual "already installed, skip" check.
FORCE_REBUILD_IMPOSM="${FORCE_REBUILD_IMPOSM:-false}"
FORCE_REBUILD_TIPPECANOE="${FORCE_REBUILD_TIPPECANOE:-false}"

# abt-vundler (converts a bundled mbtiles into Esri Compact Cache V2 tile
# bundles) lives in-tree at abtv2-tools/vundler-rs/ rather than a separate
# upstream repo, so -- unlike imposm/tippecanoe above -- there's no _REF to
# pick; it's built from whatever commit ABT_REPO was cloned at (section 9
# below, after the monorepo clone in section 8). Rust toolchain via rustup
# rather than `apt install cargo`, same rationale as tippecanoe above:
# Ubuntu's packaged rustc lags behind, and the crate's 2024 edition needs a
# reasonably recent compiler. RUSTUP_HOME/CARGO_HOME point at a shared
# location under /opt rather than $HOME, mirroring MAMBA_ROOT_PREFIX below,
# so this works regardless of which user runs the script.
RUSTUP_HOME="${RUSTUP_HOME:-/opt/rust/rustup}"
CARGO_HOME="${CARGO_HOME:-/opt/rust/cargo}"
export RUSTUP_HOME CARGO_HOME
FORCE_REBUILD_VUNDLER="${FORCE_REBUILD_VUNDLER:-false}"

# /opt/micromamba rather than $HOME so it's a single well-known location
# regardless of which user runs this script or later activates the env, and
# so it can be shared/inspected system-wide (e.g. by a service account).
# MICROMAMBA_BIN follows the same "bin/" layout the official micromamba
# installer uses, i.e. living inside MAMBA_ROOT_PREFIX rather than
# /usr/local/bin, so a single directory add to PATH covers both.
MAMBA_ROOT_PREFIX="${MAMBA_ROOT_PREFIX:-/opt/micromamba}"
MICROMAMBA_BIN="${MICROMAMBA_BIN:-$MAMBA_ROOT_PREFIX/bin/micromamba}"
CONDA_ENV_NAME="${CONDA_ENV_NAME:-abtv2}"
export MAMBA_ROOT_PREFIX

INSTALL_POSTGRES="${INSTALL_POSTGRES:-true}"
CONFIGURE_POSTGRES="${CONFIGURE_POSTGRES:-true}"
INSTALL_IMPOSM="${INSTALL_IMPOSM:-true}"
INSTALL_TIPPECANOE="${INSTALL_TIPPECANOE:-true}"
INSTALL_VUNDLER="${INSTALL_VUNDLER:-true}"
INSTALL_CONDA="${INSTALL_CONDA:-true}"

# --- Helpers -----------------------------------------------------------------

CURRENT_STAGE="startup"

stage() {
    CURRENT_STAGE="$1"
    echo
    echo "==> $1"
}

on_error() {
    local exit_code=$?
    echo "!!! setup_ubuntu.sh failed during stage: ${CURRENT_STAGE} (exit code ${exit_code})" >&2
    exit "$exit_code"
}
trap on_error ERR

# PG_SERVICE_NAME (section 3 below) wraps pg_ctl, but nothing stops a
# postmaster from being started directly via `pg_ctl start -D PG_DATA_DIR`
# -- e.g. by hand, while debugging -- instead of `systemctl start
# PG_SERVICE_NAME`. systemd has no record of a unit it didn't start, so
# `systemctl start`/`restart` still run the unit's own ExecStart (pg_ctl
# start), which then fails outright because a postmaster is already bound
# to PG_DATA_DIR/PG_PORT. These helpers check for that out-of-band case
# directly via `pg_ctl status` rather than trusting systemd's view alone,
# so the rest of the script behaves the same regardless of how Postgres
# was last started/stopped. They depend on PG_SERVICE_NAME/PG_DATA_DIR/
# PG_BIN_DIR, which aren't assigned their final values until section 3.

pg_is_running() {
    sudo -u postgres env "PATH=${PG_BIN_DIR}:/usr/bin:/bin" \
        pg_ctl status -D "$PG_DATA_DIR" >/dev/null 2>&1
}

pg_service_stop() {
    if systemctl is-active --quiet "$PG_SERVICE_NAME" 2>/dev/null; then
        sudo systemctl stop "$PG_SERVICE_NAME"
    fi
    # Fallback: systemd only stopped something above if it was the one that
    # started it. A postmaster started directly via pg_ctl is invisible to
    # systemd and would otherwise still be left holding PG_DATA_DIR/PG_PORT.
    if pg_is_running; then
        echo "Stopping postmaster running against ${PG_DATA_DIR} (not managed by ${PG_SERVICE_NAME}.service)"
        sudo -u postgres env "PATH=${PG_BIN_DIR}:/usr/bin:/bin" \
            pg_ctl stop -D "$PG_DATA_DIR" -m fast -w -t 60 2>/dev/null \
            || sudo kill "$(sudo head -n1 "$PG_DATA_DIR/postmaster.pid" 2>/dev/null)" 2>/dev/null \
            || true
    fi
}

pg_service_ensure_running() {
    if pg_is_running; then
        echo "Postgres is already running against ${PG_DATA_DIR}"
    else
        echo "${PG_SERVICE_NAME} is not running, starting it"
        sudo systemctl start "$PG_SERVICE_NAME"
    fi
}

pg_service_restart() {
    pg_service_stop
    # Always (re)start via systemctl, even if pg_service_stop's fallback is
    # what actually stopped it, so a previously out-of-band postmaster gets
    # adopted back under systemd from this point on.
    sudo systemctl start "$PG_SERVICE_NAME"
}

# --- 1. OS check --------------------------------------------------------------

stage "Checking OS"
if [[ -r /etc/os-release ]]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    if [[ "${ID:-}" != "ubuntu" || "${VERSION_ID:-}" != "26.04" ]]; then
        echo "Warning: this script targets Ubuntu 26.04; detected ${PRETTY_NAME:-an unrecognized OS}. Continuing anyway." >&2
    fi
else
    echo "Warning: /etc/os-release not found; cannot verify OS. Continuing anyway." >&2
fi

# --- 1b. ABT root directory ----------------------------------------------------
#
# Creates /rbt (or wherever ABT_WORKSPACE_DIR points) up front, before
# anything tries to clone into it or write pipeline output there. A plain
# `mkdir` would fail for a root-level path like /rbt, so this uses sudo and
# then hands ownership to PIPELINE_USER so every later step (git clone,
# micromamba, python abt-tools.py) can write there without sudo.

stage "Ensuring ABT root directory ${ABT_WORKSPACE_DIR} exists"
sudo mkdir -p "$ABT_WORKSPACE_DIR" "$ABT_RUN_DIR" "$ABT_RUN_DIR_3395"
sudo chown "${PIPELINE_USER}:${PIPELINE_GROUP}" "$ABT_WORKSPACE_DIR" "$ABT_RUN_DIR" "$ABT_RUN_DIR_3395"

if ! mountpoint -q "$ABT_WORKSPACE_DIR" && ! mountpoint -q "$(dirname "$ABT_WORKSPACE_DIR")"; then
    echo "Warning: neither ${ABT_WORKSPACE_DIR} nor its parent directory is a separate mount point." >&2
    echo "If this is meant to live on dedicated/fast storage, mount it there before re-running." >&2
fi

# --- 2. Base apt packages ------------------------------------------------------

stage "Installing base apt packages"
export DEBIAN_FRONTEND=noninteractive
sudo apt-get update
sudo apt-get install -y \
    build-essential git curl wget unzip aria2 \
    libsqlite3-dev zlib1g-dev sqlite3

# --- 2b. Kernel tuning for PostgreSQL / high I/O workloads ----------------------
#
# Placed before PostgreSQL is installed below so the cluster's very first
# start already picks up the systemd LimitNOFILE override.

if [[ "$KERNEL_TUNE" == "true" ]]; then
    stage "Tuning kernel parameters for PostgreSQL and high I/O (/etc/sysctl.d)"

    # Regenerated from current env vars on every run rather than checked for
    # prior existence first, same idempotency approach as the ALTER SYSTEM
    # SET tuning below: safe to re-run, always reflects current settings.
    SYSCTL_CONF="/etc/sysctl.d/99-abt-postgres.conf"
    sudo tee "$SYSCTL_CONF" >/dev/null <<EOF
# Managed by setup_ubuntu.sh -- tuning for PostgreSQL + high I/O ETL
# workloads. Re-running the script regenerates this file from the current
# VM_*/FS_* env vars; edit those instead of this file directly.

vm.swappiness = ${VM_SWAPPINESS}

vm.overcommit_memory = ${VM_OVERCOMMIT_MEMORY}
vm.overcommit_ratio = ${VM_OVERCOMMIT_RATIO}

vm.dirty_background_ratio = ${VM_DIRTY_BACKGROUND_RATIO}
vm.dirty_ratio = ${VM_DIRTY_RATIO}

# NUMA: don't let per-zone reclaim throttle allocations just because the
# local zone looks full of reclaimable cache.
vm.zone_reclaim_mode = 0

fs.file-max = ${FS_FILE_MAX}
fs.aio-max-nr = ${FS_AIO_MAX_NR}
EOF
    sudo sysctl --system >/dev/null
    echo "Applied $(basename "$SYSCTL_CONF") via sysctl --system"

    stage "Raising open-file/process limits (ulimit -n / -u) permanently"

    # /etc/sysctl.d only controls kernel-wide parameters (like fs.file-max
    # above); per-process/user ulimits are a separate mechanism. Login
    # sessions (SSH, sudo, su) get theirs from PAM via /etc/security/limits.d.
    LIMITS_CONF="/etc/security/limits.d/99-abt-postgres.conf"
    sudo tee "$LIMITS_CONF" >/dev/null <<EOF
# Managed by setup_ubuntu.sh -- raises nofile/nproc for PostgreSQL and the
# ABT pipeline user via PAM. Only applies to login sessions; systemd
# services (e.g. PostgreSQL's own unit) ignore this file entirely and get
# their LimitNOFILE baked directly into their [Service] block instead.
postgres        soft    nofile  ${NOFILE_LIMIT}
postgres        hard    nofile  ${NOFILE_LIMIT}
postgres        soft    nproc   ${NPROC_LIMIT}
postgres        hard    nproc   ${NPROC_LIMIT}
${PIPELINE_USER}        soft    nofile  ${NOFILE_LIMIT}
${PIPELINE_USER}        hard    nofile  ${NOFILE_LIMIT}
${PIPELINE_USER}        soft    nproc   ${NPROC_LIMIT}
${PIPELINE_USER}        hard    nproc   ${NPROC_LIMIT}
EOF

    # systemd services don't consult /etc/security/limits.* at all -- each
    # needs its own Limit* directive. PostgreSQL's own systemd unit
    # (PG_SERVICE_NAME, written in section 3 below) bakes LimitNOFILE
    # directly into its [Service] block rather than needing a drop-in here.

    # Global fallback so anything else that doesn't set its own Limit* still
    # gets a high ceiling instead of systemd's built-in default. Unlike unit
    # drop-ins, system.conf.d changes require daemon-reexec (not just
    # daemon-reload) to take effect.
    sudo mkdir -p /etc/systemd/system.conf.d
    sudo tee /etc/systemd/system.conf.d/99-abt-nofile.conf >/dev/null <<EOF
# Managed by setup_ubuntu.sh
[Manager]
DefaultLimitNOFILE=${NOFILE_LIMIT}
EOF

    sudo systemctl daemon-reload
    sudo systemctl daemon-reexec || true
    echo "Wrote ${LIMITS_CONF} and systemd LimitNOFILE=${NOFILE_LIMIT} overrides"
    echo "Note: sign out/in (or reconnect SSH) for interactive shells to pick up the new PAM limits."
else
    stage "Skipping kernel/ulimit tuning (KERNEL_TUNE=false)"
fi

# --- 3. PostgreSQL + PostGIS ----------------------------------------------------
#
# Deliberately does NOT let Debian's postgresql-common auto-create a "main"
# cluster (via pg_createcluster under the hood) the way a plain
# `apt-get install postgresql-contrib` normally does. Instead:
#   1. create_main_cluster=false stops that auto-creation before it happens.
#   2. initdb populates PG_DATA_DIR directly.
#   3. pg_ctl (via a small custom systemd unit, PG_SERVICE_NAME) starts it.
# This gives full control over exactly where/how the cluster is initialized,
# at the cost of bypassing postgresql-common's own cluster management --
# pg_lsclusters/pg_ctlcluster/etc. won't know about this cluster at all.

if [[ "$INSTALL_POSTGRES" == "true" ]]; then
    stage "Installing PostgreSQL and PostGIS"

    # postgresql-common alone doesn't create any cluster (that only happens
    # in the postinst of a specific postgresql-<version> package below), so
    # this is safe to install and configure before pulling that in.
    sudo apt-get install -y postgresql-common
    sudo mkdir -p /etc/postgresql-common
    sudo tee /etc/postgresql-common/createcluster.conf >/dev/null <<'EOF'
# Managed by setup_ubuntu.sh -- this pipeline initializes its own cluster
# via initdb/pg_ctl instead, so don't auto-create one on package install.
create_main_cluster = false
EOF

    sudo apt-get install -y postgresql postgresql-contrib

    PG_MAJOR="$(psql --version | grep -oE '[0-9]+' | head -n1)"
    if [[ -z "$PG_MAJOR" ]]; then
        echo "Could not determine the installed PostgreSQL major version." >&2
        exit 1
    fi
    echo "Detected PostgreSQL major version: ${PG_MAJOR}"

    # Package name is generated from the detected major version rather than
    # hardcoded (e.g. postgresql-18-postgis-3), so this keeps working if
    # Ubuntu 26.04 bumps its default PostgreSQL version in a point release.
    sudo apt-get install -y "postgresql-${PG_MAJOR}-postgis-3"

    # Defensive cleanup for hosts that ran an earlier version of this script
    # (or had Postgres installed some other way) before create_main_cluster
    # was disabled above: drop any postgresql-common-managed "main" cluster
    # for this version so it can't fight our own cluster for the same port.
    if command -v pg_lsclusters >/dev/null 2>&1 && pg_lsclusters -h 2>/dev/null | awk -v v="$PG_MAJOR" '$1==v && $2=="main"' | grep -q .; then
        echo "Dropping pre-existing postgresql-common-managed ${PG_MAJOR}/main cluster"
        sudo pg_dropcluster --stop "$PG_MAJOR" main
    fi

    # postgresql-common also ships a generic postgresql.service (aggregating
    # a per-cluster postgresql@<version>-main.service instance) that starts
    # any *already-registered* cluster on every boot and package
    # install/upgrade, independently of create_main_cluster/pg_dropcluster
    # above. Left enabled, it brings back a postmaster bound to the same
    # PGDATA/port as our own initdb/pg_ctl-managed cluster -- which is
    # exactly what caused initdb's bootstrap backend to fail below with
    # "pre-existing shared memory block ... is still in use". Stop, disable,
    # and mask it so it can never come back; PG_SERVICE_NAME owns the
    # cluster's lifecycle instead.
    sudo systemctl stop postgresql "postgresql@${PG_MAJOR}-main" 2>/dev/null || true
    sudo systemctl disable postgresql "postgresql@${PG_MAJOR}-main" 2>/dev/null || true
    sudo systemctl mask postgresql 2>/dev/null || true

    # initdb/pg_ctl (unlike psql/pg_dump/etc.) aren't exposed on PATH by
    # Debian's update-alternatives wrappers, so add them explicitly -- both
    # for the rest of this script and permanently for future shells.
    PG_BIN_DIR="/usr/lib/postgresql/${PG_MAJOR}/bin"
    export PATH="${PG_BIN_DIR}:${PATH}"
    sudo tee /etc/profile.d/99-abt-postgresql-path.sh >/dev/null <<EOF
# Managed by setup_ubuntu.sh
export PATH="${PG_BIN_DIR}:\$PATH"
EOF
    sudo chmod 644 /etc/profile.d/99-abt-postgresql-path.sh

    PG_DATA_DIR="${PG_DATA_DIR:-/var/lib/postgresql/${PG_MAJOR}/main}"
    PG_LOG_FILE="${PG_LOG_FILE:-/var/log/postgresql/postgresql-${PG_MAJOR}-main.log}"
    stage "Initializing PostgreSQL ${PG_MAJOR} data directory at ${PG_DATA_DIR} (initdb)"

    # Stop any server already running against this data directory (e.g. left
    # over from a previous run of this script, or started directly via
    # pg_ctl rather than systemctl) before touching its contents. initdb
    # runs its own temporary "bootstrap" backend to populate template1, and
    # if an old postmaster for this same data dir/port is still attached to
    # a shared memory segment -- even after FORCE_REINIT_POSTGRES wipes its
    # files out from under it -- that bootstrap backend fails with "pre-
    # existing shared memory block ... is still in use".
    echo "Stopping any server already running against ${PG_DATA_DIR} before (re)initializing it"
    pg_service_stop

    if ! mountpoint -q "$PG_DATA_DIR" && ! mountpoint -q "$(dirname "$PG_DATA_DIR")"; then
        echo "Warning: neither ${PG_DATA_DIR} nor its parent directory is a separate mount point." >&2
        echo "If this is meant to live on a dedicated NVMe device, mount it there before re-running." >&2
    fi

    # PG_VERSION is the canonical marker initdb leaves behind; its presence
    # is what "already initialized" means here (pg_lsclusters can't tell us,
    # since this data directory isn't registered with postgresql-common).
    if [[ -f "$PG_DATA_DIR/PG_VERSION" && "$FORCE_REINIT_POSTGRES" != "true" ]]; then
        echo "Data directory already initialized (found ${PG_DATA_DIR}/PG_VERSION), leaving it in place"
    else
        if [[ -d "$PG_DATA_DIR" ]] && [[ -n "$(sudo find "$PG_DATA_DIR" -maxdepth 1 -mindepth 1 2>/dev/null)" ]]; then
            if [[ "$FORCE_REINIT_POSTGRES" == "true" ]]; then
                echo "FORCE_REINIT_POSTGRES=true: wiping existing contents of ${PG_DATA_DIR}"
                sudo rm -rf "${PG_DATA_DIR:?}"/*
            else
                echo "Error: ${PG_DATA_DIR} already exists, is not empty, and has no PG_VERSION marker." >&2
                echo "Set FORCE_REINIT_POSTGRES=true to wipe it and initdb fresh, or set PG_DATA_DIR to a different path." >&2
                exit 1
            fi
        fi

        sudo mkdir -p "$PG_DATA_DIR"
        sudo chown postgres:postgres "$PG_DATA_DIR"
        sudo chmod 700 "$PG_DATA_DIR"

        echo "Running initdb for a fresh cluster at ${PG_DATA_DIR}"
        sudo -u postgres env "PATH=${PG_BIN_DIR}:/usr/bin:/bin" \
            initdb -D "$PG_DATA_DIR" --encoding=UTF8 --locale=C.UTF-8
    fi

    # Ensure the configured port is what postgresql.conf actually has,
    # regardless of which branch above ran (a freshly initdb'd cluster
    # always has the compiled-in default of 5432, and PG_PORT may differ
    # from that even on an already-initialized data directory if it was
    # changed since the last run).
    if sudo grep -qE '^port\s*=' "$PG_DATA_DIR/postgresql.conf"; then
        sudo sed -i "s/^port\s*=.*/port = ${PG_PORT}/" "$PG_DATA_DIR/postgresql.conf"
    else
        echo "port = ${PG_PORT}" | sudo tee -a "$PG_DATA_DIR/postgresql.conf" >/dev/null
    fi

    stage "Starting PostgreSQL ${PG_MAJOR} via ${PG_SERVICE_NAME}.service (pg_ctl)"
    sudo mkdir -p "$(dirname "$PG_LOG_FILE")"
    sudo chown postgres:postgres "$(dirname "$PG_LOG_FILE")"

    # Regenerated from current env vars on every run, same idempotency
    # approach as the sysctl.d/limits.d files above: safe to re-run, always
    # reflects current settings. daemon-reload picks up any change; the
    # actual start/restart happens further down once tuning is applied too.
    sudo tee "/etc/systemd/system/${PG_SERVICE_NAME}.service" >/dev/null <<EOF
# Managed by setup_ubuntu.sh -- wraps pg_ctl directly rather than using
# postgresql-common's cluster tooling, since this cluster was initialized
# with a plain initdb instead of pg_createcluster.
[Unit]
Description=PostgreSQL ${PG_MAJOR} (${PG_DATA_DIR}, managed by setup_ubuntu.sh)
After=network.target

[Service]
Type=forking
User=postgres
Group=postgres
Environment=PGDATA=${PG_DATA_DIR}
Environment=PATH=${PG_BIN_DIR}:/usr/bin:/bin
ExecStart=${PG_BIN_DIR}/pg_ctl start -D ${PG_DATA_DIR} -l ${PG_LOG_FILE} -w -t 120
ExecStop=${PG_BIN_DIR}/pg_ctl stop -D ${PG_DATA_DIR} -m fast
ExecReload=${PG_BIN_DIR}/pg_ctl reload -D ${PG_DATA_DIR}
TimeoutSec=120
LimitNOFILE=${NOFILE_LIMIT}

[Install]
WantedBy=multi-user.target
EOF

    sudo systemctl daemon-reload
    sudo systemctl enable --now "$PG_SERVICE_NAME"
else
    stage "Skipping PostgreSQL install (INSTALL_POSTGRES=false)"
    PG_MAJOR="$(psql --version 2>/dev/null | grep -oE '[0-9]+' | head -n1 || true)"
    PG_DATA_DIR="${PG_DATA_DIR:-/var/lib/postgresql/${PG_MAJOR}/main}"
    PG_BIN_DIR="${PG_BIN_DIR:-/usr/lib/postgresql/${PG_MAJOR}/bin}"
    PG_LOG_FILE="${PG_LOG_FILE:-/var/log/postgresql/postgresql-${PG_MAJOR}-main.log}"
fi

# --- 4 & 5. Role / database / extensions / tuning -------------------------------

if [[ "$CONFIGURE_POSTGRES" == "true" ]]; then
    # A cluster can be correctly *initialized* without actually being
    # *started* -- e.g. after a reboot. Everything from here on needs a
    # live connection, so explicitly check and start it rather than
    # assuming the enable --now above (section 3) left it running.
    stage "Ensuring Postgres is running"
    pg_service_ensure_running

    stage "Creating role '${PG_USER}' and database '${PG_DB}'"

    # Unquoted heredoc so ${PG_USER}/${PG_PASSWORD} interpolate; \$\$ escapes
    # Postgres's own dollar-quoting so bash doesn't try to expand it.
    sudo -u postgres psql -v ON_ERROR_STOP=1 -q <<SQL
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '${PG_USER}') THEN
        CREATE ROLE ${PG_USER} WITH LOGIN SUPERUSER PASSWORD '${PG_PASSWORD}';
    ELSE
        ALTER ROLE ${PG_USER} WITH LOGIN SUPERUSER PASSWORD '${PG_PASSWORD}';
    END IF;
END
\$\$;
SQL

    if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname = '${PG_DB}'" | grep -q 1; then
        sudo -u postgres createdb -O "${PG_USER}" "${PG_DB}"
    fi

    stage "Creating extensions in '${PG_DB}'"
    # dblink is required because rbt-schema/carto_sql/005a_water_polygon.sql
    # and 009_land_cover.sql open password-less dblink_connect() sessions to
    # fan out a parallel polygon dissolve; that only works for a superuser
    # (or a role explicitly trusted via pg_hba.conf), which is why PG_USER
    # above is created WITH ... SUPERUSER rather than a restricted role.
    # pg_trgm supplies the "%" similarity operator used throughout carto_sql
    # (e.g. 004_railway.sql's LOWER(service) % 'siding') for fuzzy-matching
    # OSM tag values/typos; it ships in postgresql-contrib but still needs
    # to be activated per-database like the others.
    sudo -u postgres psql -v ON_ERROR_STOP=1 -q -d "${PG_DB}" <<'SQL'
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS hstore;
CREATE EXTENSION IF NOT EXISTS dblink;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
SQL

    stage "Tuning postgresql.conf via ALTER SYSTEM"
    sudo -u postgres psql -v ON_ERROR_STOP=1 -q <<SQL
ALTER SYSTEM SET shared_buffers = '${PG_SHARED_BUFFERS}';
ALTER SYSTEM SET effective_cache_size = '${PG_EFFECTIVE_CACHE_SIZE}';
ALTER SYSTEM SET maintenance_work_mem = '${PG_MAINTENANCE_WORK_MEM}';
ALTER SYSTEM SET max_worker_processes = ${PG_MAX_WORKER_PROCESSES};
ALTER SYSTEM SET max_parallel_workers = ${PG_MAX_PARALLEL_WORKERS};
ALTER SYSTEM SET max_parallel_workers_per_gather = ${PG_MAX_PARALLEL_WORKERS_PER_GATHER};
ALTER SYSTEM SET max_connections = ${PG_MAX_CONNECTIONS};
ALTER SYSTEM SET random_page_cost = 1.1;
-- Complements the NOFILE_LIMIT ulimit raised via systemd LimitNOFILE above:
-- Postgres itself still caps how many files each backend/worker keeps open.
ALTER SYSTEM SET max_files_per_process = ${PG_MAX_FILES_PER_PROCESS};
SQL

    stage "Restarting PostgreSQL to apply tuning"
    pg_service_restart
else
    stage "Skipping PostgreSQL role/database/tuning configuration (CONFIGURE_POSTGRES=false)"
fi

# --- 6. imposm -------------------------------------------------------------------

if [[ "$INSTALL_IMPOSM" == "true" ]]; then
    stage "Building imposm3 from ${IMPOSM_REF}"
    if command -v imposm >/dev/null 2>&1 && [[ "$FORCE_REBUILD_IMPOSM" != "true" ]]; then
        echo "imposm already installed at $(command -v imposm), skipping (set FORCE_REBUILD_IMPOSM=true to rebuild)"
    else
        # Build deps: Go toolchain (cgo) plus the C libraries imposm3 binds
        # to (LevelDB for its node cache, GEOS for geometry processing).
        sudo apt-get install -y golang-go libleveldb-dev libgeos-dev

        IMPOSM_TMP_DIR="$(mktemp -d)"
        (
            cd "$IMPOSM_TMP_DIR"
            git clone --branch "${IMPOSM_REF}" --depth 1 https://github.com/omniscale/imposm3.git
            cd imposm3
            make build
            sudo install -m 755 imposm /usr/local/bin/imposm
        )
        rm -rf "$IMPOSM_TMP_DIR"
        imposm version
    fi
else
    stage "Skipping imposm install (INSTALL_IMPOSM=false)"
fi

# --- 7. tippecanoe ---------------------------------------------------------------

if [[ "$INSTALL_TIPPECANOE" == "true" ]]; then
    stage "Building tippecanoe from ${TIPPECANOE_REF}"
    # Do NOT `apt install tippecanoe` -- Ubuntu 26.04 ships 2.53.0, below the
    # >=2.76 the pipeline requires. Build the requested branch from source.
    if command -v tippecanoe >/dev/null 2>&1 && [[ "$FORCE_REBUILD_TIPPECANOE" != "true" ]]; then
        echo "tippecanoe already installed at $(command -v tippecanoe), skipping (set FORCE_REBUILD_TIPPECANOE=true to rebuild)"
    else
        TIPPECANOE_TMP_DIR="$(mktemp -d)"
        (
            cd "$TIPPECANOE_TMP_DIR"
            git clone --branch "${TIPPECANOE_REF}" --depth 1 https://github.com/felt/tippecanoe.git
            cd tippecanoe
            make -j"$(nproc)"
            sudo make install
        )
        rm -rf "$TIPPECANOE_TMP_DIR"
        tippecanoe --version
        # tile-join has no -v/--version flag (only tippecanoe itself does),
        # so just confirm the binary landed on PATH rather than probing it.
        command -v tile-join >/dev/null
        echo "tile-join installed at $(command -v tile-join)"
    fi
else
    stage "Skipping tippecanoe install (INSTALL_TIPPECANOE=false)"
fi

# --- 8. Clone the abt monorepo (abtv2-tools/ + rbt-schema/) ------------------------

if [[ "$CLONE_REPO" == "true" ]]; then
    stage "Cloning abt monorepo into ${ABT_MONOREPO_DIR}"
    if [[ ! -d "$ABT_MONOREPO_DIR" ]]; then
        git clone "$ABT_REPO" "$ABT_MONOREPO_DIR"
    else
        echo "abt monorepo already present at ${ABT_MONOREPO_DIR}, skipping clone"
    fi
else
    stage "Skipping repo cloning (CLONE_REPO=false)"
fi

ABT_TOOLS_DIR="$ABT_MONOREPO_DIR/abtv2-tools"
ABT_SCHEMA_DIR="$ABT_MONOREPO_DIR/rbt-schema"
ENV_YAML="$ABT_TOOLS_DIR/env.yaml"
VUNDLER_CRATE_DIR="$ABT_TOOLS_DIR/vundler-rs"

# --- 9. Rust toolchain + abt-vundler ---------------------------------------------
#
# Placed after the monorepo clone (section 8) rather than alongside
# imposm/tippecanoe above, since -- unlike those -- there's nothing to
# fetch from a separate upstream repo here: the source is ABT_REPO's own
# abtv2-tools/vundler-rs/, so it can only be built once that clone exists.

if [[ "$INSTALL_VUNDLER" == "true" ]]; then
    stage "Installing Rust toolchain (rustup) for abt-vundler"

    sudo mkdir -p "$(dirname "$RUSTUP_HOME")"
    sudo chown "${PIPELINE_USER}:${PIPELINE_GROUP}" "$(dirname "$RUSTUP_HOME")"

    export PATH="${CARGO_HOME}/bin:${PATH}"
    sudo tee /etc/profile.d/99-abt-rust-path.sh >/dev/null <<EOF
# Managed by setup_ubuntu.sh
export RUSTUP_HOME="${RUSTUP_HOME}"
export CARGO_HOME="${CARGO_HOME}"
export PATH="${CARGO_HOME}/bin:\$PATH"
EOF
    sudo chmod 644 /etc/profile.d/99-abt-rust-path.sh

    if command -v cargo >/dev/null 2>&1; then
        echo "cargo already installed at $(command -v cargo), skipping rustup install"
    else
        curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \
            | sh -s -- -y --default-toolchain stable --no-modify-path
        cargo --version
    fi

    stage "Building abt-vundler from ${VUNDLER_CRATE_DIR}"
    if [[ ! -d "$VUNDLER_CRATE_DIR" ]]; then
        echo "Cannot find ${VUNDLER_CRATE_DIR} -- set ABT_WORKSPACE_DIR/ABT_MONOREPO_DIR, or leave CLONE_REPO=true so the monorepo gets checked out first." >&2
        exit 1
    fi

    if command -v abt-vundler >/dev/null 2>&1 && [[ "$FORCE_REBUILD_VUNDLER" != "true" ]]; then
        echo "abt-vundler already installed at $(command -v abt-vundler), skipping (set FORCE_REBUILD_VUNDLER=true to rebuild)"
    else
        # rusqlite's "bundled" feature compiles its own vendored SQLite from
        # source instead of linking the system library, so build-essential
        # (already installed in section 2) covers this crate's only native
        # build dependency -- nothing further to install here.
        (
            cd "$VUNDLER_CRATE_DIR"
            cargo build --release
            sudo install -m 755 target/release/abt-vundler /usr/local/bin/abt-vundler
        )
        abt-vundler --version
    fi
else
    stage "Skipping abt-vundler build (INSTALL_VUNDLER=false)"
fi

# --- 10. micromamba + env ------------------------------------------------------------

if [[ "$INSTALL_CONDA" == "true" ]]; then
    stage "Installing micromamba"

    # /opt requires root to create, same as ABT_WORKSPACE_DIR above; hand
    # ownership to PIPELINE_USER afterward so env creation/activation below
    # (and any later `micromamba install`) doesn't need sudo.
    sudo mkdir -p "$MAMBA_ROOT_PREFIX"
    sudo chown "${PIPELINE_USER}:${PIPELINE_GROUP}" "$MAMBA_ROOT_PREFIX"

    # Permanent PATH entry for MAMBA_ROOT_PREFIX/bin, mirroring how the
    # PostgreSQL bin dir is added above -- both for this script (immediately)
    # and for future login shells.
    export PATH="${MAMBA_ROOT_PREFIX}/bin:${PATH}"
    sudo tee /etc/profile.d/99-abt-micromamba-path.sh >/dev/null <<EOF
# Managed by setup_ubuntu.sh
export PATH="${MAMBA_ROOT_PREFIX}/bin:\$PATH"
EOF
    sudo chmod 644 /etc/profile.d/99-abt-micromamba-path.sh

    if [[ -x "$MICROMAMBA_BIN" ]]; then
        echo "micromamba already installed at ${MICROMAMBA_BIN}, skipping installer"
    else
        # micro.mamba.pm serves per-architecture builds under different path
        # segments (e.g. linux-64 for x86_64, linux-aarch64 for arm64) --
        # hardcoding linux-64 here would silently fetch an x86_64 binary onto
        # an arm64 host and fail at run time with "Exec format error" rather
        # than at download time, so pick the segment from uname -m instead.
        case "$(uname -m)" in
            x86_64) MICROMAMBA_PLATFORM="linux-64" ;;
            aarch64|arm64) MICROMAMBA_PLATFORM="linux-aarch64" ;;
            ppc64le) MICROMAMBA_PLATFORM="linux-ppc64le" ;;
            *)
                echo "Unsupported architecture for micromamba: $(uname -m)" >&2
                exit 1
                ;;
        esac
        echo "Detected architecture $(uname -m), fetching micromamba for ${MICROMAMBA_PLATFORM}"

        MICROMAMBA_TMP_DIR="$(mktemp -d)"
        (
            cd "$MICROMAMBA_TMP_DIR"
            curl -Ls "https://micro.mamba.pm/api/micromamba/${MICROMAMBA_PLATFORM}/latest" | tar -xvj bin/micromamba
            sudo mkdir -p "$(dirname "$MICROMAMBA_BIN")"
            sudo install -m 755 bin/micromamba "$MICROMAMBA_BIN"
        )
        rm -rf "$MICROMAMBA_TMP_DIR"

        # Writes shell init into *this* user's ~/.bashrc (run without sudo,
        # so $HOME resolves correctly); takes effect in new shells.
        "$MICROMAMBA_BIN" shell init -s bash -r "$MAMBA_ROOT_PREFIX"
    fi

    stage "Creating/updating environment '${CONDA_ENV_NAME}'"
    if [[ ! -f "$ENV_YAML" ]]; then
        echo "Cannot find ${ENV_YAML} -- set ABT_WORKSPACE_DIR/ABT_MONOREPO_DIR, or leave CLONE_REPO=true so the monorepo gets checked out first." >&2
        exit 1
    fi

    if [[ -d "$MAMBA_ROOT_PREFIX/envs/$CONDA_ENV_NAME" ]]; then
        "$MICROMAMBA_BIN" install -y -n "$CONDA_ENV_NAME" -f "$ENV_YAML"
    else
        "$MICROMAMBA_BIN" create -y -n "$CONDA_ENV_NAME" -f "$ENV_YAML"
    fi
else
    stage "Skipping micromamba install (INSTALL_CONDA=false)"
fi

# --- 11. Verification ----------------------------------------------------------------

stage "Verifying installation"

run_in_env() {
    if [[ "$INSTALL_CONDA" == "true" ]]; then
        "$MICROMAMBA_BIN" run -n "$CONDA_ENV_NAME" "$@"
    else
        "$@"
    fi
}

echo "abt_root:    ${ABT_WORKSPACE_DIR} (monorepo: ${ABT_MONOREPO_DIR}, run dir: ${ABT_RUN_DIR}, run dir [3395]: ${ABT_RUN_DIR_3395})"
echo "python:      $(run_in_env python --version 2>&1 || echo 'not available')"
echo "psql:        $(psql --version 2>&1 || echo 'not available')"
echo "initdb:      $("${PG_BIN_DIR}/initdb" --version 2>&1 || echo 'not available')"
echo "pg_ctl:      $("${PG_BIN_DIR}/pg_ctl" --version 2>&1 || echo 'not available')"
if [[ -n "${PG_DATA_DIR:-}" ]]; then
    echo "pg_data_dir: ${PG_DATA_DIR} ($(systemctl is-active "$PG_SERVICE_NAME" 2>/dev/null || echo 'unknown'))"
fi
if [[ "$KERNEL_TUNE" == "true" ]]; then
    echo "swappiness:  $(cat /proc/sys/vm/swappiness 2>&1 || echo 'not available')"
    echo "nofile(pg):  $(systemctl show -p LimitNOFILE --value "$PG_SERVICE_NAME" 2>/dev/null || echo 'not available')"
fi
if [[ "$CONFIGURE_POSTGRES" == "true" ]]; then
    echo "postgis:     $(PGPASSWORD="$PG_PASSWORD" psql -h 127.0.0.1 -p "$PG_PORT" -U "$PG_USER" -d "$PG_DB" -tAc 'SELECT postgis_version();' 2>&1 || echo 'connection failed')"
fi
echo "ogr2ogr:     $(run_in_env ogr2ogr --version 2>&1 || echo 'not available')"
echo "aria2c:      $(aria2c --version 2>&1 | head -n1 || echo 'not available')"
echo "imposm:      $(imposm version 2>&1 || echo 'not available')"
echo "tippecanoe:  $(tippecanoe --version 2>&1 || echo 'not available')"
echo "tile-join:   $(command -v tile-join 2>&1 || echo 'not available')"
echo "abt-vundler: $(abt-vundler --version 2>&1 || echo 'not available')"

stage "Setup complete"
cat <<SUMMARY

Full log saved to: ${LOG_FILE}

Next steps (see README.md section 5 for the full planet walkthrough):

  # Open a new shell (or reconnect SSH) so this session picks up the raised
  # ulimit -n from /etc/security/limits.d (confirm with: ulimit -n) and the
  # initdb/pg_ctl PATH addition from /etc/profile.d (confirm with: which initdb)

  # micromamba shell init already wrote to ~/.bashrc; open a new shell, or:
  eval "\$(${MICROMAMBA_BIN} shell hook -s bash)"
  micromamba activate ${CONDA_ENV_NAME}
  cd ${ABT_TOOLS_DIR}

  export PGHOST=127.0.0.1
  export PGPORT=${PG_PORT}
  export PGUSER=${PG_USER}
  export PGPASSWORD=${PG_PASSWORD}
  export PGDATABASE=${PG_DB}

  # -n/--num-workers is optional -- it now defaults to a value scaled to
  # this host's core count; pass it explicitly to override.
  python abt-tools.py download -w ${ABT_RUN_DIR} -s ${ABT_SCHEMA_DIR} -d all -k planet
  python abt-tools.py import   -w ${ABT_RUN_DIR} -s ${ABT_SCHEMA_DIR} -d all -p env -k planet
  python abt-tools.py carto    -w ${ABT_RUN_DIR} -s ${ABT_SCHEMA_DIR} -p env
  python abt-tools.py export   -w ${ABT_RUN_DIR} -s ${ABT_SCHEMA_DIR} -p env -z 13
  python abt-tools.py bundler  -w ${ABT_RUN_DIR} -s ${ABT_SCHEMA_DIR} -p env

  # Optional EPSG:3395 (World Mercator) variant, reusing the same carto'd
  # export schema -- written into its own workspace (${ABT_RUN_DIR_3395})
  # rather than ${ABT_RUN_DIR} itself; see init.sh's comments for why.
  python abt-tools.py export   -w ${ABT_RUN_DIR_3395} -s ${ABT_SCHEMA_DIR} -p env -z 13 --projection-override EPSG:3395
  python abt-tools.py bundler  -w ${ABT_RUN_DIR_3395} -s ${ABT_SCHEMA_DIR} -p env

  # For a smaller single-extract test build instead (e.g. Norway), see
  # README.md section 6 -- swap in -k norway -c and a separate database.

SUMMARY