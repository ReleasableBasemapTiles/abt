# ABT (Releasable/Army Basemap Tiles) — Ubuntu Setup & Planet-Scale Walkthrough

This monorepo contains two components used together:

- [`abtv2-tools/`](abtv2-tools/) — the Python CLI/orchestration engine (`abt-tools.py`). This is the code that chains external geo tools together.
- [`rbt-schema/`](rbt-schema/) — the schema/config content (imposm mappings, aux-data source configs, SQL transforms, tile export configs) that gets passed to the CLI as `--schema-dir`.

Neither is useful without the other: `abtv2-tools` is a generic pipeline runner, and `rbt-schema` defines the specific dataset it builds. They used to be two separate git repositories (`abtv2-tools`, `rbt-schema`) and were merged into this single repo with their full commit history preserved -- see each subdirectory's own history via `git log -- abtv2-tools/` / `git log -- rbt-schema/`.

This document covers:

1. What the pipeline does and how it's structured
2. How to provision a fresh Ubuntu 26.04 machine with every dependency it needs
3. A full worked example building tiles for the entire planet -- plus a smaller single-country (Norway) variant for fast local iteration

## 1. What this pipeline does

ABT turns OpenStreetMap data plus a handful of auxiliary open datasets (Natural Earth, NGA GeoNames, OurAirports, FieldMaps admin boundaries, USGS domestic names, US Dept. of State LSIB, DISDI/MIRTA installations) into a bundled Mapbox vector tileset (`.mbtiles`), with an optional conversion to an Esri Compact Cache V2 tile bundle.

The pipeline is a strict sequence of CLI subcommands — there is no DAG engine, Makefile, or scheduler. Each stage reads from and writes to a `--working-dir` you choose, and reads pipeline configuration from a `--schema-dir` (in practice, your `rbt-schema` checkout). Within the `carto` stage itself, independent `carto_sql/*.sql` scripts can run concurrently against Postgres -- see "Parallelism and carto concurrency" below:

```mermaid
flowchart LR
    downloadStage["download<br/>Geofabrik PBF + aux sources"] --> importStage["import<br/>imposm + ogr2ogr into PostGIS"]
    importStage --> cartoStage["carto<br/>carto_sql/*.sql builds export schema"]
    cartoStage --> exportStage["export<br/>PostGIS to FlatGeobuf to MBTiles"]
    exportStage --> bundlerStage["bundler<br/>tile-join into joined.mbtiles"]
    bundlerStage --> vundlerStage["vundler, optional<br/>converts to Esri Compact Cache V2"]
```

| Stage | Tool(s) invoked | Reads | Writes |
|---|---|---|---|
| `download` | `requests` (Geofabrik extracts, aux), `aria2c` (planet), `boto3` (anonymous S3) | Geofabrik/planet index, aux source URLs | `<working_dir>/osm/pbf/`, `<working_dir>/aux_downloads/` |
| `import` | `imposm`, `ogr2ogr` | PBF + aux downloads | Postgres schemas `osm`, `aux_data` |
| `carto` | raw SQL via `psycopg2`, optionally several scripts at once | Postgres schemas `osm`, `aux_data` | Postgres schema `export` |
| `export` | `ogr2ogr`, `tippecanoe` | Postgres schema `export` | `<working_dir>/flatgeobuf/*.fgb`, `<working_dir>/mbtiles/*.mbtiles` |
| `bundler` | `tile-join` | `<working_dir>/mbtiles/*` | `<working_dir>/bundled/joined.mbtiles` |
| `vundler` | pure Python (sqlite3), concurrent per zoom level | `bundled/joined.mbtiles` | `<working_dir>/bundled/vundled/p12/` |

Only `download` and `export` skip work that's already done (they check for existing output files). `import`, `carto`, `bundler`, and `vundler` always redo the full operation, so the SQL in `carto_sql/` is written to be safely re-runnable.

`bundler` also accepts `-z/--max-zoom` to cap the joined output at a given zoom level -- e.g. for a smaller "RBT Small" package alongside the full-resolution one. Each input is pre-trimmed with SQLite before `tile-join` runs, rather than relying on `tile-join` itself to filter by zoom.

