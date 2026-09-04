# ABT Tools (abtv2-tools)

Modular pipeline for building vector tilesets from OpenStreetMap and other open data. Chains together open-source utilities to produce Mapbox vector tilesets (.mbtiles) and Esri Vector Tile Packages (.vtpk).

Entry point: `python abt-tools.py <command> [options]`

This directory is one half of the monorepo: it's the generic pipeline runner, paired with the sibling [`../rbt-schema/`](../rbt-schema/) schema/config directory passed in as `--schema-dir` -- see "Pipeline" below for what that directory needs to contain. If you're setting up a fresh host and/or want a full worked example (Ubuntu 26.04 provisioning, a full planet build end to end, plus a smaller single-extract variant), see the parent workspace's [`README.md`](../README.md); this file is the standalone CLI/pipeline reference.

## Dependencies

ABT was developed in Python 3.14 (see `env.yaml`) and tested on Rocky Linux 9 and Ubuntu 26.04.

- Python 3.14
- PostgreSQL >=16 / PostGIS >=3.4
- GDAL (ogr2ogr) >=3.9.2
- imposm3 >=0.14
- tippecanoe >=2.76
- aria2 (`aria2c`) -- only needed for `download -k planet`; see "Commands" below

Python packages: `env.yaml`. PostgreSQL connection: `PGHOST`/`PGPORT`/`PGDATABASE`/
`PGUSER`/`PGPASSWORD` env vars, or `--pg-config`.

`postgis`, `hstore`, `dblink`, and `pg_trgm` extensions must be created in the target
database (`hstore` for imposm's `hstore_tags` column, `dblink` for the parallel-dissolve
`carto_sql` scripts below, `pg_trgm` for the `%` fuzzy-match operator used throughout
`carto_sql`); `dblink`'s password-less internal connections additionally require the
pipeline's PostgreSQL role to be a superuser (or explicitly trusted via `pg_hba.conf`).

For a from-scratch Ubuntu 26.04 host, [`setup_ubuntu.sh`](setup_ubuntu.sh) automates
all of the above (packages, PostGIS, imposm3/tippecanoe builds, the Python env, and this
database/role/extension setup) -- see "Ubuntu setup script" below.

## Ubuntu setup script

