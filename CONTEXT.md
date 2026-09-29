# CONTEXT.md

This is background for anyone, human or agent, who is about to change this repo. It covers what
the project produces, its vocabulary, how the pieces fit together, and why they are built the way
they are. Operational rules and commands are in [CLAUDE.md](CLAUDE.md), and step-by-step guides
are in `docs/`. Everything here was checked against the code on 2026-09-29. Where the prose docs
and the code disagree, the code wins; see [Known doc drift](#known-doc-drift).

## What the project produces

The product is **RBT (Releasable Basemap Tiles)**, a global vector basemap. It is built from
OpenStreetMap plus these authoritative open datasets:

- Natural Earth
- NGA GeoNames
- OurAirports
- FieldMaps administrative boundaries
- USGS domestic names
- the U.S. Department of State LSIB
- DISDI/MIRTA installations
- Overture Maps buildings

The repo and tooling are called **ABT**. Older docstrings expand that as "Army Basemap Tiles", and
so does the fallback bundle name used by `tile-join`. The tileset's own
`tile-metadata/metadata.py` names it "Releasable Basemap Tiles (RBT)".

The pipeline can produce three outputs per projection. A production run of `init.sh` builds and
uploads only the first. The other two take a separate `bundler -z` or `vundler` run:

| Output | Location | Notes |
|---|---|---|
| Bundled vector tileset | `<working_dir>/bundled/joined.mbtiles` | Vector tiles (`format: pbf`), zooms 0–13 by default. Uploaded to S3 as `RBT.mbtiles` for EPSG:3857 and as `RBT.btis` for any other projection. |
| "RBT Small" | Same file, built with `bundler -z <N>` | A copy of the bundle capped at a lower zoom. |
| Esri Compact Cache V2 | `<working_dir>/bundled/vundled/p12/` | `tile/L##/R####C####.bundle` files plus `metadata.json`. This isn't a complete `.vtpk`; there's no `conf.xml` or `root.json`. |

The default projections are:

- **EPSG:3857 (Web Mercator).** Produces standard MBTiles.
- **EPSG:3395 (World Mercator)** and **EPSG:4087 (World Equidistant Cylindrical).** Produce
  non-standard MBTiles, tagged per the BTIS convention (NGA.IS.0081-1). See
  [Projections](#projections-and-the-override-trick).

The code is a U.S. Government work, dedicated to the public domain under CC0 (`LICENSE`). `NOTICE`
covers the MIT-licensed planet-mirror code that `abt/download/planet_mirrors.py` adapts from
openmaptiles-tools. Generated tiles keep their source data's licenses. OSM, FieldMaps, and Overture
data are under ODbL, which requires attribution and share-alike.

## Glossary

| Term | Meaning in this repo |
|---|---|
| `abtv2-tools` | The engine: the `abt-tools.py` CLI, the `abt/` package, and the Rust `vundler-rs/`. It's generic and has no knowledge of specific layers. |
| `rbt-schema` | The content: everything passed as `--schema-dir`. It defines *what* gets built. |
| schema dir | A directory containing `import/osm/`, `import/aux_data/`, `export/`, and `carto_sql/`, which `DataSchema` validates. `bundler` also requires `tile-metadata/metadata.py`. |
| working dir | The output tree for a run, passed as `-w`. See [Working directory layout](#working-directory-layout). |
| Geofabrik key | A region ID from Geofabrik's index, such as `norway`, passed as `-k`. The value `planet` means the full planet PBF, downloaded from several mirrors with `aria2c`. |
| aux data | Any non-OSM source, with one `import/aux_data/*.json` config per source. `ogr2ogr` loads it into the `aux_data` schema. |
| imposm (imposm3) | Loads the OSM PBF into the `osm` schema using the mappings in `import/osm/*.yml`, creating `osm.osm_<mapping>` tables. It's built from omniscale/imposm3. It drops every tag that nothing loads while it reads the PBF; see `import/imposm_base.yml`. |
| carto | The SQL transform stage. It runs `carto_sql/*.sql` to build the `export.*` materialized views. It has nothing to do with CartoCSS. |
| execution plan | `carto_sql/execution_plan.yml`, which splits the carto scripts into a prefix, groups that run concurrently, and a suffix. |
| layer / `layer_id` | One output tile layer. Each has one `export/*.json` config, one `export.<layer_id>` view, and one per-layer `.mbtiles` file. |
| FlatGeobuf (`.fgb`) | The intermediate format between PostGIS and tippecanoe, stored in `<working_dir>/flatgeobuf/`. |
| tippecanoe / `tile-join` | tippecanoe builds each per-layer `.mbtiles` from its `.fgb`; `tile-join` merges them into one file. Both come from the felt/tippecanoe fork, built from source. |
| MBTiles | A SQLite container for tiles (tables `tiles` or `map` plus `images`, and `metadata`). |
| BTIS | The Basemap Tile Package convention (NGA.IS.0081-1). Here it means the `crs`, `btp_schema_version`, and `changelog_url` metadata rows added to non-3857 output, and the `.btis` object name used on S3. |
| projection override | `export --projection-override EPSG:<code>`. PostGIS reprojects the data, and tippecanoe is told the result is already in EPSG:3857. |
| bundler | The `tile-join` stage, which writes `bundled/joined.mbtiles`. |
| vundler | Converts the bundle to Esri Compact Cache V2, where each `.bundle` file holds a 128×128 block of tiles. The Rust binary `abt-vundler` does the work. |
| Overture pipeline | The scripts in `rbt-schema/scripts/overture/`. They build `building_polygon_<srs>.mbtiles` without Postgres, and `bundler -q` adds it to the bundle. |
| run summary | `<working_dir>/logs/<run_id>/summary.json`, written by `RunReporter`. It records `SUCCESS` or `FAILED` for each task in each stage, plus an overall status of `SUCCESS`, `FAILED`, or `PARTIAL_FAILURE`. |
| mirrors | Standalone copies of `abtv2-tools/` and `rbt-schema/`, published from abt's `main`. |

## The pipeline

The pipeline is a strict sequence of CLI subcommands. There's no DAG engine or scheduler;
`init.sh` is the only thing that chains the stages together.

| Stage | Does | External tools | Reads → writes | When re-run |
|---|---|---|---|---|
| `download` | Fetches the OSM PBF and every aux source | `requests`, `aria2c` (planet only, checksums compared across mirrors), `boto3` (anonymous S3 access) | Geofabrik index and source URLs → `osm/pbf/`, `aux_downloads/` | Skips files that are already present |
| `import` | Loads everything into PostGIS | `imposm`, `ogr2ogr` | PBF and downloads → schemas `osm` and `aux_data` | Drops and rebuilds `aux_data`. Won't re-import into a populated `osm` schema without `-f`, because a planet import takes over 24 hours. `-c` clips the aux data to the extract's bounding box. |
| `carto` | Builds the view for every layer | SQL through `psycopg2`, with `dblink` inside the SQL | `osm`, `aux_data` → `export` and the intermediate schemas | Always rebuilds everything; the scripts are idempotent |
| `export` | For each layer, exports PostGIS → `.fgb` → `.mbtiles` | `ogr2ogr`, `tippecanoe` | `export.*` → `flatgeobuf/`, `mbtiles/` | Skips an existing `.fgb` and an `.mbtiles` that holds tiles. Each tool writes under `.partial/`, and its file moves into place only when the tool exits 0, so a crash leaves nothing at the final path. A tile-less `.mbtiles` from older code is deleted and rebuilt; a truncated `.fgb` from older code is still skipped, so delete it. |
| `bundler` | Joins the layer files and any `-q` extras | `tile-join`, SQLite | `mbtiles/` → `bundled/joined.mbtiles` | Always rebuilds everything |
| `vundler` | Converts the bundle to Esri format | `abt-vundler` | `bundled/joined.mbtiles` → `bundled/vundled/p12/` | Always rebuilds everything |

For debugging, `debug_aux_import -a <name>` imports a single aux config,
`import/aux_data/<name>.json`. Pass the basename without the extension.

### Working directory layout

`ProcessingDirectorySchema.init_working_directories()` creates this tree on every invocation
except `vundler`'s. `docs/overview/working-directory.md` lists every file:

```text
<working_dir>/
  osm/                 PBF (osm/pbf/), imposm cache and mapping
  aux_downloads/       downloaded and extracted aux sources; <file>.part while downloading,
                       <name>_extracted.partial/ while extracting, then .<name>_extracted.complete
  flatgeobuf/          <layer_id>.fgb       (export, step 1; written in flatgeobuf/.partial/ first)
  mbtiles/             <layer_id>.mbtiles   (export, step 2; written in mbtiles/.partial/ first)
  bundled/             joined.mbtiles, vundled/p12/, and _tmp/ (bundler -z only)
  tmp/                 ogr_tmp/, tippecanoe_tmp/, per-layer temp dirs
  logs/<run_id>/       one per invocation (YYYY-MM-DD_HHMMSS): download/ import/ carto/ fgb/
                       mbtiles/, a *.log per task, and summary.json
```

`.fgb` filenames don't include the projection, so each projection needs its own working dir.
`init.sh` uses `$WORKSPACE` for EPSG:3857 and `$WORKSPACE-<srs>` for every other projection.

### PostgreSQL

- **Schemas:**
  - `osm`, loaded by imposm.
  - `aux_data`, loaded by `ogr2ogr`.
  - `export`, with one materialized view per layer. Carto can also build views that nothing
    tiles, such as `export.golf_course` and `export.sports_ground`.
  - Intermediate schemas that carto owns, listed under `custom_schemas` in
    `execution_plan.yml`: `water`, `transportation`, `landuse`, `landcover`, `infrastructure`,
    `aeroway`, `dam`, and `poi`.
- **Extensions:**
  - `postgis`
  - `hstore`, for imposm's tag columns
  - `dblink`, for the parallel dissolve workers inside the carto SQL
  - `pg_trgm`, for fuzzy matching of tag values

  The carto scripts open `dblink` loopback connections with no user or password
  (`dbname=… port=…`). dblink allows a password-less connection only for a superuser, whatever
  `pg_hba.conf` says, so the pipeline role must be a superuser. Each loopback session logs in over
  the local socket as `postgres`, the OS user the server runs as, so the server must also accept
  `postgres` on that socket without a password. A `setup_ubuntu.sh` cluster trusts every local
  connection, and a stock Ubuntu cluster uses `peer`.
- **Connection:** `-p env` reads `PGHOST`, `PGPORT`, `PGUSER`, `PGPASSWORD`, and `PGDATABASE`,
  and doesn't connect until the first query. `-p "host,port,user,password,db"` runs `SELECT 1` at
  startup to test the connection.
- **`bundler` still needs `-p`,** even though it never queries Postgres. It builds `TileLayer`
  objects, and each one requires a `PGConfig`.
- **`max_connections` has to be high.** `setup_ubuntu.sh` sets 400 because each concurrent carto
  group can open up to 16 extra `dblink` connections. A limit that's too low fails partway through
  a run rather than at startup.

## How `abtv2-tools` is put together

```text
abt-tools.py                 the root Typer app. Its callback raises RLIMIT_NOFILE, then it
                             mounts one sub-app per command (7 in all)
  abt/cli_funcs/<stage>.py   parses flags (from utils/fields.py), calls init_*(), sets the exit code
    engine module            builds command lines or SQL from the schema config
      run_subprocess()       runs ogr2ogr, tippecanoe, tile-join, imposm, or abt-vundler, with a
                             log per task
```

| Module | Role |
|---|---|
| `schema.py` | `DataSchema` validates the schema dir and finds its files. `ProcessingDirectorySchema` builds the working-dir tree. |
| `osm_data_model.py` | Reads the Geofabrik index, selects the OSM extract, handles imposm mapping files and setup, and computes the bounding box for `-c`. |
| `aux_data_model.py` | Turns each `import/aux_data/*.json` into an `AuxDataLayer`, then builds its download and `ogr2ogr` import commands. |
| `download/` | `downloader.py` handles HTTP and S3. `planet_mirrors.py` finds planet mirrors and requires them to agree on checksums. |
| `importer/importer.py` | `Importer` runs one `ogr2ogr` or `imposm` import. |
| `carto_processing_model.py` | `CartoExecutionPlan`, `CartoGroup`, and `CartoProcessingModel`. |
| `export/tile_layer_model.py` | `TileLayer` turns one `export/*.json` into the `ogr2ogr` SQL and flags and the `tippecanoe` flags. |
| `export/exporter.py` | Runs the two export steps and skips work that's already done. |
| `export/bundler_model.py`, `export/bundler.py` | Build the `tile-join` command, trim zooms, and rewrite the metadata. |
| `export/mbtiles_metadata.py` | Reads and writes the metadata table. It also holds the BTIS constants, looks up a CRS's area of use, and checks whether a tileset is complete. |
| `vundler.py`, `vundler_model.py` | A thin wrapper that shells out to `abt-vundler`. |
| `parallel.py` | `ParallelExecutor`: a thread pool with per-task logging that reports into `RunReporter`. |
| `utils/` | `fields.py` defines every CLI option and `default_num_workers`. Also `pg_config.py`, `subprocess_tools.py`, `logger.py`, `run_reporter.py`, `rlimit.py`, and `zip_tools.py`. |

### Concurrency

- **Threads, not processes.** `ParallelExecutor` is a `ThreadPoolExecutor`. Each task spends most
  of its time waiting on a subprocess, so the GIL doesn't matter. `download` and `import` also
  run the OSM step on a thread of its own, alongside the `-n` aux workers, so with `-d all`
  imposm and the aux imports share the host.
- **Worker defaults scale with the host.** Each default is `max(floor, cpu_count // divisor)`,
  computed at import time. The floor is 4 unless noted.

  | Command | Divisor | Notes |
  |---|---|---|
  | `download` | 4 | |
  | `import` | 2 | |
  | `export` | 3 | Each worker runs a multi-threaded tippecanoe. |
  | `vundler` | 1 | |
  | `carto --carto-concurrency` | 6 | The floor is 1, so carto runs sequentially on an 8-vCPU host and runs 8 groups at once on a 48-vCPU host. |

- **carto runs in stages:**
  1. It creates everything in `custom_schemas` and `extensions` once, up front. Otherwise
     concurrent sessions would race on the first `CREATE SCHEMA`.
  2. It runs the prefix scripts one at a time.
  3. It runs the groups concurrently, starting them in plan order, longest first. A group runs its
     scripts in order, each on its own connection, so session state doesn't carry from one script
     to the next. A failing group doesn't stop the other groups.
  4. It runs the suffix only if every group succeeded.

  Before any of this, it checks the plan against the files on disk. All of it needs a plan and
  `-n` above 1. At `-n 1`, the default below 12 vCPUs, carto runs every script in filename order,
  and it neither checks the plan nor creates its schemas and extensions.
- **Concurrent groups get scaled-down settings.** Each group connects with libpq
  `options='-c abt.dissolve_shards=N -c abt.parallel_workers_per_gather=M'`, sized so that all the
  groups together don't oversubscribe the host. The groups that start together split a budget of
  `max(cpu_count - 4, cpu_count // 2)` in proportion to their `weights` in the plan (default 1; a
  group's weight is its heaviest script's). A group gets its share as shards and a quarter of it
  as workers, each at least 2 and at most the sequential defaults (16 and 10). `009_land_cover`
  and `005a_water_polygon` have weight 2, so at 48 vCPU and `-n 8` they get 8 shards and every
  other group 4. The heavy scripts (`003_road`,
  `005a_water_polygon`, `009_land_cover`, and `022_dam`) read these settings with
  `current_setting(..., true)`. When a setting isn't there, they fall back to the values they used
  when scripts ran one at a time.
- **The CLI raises the open-file limit first.** tippecanoe sizes itself to the core count and needs
  about ten file descriptors per reader thread, plus temp files. On a large host the default soft
  limit of 1024 makes every layer fail with exit code 111. So before any command runs, the CLI
  raises its soft limit to the hard limit.

### Failure semantics

Every command except `vundler` records each task's outcome and `duration_s` in `RunReporter`.
When a step fails, the task's later steps are recorded `FAILED` as `not attempted (<stage>
failed)`, and `carto` also records every script under `carto_scripts`. A command exits with code
1 if it raises an exception or if `overall_status` isn't `SUCCESS`; `vundler` exits 1 only if it
raises. When something fails, read `logs/<run_id>/summary.json` first, then the failed task's
`*.log`.

Some failures are quiet, or show up only a stage later:

- An OSM tag key that no mapping loads reads as NULL in `carto_sql`, with no error, because imposm
  drops it while it reads the PBF. `tests/test_imposm_tags.py` catches this for the keys that
  `carto_sql` and the mapping filters read.
- A failed aux download or import fails its stage, which exits 1. If you run the next stage
  anyway, the gap shows up only when `carto` can't find that `aux_data.*` table. MIRTA is the
  likeliest: its host, `www.acq.osd.mil`, may be unreachable from some networks, and its config
  sets `"verify_tls": false` because that host omits an intermediate certificate.

`bundler` doesn't fail on missing inputs either, but it does report them. It leaves out any layer
with no per-layer `.mbtiles` or `.btis` file, any `-q` path that doesn't exist, and any input with
no populated tiles table, then joins the rest. Each kind of skip prints its own `NOTE: skipping`
line, and the run still reports `SUCCESS`. `export` moves a layer's file into place only once
tippecanoe succeeds, and tippecanoe fails a layer with no features, so a layer that failed or had
nothing to export shows up in the bundler only as a not-found note. Read the bundler output after
a run.

## The schema content model

| Path | Consumed by | Binding |
|---|---|---|
| `import/osm/*.yml` | `import`, through imposm | A mapping named `<name>` becomes the table `osm.osm_<name>`. |
| `import/imposm_base.yml` | `import`, merged into `<working_dir>/osm/combined_mapping.yaml` | Optional top-level imposm settings; must not define `tables`. `tags: include:` keeps the tag keys that `carto_sql` or a mapping filter reads but no mapping loads. A change needs a fresh OSM import. |
| `import/aux_data/*.json` | `download`, `import` | Each `aux_load` entry becomes a table in `aux_data`. See `docs/schema/aux-data.md`. |
| `static_data/` | `import`, through `local_path` in the aux configs | Data files committed to git. |
| `carto_sql/*.sql` | `carto`, which globs them non-recursively and sorts them | Each builds one or more `export.<layer_id>` views. |
| `carto_sql/execution_plan.yml` | `carto` | Must list every script exactly once. |
| `carto_sql/static_data/*.sql` | Nothing runs these automatically | An alternative to aux import for seeding tables by hand with `psql`. |
| `export/*.json` | `export`, `bundler` | `layer_id` matches `export.<layer_id>` and `mbtiles/<layer_id>.mbtiles`. |
| `tile-metadata/metadata.py` | `bundler`, docs hook | Loaded with `importlib`; must define `metadata`. |
| `scripts/overture/` | `init.sh --overture`, or run by hand | The output is added to the bundle with `bundler -q`. |

- **`metadata.py` is Python, not data.** Its `production_date` is set when the module loads.
  `bundler` writes the whole dict into the bundle's `metadata` table, with these exceptions:
  - `tile-join` computes `bounds` and `format` itself.
  - The dict's `center` replaces tile-join's value when no projection override is in effect.
- **Fields in `export/*.json`:**
  - `layer_id`
  - `geometry_type`: `polygon`, `linestring`, or `point`
  - `attributes[]`, each with a `name` and a `type` (`string`, `int`, `float`, or `bool`). They
    become tippecanoe's `-y` and `-T` flags. A layer with no attributes gets `-X`.
  - `tippecanoe_options`: `minimum_zoom`, `maximum_zoom`, `additional_flags`, and `filter`
    (passed as `-j`)
  - `ogr_export_options.additional_flags`

  `export -z` caps the maximum zoom of every layer. Flag strings are split on spaces, so quoting
  doesn't work (R7).
- **The `.skip` suffix** takes a file out of the `*.sql` and `*.json` globs. Today it disables the
  OSM buildings layer (`031_building.sql.skip` and `building_polygon.json.skip`) in favor of
  Overture's.
- **Every carto script has the same structure:** a header block, session-level `SET` statements,
  and then idempotent `BEGIN … COMMIT` blocks. Three scripts wrap the rest:
  - `000_update_aux_geom.sql` normalizes the geometry column of every `aux_data` table: it renames
    the column to `geometry`, reprojects from 3857 to 4326, and builds a GiST index on it unless
    one exists (ogr2ogr's import normally made one).
  - `001_set_schema.sql` recreates the `export` schema and helper functions such as `ZRes(z)`.
  - `099_update_geometry.sql` normalizes `export.*` at the end.

## Projections and the override trick

tippecanoe only tiles Web Mercator. `export --projection-override EPSG:<code>` works around this
in three steps:

1. The `ogr2ogr` SQL selects `ST_Transform(geometry, <code>)`, so the `.fgb` holds coordinates in
   metres in the target CRS.
2. tippecanoe gets `-s EPSG:3857`, so it tiles those metres as if they were Web Mercator (see
   mapbox/tippecanoe#422).
3. The per-layer metadata is rewritten. `crs` is added, and `bounds` and `center` come from PROJ's
   area of use for the CRS, because tippecanoe's values are wrong for this data.

`bundler` does the same for the joined file, and also adds `btp_schema_version` and
`changelog_url` (whose value is still `TBD`). The trick only makes sense for CRSs measured in
metres. Nothing checks this: a degree-based code produces garbage tiles without any error. Passing
`EPSG:3857` explicitly is treated as no override.

EPSG:4087 needs PROJ 9.8 or later, which added the ellipsoidal Equidistant Cylindrical method.
Older PROJ versions put northings tens of kilometres off. `env.yaml` pins `proj>=9.8`. DuckDB
bundles an older PROJ, so the Overture `shard.sh` reprojects with the system `ogr2ogr` instead of
DuckDB's `ST_Transform`. `scripts/overture/check_proj_agreement.py` checks that pyproj, DuckDB, and
PostGIS agree within 1 mm, and `init.sh` runs it for every non-3857 projection before any other
work starts.

## `init.sh`, the production orchestrator

The script runs six steps:

1. `download`, for the planet.
2. `import`, for the planet.
3. `carto`, for the planet.
4. `export` for every projection, in parallel.
5. `bundler` for every projection, in parallel. This step adds the Overture buildings and contours
   with `-q`.
6. `aws s3 cp` for each bundle, unless `--no-upload`, which prints the bundle paths instead.

| Flag | Effect |
|---|---|
| `--projections "3857 3395 4087"` | Sets which projections to build. |
| `--overture [list]` | Adds the Overture buildings. |
| `--overture-clean` | Like `--overture`, and also deletes each projection's `.fgb` shards once that projection is tiled. |
| `--contours <dir>` | Adds contours from `<dir>`. |
| `--from export` | Skips steps 1–3. A preflight first runs `ogrinfo` to confirm that every `.fgb` exists and is readable. |
| `--no-upload` | Stops after step 5. Skips the `aws` and AWS STS checks. |
| `-h`, `--help` | Prints the flags and environment variables, then exits. |

Only `-p env`, the planet, and `ZOOM=13` are fixed. Everything else comes from environment
variables whose defaults match a `setup_ubuntu.sh` host, and `bash init.sh --help` lists them:

- **Paths.** Data goes under `ABT_WORKSPACE_DIR` (`/rbt`), and `ABT_RUN_DIR` and
  `ABT_OVERTURE_DIR` override the working directories under it. `ABT_TOOLS` and `ABT_SCHEMA_DIR`
  default to the checkout next to `init.sh`.
- **Run.** `ABT_JOBS` (12) sets the workers per stage, `ABT_S3_BUCKET_PREFIX` the upload
  destination, and `PYTHON` the interpreter.
- **Postgres.** `PG_HOST`, `PG_PORT`, `PG_USER`, `PG_PASSWORD`, and `PG_DB` default to
  `127.0.0.1`, `5432`, and `rbt` for the role and database. The script exports them as `PGHOST`
  and the rest, overwriting any already set, so a shell still pointed at another database can't
  send the build there.

Unless `--no-upload` is passed, the script stops immediately if `aws` or the AWS STS variables
are missing.

## Overture buildings

The scripts in `rbt-schema/scripts/overture/` build the buildings layer without Postgres:

1. `fetch.sh` finds the latest Overture release on S3 (or uses the one set in `OVERTURE_RELEASE`),
   syncs the GeoParquet files, and runs `shard.sh` once per projection.
2. `tile.sh` runs tippecanoe on the shards.
3. `tag_crs.py` writes `crs` into each non-3857 output. It uses only the standard library.

`lock.sh` takes an `flock` on the data dir so that two runs can't write to it at the same time.
The pipeline needs `duckdb` and the AWS CLI. That's why `setup_ubuntu.sh` installs both, even
though `abt-tools.py` doesn't use either.

## vundler-rs

The original pure-Python vundler had two measured problems:

- It rewrote each bundle's index about 40 times. It walked tiles row by row, so it reopened a
  bundle once for every tile row the bundle contained.
- It couldn't run more than about 2× in parallel. Work was split by zoom level, and zoom 13 alone
  held 48% of the tiles.

The Rust port fixes both:

- It flattens every zoom level's bundle keys into a single work list for `rayon`.
- It writes each `.bundle` in one pass: the header, then the payloads, then one seek back to write
  the index.
- It finds bundles from the coordinates in the `map` table, without reading tile blobs. It fetches
  each bundle's tiles unsorted, which avoids a temporary B-tree.
- It opens one read-only SQLite connection per worker thread.

The CLI is `abt-vundler -i <mbtiles> -o <dir> -z <max_zoom> [-n <threads>]`.

It differs from the Python reference in three known and accepted ways (R1–R3):

- An orphaned `map` row produces an empty bundle file in Rust only.
- The `R{:04x}C{:04x}` bundle names grow past 10 characters at zoom 17 and above.
- A missing `metadata` table fails in both implementations.

The tests, from narrowest to widest scope:

1. Unit tests in `src/*.rs`.
2. `tests/cli.rs`, which tests the compiled binary.
3. `tests/test_golden.py`, which compares the binary's output with the frozen reference in
   `tests/reference/vundler_reference.py`, taken from commit `9b85f2b`.
4. `bench/`, which measures time and memory and diffs the output semantically on large fixtures.
   The fixtures are gitignored.

## Repository history and process

- **The monorepo combines two repos.** `abtv2-tools` and `rbt-schema` used to be separate
  repositories. They were merged in with `git subtree add`, which kept their histories, so
  `git log -- abtv2-tools/` still works. abt is now the source of truth, and
  `.github/scripts/subtree-sync.sh` publishes each directory back out:
  - `git subtree split` always produces the same commits, so a mirror only ever fast-forwards.
  - If a mirror gets commits of its own, the check fails until they're either brought into abt
    with a merge commit or discarded through `SUBTREE_SYNC_OVERWRITE`. That variable currently
    holds `abtv2-tools@eeb8f4a`, the only reconciliation so far.
  - Publishing runs on every push to `main` and nightly at 06:37 UTC. It uses a token stored in
    the `subtree-sync` environment.
- **Releases.** git-cliff builds `CHANGELOG.md` from Conventional Commits on every push to `main`
  and on every `v*` tag. Every PR so far has been merged with a merge commit, which git-cliff
  skips, so each commit on a PR branch becomes its own changelog line. Version 2.0.0 was cut on
  2026-09-17. GitHub Releases are created by hand.
  Commits from before 2026-09-17 don't follow Conventional Commits, so older `git log` subjects
  look inconsistent.
- **Design history.** `.cursor/plans/*.plan.md` holds the design plan for each major change. Read
  the relevant plan before you rework one of these areas:
  - the Rust vundler port
  - the test harnesses and code review
  - `init.sh --from export`
  - the parameterization of projections and contours
  - the Overture concurrency fixes and EPSG:4087
  - the switch to `.mbtiles` everywhere
  - the `--max-zoom` port
  - the `rbt-schema` subtree pull

  `.cursor/rules/conventional-commits.mdc` holds the same commit rule for Cursor.
- **The tests are recent.** Before the review in `docs/project/code-review-findings.md`, the
  Python package had no tests, and the Rust port had overwritten the oracle meant to check it.
  That review added both suites, fixed findings F1–F9, and left R1–R10 open. The September 2026
  review (`docs/project/code-review-2026-09.md`) fixed B0–B20 and S1–S4, closed R4 and R6, added
  the root `tests/` suite, and added the Tests workflow, which runs every suite in CI.

## Hosts and sizing

The target OS is Ubuntu 26.04. `setup_ubuntu.sh` provisions everything in numbered stages. Most
stages check whether their work is already done before redoing it, but by default the Postgres
tuning stage re-applies its settings and restarts Postgres on every run. The stages cover:

- kernel and ulimit tuning
- PostgreSQL and PostGIS, run under a custom systemd unit (`postgresql-rbt`)
- imposm and tippecanoe, built from source
- the AWS CLI and duckdb
- the Rust toolchain and `abt-vundler`
- a micromamba environment built from `env.yaml`

| Tier | Hardware | Use |
|---|---|---|
| Small extract | 8 vCPU, 32 GB RAM, 100 GB SSD | Iterating on schema and SQL with one country (`docs/walkthroughs/norway.md`). `setup_ubuntu.sh` sizes Postgres for this tier by itself: `PG_TIER=auto` picks it below 128 GB of RAM. See `docs/install/performance.md`. |
| Planet | 48 vCPU, 384 GB RAM, 2 TB+ NVMe | Production. The planet PBF is over 80 GB, and `import` alone takes over 24 hours. `PG_TIER=auto` picks this tier at 128 GB of RAM or more. |

Minimum tool versions: PostgreSQL 16 with PostGIS 3.4, GDAL 3.9.2, imposm3 0.14, and tippecanoe
2.76. Planet downloads also need `aria2c`.

## Known issues and open decisions

These findings from the code review (`docs/project/code-review-findings.md`) are still open. The
September 2026 review fixed R4 and R6 and says R1–R3 stand by design, though the findings table
still marks them Open. The rest wait on a decision.

| # | Issue |
|---|---|
| R1 | For an orphaned `map` row, Rust writes an empty `.bundle` file; Python writes nothing. |
| R2 | At zoom 17 and above, bundle filenames grow past `R####C####` (in both implementations). |
| R3 | A missing `metadata` table makes both implementations fail. |
| R5 | `with self.conn as conn:` doesn't close psycopg2 connections, so `osm_populated`, `reset_aux_schema`, `test_sql`, and `execute_sql` (which `runSQLScript` calls) each leak one connection per call. `table_sizes` closes its own. |
| R7 | Flag strings are split on spaces instead of with `shlex.split`. |
| R8 | `layer_id` and attribute names go into SQL identifiers unescaped. The risk is low because the config is static. |
| R9 | Loggers don't create their log directories, so every caller has to. |
| R10 | Loggers are cached for the whole process by stage and name, so a later call with a different directory keeps writing to the first one. |

The "Report only" section of `docs/project/code-review-2026-09.md` holds newer open decisions.
Among them: sequential `carto` never creates the plan's extensions (`004` and `014` need
`pg_trgm`); the `dblink` connection strings name no user; `init.sh --from` can't restart between
download and export; `init.sh` requires `AWS_SESSION_TOKEN` and only checks that it's set; the
Overture scripts have shellcheck findings, so CI skips them; and several SQL behaviors change the
output.

### Known doc drift

None known as of 2026-09-29. If you find prose that disagrees with the code and can't fix it in
the same change, list it here.

## Where to start

| Task | Start with |
|---|---|
| Add or change a tile layer | `docs/schema/adding-a-layer.md`, then the schema checklist in CLAUDE.md |
| Change how a layer tiles | `rbt-schema/export/<file>.json`, `abt/export/tile_layer_model.py` |
| Debug a failing `carto` group | `logs/<run_id>/carto/`, `docs/reference/troubleshooting.md`, and the header of the failing script |
| Speed up `carto` | The header and `weights` of `execution_plan.yml`, `group_guc_values` and `CartoProcessingModel._group_pg_configs`, the `carto_scripts` stage in a run's `summary.json`, `docs/install/performance.md` |
| Add a CLI flag | `abt/utils/fields.py`, then the stage's `cli_funcs/*.py` |
| Add a data source | An existing `import/aux_data/*.json`, `abt/aux_data_model.py`, `debug_aux_import` |
| Change bundle metadata or attribution | `rbt-schema/tile-metadata/metadata.py`, `abt/export/bundler.py` |
| Add a projection | `docs/walkthroughs/init-sh.md`, `init.sh --projections`, `check_proj_agreement.py` |
| Change vundler performance or output format | The doc comments in `vundler-rs/src/{main,bundle,db}.rs`, `bench/README.md` |
| Fix a mirror sync failure | The "When a mirror has diverged" section of `docs/project/mirrors.md` |