### Parallelism and carto concurrency

`carto` groups `carto_sql/*.sql` scripts by [`rbt-schema/carto_sql/execution_plan.yml`](rbt-schema/carto_sql/execution_plan.yml): a small sequential prefix (`000_update_aux_geom.sql`, `001_set_schema.sql`) creates the `export` schema and every carto-owned custom schema up front, then independent script groups run concurrently against Postgres (up to `-n/--carto-concurrency` at a time, one Postgres connection per group), then a sequential suffix (`099_update_geometry.sql`) normalizes everything once every group has finished. `--carto-concurrency` defaults to a value scaled to the host's CPU count (`cpu_count // 6`, floored at 1) -- 8 on the 48 vCPU planet tier documented in this guide, or 1 (fully sequential, today's historical behavior) on an 8 vCPU host like the smaller single-extract tier in §6.

This changes carto's failure behavior: previously any script failing aborted the entire run immediately. Now, a script failing aborts only its own group -- every other independent group still runs to completion -- and the sequential suffix only runs if every group succeeded. Check `logs/<run_id>/carto/` for which specific group failed; independent groups are safe to re-run on their own since (per the Reuse section below) every carto_sql script drops/recreates its own tables.

If `rbt-schema/carto_sql/execution_plan.yml` is missing (an older or third-party `--schema-dir`) or `--carto-concurrency 1` is passed explicitly, `carto` falls back to running every script sequentially in filename order, exactly as before.

For the full CLI reference (every flag), see [`abtv2-tools/README.md`](abtv2-tools/README.md).

## 2. Sizing

The `carto` SQL scripts hardcode session tuning and a fixed degree of parallelism, most visibly in [`rbt-schema/carto_sql/005a_water_polygon.sql`](rbt-schema/carto_sql/005a_water_polygon.sql) and [`rbt-schema/carto_sql/009_land_cover.sql`](rbt-schema/carto_sql/009_land_cover.sql):

```27:35:rbt-schema/carto_sql/005a_water_polygon.sql
SET work_mem = '2GB';
SET maintenance_work_mem = '16GB';
SELECT set_config('max_parallel_workers_per_gather',
                   COALESCE(current_setting('abt.parallel_workers_per_gather', true), '10'),
                   false);
SET parallel_setup_cost = 100;
SET parallel_tuple_cost = 0.01;
SET jit = off;
SET synchronous_commit = off;
```

These scripts also open up to 16 parallel `dblink` worker connections to dissolve global water/land-cover polygons. This cost is driven by the *source* data's global extent, not by `-k`/`--osm-key` -- it's roughly the same whether `carto` is building the full planet or a single small country. `carto` scales `max_parallel_workers_per_gather` and the dissolve's shard count down automatically (via the `abt.parallel_workers_per_gather`/`abt.dissolve_shards` GUCs above) when several concurrent script groups share the box -- see abtv2-tools' README "Carto concurrency" section for the mechanics. For this doc:

