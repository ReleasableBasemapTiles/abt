# init.sh Orchestrator

`/rbt/abt/init.sh` — or `init.sh` at the root of a clone — is the production orchestrator: a single script that runs the full six-stage pipeline end-to-end, per projection, in parallel across `--projections` (default `3857 3395 4087`). It hardcodes planet-scale defaults and paths under `/rbt/...`, and is meant to be run as-is on a provisioned production host rather than customized per-invocation beyond its documented flags.

!!! tip "When to use this vs. the manual walkthroughs"
    `init.sh` is the all-in-one production path: multi-projection, uploads to S3, and optionally folds in Overture buildings and/or contours. The [Norway](norway.md) and [Planet](planet.md) walkthroughs are the manual, single-projection, stage-by-stage path — reach for those when you're iterating on schema/SQL changes or debugging one stage in isolation, and reach for `init.sh` when you want the whole production build in one command.

## What it does

`init.sh` chains the same six CLI stages documented under [Pipeline Stages](../pipeline/download.md) into `[1/6]`–`[6/6]`:

| Stage | What runs | Notes |
|---|---|---|
| `[1/6] download` | `abt-tools.py download` | Skipped entirely if `--from export` |
| `[2/6] import` | `abt-tools.py import -c` | Skipped entirely if `--from export` |
| `[3/6] carto` | `abt-tools.py carto` | Skipped entirely if `--from export` |
| `[4/6] export` | `abt-tools.py export`, once per projection | Runs every listed projection **in parallel** |
| `[5/6] bundler` | `abt-tools.py bundler`, once per projection | Runs in parallel; folds in Overture buildings and/or contours via `-q` when enabled |
| `[6/6] upload` | `aws s3 cp`, once per projection | Runs in parallel, after every projection's bundle is resolved up front |