[`setup_ubuntu.sh`](setup_ubuntu.sh) is an idempotent bootstrap for a fresh Ubuntu
26.04 host that installs everything under Dependencies above end to end: base build
tooling, PostgreSQL 18 + PostGIS 3.6 (initialized directly via `initdb`/`pg_ctl` under
a custom systemd unit rather than Debian's `postgresql-common` cluster tooling), the
`postgis`/`hstore`/`dblink`/`pg_trgm` extensions plus a superuser role and database,
`imposm3` and `tippecanoe` built from source (`master`/`main` by default), a
`micromamba`-managed Python env from `env.yaml`, kernel/ulimit tuning for
high-throughput I/O (`vm.swappiness`, dirty-page ratios, `nofile`/`nproc` limits), and
optionally clones the monorepo (this directory plus its `../rbt-schema/` sibling).

```bash
./setup_ubuntu.sh
```

Safe to re-run: every stage checks whether its work is already done before repeating
it (e.g. skips rebuilding `tippecanoe` if it's already on `PATH`, skips `initdb` if
`PG_VERSION` already exists at `PG_DATA_DIR`). Output is mirrored to a timestamped log
file under `$HOME` (override with `LOG_FILE`).

Configuration is entirely via environment variables, all optional; a few of the more
commonly overridden ones:

| Variable | Default | Purpose |
|---|---|---|
| `ABT_WORKSPACE_DIR` | `/rbt` | Root dir for the repo checkout + run data |
| `PG_DATA_DIR` | `/var/lib/postgresql/<major>/main` | PostgreSQL data directory (e.g. point at a mounted NVMe device) |
| `PG_DB` / `PG_USER` / `PG_PASSWORD` / `PG_PORT` | `rbt` / `rbt` / `rbt` / `5432` | Pipeline's database/role |
| `IMPOSM_REF` / `TIPPECANOE_REF` | `master` / `main` | Git ref each tool is built from |
| `CONDA_ENV_NAME` | `abtv2` | micromamba environment name |
| `CLONE_REPO` | `true` | Set `false` to skip cloning `ABT_REPO` |
| `INSTALL_POSTGRES` / `INSTALL_IMPOSM` / `INSTALL_TIPPECANOE` / `INSTALL_CONDA` | `true` | Set any to `false` to skip that stage entirely |

For the complete list (every variable, its default, and inline comments explaining
the reasoning), read the "Configuration" block at the top of the script itself. See
the parent workspace's [`README.md`](../README.md) section 3 for the manual,
step-by-step equivalent of what this automates, section 5 for a full planet
walkthrough using the environment it sets up, and section 6 for a smaller
single-extract variant.

## Pipeline

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

All commands take `-w/--working-dir` (output) and `-s/--schema-dir` (input config).

`--schema-dir` (you provide this):
```
import/osm/        imposm mapping YAML
import/aux_data/   aux data JSON configs
export/            per-layer export JSON configs
carto_sql/         SQL scripts; run in filename order by default, or grouped
                   by an optional carto_sql/execution_plan.yml -- see "Carto
                   concurrency" below
tile-metadata/     metadata.py, defines a `metadata` dict (name, description,
                   attribution, tags, license, etc.) written into the bundled
                   mbtiles -- required by `bundler`
```

## Sizing

`carto_sql` scripts can hardcode aggressive session tuning and a fixed degree of
parallelism (e.g. `SET work_mem = '2GB'`, 10-way `max_parallel_workers_per_gather`),
independent of whatever `-s/--schema-dir` you point at. Some also open many parallel
`dblink` worker connections (e.g. 16, in `rbt-schema`'s water/land-cover dissolve
scripts) to fan out a global polygon dissolve -- this cost is the same whether you're
building a small extract or the full planet, since it's driven by the *source* data's
global extent, not your `-k`/`--osm-key` selection. The parallel-worker and dblink
shard counts are overridable per run via custom Postgres GUCs rather than fixed --
see "Carto concurrency" below.

As a rough guide for a single-country/small-extract build: 8 vCPUs, 32 GB RAM, and
100 GB SSD is comfortable. A full-planet build needs meaningfully more (32+ vCPUs,
128+ GB RAM, 2+ TB NVMe) and the `import` step alone can take 24+ hours. Tune
Postgres's own `shared_buffers`/`effective_cache_size` in `postgresql.conf` well below
what `carto_sql`'s per-session `work_mem`/`maintenance_work_mem` overrides request,
since those are additive per concurrent `dblink` worker, not shared.

### Large single-host tier (48 vCPUs / 384 GB)

On a big single box, both the CLI and `carto_sql` itself scale up automatically
rather than needing to be babysat per invocation:

- `-n/--num-workers` (`download`/`import`/`export`) defaults to a value derived
  from `os.cpu_count()` instead of a flat `4` -- still fully overridable, but
  sized so you don't need to pass `-n` by hand just to make use of the box.
- `carto` accepts a `--carto-concurrency` flag (also auto-scaled by default) to
  run independent `carto_sql` script groups concurrently instead of one script
  at a time -- see "Carto concurrency" below. It scales down each concurrent
  group's internal `dblink`/parallel-worker settings so groups don't fight each
  other for the same cores; see the `abt.*` settings referenced there.
- `setup_ubuntu.sh`'s `PG_*` tuning variables need overriding for this tier --
  see the parent workspace [`README.md`](../README.md) Sizing section for a
  copy-pasteable block (`shared_buffers`/`effective_cache_size` scaled to 384 GB,
  `max_connections` raised to cover concurrent `carto` groups' `dblink` fan-out).

## Carto concurrency

By default `carto` runs every `carto_sql/*.sql` file sequentially, in filename
order -- unchanged from before. If `-s/--schema-dir`'s `carto_sql/execution_plan.yml`
is present, it instead runs in three phases (see [`abt/carto_processing_model.py`](abt/carto_processing_model.py)):

1. **Prefix** -- runs sequentially (e.g. schema setup, aux geometry normalization).
2. **Groups** -- each group is an ordered list of scripts that must run on one
   connection in that order (e.g. a script that calls a function another script
   defines); independent groups run concurrently with each other, up to
   `-n/--carto-concurrency` at a time.
3. **Suffix** -- runs sequentially, only once every group has succeeded (e.g.
   the final geometry-normalization pass, which touches every `export.*` table).

`rbt-schema/carto_sql/execution_plan.yml` also lists every custom schema/extension
these scripts create (`water`, `landcover`, `dblink`, etc.); `carto` creates all of
them once, up front, before any group starts -- `CREATE SCHEMA/EXTENSION IF NOT EXISTS`
is not safe to run from two concurrent sessions the *first* time a schema is created,
so this avoids that race entirely rather than relying on script ordering.

Because several groups now share the box at once, `carto` also scales down two
custom Postgres GUCs for the duration of the groups phase -- `abt.dissolve_shards`
(dblink worker connections a water/land-cover-style dissolve opens) and
`abt.parallel_workers_per_gather` (native Postgres parallel workers per query) --
roughly proportional to `(available cores) / --carto-concurrency`. Scripts that
don't read these GUCs (`current_setting('abt.dissolve_shards', true)`, with a
`COALESCE` fallback to their original hardcoded value) are unaffected either way.

`execution_plan.yml` is validated against the actual `carto_sql/*.sql` files present
before anything runs: a script on disk but missing from the plan (would silently
never execute), a plan entry with no matching file, or a script listed twice all
fail fast with a clear error rather than silently producing an incomplete tileset.

If `execution_plan.yml` is absent, or `--carto-concurrency 1` is passed explicitly,
`carto` falls back to the exact historical sequential behavior.

## Commands

```
download -w <dir> -s <dir> -d {osm,aux,all} [-n workers] [-k osm_key]
```
Downloads OSM PBF and/or aux files. Skips files that already exist.
`-k/--osm-key` **defaults to `planet`** when omitted -- always pass an explicit
Geofabrik key (e.g. `-k norway`) unless a full-planet download is actually intended.

For `-k planet` specifically, OSM PBF download goes through `aria2c` instead of a
plain HTTP GET: [`abt/download/planet_mirrors.py`](abt/download/planet_mirrors.py)
queries the ~11 known public planet mirrors concurrently, cross-checks their
reported MD5/date/size to agree on one current file, and hands every URL serving
it to `aria2c` at once, which downloads segments from all of them in parallel --
aggregating their bandwidth instead of being capped by any single mirror. MD5
verification is mandatory for planet: if the mirrors can't be reconciled into one
trustworthy hash, the download fails rather than proceeding unverified. Geofabrik
extracts only ever publish one URL each, so they keep using the original
single-stream `requests` downloader -- this only changes `-k planet` behavior.
Requires the `aria2` apt package (installed by `setup_ubuntu.sh`).

```
import -w <dir> -s <dir> -d {osm,aux,all} [-n workers] [-p pg_config] [-k osm_key] [-f] [-c]
```
Imports OSM (imposm) and/or aux data (ogr2ogr) into PostgreSQL. Always full re-run.
If OSM data already exists, the whole command aborts with an error rather than
overwriting it (a full re-import can take 24+ hours) -- pass `-f/--force` to proceed
anyway. `-c/--clip-aux` clips aux data imports to the `-k` GeoFabrik extract's
bounding box (both a `-spat` pre-filter and a real `-clipsrc` clip, since a
bbox filter alone won't shrink a globally-dissolved layer) -- for fast test
builds; ignored when `-k` is `planet` or omitted.

```
carto -w <dir> -s <dir> [-p pg_config] [-n carto_concurrency]
```
Runs every `carto_sql/*.sql` file, in filename order by default, or in the
groups defined by `-s/--schema-dir`'s `carto_sql/execution_plan.yml` -- see
"Carto concurrency" above. `-n/--carto-concurrency` caps how many independent
groups run at once (defaults to a value scaled to this host's CPU count; `1`
forces the historical fully-sequential behavior). Always re-runs everything;
scripts must be safe to re-run.

```
export -w <dir> -s <dir> [-n workers] [-p pg_config] [-z max_zoom] [--projection-override EPSG:code]
```
Per layer: PostgreSQL -> FlatGeobuf (ogr2ogr) -> MBTiles (tippecanoe). Skips either
step if its output file already exists. `--projection-override` is advanced/
non-standard (`export --help` for details); output still uses the `.mbtiles`
extension but won't conform to the MBTiles 1.3 spec.

```
bundler -w <dir> -s <dir> [-p pg_config] [-q path ...] [-o output_name] [-z max_zoom]
```
Joins all `mbtiles/*.mbtiles` (or `.btis`) per layer into one package via
tile-join. Always rebuilds from scratch. Fails on mismatched projections across
inputs. Output defaults to `joined.mbtiles`; `-o/--output-name` overrides this
and is used exactly as given.
`-q/--additional-mbtiles` folds in an externally-produced mbtiles file (e.g.
contours); repeatable for more than one. `-z/--max-zoom` caps the bundle at a
given zoom level -- e.g. for a smaller "RBT Small" package -- by pre-trimming
every input with SQLite before tile-join runs; omit for no cap (full
resolution).

```
vundler -w <dir> [-i input_path] [-o output_dir] [-z max_zoom] [-n workers]
```
Converts a bundled mbtiles file into Esri Compact Cache V2 tile bundles
(`.bundle` files per zoom level, plus a bare `metadata.json`), zoom levels
converted concurrently (`-n/--num-workers`, defaults to one per core). Not a
complete `.vtpk` -- no `conf.xml`/`root.json`/styles. `-i/--input-path`
defaults to `bundled/joined.mbtiles` (or `joined.btis`, if present);
`-o/--output-dir` defaults to `bundled/vundled/p12`.

## Reuse

Only `export` and `download` skip existing outputs. `import`, `carto`,
`bundler`, and `vundler` always redo the full operation.

To rebuild one layer: delete its `flatgeobuf/<layer>.fgb` and/or
`mbtiles/<layer>.mbtiles` (or `.btis`, if present), then re-run `export`. Deleting
only the mbtiles file (keeping the fgb) skips straight to the tippecanoe step.

## Troubleshooting

**One `carto` script/group fails; does the whole run abort?**
The sequential prefix and suffix (see "Carto concurrency" above) still abort the
whole run if they fail. A script inside a concurrent group failing only aborts
that group -- [`abt/carto_processing_model.py`](abt/carto_processing_model.py)
still runs every other independent group to completion, then raises once they've
all finished, naming exactly which group(s) failed. Without `execution_plan.yml`
(or with `-n/--carto-concurrency 1`), it's the historical behavior: sequential,
stops at the first exception. Either way, fix the root cause and re-run `carto`
-- every script drops/recreates its own tables, so re-running is safe.

**Confirming a Geofabrik key.**
The full list of valid `-k`/`--osm-key` values is Geofabrik's live index at
`https://download.geofabrik.de/index-v1.json` (each entry's `id` field is a valid
key); the corresponding PBF lives at `https://download.geofabrik.de/<id>-latest.osm.pbf`.

**`ERROR: password is required` / `dblink_connect` fails in `carto`.**
The configured PostgreSQL role isn't a superuser, or `pg_hba.conf` doesn't trust its
local connections -- see the `dblink`/`pg_trgm` note under Dependencies above.

## Debug

```
debug_aux_import -w <dir> -s <dir> -a <aux_file> [-p pg_config]
```
Imports a single aux file in isolation.
