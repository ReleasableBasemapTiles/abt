# Code Review, November 2026

A review of the whole monorepo, finished on 2026-11-19, at commit `7201e2e`: the project structure, `init.sh` and `setup_ubuntu.sh`, the CI workflows, `abtv2-tools/`, `rbt-schema/` and this documentation. It looked for changes that would do one of three things:

1. make the project easier for a new user to pick up;
2. make a build more reliable;
3. make a build faster.

It excludes everything the [September 2026 review](code-review-2026-09.md) and the [first review](code-review-findings.md) already record. Every item in September's "Recommended, not implemented" list is still open, and isn't repeated here.

The review read the code; it ran no pipeline stage. Each finding was checked against the code a second time before it was listed. *(inferred)* marks one reasoned from the code and not reproduced, and *(estimate)* marks a gain nobody has measured. The three carto scripts added most recently (`009a`, `034`, `035`) and `scripts/overture/land_cover_extract.sh` were scanned for the patterns below, not read line by line.

Findings are numbered L (reliability), P (performance) and O (onboarding). Each has a score, (Impact + Risk) × (6 − Effort) with each term from 1 to 5, so a cheap fix for a costly failure ranks first. Line numbers are given only for files this change didn't touch.

## Summary

- **Three outputs could be published half-built.** `bundler` deleted the last good `joined.mbtiles` before it built the replacement in place (L1). A killed Overture tiling run left a partial tileset that the next `init.sh` run took for a finished one (L3). `summary.json` was written in place, so a kill or a full disk mid-write left truncated JSON (L5). All three now appear under their final name only when they're complete.
- **The README quick start couldn't finish.** It set the host up with `setup_ubuntu.sh` and then sent the reader to a walkthrough written for the manual install, which used a database nothing had created (O1). It now runs through to a tileset.
- **Eleven findings are fixed here, two of them in part** (L5, L16). Each fix is small and changes no tile content. The tables below name the commit.
- **32 findings are left as recommendations.** The six with the highest scores are L2 (`export` reuses stale output), L4 (the upload default), L6 (the import backup schema), L7 (sequential `carto` oversubscribes a small host), L8 (unpinned tool builds) and O2 (`init.sh` can only build the planet).
- **Three need a decision before any code changes:** L4, L6 and L13. See [Report only](#report-only).
- **No performance finding is implemented.** September took the cheap ones, and the ten here need a build host to measure.

## Before the next build

1. **`init.sh` needs `flock`,** from util-linux, which Ubuntu installs by default. It now takes a lock on `.init.lock` in its run directory and exits at once if another run holds it. The lock doesn't cover the database: two runs with different run directories still must not share a `PG_DB`. See [init.sh Orchestrator](../walkthroughs/init-sh.md#one-run-at-a-time).
2. **Rebuilding a bundle needs room for two.** `bundler` builds under `bundled/.partial/` and keeps the previous `joined.mbtiles` until the new one is complete, so both exist for the length of the run.
3. **Check Overture output from before this change.** `init.sh` still skips the Overture job when `building_polygon_<srs>.mbtiles` exists for every projection. A file that an interrupted run of the old `tile.sh` left there is still taken as complete; delete it if you can't vouch for it. Any `-journal` file beside it can stay: the next run removes it.
4. **Old `setup_ubuntu.sh` logs still hold the password.** New runs create `~/setup_ubuntu-<time>.log` readable only by its owner and print a placeholder for any password but the default. Logs from earlier runs keep the `export PGPASSWORD=…` line and their old permissions.
5. **Pull requests have two new ways to fail.** The Docs workflow fails one that leaves a [generated page](testing.md#running-the-suites-locally) stale, and every workflow job has a time limit.
6. **Merge with a merge commit or a rebase, not a squash,** so each fix keeps its own changelog line.

## Fixed

| # | Severity | Where | What was wrong, and the fix | Commit |
|---|---|---|---|---|
| L1 | High | `abt/export/bundler.py`, `bundler_model.py` | `bundler` unlinked `bundled/joined.mbtiles`, ran `tile-join` onto that path, then made three to five metadata edits there. A failure at any point left no bundle, or a half-labelled one for `vundler` and the upload, and the last good bundle was gone. It now joins and labels under `bundled/.partial/` and renames the result into place last, after removing any SQLite journal a killed run left beside the final name, which would otherwise be rolled back into the new file. | `5383e3d` |
| L3 | High | `scripts/overture/tile.sh` | tippecanoe wrote straight to `building_polygon_<srs>.mbtiles`, the file `init.sh` tests to decide the Overture job is done, and `init.sh` kills `tile.sh` whenever another stage fails. The next run could bundle a partial tileset, or one never tagged with its CRS. `tile.sh` now tiles and tags under `<data_dir>/.partial/` and moves the file into place last, removing a leftover journal first as the bundler does. | `8791517` |
| L5 (part) | Medium | `abt/utils/run_reporter.py` | `summary.json` was opened for writing in place, so a kill or a full disk mid-write left truncated JSON where `init.sh` and other readers expect a whole summary. It's written as `summary.json.tmp` and renamed. The rest of L5 is below. | `6eee45c` |
| L10 | Medium: security | `setup_ubuntu.sh` | The run log was created with the default umask, and the closing summary printed `export PGPASSWORD=<value>` into it. The password was also spliced unquoted into the `CREATE ROLE` statement, so one containing a quote or `$$` broke the statement or ran as SQL. The log is created mode 600, and only when `LOG_FILE` names a regular file, so `LOG_FILE=/dev/null` under sudo is left alone. The summary prints a placeholder for any password but the default `rbt`. The role name and password are quoted as an identifier and as literals, and reach `psql` on stdin, where neither `ps` nor sudo's log shows them. | `fffd68c` |
| L11 | Low | `abtv2-tools/tests/test_overture_check_proj_agreement.py` | The real-DuckDB test skipped only when the `duckdb` binary was missing, so it failed on a machine that has `duckdb` without its `spatial` extension. It skips when `LOAD spatial` fails. | `e69192c` |
| L12 | Medium | `init.sh` | Nothing stopped two runs from sharing a run directory; only the Overture scripts took a lock. `init.sh` takes `flock -n` on `.init.lock` in the run directory (`ABT_RUN_DIR`) after its preflight checks and before any stage, and a second run exits naming the PID that holds it. The stage commands, the Overture scripts and the uploads inherit the descriptor, so the lock outlives a killed `init.sh` while any of them runs. Its limits are under [Noticed while fixing](#noticed-while-fixing). | `cc15259` |
| L16 (part) | Low | `.github/workflows/*.yml` | No job had `timeout-minutes`, so a hung step held a runner for GitHub's default six hours. All ten jobs have a limit, set from their recent run times. The rest of L16 is below. | `5df1595` |
| O1 | High | `README.md`, `docs/walkthroughs/norway.md` | The quick start installed with `setup_ubuntu.sh` (database `rbt`, micromamba) and then pointed at a walkthrough written for the manual install (`conda`, database `rbt_norway`), with the `createdb` step on a third page. The README now carries the whole sequence for a `setup_ubuntu.sh` host, and the walkthrough has the `createdb` block and both environment activations. | `a194f9d` |
| O3 | Medium | `.github/workflows/docs.yml` | The docs build regenerates five committed pages from code and schema, and nothing checked that the committed copies matched. On a pull request the workflow now runs `git diff --exit-code -- docs/` after the build. | `3ff7782` |
| O4 | Medium | `docs/reference/troubleshooting.md` | No entry covered a missing `pg_trgm` in sequential `carto`, `too many clients already`, tippecanoe's exit 111, allocation failures under strict overcommit, or a full disk. Each has one now, with the `init.sh` lock message. | `8c3ec20` |
| O5 | Low | `docs/overview/`, both component READMEs, `CONTRIBUTING.md`, `docs/project/` | Three pages described a root README that held the walkthroughs, and one pointed at a flag reference that didn't exist. The commit rules were kept by hand in two places and had diverged. The pipeline overview left out Overture buildings, four pages counted 58 export layers where there are 62, the glossary lacked BTIS and the run summary, and `testing.md`'s list of test files was out of date. `docs/project/contributing.md` now includes the rules from `CONTRIBUTING.md`. | `8d163d1` |

## Recommended, not implemented

### Reliability

| # | Where | What happens now | Change | Score |
|---|---|---|---|---|
| L2 | `abt/export/exporter.py:51-52`, `:68` | `export` skips a layer when its `.fgb` exists, or its `.mbtiles` holds tiles. Nothing ties either file to the `carto` run, layer config, zoom or projection that produced it, so [init.sh Orchestrator](../walkthroughs/init-sh.md) tells operators to delete `flatgeobuf/` and `mbtiles/` by hand after rerunning `carto`. Forgetting ships the last build's layers. | Write a fingerprint beside each output (a hash of the command without the password, plus the `carto` run ID) and skip only on a match. Add `export --force`. | 36 |
| L4 | `init.sh` (`S3_BUCKET_PREFIX`, the `aws s3 cp` loop, `AWS_DEFAULT_REGION`) | The upload is on by default, to a bucket name fixed in the script. `aws s3 cp` replaces `<srs>/RBT.mbtiles` with no checksum, no size check and no previous copy kept. The region is hard-set. | Require an explicit prefix, or an `--upload` flag. Add `--checksum-algorithm SHA256` and a `head-object` size check. Honor `AWS_DEFAULT_REGION` when it's set. | 32 |
| L6 | `abt/importer/importer.py:77-89` | `imposm -deployproduction` moves the previous import to the `backup` schema, and nothing removes it. Each planet `import -f` leaves a second full copy of the OSM tables on disk. | `import --remove-backup`, and a decision on the default. | 30 |
| L7 | `abt/carto_processing_model.py:198-200`; `009_land_cover.sql:318` | Sequential `carto`, the default below 12 vCPUs, sets no `abt.*` settings, so `005a` and `009` each start 16 dissolve workers. Each `009` worker gets `work_mem=2GB`, `maintenance_work_mem=16GB` and 10 parallel workers, on a host the docs size at 8 vCPUs and 32 GB. | In sequential mode, apply `group_guc_values` for a single group, and create the plan's schemas and extensions (September's `pg_trgm` item). | 28 |
| L8 | `setup_ubuntu.sh` (`IMPOSM_REF`, `TIPPECANOE_REF`, `DUCKDB_VERSION`, the micromamba and AWS CLI downloads) | imposm and tippecanoe build from `master` and `main`; DuckDB, micromamba and the AWS CLI are fetched as `latest`; nothing is checksummed. The comment says a ref may be a commit, but `git clone --branch` rejects one. A tippecanoe already on `PATH` is kept whatever its version. | Default to release tags. Fetch by ref so a commit works. Check a minimum version. Pin and verify with `sha256sum -c`, and record the versions that were installed. | 28 |
| L9 | `init.sh` (the `$PYTHON` check); `abt/cli_funcs/cli_helpers.py:27-28`; `scripts/overture/check_proj_agreement.py` | `init.sh` checks only that `$PYTHON` is on `PATH` before a download that takes hours. `-p env` never tests the connection, and the PROJ check treats a refused connection as a skip. Nothing checks tool versions, extensions, `max_connections` or free disk. | One `doctor` command (tools and minimum versions, `test_sql()`, extensions, disk), run by each stage, by `init.sh`, and at the end of `setup_ubuntu.sh`. | 27 |
| L13 | `rbt-schema/tile-metadata/metadata.py` | The licence list omits NGA GeoNames, USGS, the Department of State LSIB and DISDI/MIRTA, and the attribution string omits LSIB and DISDI. All four are imported. | Add the entries once each source's terms are confirmed. This changes the metadata in every shipped bundle. | 25 |
| L14 | `setup_ubuntu.sh` (the Postgres tuning stage) | Every rerun stops and restarts Postgres, though the header calls rerunning safe. A rerun during a build kills its `carto` or `import` session. | Restart only when `pg_settings.pending_restart` is set, or the unit or port changed. | 24 |
| L15 | `abt/parallel.py:119-121`; `abt/utils/subprocess_tools.py:48`; `init.sh` (`trap cleanup_overture`); the `dblink` `EXCEPTION` blocks in `005a` and `009` | Ctrl-C lets queued tasks start. SIGTERM orphans `imposm` and `tippecanoe`. `init.sh`'s trap covers only the Overture job. A `carto` client that dies leaves its server queries and `dblink` workers running and holding locks *(inferred)*. | Cancel queued futures and terminate tracked children on a signal. Trap every background PID. Set `client_connection_check_interval`, and call `dblink_cancel_query`. | 21 |
| L5 (rest) | `abt/utils/run_reporter.py` | The summary is written once, after all the work. An OOM kill a day into an import leaves no record of what finished. | Flush it periodically with a status of `RUNNING`. | 20 |
| L17 | `abt/aux_data_model.py:141-160`; `abt/export/tile_layer_model.py:149-161` | Config keys are read with `.get()`, so a typo such as `minimum_zom` silently falls back to the default. | Pydantic `extra="forbid"`, and a root `tests/` check over every config file. | 20 |
| L18 | `abt/osm_data_model.py:286-287`; `abt/download/downloader.py:52-67`, `106-125`; `import/aux_data/*.json` | Geofabrik extracts aren't checked against the published `.md5`, and a file already downloaded is never refreshed. An HTTP download restarts from zero after a drop. Aux URLs carry no version and no checksum, and `overture_land_cover.json` downloads from a personal Hugging Face account at `resolve/main`. | Verify the `.md5`. Resume with `Range`. Allow a `sha256` per source and record it in `summary.json`. Host the land-cover archive under the organization and pin its revision. | 18 |
| L16 (rest) | `.github/workflows/*.yml` | Actions are pinned by tag, though `changelog.yml` holds `contents: write`. Nothing lints Python or runs clippy or rustfmt. The changelog push doesn't rebase and retry. | Pin actions by SHA, with Dependabot to move them. Add lint jobs. Retry the push. | 16 |
| L19 | `carto_sql/003`, `006`, `023`, `025`, `026` | The `-- Sources:` header lines disagree with the tables the SQL reads, and [Database Schema](../schema/database.md) is generated from them. | A `tests/test_schema_guards.py` check that compares each header with the `osm.*` and `aux_data.*` names in its script. | 16 |

### Performance

Every gain here is an *(estimate)* until a planet run's timings exist.

| # | Where | What happens now | Change | Score |
|---|---|---|---|---|
| P1 | `abt/cli_funcs/export_tiles.py:99`; `abt/export/tile_layer_model.py:306-326` | At 48 vCPUs, 16 export workers each start a tippecanoe that uses every core, times three projections under `init.sh`. September's item 5 covered only `init.sh`. | Give `run_subprocess` an `env=` argument, and set `TIPPECANOE_MAX_THREADS` to the cores divided by the workers for each child. | 24 |
| P2 | `init.sh` (`JOBS`); `abt/utils/fields.py:17-29` | `JOBS="${ABT_JOBS:-12}"` is passed as `-n` to every stage, which overrides the CLI's host-scaled defaults: `import` would use 24 at 48 vCPUs and 4 at 8. The gain on the planet host is small. It matters once O2 runs `init.sh` on small hosts. | Omit `-n` for `download` and `import` when `ABT_JOBS` is unset, and size `export` per projection with P1. | 20 |
| P3 | `005a_water_polygon.sql:169`, `:294`, `:911`; `009_land_cover.sql:368` | Each of the N dissolve workers scans the whole source to pick out its shard. The authors already fixed this once, for `cluster_src`. | Store a `shard` column with a btree index in each source. | 20 |
| P4 | `carto_sql/021`, `026`, `027`; `022_dam.sql` | Only five scripts set `work_mem`. The heavy joins run at the 4 MB default, because `setup_ubuntu.sh` sets none. `022`, a small layer, takes 16 GB of `maintenance_work_mem`. | Have `carto` pass a tier-sized profile in each connection's `options`. | 20 |
| P5 | `setup_ubuntu.sh` (`PG_TIER`, the `ALTER SYSTEM` block) | The tier is picked by RAM alone, so a 128 GB host with 16 vCPUs gets 44 worker processes. `autovacuum_work_mem` inherits 8 GB. Huge pages aren't sized for a 96 GB `shared_buffers` *(inferred)*. | Derive the parallel settings from `nproc`. Set `autovacuum_work_mem`. Size `vm.nr_hugepages`. | 20 |
| P6 | `abt/utils/fields.py:28`; `abt/carto_processing_model.py:276` | `os.cpu_count()` ignores cgroup limits, and the `carto` budget never checks the server's `max_connections` or `max_parallel_workers`. | Use `os.process_cpu_count()`. Cap the `dblink` fan-out against the server's limits, and fail early. | 20 |
| P7 | `abt/importer/importer.py`; `005a`, `021`, `022`, `027` | Nothing runs `ANALYZE` after an import, and few scripts analyze the tables they go on to join, so early `carto` plans may run on default estimates. Autovacuum may already cover the OSM tables. | Measure first. Then `ANALYZE` after import, and after each intermediate table a later statement joins. | 20 |
| P8 | `scripts/overture/shard.sh:64`; `init.sh` (the Overture job) | Every shard worker runs `INSTALL spatial`, and tiling starts only after every projection is sharded. | Install once in `fetch.sh`. Start each projection's tiling when its shards exist. | 16 |
| P9 | `005a`, `009`, `012`, `014`, `015`, `019`, `020`, `025` | The largest layers sit on disk two or three times until export finishes. Six export views are `SELECT *` copies of an intermediate table. `export.golf_course` and `export.sports_ground` are built and never tiled. Several scratch tables are logged. | Build the export views directly. Drop intermediates when they're done. `.skip` the untiled views. Make scratch tables `UNLOGGED`. | 15 |
| P10 | `abt/download/downloader.py:166-180`; `abt/export/tile_layer_model.py:276-285` | `aria2c` preallocates the 80 GB planet file and has no retry or slow-mirror flags. `ogr2ogr` reads PostGIS with the default 500-row cursor. | `--file-allocation=falloc`, `--max-tries` and `--lowest-speed-limit`. Benchmark `OGR_PG_CURSOR_PAGE`. | 15 |

### Onboarding

| # | Where | What happens now | Change | Score |
|---|---|---|---|---|
| O2 | `init.sh` (`KIND`, `ZOOM`) | `KIND="planet"` and `ZOOM=13` are fixed, so the orchestrator can't build an extract. | `--kind` and `ABT_ZOOM`. `init.sh --kind norway --no-upload --projections 3857` then serves as a first run, and as a scheduled CI smoke test. | 28 |
| O6 | repo-wide | There's no `style.json`, viewer command or screenshot. The Norway walkthrough ends at a `sqlite3` query of the metadata table. | A minimal MapLibre style, a one-line viewer command, and two screenshots. | 20 |
| O7 | `abtv2-tools/pyproject.toml`, `env.yaml`, `requirements-dev.txt` | There's no `[project]` table or entry point, so the CLI runs only as `python abt-tools.py` from one directory. Two dependency lists are synced by hand. There's no lockfile, lint config or task runner. | A `[project]` table with an `abt` entry point. ruff. A `justfile`. A locked conda environment. | 18 |
| O8 | `docs/schema/adding-a-layer.md`; `CLAUDE.md`; `docs/_hooks/gen_db_schema.py` | Adding a layer touches five to nine files, with no template. The offline check is a 25-line heredoc. A layer's theme lives in the docs build code. | A `validate-schema` command. A `-- Theme:` header in place of `THEMES`. A scaffold script. | 18 |
| O9 | `abt/cli_funcs/run_carto.py` | `carto` has no `--only` or `--from`. Testing one SQL edit reruns every script, and a failure in one group after hours reruns the groups that passed. | `carto --only <script>[,…]` and `--from <script>`. | 18 |
| O10 | `docs/walkthroughs/*.md`; `docs/install/performance.md` | No page gives a stage's time, disk or RAM, though `summary.json` has recorded `duration_s` since September. | A "typical run" table per tier, from one Norway and one planet run. | 16 |
| O11 | `abt/utils/subprocess_tools.py` | There's no way to see what a stage would run, though every command is already built as a list. | `--dry-run`, printing the redacted commands. | 16 |
| O12 | repo-wide | The only supported host is a dedicated Ubuntu 26.04 machine that `setup_ubuntu.sh` reconfigures. There's no container path. | A `docker-compose.yml` for small extracts. | 14 |
| O13 | `rbt-schema/export/*.json` | 58 of 62 layer descriptions and 216 of 250 attribute descriptions are empty, so the generated [Layer Registry](../schema/layers.md) says almost nothing. | Fill them in, and test that each layer has a description. | 12 |
| O14 | `abt/cli_funcs/*.py`; `abt/download/downloader.py:183-222` | Public names carry typos (`cli_impoter`, `init_carto_runer`), there are two different `prep_aux` functions, and `DownloadOverture`'s S3 path is unused. | Rename, fold and delete. | 12 |

## Report only

### Decisions needed first

- **L4, the upload default.** Whoever owns the bucket named in `init.sh` should confirm it before the default changes, and say whether a first-time user should upload at all.
- **L6, the import backup.** Keeping the previous import is a rollback path. Dropping it by default halves the OSM footprint and removes that path.
- **L13, licence wording.** The four entries need each source's terms checked by someone who can speak for them.

### Noticed while fixing

- **`setup_ubuntu.sh` still treats the repository as private.** The comment above `ABT_REPO` says so, and the default is the deploy-key SSH alias `git@abt:…`, which a host without that alias can't clone from. The repository is public. Run from a checkout, as the README does, the script uses that checkout and never clones.
- **`setup_ubuntu.sh` still builds other SQL from its variables.** The role statement is quoted now, but `PG_DB` goes into `WHERE datname = '${PG_DB}'` as it is. The operator sets it, so the risk is low.
- **Typer isn't pinned** (`typer>=0.12`). A release that changes how help text renders fails the new stale-page check on every pull request until `reference/cli.md` is regenerated. It happened on this change's own pull request: CI installed Typer 0.29, which shows a repeatable option's type as `<list[Path]>` where 0.27 showed `<path>`. `bundler`'s `--additional-mbtiles` now names its own label, so that page no longer depends on which of the two is installed. A pin, or the lockfile in O7, would cover the next such change.
- **`CONTRIBUTING.md` prefers squash merges, and every pull request so far has landed as a merge commit.** One of the two should change.
- **A failed `bundler` run leaves its partial file** in `bundled/.partial/` until the next run clears it, as `export` does.
- **The `init.sh` lock doesn't cover the database.** It is on the run directory, so two runs with different `ABT_RUN_DIR`s and the same `PG_DB` aren't stopped and would import over each other. A Postgres advisory lock held for the length of the run would cover that.
- **The tools a stage starts don't hold the `init.sh` lock.** Python closes inherited descriptors in its children, so an imposm or tippecanoe that a killed stage orphaned (L15) keeps writing after the lock is released.
- **`bundler -o` with a path loses the staging.** An absolute `--output-name` makes the partial and final paths the same file, so the bundle is built in place as before; a relative one with a missing subdirectory fails at the rename, after the whole join. Staging beside the final path, or rejecting a name with a separator, would fix both.

### In good shape

Every relative link in these docs resolves, and every page is in the nav. Every `export/*.json` `layer_id` has a view. No literal shard modulus remains. The `dblink` strings use `current_database()` and the live port. Export and download staging is correct. CI runs all four test suites, and every workflow has a concurrency group.

## Verification

- `abtv2-tools` pytest: 376 passed, 1 skipped (the real-DuckDB test, on a machine without the `spatial` extension). Root `tests/`: 38 passed. Both ran on Python 3.14 with Typer 0.27, and again on Python 3.13 with the package versions CI installs (Typer 0.29).
- `cargo test --locked`: 23 passed. The golden cross-check: 9 passed. Neither covers changed code; they're a regression check.
- `shellcheck` is clean on `init.sh`, `setup_ubuntu.sh` and `.github/scripts/subtree-sync.sh`, and `bash init.sh --help` runs.
- `mkdocs build --strict` passes and leaves no difference under `docs/`, on both of those setups.
- On the pull request, CI ran the lock and staging tests against the real `flock(1)` (38 passed), and the stale-page check failed the first push for the Typer difference described under [Noticed while fixing](#noticed-while-fixing).
- L10's SQL ran against a scratch PostgreSQL 18.6 cluster: creating the role, altering an existing one, and passwords containing `'`, `$$`, a backslash and `$(id)`, each followed by a login with that password. The log's mode was checked for a new log and an existing one.
- L12 and L3 run the real `init.sh` and `tile.sh` against stand-in tools. The journal tests for L1 and L3 leave a real hot SQLite journal beside the final name and check the new file's integrity after its first open.
- A second reviewer with no part in the fixes read the whole branch. It found the lock on the data root instead of the run directory (a host that set `ABT_RUN_DIR` and couldn't create the default data root could no longer start), the stale-journal case, and a `chmod` that, run as root with `LOG_FILE=/dev/null`, would have made `/dev/null` unreadable to every other user. All three are fixed in the commits above, each with a test that failed first.

Not verified:

- **The lock on a network filesystem.** Locally the tests ran on macOS, which has no `flock(1)`, with a stand-in that makes the same `flock(2)` call; CI ran them against the real one. Both used a local disk.
- **Whether a killed `tile-join` or tippecanoe leaves a hot journal.** The journal tests make one with Python's `sqlite3`; neither tool was killed mid-write.
- **`setup_ubuntu.sh` end to end.** Only the role SQL and the log's mode were exercised.
- **The job timeouts.** The workflows run with them, but no job has yet run long enough to reach one.
- **Any timing.** No pipeline stage ran, so every performance finding is an estimate.