`3857` (Web Mercator, the default) is the one case every derived path special-cases: it uses the unsuffixed `$WORKSPACE`, while every other listed projection gets its own `$WORKSPACE-<srs>` tree (via the script's `workspace_for()` helper) and is run through `--projection-override EPSG:<srs>` at `[4/6]`.

Each projection's `[4/6]`/`[5/6]` work runs as a background job; a `wait_jobs` helper waits for every one of them even after an earlier failure (so a fast failure never leaves a still-running sibling unreported or orphaned) and reports `ok`/`FAILED` per projection before the script aborts on any failure.

!!! note "Postgres credentials differ from the manual walkthroughs"
    `init.sh` hardcodes `PGUSER=rbt` / `PGPASSWORD=rbt` / `PGDATABASE=rbt` (and `PGHOST=127.0.0.1` / `PGPORT=5432`) — this matches [`setup_ubuntu.sh`'s own defaults](../install/configuration.md) (`PG_DB`/`PG_USER`/`PG_PASSWORD` all default to `rbt`), since `init.sh` is meant to run on a host provisioned by that script. The [Planet](planet.md) and [Norway](norway.md) walkthroughs instead use `abt` / `abt_planet` / `abt_norway` purely as an illustrative example role/database name for the *manual* setup path in [Ubuntu Setup](../install/ubuntu.md) — the two aren't meant to coexist unmodified. If you're moving between the manual walkthroughs and `init.sh` on the same host, make sure the role/database you actually provisioned matches whichever path you're running.

## Hardcoded configuration

None of the following are exposed as flags or read from the environment — they're literal values at the top of the script, so changing them means editing `init.sh` itself:

| Variable | Value |
|---|---|
| `ABT_TOOLS` | `/rbt/abtv2-tools/abt-tools.py` |
| `WORKSPACE` | `/rbt/run-planet` |
| `SCHEMA` | `/rbt/rbt-schema` |
| `JOBS` | `12` |
| `PROVIDER` | `env` (`--pg-config`) |
| `KIND` | `planet` (`--osm-key`) |
| `ZOOM` | `13` |
| `S3_BUCKET_PREFIX` | `s3://data-478728046499-us-east-1-an` |
| `OVERTURE_DIR` | `/rbt/overture` (only read when `--overture` is passed) |
| `OVERTURE_SCRIPTS` | `$SCHEMA/scripts/overture` |

Each projection uploads to `$S3_BUCKET_PREFIX/<srs>/<name>` at `[6/6]` — e.g. `.../3857/RBT.mbtiles`. The uploaded filename itself is projection-dependent (`RBT.mbtiles` for `3857`, `RBT.btis` for every other projection), independent of what the bundler actually names its output on disk (`bundled/joined.mbtiles`, with a `bundled/joined.btis` fallback kept only for a bundle produced before that was the standard name).

## Command-line flags

| Flag | Effect |
|---|---|
| `--overture [EPSG list]` | Also fetches and tiles Overture buildings in the background; folds the result into each projection's bundle. |
| `--overture-clean [EPSG list]` | Same as `--overture`, and additionally deletes each projection's FlatGeobuf shards as soon as it's tiled. |
| `--projections "<space-separated EPSG codes>"` | Overrides which EPSG codes `[4/6]`–`[6/6]` run for. Default: `3857 3395 4087`. |
| `--contours <dir>` | Folds `contours_<srs>.mbtiles` from the given directory into each projection's bundle. |
| `--from {download\|export}` | Where to start the pipeline. Default: `download`. |

Every `--projections` entry must be a numeric EPSG code, and at least one must be given; `init.sh` validates both up front and exits before doing any work otherwise.

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
2. Verifies with `ogrinfo -so -al` that every listed projection's workspace already has a complete, *readable* `.fgb` for each layer — this catches a truncated `.fgb` left behind by an interrupted `ogr2ogr`, not just a missing file.

The whole preflight runs, and can abort, **before** touching Postgres or launching `--overture`'s background pipeline, so a missing/unreadable `.fgb` fails immediately rather than hours into `[4/6]`.

The default, `download`, runs the full pipeline from the top.

## Fail-fast preflight checks

Before any multi-hour work starts, `init.sh` checks (and exits immediately on failure):

- `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, and `AWS_SESSION_TOKEN` are exported (required for the `[6/6]` upload).
- If `--overture` was passed: `duckdb`, `aws`, and `ogr2ogr` are on `PATH` (`ogr2ogr` is what `shard.sh` now uses to reproject non-3857 targets -- see [Overture Buildings](../pipeline/overture.md)).
- If `--contours` was passed: `sqlite3` is on `PATH`, plus the per-file CRS-tag checks described above.
- If `--from export` was passed: `ogrinfo` is on `PATH`, plus the `.fgb` completeness/readability checks described above.
- If `--projections`/`--overture`/`--overture-clean` list any non-`3857` code: `check_proj_agreement.py` confirms every reachable PROJ engine (pyproj, DuckDB, PostGIS) agrees on that code's coordinates, regardless of `--from`/`--overture` -- see [Overture Buildings](../pipeline/overture.md#proj-version-agreement).

## Cleanup on exit

`init.sh` installs `trap cleanup_overture EXIT INT TERM`. If `--overture` started a background fetch+tile pipeline and `init.sh` itself exits early for any reason — a normal Ctrl-C, or a `set -e` abort from a failure hours later at `[4/6]`–`[6/6]` — this trap kills that background pipeline's whole process group (not just the immediate subshell), so a failure doesn't leave an orphaned `fetch.sh` running to collide with a later re-run.

This trap only covers `init.sh` exiting normally enough to run it — a `kill -9` on `init.sh` itself, or a host crash, still bypasses it. See the "Concurrency" section of [Overture Buildings](../pipeline/overture.md) for the `flock` that catches those remaining cases on the next run instead.

## Example invocations

```bash
./init.sh                                    # full planet, 3857/3395/4087, from download
./init.sh --overture --overture-clean        # same, plus Overture buildings, cleaning shards as it goes
./init.sh --from export                      # reuse existing .fgb files, skip straight to export/bundle/upload
./init.sh --projections "3857" --contours /rbt/contours
```
