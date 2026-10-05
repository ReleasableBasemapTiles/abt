# init.sh Orchestrator

`init.sh`, at the root of the monorepo (`/rbt/init.sh` on a host laid out by `setup_ubuntu.sh`), is the production orchestrator. It runs `download`, `import` and `carto` once, then `export`, `bundler` and an S3 upload for each projection in `--projections` (default `3857 3395 4087`), with the projections in parallel. Its defaults are planet-scale, with data under `/rbt`. Environment variables override the paths, the worker count, the upload destination and the Postgres connection (see [Configuration](#configuration)), and `./init.sh --help` lists them with the flags.

!!! tip "When to use this vs. the manual walkthroughs"
    `init.sh` is the all-in-one production path: multi-projection, uploads to S3, and optionally folds in Overture buildings and/or contours. The [Norway](norway.md) and [Planet](planet.md) walkthroughs are the manual, single-projection, stage-by-stage path — reach for those when you're iterating on schema/SQL changes or debugging one stage in isolation, and reach for `init.sh` when you want the whole production build in one command.

## What it does

`init.sh` chains five `abt-tools.py` stages, documented under [Pipeline Stages](../pipeline/download.md), and an S3 upload into `[1/6]`–`[6/6]`:

| Stage | What runs | Notes |
|---|---|---|
| `[1/6] download` | `abt-tools.py download` | Skipped entirely if `--from export` |
| `[2/6] import` | `abt-tools.py import` | Skipped entirely if `--from export` |
| `[3/6] carto` | `abt-tools.py carto` | Skipped entirely if `--from export` |
| `[4/6] export` | `abt-tools.py export`, once per projection | Runs every listed projection **in parallel** |
| `[5/6] bundler` | `abt-tools.py bundler`, once per projection | Runs in parallel; folds in Overture buildings and/or contours via `-q` when enabled |
| `[6/6] upload` | `aws s3 cp`, once per projection | Runs in parallel, after every projection's bundle is resolved up front. With `--no-upload`, prints each bundle's path instead |

`3857` (Web Mercator, the default) is the one case every derived path special-cases: it uses the unsuffixed `$WORKSPACE`, while every other listed projection gets its own `$WORKSPACE-<srs>` tree (via the script's `workspace_for()` helper) and is run through `--projection-override EPSG:<srs>` at `[4/6]`.

Each projection's `[4/6]`/`[5/6]` work runs as a background job; a `wait_jobs` helper waits for every one of them even after an earlier failure (so a fast failure never leaves a still-running sibling unreported or orphaned) and reports `ok`/`FAILED` per projection before the script aborts on any failure.

!!! note "Postgres connection"
    `init.sh` connects as `PG_USER`/`PG_PASSWORD` to `PG_DB` on `PG_HOST`:`PG_PORT`: the names, and the defaults (`rbt`/`rbt`/`rbt` on `127.0.0.1:5432`), that [`setup_ubuntu.sh`](../install/configuration.md) uses, so a host set up with other values runs `init.sh` with the same ones. It sets `PGHOST`/`PGPORT`/`PGUSER`/`PGPASSWORD`/`PGDATABASE` from them and ignores any already exported, so a shell still pointed at another database can't redirect the build into it. The [Planet walkthrough](planet.md) uses the same role and database; the [Norway walkthrough](norway.md) uses its own `rbt_norway` database, which `init.sh` never touches.

## Configuration

The values at the top of the script come from the environment where there's a variable for them, named as in [`setup_ubuntu.sh`](../install/configuration.md) where it has one. The code paths default to the checkout `init.sh` sits in, wherever that is, and the data paths to `$ABT_WORKSPACE_DIR`:

| Variable | Set from | Default |
|---|---|---|
| `ABT_TOOLS` | `ABT_TOOLS` | `abtv2-tools/abt-tools.py` next to `init.sh` |
| `SCHEMA` | `ABT_SCHEMA_DIR` | `rbt-schema` next to `init.sh` |
| `WORKSPACE` | `ABT_RUN_DIR` | `$ABT_WORKSPACE_DIR/run-planet`, with `ABT_WORKSPACE_DIR` defaulting to `/rbt` |
| `OVERTURE_DIR` | `ABT_OVERTURE_DIR` | `$ABT_WORKSPACE_DIR/overture` (only read when `--overture` is passed) |
| `JOBS` | `ABT_JOBS` | `12` |
| `S3_BUCKET_PREFIX` | `ABT_S3_BUCKET_PREFIX` | `s3://data-478728046499-us-east-1-an` |
| `PYTHON` | `PYTHON` | `python`, the interpreter every stage (and the Overture scripts) runs with |
| `PGHOST`, `PGPORT`, `PGUSER`, `PGPASSWORD`, `PGDATABASE` | `PG_HOST`, `PG_PORT`, `PG_USER`, `PG_PASSWORD`, `PG_DB` | `127.0.0.1`, `5432`, `rbt`, `rbt`, `rbt` |
| `PROVIDER` | — | `env` (`--pg-config`) |
| `KIND` | — | `planet` (`--osm-key`) |
| `ZOOM` | — | `13` |
| `OVERTURE_SCRIPTS` | — | `$SCHEMA/scripts/overture` |

With the monorepo cloned to `/rbt` (`git clone ... /rbt && /rbt/setup_ubuntu.sh`), the defaults come to the values `init.sh` always had; from a clone anywhere else, the code paths follow the clone. A host set up with, say, `ABT_WORKSPACE_DIR=/data PG_DB=planet ./setup_ubuntu.sh` runs `ABT_WORKSPACE_DIR=/data PG_DB=planet ./init.sh`.

Each projection uploads to `$S3_BUCKET_PREFIX/<srs>/<name>` at `[6/6]` — e.g. `.../3857/RBT.mbtiles`. The uploaded filename itself is projection-dependent (`RBT.mbtiles` for `3857`, `RBT.btis` for every other projection), independent of what the bundler actually names its output on disk (`bundled/joined.mbtiles`, with a `bundled/joined.btis` fallback kept only for a bundle produced before that was the standard name).

## Command-line flags

| Flag | Effect |
|---|---|
| `--overture [EPSG list]` | Also fetches and tiles Overture buildings in the background; folds the result into each projection's bundle. |
| `--overture-clean [EPSG list]` | Same as `--overture`, and additionally deletes each projection's FlatGeobuf shards as soon as it's tiled. |
| `--projections "<space-separated EPSG codes>"` | Overrides which EPSG codes `[4/6]`–`[6/6]` run for. Default: `3857 3395 4087`. |
| `--contours <dir>` | Folds `contours_<srs>.mbtiles` from the given directory into each projection's bundle. |
| `--from {download\|export}` | Where to start the pipeline. Default: `download`. |
| `--no-upload` | Stops after `[5/6]`: no S3 upload and none of its AWS checks. Prints where each projection's bundle is instead. |
| `-h`, `--help` | Prints the flags and environment variables. |

Every `--projections` entry must be a numeric EPSG code, and at least one must be given; `init.sh` validates both up front and exits before doing any work otherwise. `--projections`, `--contours` and `--from` exit with an error when their value is missing.

### `--overture` and `--overture-clean`

`--overture` fetches and tiles [Overture Buildings](../pipeline/overture.md) in the background, folding the result into each `[5/6]` bundler run via `-q`/`--additional-mbtiles`. Its optional list argument (e.g. `--overture "3857 4087"`) is shorthand for also passing that list to `--projections` — it's only consumed when the next argument doesn't look like a flag, so a bare `--overture --contours ...` (no list) still parses correctly.

It skips re-launching the multi-hour fetch+tile pipeline if every listed projection's `building_polygon_<srs>.mbtiles` already exists (the `overture_already_tiled` check) — useful when combined with `--from export` to reuse Overture output from an earlier run.

`--overture-clean` implies `--overture` and additionally deletes each projection's FlatGeobuf shards as soon as that projection is tiled, trading re-shard work on a later run for a much smaller disk footprint. It accepts the same optional projection-list shorthand as `--overture`. It does **not** lower peak disk usage, since `fetch.sh` shards every listed projection before tiling starts on any of them — see [Overture Buildings](../pipeline/overture.md).

### `--projections`

Overrides which EPSG codes `[4/6]`–`[6/6]` run for (default `3857 3395 4087`). Any code other than `3857` is assumed metres-based and run through `--projection-override`, exactly like `3395`/`4087` always were.

### `--contours`

Folds `contours_<srs>.mbtiles` from the given directory into each projection's bundle via `-q`, alongside Overture buildings if `--overture` is also enabled. `3857` contours must carry no `crs` metadata row; non-3857 contours are tagged in place via Overture's own `tag_crs.py` if untagged, or rejected outright if already tagged with a different EPSG code than the one being requested.

### `--from {download|export}`

`--from export` skips `[1/6]`–`[3/6]` and jumps straight to `[4/6]`, after a preflight that:

1. Reads every export layer's `layer_id` from `rbt-schema/export/*.json` (globbing `*.json`, so a disabled layer's `*.json.skip` is correctly excluded).
2. Verifies with `ogrinfo -so -al` that every listed projection's workspace already has a *readable* `.fgb` for each layer. That catches a missing or unreadable file, but not a truncated one: `ogrinfo` reads only the header, and it (and `tippecanoe`) exit 0 on a cut-off FlatGeobuf. `export` doesn't leave those behind, though: it writes each `.fgb` under `flatgeobuf/.partial/` and moves it into place only once `ogr2ogr` succeeds.

The whole preflight runs, and can abort, **before** touching Postgres or launching `--overture`'s background pipeline, so a missing/unreadable `.fgb` fails immediately rather than hours into `[4/6]`.

`[4/6]` then skips every `.fgb`, and every finished `.mbtiles`, already in place (see [Export](../pipeline/export.md)), so `--from export` after a complete run only re-bundles and re-uploads, for example to fold in Overture buildings or contours.

The default, `download`, runs the full pipeline from the top.

## Fail-fast preflight checks

Before any multi-hour work starts, `init.sh` checks (and exits immediately on failure):

- `$PYTHON` is on `PATH`, `$ABT_TOOLS` exists, `$SCHEMA` has an `export/` directory, and `ABT_JOBS` is a positive whole number.
- Unless `--no-upload` was passed: the `aws` CLI is on `PATH`, and `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, and `AWS_SESSION_TOKEN` are exported (required for the `[6/6]` upload). Only their presence is checked. STS session credentials exported at the start can expire before a planet run reaches `[6/6]`, so check their lifetime first, or run with `--no-upload` and copy the listed bundles up with `aws s3 cp` afterwards.
- If `--overture` was passed: `duckdb`, `aws`, and `ogr2ogr` are on `PATH` (`ogr2ogr` is what `shard.sh` now uses to reproject non-3857 targets -- see [Overture Buildings](../pipeline/overture.md)).
- If `--contours` was passed: `sqlite3` is on `PATH`, plus the per-file CRS-tag checks described above.
- If `--from export` was passed: `ogrinfo` is on `PATH`, plus the `.fgb` existence/readability checks described above.
- Whenever the projection list has a code other than `3857`, as the default list does: `check_proj_agreement.py` confirms that the reachable engines that reproject (the GDAL behind `ogr2ogr`, and PostGIS) agree with pyproj on that code's coordinates; DuckDB's result is only reported. This runs regardless of `--from`/`--overture` -- see [Overture Buildings](../pipeline/overture.md#proj-version-agreement).

## Re-running

A second full run (`--from download`) against a database that already holds an OSM import stops at `[2/6]`: `import` won't overwrite one without `--force`, which `init.sh` doesn't pass, since a planet import takes 24+ hours. `init.sh` has no start between `download` and `export`, so to redo `carto` on an existing import, run it by hand, delete each projection's `flatgeobuf/` and `mbtiles/` directories, and run `export` and `bundler` by hand too (see the [Planet walkthrough](planet.md)).

## Cleanup on exit

`init.sh` installs `trap cleanup_overture EXIT INT TERM`. If `--overture` started a background fetch+tile pipeline and `init.sh` itself exits early for any reason — a normal Ctrl-C, or a `set -e` abort from a failure hours later at `[4/6]`–`[6/6]` — this trap kills that background pipeline's whole process group (not just the immediate subshell), so a failure doesn't leave an orphaned `fetch.sh` running to collide with a later re-run.

This trap only covers `init.sh` exiting normally enough to run it — a `kill -9` on `init.sh` itself, or a host crash, still bypasses it. See the "Concurrency" section of [Overture Buildings](../pipeline/overture.md) for the `flock` that catches those remaining cases on the next run instead.

## Example invocations

```bash
./init.sh --help                             # flags and environment variables
./init.sh                                    # full planet, 3857/3395/4087, from download
./init.sh --overture --overture-clean        # same, plus Overture buildings, cleaning shards as it goes
./init.sh --from export                      # reuse existing .fgb files, skip straight to export/bundle/upload
./init.sh --projections "3857" --contours /rbt/contours
ABT_WORKSPACE_DIR=/data ./init.sh --no-upload  # data under /data, no S3 upload
```