| Tier | vCPUs | RAM | Disk | Use case |
|---|---|---|---|---|
| **Planet (documented in this guide)** | 48 | 384 GB | 2+ TB NVMe | Full-planet builds (§5) -- the tier `setup_ubuntu.sh`'s default `PG_*` tuning and `abt-tools.py`'s auto-scaled `-n/--num-workers`/`--carto-concurrency` defaults (see abtv2-tools' README Sizing section) are aimed at. 32+ vCPUs / 128+ GB RAM is a workable floor, but expect the `import` step alone to take 24+ hours even on hardware this size -- the planet PBF alone is 80+ GB, before Postgres or tile output. |
| Small extract | 8 | 32 GB | 100 GB SSD | Single-country/small-region test builds (§6, e.g. Norway) -- fast iteration on schema/SQL changes without planet-scale time or disk cost. |

On the 384 GB tier, Postgres itself should still be configured with a much smaller `shared_buffers`/`effective_cache_size` than the `carto_sql` scripts' own per-session `work_mem`/`maintenance_work_mem` overrides -- see the `postgresql.conf` block in the next section. `setup_ubuntu.sh` already defaults to this tuning; override the `PG_*` env vars before running it only if your host's specs differ meaningfully from 48 vCPU / 384 GB:

```bash
export PG_SHARED_BUFFERS=96GB              # ~25% of RAM
export PG_EFFECTIVE_CACHE_SIZE=192GB       # ~50% of RAM
export PG_MAINTENANCE_WORK_MEM=8GB
export PG_MAX_WORKER_PROCESSES=44          # leave a few cores for the OS/other daemons
export PG_MAX_PARALLEL_WORKERS=40
export PG_MAX_PARALLEL_WORKERS_PER_GATHER=8
export PG_MAX_CONNECTIONS=400              # covers concurrent carto groups' dblink fan-out + import/export worker pools
export PG_MAX_FILES_PER_PROCESS=4096       # matches the NOFILE_LIMIT ulimit setup_ubuntu.sh also raises
./setup_ubuntu.sh
```

`PG_MAX_CONNECTIONS` matters more at this scale than for a small extract: running `carto` with `--carto-concurrency` greater than 1 means several script groups hold their own connection simultaneously, and the water/land-cover scripts each additionally fan out up to 16 `dblink` worker connections from within whichever group is running them -- see "Parallelism and `carto` concurrency" above.

For the smaller 8 vCPU / 32 GB single-extract tier (§6), scale all of the above down instead -- see §3.2's alternative `postgresql.conf` block. The 16 concurrent `dblink` workers each requesting up to 1 GB of `work_mem` (set inside the SQL itself, not from `postgresql.conf`) are comfortably inside 32 GB at that tier, since the dissolve operates on a small, already-clipped set of polygons.

## 3. Ubuntu 26.04 setup

Run all of this on a fresh Ubuntu 26.04 ("resolute") host. Steps assume a non-root user with `sudo`.

### 3.1 Base packages

```bash
sudo apt update
sudo apt install -y \
  build-essential git curl wget unzip aria2 \
  libsqlite3-dev zlib1g-dev sqlite3
```

`libsqlite3-dev` and `zlib1g-dev` are needed to build tippecanoe from source (below); `build-essential` supplies `g++`/`make`; `sqlite3` is the CLI used later to inspect the final `.mbtiles` output; `aria2` provides `aria2c`, used by `download -k planet` for a multi-mirror, checksum-verified download of the planet file (see [`abtv2-tools/README.md`](abtv2-tools/README.md#commands)) -- required for the planet walkthrough in §5 below; skip it only if you'll exclusively use the smaller single-extract walkthrough in §6, which passes `-k norway` instead.

### 3.2 PostgreSQL 18 + PostGIS 3.6

Ubuntu 26.04 ships PostgreSQL 18 and PostGIS 3.6 in its default repositories — no PGDG repo needed, both comfortably exceed the pipeline's stated minimums (PostgreSQL >=16 / PostGIS >=3.4):

```bash
sudo apt install -y postgresql postgresql-contrib postgresql-18-postgis-3
```

Verify:

```bash
psql --version
```

**Create a database and role.** The `carto` scripts run `CREATE EXTENSION IF NOT EXISTS dblink` and then open password-less internal connections via `dblink_connect` to fan out a parallel polygon dissolve (see [`rbt-schema/carto_sql/005a_water_polygon.sql`](rbt-schema/carto_sql/005a_water_polygon.sql)):

```255:263:rbt-schema/carto_sql/005a_water_polygon.sql
    nshards CONSTANT int := COALESCE(current_setting('abt.dissolve_shards', true)::int, 16);
    connstr CONSTANT text := format(
        'dbname=%s options=''-c work_mem=1GB -c synchronous_commit=off -c jit=off''',
        current_database());
    i int;
    n int;
BEGIN
    FOR i IN 0 .. nshards - 1 LOOP
        PERFORM dblink_connect('dissolve_w' || i, connstr);
```

`dblink` will only accept a password-less connection string like this for a Postgres **superuser** (or a role explicitly trusted via `pg_hba.conf`). The simplest path is to make the pipeline's role a superuser:

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

Building the smaller single-extract walkthrough instead (§6)? Give it its own database under the same role, so both can coexist on one Postgres instance:

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

`hstore` is required because imposm mappings store OSM tags as an `hstore_tags` column (see e.g. `rbt-schema/import/osm/*.yml`); `dblink` is required by the two carto scripts above; `postgis` is required throughout; `pg_trgm` supplies the `%` similarity operator used across `carto_sql` for fuzzy-matching OSM tag values/typos (e.g. `LOWER(service) % 'siding'` in `rbt-schema/carto_sql/004_railway.sql`).

Confirm `pg_hba.conf` allows local password auth for the `abt` role (the default `scram-sha-256`/`peer` mix on a fresh install is normally fine for local TCP connections on `127.0.0.1`; only adjust this if `psql -h 127.0.0.1 -U abt` fails to connect below).

**Tune `postgresql.conf`** for the 384 GB planet tier documented in this guide (find the file with `sudo -u postgres psql -c 'SHOW config_file;'`):

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

Building the smaller single-extract tier instead (§6)? These lighter values are comfortably sized for 8 vCPUs / 32 GB instead:

```conf
shared_buffers = 8GB
effective_cache_size = 24GB
maintenance_work_mem = 2GB
max_worker_processes = 10
max_parallel_workers = 10
max_parallel_workers_per_gather = 4
random_page_cost = 1.1
```

### 3.3 imposm 0.14+

Not packaged in apt. Install the official static binary (no Go toolchain needed):

```bash
cd /tmp
curl -LO https://github.com/omniscale/imposm3/releases/download/v0.14.2/imposm-0.14.2-linux-x86-64.tar.gz
tar xzf imposm-0.14.2-linux-x86-64.tar.gz
sudo install -m 755 imposm-0.14.2-linux-x86-64/imposm /usr/local/bin/imposm
imposm version
```

### 3.4 tippecanoe 2.76+ (build from source)

Ubuntu 26.04's `tippecanoe` apt package is version 2.53.0 — below the pipeline's required >=2.76. Build the current release from source instead:

```bash
cd /tmp
git clone --branch 2.79.0 --depth 1 https://github.com/felt/tippecanoe.git
cd tippecanoe
make -j"$(nproc)"
sudo make install
tippecanoe --version
tile-join --version
```

Do **not** `sudo apt install tippecanoe` — it will silently satisfy the package manager while installing a version too old for some of the pipeline's export/bundler flags.

### 3.5 GDAL / Python environment

GDAL/`ogr2ogr` >=3.9.2 is required; Ubuntu 26.04 ships GDAL 3.12.2, so the system package alone would suffice for the CLI tool, but the Python side also needs GDAL's Python bindings plus several other packages, all pinned together in [`abtv2-tools/env.yaml`](abtv2-tools/env.yaml). Use conda/Miniforge for this rather than mixing system and pip GDAL builds:

```bash
cd /tmp
curl -L -O https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh
bash Miniforge3-Linux-x86_64.sh -b -p "$HOME/miniforge3"
source "$HOME/miniforge3/etc/profile.d/conda.sh"
conda init bash
exec bash   # reload shell so `conda` is on PATH
```

Then, from your `abtv2-tools` checkout (see §4 below for cloning):

```bash
cd ~/abt/abtv2-tools
conda env create -f env.yaml
conda activate abtv2
ogr2ogr --version
```

### 3.6 Verify everything

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

## 4. Clone the repo

`abtv2-tools/` and `rbt-schema/` are both subdirectories of this one repo, at
the same fixed relative path to each other that the CLI expects, so a single
clone is all `abt-tools.py` needs -- `--schema-dir ../rbt-schema` (used
throughout this doc) resolves correctly from inside `abtv2-tools/` without
any extra setup:

```bash
mkdir -p ~/abt && cd ~/abt
git clone git@github.com:ReleaseableBasemapTiles/abt.git .
```

(Use the HTTPS clone URL, `https://github.com/ReleaseableBasemapTiles/abt.git`,
instead if you don't have SSH keys configured for GitHub.)

If this is a private repo and you're using a deploy key rather than a
GitHub-wide SSH key, add a `Host` alias to `~/.ssh/config`:

```
Host abt
    HostName ssh.github.com
    Port 443
    User git
    IdentityFile ~/.ssh/id_ed25519_abt
    IdentitiesOnly yes
```

...then clone using the alias as the hostname instead of `github.com`:

```bash
git clone git@abt:ReleaseableBasemapTiles/abt.git .
```

`setup_ubuntu.sh` defaults `ABT_REPO` to exactly this alias-based URL;
override it if you're using a different SSH setup or the plain HTTPS URL.

## 5. Planet walkthrough

This builds a complete tileset for the entire planet (Geofabrik/OSM key `planet`, PBF currently 80+ GB) using the environment set up above.

### 5.1 Configure the database connection

```bash
conda activate abtv2
cd ~/abt/abtv2-tools

export PGHOST=127.0.0.1
export PGPORT=5432
export PGUSER=abt
export PGPASSWORD=abt
export PGDATABASE=abt_planet
```

With these exported, every command below can use `-p env` for `--pg-config`.

### 5.2 Download

```bash
python abt-tools.py download \
  -w ~/abt/run-planet \
  -s ../rbt-schema \
  -d all \
  -k planet \
  -n 12
```

- `-k planet` is actually the default `--osm-key` and could be omitted, but it's spelled out here for clarity, matching the explicit `-k norway` in the smaller single-extract walkthrough (§6).
- `-d all` downloads both the planet PBF and every auxiliary dataset (Natural Earth, NGA GeoNames, OurAirports, FieldMaps boundaries, USGS names, DoS LSIB, DISDI/MIRTA, OSM coastline/ocean extracts) -- none of these get clipped for a planet build; see the `-c` note under Import below.
- For `-k planet` specifically, the OSM PBF download goes through `aria2c` instead of a plain HTTP GET: [`planet_mirrors.py`](abtv2-tools/abt/download/planet_mirrors.py) queries the ~11 known public planet mirrors concurrently, cross-checks their reported MD5/date/size to agree on one current file, and hands every URL serving it to `aria2c` at once, which pulls segments from all of them in parallel -- aggregating their bandwidth instead of being capped by a single mirror. Checksum verification is mandatory: the download fails outright rather than proceeding on an unverified file if the mirrors can't be reconciled into one trustworthy hash.
- Output: `~/abt/run-planet/osm/pbf/planet-latest.osm.pbf` (80+ GB) and `~/abt/run-planet/aux_downloads/`.
- This step skips files that already exist, so it's safe to re-run if interrupted; `aria2c` itself also resumes a partial planet download and re-validates its checksum on resume.
- `-n/--num-workers` is shown explicitly (`12`) here since it matches this doc's 48 vCPU planet tier's auto-computed default for `download` (`cpu_count // 4`; see Sizing). It's optional everywhere it appears below -- `import` computes its own default as `cpu_count // 2`, `export` as `cpu_count // 3` -- pass it explicitly to override any of them.

### 5.3 Import

```bash
python abt-tools.py import \
  -w ~/abt/run-planet \
  -s ../rbt-schema \
  -d all \
  -n 24 \
  -p env \
  -k planet
```

- No `-c`/`--clip-aux` here -- it's a no-op for `-k planet` (there's no bounding box to clip aux data against for the whole planet), so every aux dataset loads in full.
- OSM data goes in via `imposm import` into the `osm` schema; aux data goes in via `ogr2ogr` in parallel into the `aux_data` schema (which is dropped and recreated first).
- This is the single longest step of a planet build -- expect 24+ hours even on the 48 vCPU / 384 GB tier documented above.
- If you re-run `import` after OSM data already loaded successfully, it will abort with an error unless you add `-f`/`--force` (a full re-import of the planet is expensive, so this guards against doing it by accident).

### 5.4 Carto (SQL transform)

```bash
python abt-tools.py carto \
  -w ~/abt/run-planet \
  -s ../rbt-schema \
  -p env
```

Runs every file in `rbt-schema/carto_sql/*.sql`, building the `export` schema from `osm`/`aux_data` -- by default several independent scripts run concurrently rather than strictly in filename order (see "Parallelism and carto concurrency" in §1), defaulting to 8 groups at once on this tier's 48 vCPUs; pass `-n 1` for the old one-at-a-time behavior. This always re-runs from scratch and aborts on the first prefix/suffix failure, or if any concurrent group fails — see §7 for the most likely failure here.

### 5.5 Export to tiles

```bash
python abt-tools.py export \
  -w ~/abt/run-planet \
  -s ../rbt-schema \
  -n 16 \
  -p env \
  -z 13
```

For each of the ~58 layers defined in `rbt-schema/export/*.json`: `export.<layer>` → `flatgeobuf/<layer>.fgb` (via `ogr2ogr`) → `mbtiles/<layer>.mbtiles` (via `tippecanoe`, up to zoom 13). Both conversion steps are skipped if their output file already exists, so a partial re-run only redoes missing layers -- valuable at this scale, since redoing the whole stage from scratch is expensive. This is the most disk-hungry step at global scale (`flatgeobuf/` and `mbtiles/` each hold a full planet's worth of geometry per layer); budget against the 2+ TB NVMe in Sizing above.

### 5.6 Bundle

```bash
python abt-tools.py bundler \
  -w ~/abt/run-planet \
  -s ../rbt-schema \
  -p env
```

Runs `tile-join` across every per-layer `.mbtiles` file, stamping metadata from `rbt-schema/tile-metadata/metadata.py`, and writes `~/abt/run-planet/bundled/joined.mbtiles`. At planet scale this reads every layer's full-planet `.mbtiles` at once and always rebuilds from scratch, so budget real time and disk headroom for this step too.

Add `-z/--max-zoom` (e.g. `-z 8`) to also produce a smaller, zoom-capped "RBT Small" package. Each input is pre-trimmed with SQLite to the given zoom before `tile-join` runs, rather than reading every layer's full-planet `.mbtiles` a second time just to filter by zoom.

### 5.7 (Optional) Vundler — Esri tile bundle

```bash
python abt-tools.py vundler \
  -w ~/abt/run-planet \
  -z 13
```

Converts `bundled/joined.mbtiles` into an Esri Compact Cache V2 bundle tree at `bundled/vundled/p12/`, converting zoom levels concurrently (one worker per core by default -- 48 here; see Sizing). This is not a complete `.vtpk` (no `conf.xml`/`root.json`/styles), just the raw tile bundle structure plus a bare `metadata.json`.

### 5.8 Check the results

Every stage writes a JSON summary and per-tool logs under a timestamped run folder:

```bash
cat ~/abt/run-planet/logs/*/summary.json
```

Inspect the final tileset:

```bash
sqlite3 ~/abt/run-planet/bundled/joined.mbtiles \
  "SELECT name, value FROM metadata;"
```

Or open `bundled/joined.mbtiles` in any MBTiles-aware viewer (e.g. QGIS, tileserver-gl, Mapbox Studio's local preview) to visually confirm global coverage -- coastlines, roads, and place names rendering correctly worldwide rather than just in one country.

## 6. Small extract walkthrough (Norway)

For fast iteration on schema/SQL changes -- without paying planet-scale time or disk cost -- the same pipeline can build a single Geofabrik extract instead of the whole planet. This walks through Norway (Geofabrik key `norway`, PBF currently ~1.4 GB) as a concrete example; swap in any other Geofabrik key for a different extract (see "Confirming your Geofabrik key" in §7). It assumes the 8 vCPU / 32 GB tier from Sizing above, and a separate `abt_norway` database (see the note at the end of §3.2) so it can coexist with a planet build on the same host.

### 6.1 Configure the database connection

```bash
conda activate abtv2
cd ~/abt/abtv2-tools

export PGHOST=127.0.0.1
export PGPORT=5432
export PGUSER=abt
export PGPASSWORD=abt
export PGDATABASE=abt_norway
```

With these exported, every command below can use `-p env` for `--pg-config`.

### 6.2 Download

```bash
python abt-tools.py download \
  -w ~/abt/run-norway \
  -s ../rbt-schema \
  -d all \
  -k norway \
  -n 4
```

- `-k norway` selects Norway from Geofabrik's live index instead of the default `planet` — **do not omit `-k`**, or this becomes a full-planet download.
- `-d all` downloads both the Norway PBF and every auxiliary dataset (Natural Earth, NGA GeoNames, OurAirports, FieldMaps boundaries, USGS names, DoS LSIB, DISDI/MIRTA, OSM coastline/ocean extracts).
- Output: `~/abt/run-norway/osm/pbf/norway-latest.osm.pbf` and `~/abt/run-norway/aux_downloads/`.
- This step skips files that already exist, so it's safe to re-run if it's interrupted.
- `-n/--num-workers` is shown explicitly (`4`) here since it matches this tier's (8 vCPU) auto-computed default; it's optional everywhere it appears below and scales up on its own on bigger hosts (see Sizing) -- pass it explicitly to override either way.

### 6.3 Import

```bash
python abt-tools.py import \
  -w ~/abt/run-norway \
  -s ../rbt-schema \
  -d all \
  -n 4 \
  -p env \
  -k norway \
  -c
```

- `-c`/`--clip-aux` clips the globally-scoped aux datasets (Natural Earth, coastlines, etc.) to Norway's bounding box before loading them — this is what keeps a "small area" build fast; it's ignored if `-k` is `planet` or omitted (see §5.3).
- OSM data goes in via `imposm import` into the `osm` schema; aux data goes in via `ogr2ogr` in parallel into the `aux_data` schema (which is dropped and recreated first).
- If you re-run `import` after OSM data already loaded successfully, it will abort with an error unless you add `-f`/`--force` (a full re-import is assumed to be expensive, even though Norway alone is fast).

### 6.4 Carto (SQL transform)

```bash
python abt-tools.py carto \
  -w ~/abt/run-norway \
  -s ../rbt-schema \
  -p env
```

Runs every file in `rbt-schema/carto_sql/*.sql`, building the `export` schema from `osm`/`aux_data` -- by default several independent scripts run concurrently rather than strictly in filename order (see "Parallelism and carto concurrency" in §1), though on an 8 vCPU host this computes to 1 (fully sequential), matching pre-concurrency behavior. This always re-runs from scratch and aborts on the first prefix/suffix failure, or if any concurrent group fails — see §7 for the most likely failure here.

### 6.5 Export to tiles

```bash
python abt-tools.py export \
  -w ~/abt/run-norway \
  -s ../rbt-schema \
  -n 4 \
  -p env \
  -z 13
```

For each of the ~58 layers defined in `rbt-schema/export/*.json`: `export.<layer>` → `flatgeobuf/<layer>.fgb` (via `ogr2ogr`) → `mbtiles/<layer>.mbtiles` (via `tippecanoe`, up to zoom 13). Both conversion steps are skipped if their output file already exists, so a partial re-run only redoes missing layers.

### 6.6 Bundle

```bash
python abt-tools.py bundler \
  -w ~/abt/run-norway \
  -s ../rbt-schema \
  -p env
```

Runs `tile-join` across every per-layer `.mbtiles` file, stamping metadata from `rbt-schema/tile-metadata/metadata.py`, and writes `~/abt/run-norway/bundled/joined.mbtiles`.

Add `-z/--max-zoom` to cap the output at a given zoom level for a smaller package, e.g. an "RBT Small" build.

### 6.7 (Optional) Vundler — Esri tile bundle

```bash
python abt-tools.py vundler \
  -w ~/abt/run-norway \
  -z 13
```

Converts `bundled/joined.mbtiles` into an Esri Compact Cache V2 bundle tree at `bundled/vundled/p12/`. This is not a complete `.vtpk` (no `conf.xml`/`root.json`/styles), just the raw tile bundle structure plus a bare `metadata.json`.

### 6.8 Check the results

Every stage writes a JSON summary and per-tool logs under a timestamped run folder:

```bash
cat ~/abt/run-norway/logs/*/summary.json
```

Inspect the final tileset:

```bash
sqlite3 ~/abt/run-norway/bundled/joined.mbtiles \
  "SELECT name, value FROM metadata;"
```

Or open `bundled/joined.mbtiles` in any MBTiles-aware viewer (e.g. QGIS, tileserver-gl, Mapbox Studio's local preview) to visually confirm Norway's coastline, roads, and place names rendered correctly.

## 7. Troubleshooting

**`ERROR: password is required` / `dblink_connect` fails in `carto`.**
The `abt` role isn't a superuser, or `pg_hba.conf` doesn't trust its local connections. Re-run the `CREATE ROLE ... SUPERUSER` step in §3.2, or add a `trust`/`scram-sha-256` entry for `abt` on `127.0.0.1/32` in `pg_hba.conf` and `sudo systemctl reload postgresql`.

**`carto` fails partway through, referencing `aux_data.mirtalocations_a` (in `023_military.sql`) or another `aux_data.*` table that "doesn't exist".**
This means the corresponding aux source failed to download or import — check `~/abt/run-planet/logs/<run_id>/download/` and `.../import/` (or `~/abt/run-norway/...` if you're on the small-extract walkthrough) for that source's log. The MIRTA/DISDI installations dataset in particular is fetched from `datacollects.blob.core.usgovcloudapi.net` (see [`rbt-schema/import/aux_data/disdi_mirta.json`](rbt-schema/import/aux_data/disdi_mirta.json)) and may be unreachable from some networks; a failed download here doesn't surface as an error until `carto` runs `023_military.sql` and finds the table missing. `carto_sql` scripts are idempotent, so once the underlying aux data is fixed (re-run `download`/`import` for just that source, or use `debug_aux_import`), just re-run `carto` — it always starts from `000_*.sql` again.

**One `carto` script/group fails; does the whole run abort?**
The sequential prefix (`000`/`001`) and suffix (`099`) still abort the whole run if they fail. In between, each independent group (see "Parallelism and carto concurrency" above) fails on its own — other groups still run to completion, and the error names the failing group, e.g. `1 of 29 carto group(s) failed, suffix not run: 023_military: ...`. Fix the root cause, then simply re-run `python abt-tools.py carto ...` — every script drops/recreates its own tables, so re-running the whole stage (including groups that already succeeded) is safe, just not the cheapest option if only one layer needs a fix.

**A `download` or `import` run appears to be pulling the entire planet when you only wanted a small extract.**
`-k`/`--osm-key` defaults to `planet` when omitted. Always pass `-k norway` (or your target Geofabrik key) explicitly for the small-extract walkthrough in §6.

**Is a planet `download` actually pulling from multiple mirrors, or just one?**
Check the `download` stage's log for `planet` under `logs/<run_id>/download/` — [`planet_mirrors.py`](abtv2-tools/abt/download/planet_mirrors.py)'s `discover_planet_sources` logs every mirror it queried and which URLs it ultimately handed to `aria2c`. If too few mirrors respond, or they disagree on the file's MD5/timestamp/size, the download raises rather than silently falling back to a single unverified source — checksum verification is mandatory for `-k planet`.

**`import` aborts with "OSM schema already contains data".**
This is a safety check — a full re-import can take a long time, especially for the planet. Pass `-f`/`--force` to proceed anyway.

**You only need to rebuild one export layer.**
Delete its `flatgeobuf/<layer>.fgb` and/or `mbtiles/<layer>.mbtiles`, then re-run `export`. Deleting only the `.mbtiles` (keeping the `.fgb`) skips straight to the `tippecanoe` step.

**Confirming your Geofabrik key.**
The full list of valid `-k` values is Geofabrik's live index at `https://download.geofabrik.de/index-v1.json`; Norway's `id` is `norway`, and its PBF lives at `https://download.geofabrik.de/europe/norway-latest.osm.pbf`. `planet` is a special-cased key handled by the multi-mirror `aria2c` path in §5.2 and doesn't appear in that index.
