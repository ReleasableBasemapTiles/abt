# Ubuntu Setup

This page provisions a fresh **Ubuntu 26.04** ("resolute") host with every dependency the pipeline needs. There are two paths:

- **Manual, step-by-step** (below) — useful for understanding exactly what gets installed, or for a host that's already partially configured.
- **Automated** ([`setup_ubuntu.sh`](#automated-setup-setup_ubuntush)) — an idempotent script that covers the same steps, plus kernel/ulimit tuning, with a few differences [listed below](#how-setup_ubuntush-differs).

!!! note "Assumptions"
    Steps below assume a non-root user with `sudo`.

## 1. Base packages

```bash
sudo apt update
sudo apt install -y \
  build-essential git curl wget unzip aria2 \
  libsqlite3-dev zlib1g-dev sqlite3
```

- `libsqlite3-dev` and `zlib1g-dev` are needed to build tippecanoe from source (below).
- `build-essential` supplies `g++`/`make`.
- `sqlite3` is the CLI used later to inspect the final `.mbtiles` output.
- `aria2` provides `aria2c`, used by `download -k planet` for a multi-mirror, checksum-verified download of the planet file — required for a planet build (see [Planet walkthrough](../walkthroughs/planet.md)); skip it only if you'll exclusively build small extracts (e.g. `-k norway`, see [Norway walkthrough](../walkthroughs/norway.md)).

## 2. PostgreSQL 18 + PostGIS 3.6

Ubuntu 26.04 ships PostgreSQL 18 and PostGIS 3.6 in its default repositories — no PGDG repo needed, both comfortably exceed the pipeline's stated minimums (PostgreSQL >=16 / PostGIS >=3.4):

```bash
sudo apt install -y postgresql postgresql-contrib postgresql-18-postgis-3
```

Verify:

```bash
psql --version
```

### Create a database and role

The `carto` scripts run `CREATE EXTENSION IF NOT EXISTS dblink` and then open password-less internal connections via `dblink_connect` to fan out a parallel polygon dissolve (see `rbt-schema/carto_sql/005a_water_polygon.sql`). `dblink` accepts a password-less connection string like this only from a Postgres **superuser**, whatever `pg_hba.conf` says, so the pipeline's role must be one. Those connections name no user either, so each logs in as `postgres` over the local socket, which the stock `local all postgres peer` line in `pg_hba.conf` allows; keep it. The names below are the ones `setup_ubuntu.sh` uses by default (`PG_USER`, `PG_PASSWORD` and `PG_DB` are all `rbt`), so the walkthroughs and `init.sh` work the same on either path:

```bash
sudo -u postgres psql <<'SQL'
CREATE ROLE rbt WITH LOGIN SUPERUSER PASSWORD 'rbt';
CREATE DATABASE rbt OWNER rbt;
\c rbt
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS hstore;
CREATE EXTENSION IF NOT EXISTS dblink;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
SQL
```

Building the smaller single-extract walkthrough instead? Give it its own database under the same role, so both can coexist on one Postgres instance. This works on a host `setup_ubuntu.sh` set up, too:

```bash
sudo -u postgres createdb -O rbt rbt_norway
sudo -u postgres psql -d rbt_norway <<'SQL'
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS hstore;
CREATE EXTENSION IF NOT EXISTS dblink;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
SQL
```

See [Configuration](configuration.md) for why each of these four extensions is required. Confirm `pg_hba.conf` allows local password auth for the `rbt` role (the default `scram-sha-256`/`peer` mix on a fresh install is normally fine for local TCP connections on `127.0.0.1`; only adjust this if `psql -h 127.0.0.1 -U rbt` fails to connect later).

### Tune `postgresql.conf`

Find the file with:

```bash
sudo -u postgres psql -c 'SHOW config_file;'
```

For the **384 GB planet tier**:

```conf
shared_buffers = 96GB
effective_cache_size = 192GB
maintenance_work_mem = 8GB
max_worker_processes = 44
max_parallel_workers = 40
max_parallel_workers_per_gather = 8
max_parallel_maintenance_workers = 8
max_connections = 400
max_files_per_process = 4096
random_page_cost = 1.1
max_wal_size = 64GB
```

Restart Postgres after editing: `sudo systemctl restart postgresql`.

For the smaller **8 vCPU / 32 GB single-extract tier** instead, these lighter values are comfortably sized:

```conf
shared_buffers = 8GB
effective_cache_size = 24GB
maintenance_work_mem = 2GB
max_worker_processes = 10
max_parallel_workers = 10
max_parallel_workers_per_gather = 4
max_parallel_maintenance_workers = 2
max_connections = 400
max_files_per_process = 4096
random_page_cost = 1.1
max_wal_size = 8GB
```

On either tier, add the bulk-load settings `setup_ubuntu.sh` also applies:

```conf
checkpoint_timeout = 30min
wal_compression = lz4
wal_buffers = 64MB
effective_io_concurrency = 200
maintenance_io_concurrency = 200
jit = off
# Leave these three out on a host that replicates or archives WAL:
wal_level = minimal
max_wal_senders = 0
synchronous_commit = off
```

See [Performance & Sizing](performance.md) for the reasoning behind these two tiers, the [bulk-load profile](performance.md#bulk-load-profile), and how they interact with `carto`'s own per-session tuning.

## 3. imposm 0.14+

Not packaged in apt. Install the official static binary (no Go toolchain needed):

```bash
cd /tmp
curl -LO https://github.com/omniscale/imposm3/releases/download/v0.14.2/imposm-0.14.2-linux-x86-64.tar.gz
tar xzf imposm-0.14.2-linux-x86-64.tar.gz
sudo install -m 755 imposm-0.14.2-linux-x86-64/imposm /usr/local/bin/imposm
imposm version
```

## 4. tippecanoe 2.76+ (build from source)

!!! warning "Do not `apt install tippecanoe`"
    Ubuntu 26.04's `tippecanoe` apt package is version 2.53.0 — below the pipeline's required >=2.76. Installing it will silently satisfy the package manager while leaving a version too old for some of the pipeline's export/bundler flags.

Build the current release from source instead:

```bash
cd /tmp
git clone --branch 2.79.0 --depth 1 https://github.com/felt/tippecanoe.git
cd tippecanoe
make -j"$(nproc)"
sudo make install
tippecanoe --version
command -v tile-join   # built and installed alongside tippecanoe; it has no --version flag
```

## 5. Clone the repo

`abtv2-tools/` and `rbt-schema/` are both subdirectories of this one repo, at the same fixed relative path to each other that the CLI expects, so a single clone is all `abt-tools.py` needs — `--schema-dir ../rbt-schema` resolves correctly from inside `abtv2-tools/` without any extra setup:

```bash
mkdir -p ~/abt && cd ~/abt
git clone git@github.com:ReleasableBasemapTiles/abt.git .
```

(Use the HTTPS clone URL, `https://github.com/ReleasableBasemapTiles/abt.git`, instead if you don't have SSH keys configured for GitHub.)

If this is a private repo and you're using a deploy key rather than a GitHub-wide SSH key, add a `Host` alias to `~/.ssh/config`:

```text
Host abt
    HostName ssh.github.com
    Port 443
    User git
    IdentityFile ~/.ssh/id_ed25519_abt
    IdentitiesOnly yes
```

...then clone using the alias as the hostname instead of `github.com`:

```bash
git clone git@abt:ReleasableBasemapTiles/abt.git .
```

`setup_ubuntu.sh` defaults `ABT_REPO` to this alias-based URL; override it if you're using a different SSH setup or the plain HTTPS URL (see [Configuration](configuration.md)).

## 6. GDAL / Python environment

GDAL/`ogr2ogr` >=3.9.2 is required. The pipeline only runs GDAL's command-line tools (`ogr2ogr`, `ogrinfo`), never its Python bindings, and Ubuntu 26.04's GDAL 3.12.2 would do for those on their own. `abtv2-tools/env.yaml` still installs its own GDAL, pinned together with `proj>=9.8`, which the non-3857 projections need so that `ogr2ogr` and `pyproj` agree with PostGIS (see [Overture Buildings](../pipeline/overture.md#proj-version-agreement)), and the Python packages `abt-tools.py` imports. Use conda/Miniforge for it:

```bash
cd /tmp
curl -L -O https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh
bash Miniforge3-Linux-x86_64.sh -b -p "$HOME/miniforge3"
source "$HOME/miniforge3/etc/profile.d/conda.sh"
conda init bash
exec bash   # reload shell so `conda` is on PATH
```

Then, from your `abtv2-tools` checkout (step 5):

```bash
cd ~/abt/abtv2-tools
conda env create -f env.yaml
conda activate abtv2
ogr2ogr --version
```

See [Configuration](configuration.md) for the alternative `requirements-dev.txt` (pip) path, which exists for tests/CI rather than as a runtime alternative to this conda env.

## 7. Rust and `abt-vundler`

The [`vundler`](../pipeline/vundler.md) stage runs `abt-vundler`, a Rust binary built from this repo's `abtv2-tools/vundler-rs/`, from `PATH`. Skip this step if you'll never convert a bundle to an Esri Compact Cache.

```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain stable
source "$HOME/.cargo/env"
cd ~/abt/abtv2-tools/vundler-rs
cargo build --release
sudo install -m 755 target/release/abt-vundler /usr/local/bin/abt-vundler
abt-vundler --version
```

`rusqlite` compiles its own bundled SQLite, so `build-essential` from step 1 is the only native dependency.

## 8. AWS CLI and duckdb (optional)

Only [`init.sh`](../walkthroughs/init-sh.md) needs these: the AWS CLI for its S3 upload and for `--overture`, and duckdb for `--overture`. `abt-tools.py` needs neither. On an arm64 host, use `awscli-exe-linux-aarch64.zip` and `duckdb_cli-linux-arm64.zip`:

```bash
cd /tmp
curl -sSL https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip -o awscliv2.zip
unzip -q awscliv2.zip && sudo ./aws/install
aws --version
curl -sSL https://github.com/duckdb/duckdb/releases/latest/download/duckdb_cli-linux-amd64.zip -o duckdb_cli.zip
unzip -q duckdb_cli.zip && sudo install -m 755 duckdb /usr/local/bin/duckdb
duckdb --version
```

## 9. Verify everything

```bash
echo "python:      $(python --version)"
echo "psql:        $(psql --version)"
echo "postgis:     $(psql -d rbt -U rbt -h 127.0.0.1 -tAc 'SELECT postgis_version();')"
echo "gdal/ogr2ogr: $(ogr2ogr --version)"
echo "imposm:      $(imposm version)"
echo "tippecanoe:  $(tippecanoe --version)"
echo "tile-join:   $(command -v tile-join)"
echo "abt-vundler: $(abt-vundler --version)"
```

You'll be prompted for the `rbt` role's password by the `psql` line above unless you export `PGPASSWORD` first.

## Automated setup: `setup_ubuntu.sh`

[`setup_ubuntu.sh`](https://github.com/ReleasableBasemapTiles/abt/blob/main/setup_ubuntu.sh) is an idempotent bootstrap for a fresh Ubuntu 26.04 host that installs everything above end to end: base build tooling, PostgreSQL 18 + PostGIS 3.6 (initialized directly via `initdb`/`pg_ctl` under a custom systemd unit rather than Debian's `postgresql-common` cluster tooling), the `postgis`/`hstore`/`dblink`/`pg_trgm` extensions plus a superuser role and database, `imposm3` and `tippecanoe` built from source (`master`/`main` by default), the AWS CLI and duckdb, Rust and `abt-vundler`, a `micromamba`-managed Python env from `env.yaml`, kernel/ulimit tuning for high-throughput I/O, and optionally clones the monorepo.

```bash
./setup_ubuntu.sh
```

Safe to re-run — every stage checks whether its work is already done first (e.g. skips rebuilding `tippecanoe` if it's already on `PATH`, skips `initdb` if `PG_VERSION` already exists at `PG_DATA_DIR`). Output is mirrored to a timestamped log file under `$HOME` (override with `LOG_FILE`).

Configuration is entirely via environment variables, all optional. See [Configuration](configuration.md) for the full environment-variable reference, or read the "Configuration" block at the top of `setup_ubuntu.sh` itself for every variable with its inline reasoning.

### How `setup_ubuntu.sh` differs

The role, database and extensions, the `postgresql.conf` values, and the tools are the same on both paths. These are not:

| | Manual (this page) | `setup_ubuntu.sh` |
|---|---|---|
| Postgres cluster | Ubuntu's packaged cluster and `postgresql` service, tuned in `postgresql.conf` | Its own `initdb` cluster in `PG_DATA_DIR`, run by a `postgresql-rbt` unit (`PG_SERVICE_NAME`), tuned with `ALTER SYSTEM`. Restart it with `sudo systemctl restart postgresql-rbt` |
| Postgres tier | You pick one of the two blocks in step 2 | `PG_TIER=auto` picks it from the host's RAM |
| imposm | The v0.14.2 release binary | Built from source, `master` by default (`IMPOSM_REF`) |
| tippecanoe | The 2.79.0 tag, built from source | `main` by default (`TIPPECANOE_REF`), built from source |
| Checkout | `~/abt` | The checkout the script sits in, else a clone at `$ABT_WORKSPACE_DIR/rbt` (`/rbt/rbt`) |
| Python env | Miniforge, under `$HOME` | micromamba, under `/opt/micromamba` (`MAMBA_ROOT_PREFIX`); activate it with `micromamba activate abtv2` |
| Rust | rustup's default, under `$HOME` | Under `/opt/rust` (`RUSTUP_HOME`, `CARGO_HOME`) |
| Kernel and ulimit tuning | Not covered | `sysctl` settings, among them `vm.overcommit_memory=2`, and raised `nofile`/`nproc` limits (`KERNEL_TUNE`) |
| AWS CLI and duckdb | Optional (step 8) | Installed by default (`INSTALL_AWSCLI`, `INSTALL_DUCKDB`) |

## Where to go next

- [Configuration](configuration.md) — the full `setup_ubuntu.sh` environment-variable reference, `--schema-dir` validation, and Postgres connection options.
- [Performance & Sizing](performance.md) — the two documented hardware tiers and how `carto` scales itself across them.
- [Norway walkthrough](../walkthroughs/norway.md) and [Planet walkthrough](../walkthroughs/planet.md) — running the pipeline end to end once a host is provisioned.
- [Troubleshooting](../reference/troubleshooting.md) — common setup and pipeline failures.
