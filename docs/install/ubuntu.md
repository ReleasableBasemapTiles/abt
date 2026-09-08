# Ubuntu Setup

This page provisions a fresh **Ubuntu 26.04** ("resolute") host with every dependency the pipeline needs. There are two paths:

- **Manual, step-by-step** (below) — useful for understanding exactly what gets installed, or for a host that's already partially configured.
- **Automated** ([`setup_ubuntu.sh`](#automated-setup-setup_ubuntush)) — an idempotent script that does all of the below end to end, plus kernel/ulimit tuning and the monorepo clone.

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

The `carto` scripts run `CREATE EXTENSION IF NOT EXISTS dblink` and then open password-less internal connections via `dblink_connect` to fan out a parallel polygon dissolve (see `rbt-schema/carto_sql/005a_water_polygon.sql`). `dblink` will only accept a password-less connection string like this for a Postgres **superuser** (or a role explicitly trusted via `pg_hba.conf`). The simplest path is to make the pipeline's role a superuser:

```bash
sudo -u postgres psql <<'SQL'
CREATE ROLE abt WITH LOGIN SUPERUSER PASSWORD 'abt';
CREATE DATABASE abt_planet OWNER abt;
\c abt_planet
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS hstore;
CREATE EXTENSION IF NOT EXISTS dblink;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
SQL
```

Building the smaller single-extract walkthrough instead? Give it its own database under the same role, so both can coexist on one Postgres instance:

```bash
sudo -u postgres psql <<'SQL'
CREATE DATABASE abt_norway OWNER abt;
\c abt_norway
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS hstore;
CREATE EXTENSION IF NOT EXISTS dblink;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
SQL
```

See [Configuration](configuration.md) for why each of these four extensions is required. Confirm `pg_hba.conf` allows local password auth for the `abt` role (the default `scram-sha-256`/`peer` mix on a fresh install is normally fine for local TCP connections on `127.0.0.1`; only adjust this if `psql -h 127.0.0.1 -U abt` fails to connect later).

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
max_connections = 400
max_files_per_process = 4096
random_page_cost = 1.1
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
random_page_cost = 1.1
```

See [Performance & Sizing](performance.md) for the reasoning behind these two tiers and how they interact with `carto`'s own per-session tuning.

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
tile-join --version
```

## 5. GDAL / Python environment

GDAL/`ogr2ogr` >=3.9.2 is required; Ubuntu 26.04 ships GDAL 3.12.2, so the system package alone would suffice for the CLI tool, but the Python side also needs GDAL's Python bindings plus several other packages, all pinned together in `abtv2-tools/env.yaml`. Use conda/Miniforge for this rather than mixing system and pip GDAL builds:

```bash
cd /tmp
curl -L -O https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh
bash Miniforge3-Linux-x86_64.sh -b -p "$HOME/miniforge3"
source "$HOME/miniforge3/etc/profile.d/conda.sh"
conda init bash
exec bash   # reload shell so `conda` is on PATH
```

Then, from your `abtv2-tools` checkout (see [Clone the repo](#clone-the-repo) below):

```bash
cd ~/abt/abtv2-tools
conda env create -f env.yaml
conda activate abtv2
ogr2ogr --version
```

See [Configuration](configuration.md) for the alternative `requirements-dev.txt` (pip) path, which exists for tests/CI rather than as a runtime alternative to this conda env.

## 6. Verify everything

```bash
echo "python:      $(python --version)"
echo "psql:        $(psql --version)"
echo "postgis:     $(psql -d abt_planet -U abt -h 127.0.0.1 -tAc 'SELECT postgis_version();')"
echo "gdal/ogr2ogr: $(ogr2ogr --version)"
echo "imposm:      $(imposm version)"
echo "tippecanoe:  $(tippecanoe --version)"
echo "tile-join:   $(tile-join --version)"
```

You'll be prompted for the `abt` role's password by the `psql` line above unless you export `PGPASSWORD` first.

## Clone the repo

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

`setup_ubuntu.sh` defaults `ABT_REPO` to this alias-based URL, override it if you're using a different SSH setup or the plain HTTPS URL (see [Configuration](configuration.md)) — with one catch, see the warning below.

!!! warning "`ABT_REPO`'s built-in default has a typo"
    The GitHub organization is `ReleasableBasemapTiles` (confirmed against this repo's own `origin` remote), but `setup_ubuntu.sh`'s hardcoded `ABT_REPO` default, and a couple of `User-Agent` strings elsewhere in `abtv2-tools/abt/download/`, spell it `ReleaseableBasemapTiles` (extra "e"). The clone commands above use the correct spelling; if you instead let `setup_ubuntu.sh` clone the repo for you via its default `ABT_REPO`, override that variable first (see [Configuration](configuration.md)) or the clone step will fail against the misspelled path.

## Automated setup: `setup_ubuntu.sh`

[`setup_ubuntu.sh`](https://github.com/ReleasableBasemapTiles/abt/blob/main/setup_ubuntu.sh) is an idempotent bootstrap for a fresh Ubuntu 26.04 host that installs everything above end to end: base build tooling, PostgreSQL 18 + PostGIS 3.6 (initialized directly via `initdb`/`pg_ctl` under a custom systemd unit rather than Debian's `postgresql-common` cluster tooling), the `postgis`/`hstore`/`dblink`/`pg_trgm` extensions plus a superuser role and database, `imposm3` and `tippecanoe` built from source (`master`/`main` by default), a `micromamba`-managed Python env from `env.yaml`, kernel/ulimit tuning for high-throughput I/O, and optionally clones the monorepo.

```bash
./setup_ubuntu.sh
```

Safe to re-run — every stage checks whether its work is already done first (e.g. skips rebuilding `tippecanoe` if it's already on `PATH`, skips `initdb` if `PG_VERSION` already exists at `PG_DATA_DIR`). Output is mirrored to a timestamped log file under `$HOME` (override with `LOG_FILE`).

Configuration is entirely via environment variables, all optional and all defaulting to values matching the manual walkthrough above. See [Configuration](configuration.md) for the full environment-variable reference, or read the "Configuration" block at the top of `setup_ubuntu.sh` itself for every variable with its inline reasoning.

## Where to go next

- [Configuration](configuration.md) — the full `setup_ubuntu.sh` environment-variable reference, `--schema-dir` validation, and Postgres connection options.
- [Performance & Sizing](performance.md) — the two documented hardware tiers and how `carto` scales itself across them.
- [Norway walkthrough](../walkthroughs/norway.md) and [Planet walkthrough](../walkthroughs/planet.md) — running the pipeline end to end once a host is provisioned.
- [Troubleshooting](../reference/troubleshooting.md) — common setup and pipeline failures.
