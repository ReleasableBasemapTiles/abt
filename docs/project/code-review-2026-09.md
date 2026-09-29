# Code Review, September 2026

A review of the whole monorepo, finished on 2026-09-28: `abtv2-tools/` (the Python CLI and `vundler-rs/`), `rbt-schema/` (SQL, mappings and configs), `init.sh`, `setup_ubuntu.sh` and this documentation. It looked for three things:

1. bugs in the code and the docs;
2. changes that make the project easier to pick up;
3. ways to make a build faster, implemented where plain Python and SQL can deliver them, and recommended where a compiled language would.

The fixes are on the `claude/review-fixes-perf` branch, one conventional commit each; the tables name the commit. Findings were checked against the code, and every SQL change ran on a scratch PostgreSQL 18.6 / PostGIS 3.6.4 / GEOS 3.14.1 cluster against synthetic fixtures. Items marked *(inferred)* weren't reproduced, and *(estimate)* marks a gain that nothing has measured yet. The [earlier review](code-review-findings.md) now has a status column.

## Summary

- **Two bugs silently dropped data.** On any concurrent `carto` run, the 48 vCPU default, the water script skipped 11 of its 16 shards, losing 33 of the 50 largest inland water polygons at z5–z11 and bringing back seams at z12+ (B0). And on every build, imposm discarded 21 OSM tags that `carto` reads, and a reject filter never fired (B1).
- **21 numbered bugs are fixed** (B0–B20), plus four in the scripts and tests (S1–S4) and about 40 factual errors in the docs.
- **Performance.** The Python CLI only orchestrates: the per-row and per-tile work already runs in compiled tools (imposm in Go; GDAL, tippecanoe and tile-join in C and C++; PostGIS and GEOS in C; `abt-vundler` in Rust). Rewriting the CLI in Rust or Go would gain nothing. The gains come from doing less redundant work, overlapping stages, sizing parallelism, and tuning Postgres for bulk loads, all implemented below. One compiled-language change is worth considering later, a Rust `tile-join` replacement, and only if the new timings show the bundler is a long pole.
- **Onboarding.** A CI workflow now runs every test suite. New pages cover the [prerequisites](../install/prerequisites.md), the [working directory](../overview/working-directory.md), a [glossary](../overview/glossary.md) and a [flag matrix](../overview/pipeline.md#flags-across-commands). `init.sh` works from any checkout, and `setup_ubuntu.sh` sizes Postgres to the host.

## Before the next build

1. **Re-import OSM** with `import -d osm -f` (a full re-read; B1 changes what imposm keeps). Until then the 21 tags stay NULL. Tiles change: those tags reach the layers 003, 004, 018, 022 and 023 build, and water polygons tagged `covered=yes` drop out.
2. **Re-import `fieldmaps_adm2_polygons`**, e.g. `debug_aux_import -a fieldmaps_adm2_polygons` (B10). No tiles change, because no script reads it yet.
3. **Rerun `setup_ubuntu.sh`** for the Postgres tuning. It sets `wal_level=minimal` unless `PG_BULK_LOAD=false`, and Postgres won't start under `minimal` with replication or WAL archiving, so a host that replicates or archives needs `PG_BULK_LOAD=false`. `PG_TIER` now sizes memory to the host.
4. **Clean up old working directories.** Downloads, FlatGeobufs and MBTiles are staged now, but files an interrupted run of the old code left are still skipped. See [Troubleshooting](../reference/troubleshooting.md#download-and-import).
5. **`init.sh`'s settings are environment variables now** (`ABT_*`, `PYTHON`, and `PG_HOST`, `PG_PORT`, `PG_USER`, `PG_PASSWORD`, `PG_DB`). It ignores `PG*` variables already exported, so a shell still pointed at another database can't redirect a build. It no longer passes the no-op `-c` to the planet import.
6. **Scripts that read `summary.json`:** tasks now carry `duration_s`; export records `export_to_fgb` and `export_to_mbtiles` separately, with "not attempted" for a step whose predecessor failed; and a failed `carto` run whose other scripts succeeded reports `PARTIAL_FAILURE` rather than `FAILED` (it still exits 1). See [Working Directory](../overview/working-directory.md#summaryjson).
7. **Merge with a merge commit or a rebase, not a squash.** [Contributing](contributing.md) prefers squash-merges, which would fold these commits into one changelog entry.

## Bugs fixed

| # | Severity | Where | What was wrong, and the fix | Commit |
|---|---|---|---|---|
| B0 | High: silent data loss | `carto_sql/005a_water_polygon.sql` | Both materialized shard columns used a literal `% 16`, but the `dblink` fan-outs loop over `0 .. abt.dissolve_shards - 1`, which `carto` sets to 5 at 48 vCPU and the default concurrency. Shards 5–15 were never processed. Sequential runs, the 8 vCPU default, were unaffected. Both now use `COALESCE(current_setting('abt.dissolve_shards', true)::int, 16)`, like the loops. On a 4,200-polygon fixture the old script produced 3,638 rows at 5 shards against 3,907 at 16; the fixed script's output at 5 matches the old output at 16. `tests/test_schema_guards.py` now fails on a literal modulus in any script that reads the setting. | `4866d95` |
| B1 | High: silent data loss | `import/osm/*.yml`, `abt/osm_data_model.py` | imposm keeps only the tags a mapping uses: mapped keys, column keys, `tags: include:`, `area` and `type`. A key used only in a filter, or read only from the hstore `tags` column, is dropped when the PBF is read. 21 keys `carto` reads were always NULL (lifecycle-prefixed railway, power and highway keys, `destroyed:tunnel`, `dam:type`, `airmark`), and `water_polygon.yml`'s `reject: covered: yes` never fired. The new `import/imposm_base.yml` lists them under `tags: include:` and is merged into the combined mapping. `tests/test_imposm_tags.py` models imposm's filter and fails when a key `carto` reads isn't kept. | `ed00204` |
| B2 | Medium: security | `download/downloader.py` | Every download ran with `verify=False`, and the warning was suppressed module-wide. Certificates are verified now. `ABT_INSECURE_DOWNLOADS=1` turns that off for every source, and a source's `verify_tls: false` for one: `disdi_mirta.json` sets it, because `www.acq.osd.mil` omits an intermediate certificate. | `97f1588` |
| B3 | Medium | `downloader.py` | Downloads wrote to their final path, so a dropped connection left a truncated file every rerun skipped, and a non-200 response returned `None` and was recorded as a success. Downloads stream into `<file>.part` and are renamed when complete, and any status but 200 raises. | `97f1588` |
| B4 | Medium | `downloader.py` | Extraction was skipped whenever its folder wasn't empty, so a half-finished one was never redone. It extracts into a `.partial` sibling, renames it, and writes a `.complete` marker; old extractions redo once. | `97f1588` |
| B5 | Medium | `export/exporter.py` | An existing `.fgb` was skipped even when a killed `ogr2ogr` had left it truncated: every layer writes with `SPATIAL_INDEX=NO`, which streams features, so the header is valid. It's written under `flatgeobuf/.partial/` and moved into place. | `929a079` |
| B6 | Medium | `utils/subprocess_tools.py` | Tool output was decoded as strict UTF-8, so one bad byte in a multi-hour tool's output crashed the stage. It's decoded with `errors="replace"`. | `4ad5a52` |
| B7 | Low–medium | `osm_data_model.py` | Every download and import fetched Geofabrik's index, even for `planet`, with no timeout or status check, and twice with `-c`. `planet` skips it, and the fetch has a timeout, checks the status and is cached. | `97f1588` |
| B8 | Low–medium | `utils/pg_config.py` | Connection URIs didn't percent-encode the user or password, and `conn_str` escaped quotes SQL-style, by doubling, where libpq needs backslashes, so a password containing `@`, `/` or `'` broke the connection. Plain values are unchanged. | `4ad5a52` |
| B9 | Low | `export/bundler.py` | `set_pragma_options` set per-connection PRAGMAs on a connection it then closed: a no-op. Removed. | `779945c` |
| B10 | Low | `import/aux_data/fieldmaps_adm2_polygons.json` | Loaded polygons with `-nlt MULTILINESTRING`. Now `MULTIPOLYGON`. | `e85f11e` |
| B11 | Low: performance | `carto_sql/000_update_aux_geom.sql`, `099_update_geometry.sql` | `CREATE INDEX IF NOT EXISTS` compares index names only, so every run built a second GiST index on every aux table and on all 60 export relations, one at a time, in the prefix and suffix. An index is built now only if no valid, non-partial GiST index leads with the geometry. | `ae8030a` |
| B12 | Low | `utils/messages.py` | The invalid `--schema-dir` message described a directory layout that no longer exists. | `50cf9e5` |
| B13 | Low | `cli_funcs/*.py`, `utils/fields.py` | Wrong help: seven places called `--pg-config` "'env' or file path"; `-a` was called a path; `-n`, `-z` and `-d` were misdescribed; and docstring `Args:` sections leaked into `--help` and the CLI reference. | `50cf9e5` |
| B14 | Low | `export/bundler_model.py` | `_has_tiles` ran twice per file, and `pre_validate_tiles_exists` was dead code. | `779945c` |
| B15 | Low | `cli_funcs/import_to_pg.py` | The aux import executor logged into the download log folder. | `6bb732c` |
| B16 | Low | `cli_funcs/download.py`, `export_tiles.py` | Extraction ran after a failed download, and `tippecanoe` after a failed `ogr2ogr`, so one failure was reported twice. The dependent step is now recorded as "not attempted". | `c8f1104`, `e6fc865` |
| B17 | Low–medium | `aux_data_model.py` | The FileGDB-to-FlatGeobuf conversion MIRTA needs ran while the job list was built: serially, unlogged, and able to abort the whole import before its summary, hours into `-d all`. It runs inside its own import task now. | `6bb732c` |
| B18 | Medium | `exporter.py`, `mbtiles_metadata.py` | "Complete" meant at least one tile, so a `tippecanoe` run killed at z12 shipped without z12–z13. Output is staged under `mbtiles/.partial/`. | `929a079` |
| B19 | Medium: security | `subprocess_tools.py` | Logged commands, and the errors recorded in `summary.json`, carried the database password (`ogr2ogr`'s `PG:` string, imposm's `-connection`). Now redacted. | `4ad5a52` |
| B20 | Low | `carto_sql/026_places.sql` | A latent `''::int` cast error on an empty display segment; now `NULLIF`. The finding's other half, that 024 couldn't be rerun on its own, was a false positive: its `DROP TABLE ... CASCADE` already drops its views. | `4866d95` |

### Scripts and tests

| # | Severity | Where | What was wrong, and the fix | Commit |
|---|---|---|---|---|
| S1 | High: setup | `setup_ubuntu.sh` | Its `PG_*` defaults were the planet tier's (`shared_buffers` 96GB) on every host, although its comment said small tier. On the Norway walkthrough's 32 GB host, Postgres wouldn't restart after tuning, and rerunning couldn't recover it *(inferred; certain under the script's `vm.overcommit_memory=2`)*. `PG_TIER=auto` now sizes memory to the host, and a `shared_buffers` over 40% of RAM stops the script before it changes anything. | `60b94a1` |
| S2 | Medium | `init.sh` | It hardcoded `/rbt` paths, so a clone anywhere else failed at [1/6]; it was tracked without its executable bit, so the documented `./init.sh` failed on a fresh clone; a flag missing its value died with "unbound variable"; and it only checked for `aws` under `--overture`. | `c44cdb5` |
| S3 | Low | `init.sh` | Its preflight comment said `ogrinfo -so -al` catches a truncated `.fgb`. Tested with GDAL 3.13 and tippecanoe 2.79: both exit 0 on one. The comment is corrected, and export's staging prevents the truncation instead. | `929a079` |
| S4 | Low | `abtv2-tools/tests/test_overture_check_proj_agreement.py` | Failed to collect in the standalone `abtv2-tools` mirror, which has no `rbt-schema/`. It skips itself there now. | `21663b2` |

### Documentation

The corrections, in `5ee1ca9`, `a0fef73`, `c887766`, `cac82d6`, `4018ad7`, `6a2aa39` and `9b00e5a`:

- **Install.** The walkthroughs and `configuration.md` used an `abt` role and `abt_norway` database, but the setup creates `rbt`. Three pages said the manual and scripted setups match; they differ, and a table now lists how. The manual path lacked Rust and `abt-vundler`, the AWS CLI and duckdb; it cloned the repo after the step that needs it; and it ran `tile-join --version`, which doesn't exist. Python is 3.13, not 3.14. GDAL is used only through its command-line tools, and the pin that matters is `proj>=9.8`.
- **Pipeline.** `vundler` was described in five places as pure Python working per zoom level; it's the Rust `abt-vundler`, working per 128×128-tile bundle. `carto` creates schemas and extensions before the prefix, not after, and opens a connection per script, not per group. `tile-join` does take `-N` and `-A`. `bundler -z` without `-o` overwrites `joined.mbtiles`. `export -z` caps each layer's own maximum zoom, and export never writes `.btis`. The `work_mem` figures in Performance & Sizing were wrong.
- **Reference and project.** Troubleshooting had the wrong role, service unit, MIRTA host and Geofabrik URL. `init-sh.md` claimed six CLI stages and a truncation check that doesn't work, and missed the PROJ check's trigger and several variables. The test counts were stale (21 and 22 files; there are 27), and the vundler-rs pages said there was no CI and that the golden tests need pydantic. `cli.md` changed with the CPU count of whichever machine built the docs; it's rendered for a 48 vCPU host now.

## Performance

### Implemented

| Change | What it saves | Evidence | Commit |
|---|---|---|---|
| WAL and bulk-load tuning in `setup_ubuntu.sh` | Nothing tuned WAL before: at `max_wal_size` 1GB, bulk loads forced a checkpoint every few minutes. Now `max_wal_size` 64GB (8GB small tier), `checkpoint_timeout` 30min, `wal_compression` lz4, `wal_buffers` 64MB, I/O concurrency 200 and `jit` off. `PG_BULK_LOAD` (the default) adds `wal_level=minimal`, so every table and view `carto` creates and fills in one transaction skips the WAL. | A 173 MB `CREATE TABLE ... AS` plus index wrote 69 kB of WAL under `minimal`, against 206 MB under `replica`. | `60b94a1` |
| Skip duplicate GiST builds (B11) | 60 index builds in the suffix and one per aux table in the prefix, on every run, all on the critical path. | Fixtures: GDAL-named, reprojected, mixed-case and view indexes are reused; tables with no usable index still get one. | `ae8030a` |
| Weighted `carto` group budgets, long poles first | Every group got the same share of the host, so at 48 vCPU `005a` and `009` ran with 5 shards, throttled, long after the short groups had finished. Weighted 2, they get 8. The plan now starts the long poles first, and `017` and `023` together, so Postgres can share their scan of the building table. | Unweighted plans get the old values, except for new caps at the sequential defaults (16 shards, 10 workers), which only bind when `-n` is set low on a large host (48 vCPU at `-n 2`: 22 shards before, 16 now). | `ae8030a` |
| 026's island area computed once | `ST_Area(geometry::geography)` ran in each of six `WHEN`s. | 150k polygons: 6.25 s to 3.03 s, identical ranks. | `7eb9ff4` |
| 005a ranks its largest polygons by stored size | Ranking by `ST_NPoints` detoasted every water geometry. | Fixture output unchanged. | `4866d95` |
| Export pipelined per layer, largest first | Every `ogr2ogr` had to finish before any `tippecanoe` started, in the order `glob` returned. Each layer now goes straight from FlatGeobuf to MBTiles, and the largest export tables start first. | End to end on PostGIS 3.6 with real `ogr2ogr` and `tippecanoe`. | `e6fc865` |
| OSM alongside the aux sources under `-d all` | The OSM download and import (the planet import alone takes a day) waited for every aux source, then ran alone; each zip was extracted only after every download had finished. The OSM work runs on a thread of its own now, and each zip is extracted as soon as it lands. | Tests fail if the OSM thread is swapped for a synchronous stand-in. | `c8f1104` |
| Timings in `summary.json` | Nothing recorded how long anything took. Every task now has `duration_s`, `carto` records each script, and `carto` and `export` print their slowest tasks. This is the data for tuning the weights and deciding on the items below. | | `2125e7c` |

Measured and dropped: guarding `ST_MakeValid` with `ST_IsValid` in `005a`, `007` and `008`. The default method already short-circuits valid input (153 ms against 141 ms guarded, over 10.7M vertices). `method=structure` is 3.8× slower on valid input, but that's about a minute of CPU across a planet build *(estimate)*, and on polygons with holes and on multipolygons it reorders vertices, which would change the output bytes.

### Recommended, not implemented

Every gain here is an *(estimate)* until a planet run's timings exist.

1. **Trim the building import.** Only `017` and `023` read `osm_building_polygon`, and only rows with one of 17 `man_made` values or `tower:type=radar`. Buildings make up most of OSM's ways, and the table takes all of them, with 23 columns. The mapping [below](#a-trimmed-building-mapping) keeps only the rows and columns those scripts read; it should take the table from hundreds of millions of rows to a small fraction of that, saving hours of the planet import and much of the database's size. Tiles show OSM buildings only through those two scripts (the building layer comes from Overture), so they shouldn't change; compare `export.utility_point` and `export.radar_label` before and after.
2. **Drop the unused imports** listed [below](#unused-data): 10 imposm tables and 5 aux tables no script reads.
3. **Export once for every projection.** `init.sh` runs `export` for 3857, 3395 and 4087, so every layer is queried out of PostGIS three times. Exporting one WGS84 FlatGeobuf per layer and reprojecting file to file with `ogr2ogr -t_srs` would read Postgres once.
4. **Chain each projection's export, bundle and upload.** `init.sh` waits for every projection's export before bundling any of them, and for every bundle before uploading.
5. **Size `tippecanoe`'s threads.** `init.sh` runs `-n` exports for each of three projections at once, and every `tippecanoe` defaults to all cores: 36 all-core processes at the default `ABT_JOBS=12`. Setting `TIPPECANOE_MAX_THREADS` to the cores divided by the concurrent runs would cut the contention.
6. **Split the longest layers.** Chunk the largest exports, and give the layers that hold one geometry set per `z_level` (water, land cover) one `tippecanoe` run per level, joined afterwards, so they run in parallel.
7. **Split `005a`** so its ocean and intermittent-water work run as groups of their own, and **parallelize `009`'s second phase**.
8. **Smaller SQL costs:** `005b`'s classification lookups, `012`'s quadratic `EXISTS`, and `003`'s unused `geom_len` and extra scan.
9. **Drop unused export indexes.** Of the 176 indexes on export relations, only scripts 022–027 read their own tables back *(inferred)*; `pg_stat_user_indexes` after a run would show which are never used.
10. **Split imposm's `-read` and `-write`**, so a failed write doesn't re-read the planet. **Shard the Overture buildings once**, then reproject.

### Compiled languages

- **No rewrite of the CLI in Rust or Go.** It only starts tools and waits for them.
- **A Rust `tile-join` replacement, only if the timings show the bundler is a long pole.** `tile-join` is already multithreaded and never touches geometry. A merge still has to decompress, combine and recompress every tile, so expect 1.5–2× *(estimate)*. It could reuse `vundler-rs`'s `rusqlite` and `rayon` plumbing and its golden-test harness; the care points are duplicate layer names, merging `vector_layers`, and parity with `-pk`.
- **Minor:** `lto = "fat"` and `codegen-units = 1` for `vundler-rs`. Small, since it's I/O-bound.

## Report only

These need a decision rather than a fix, or change the output in ways the maintainers should choose.

### SQL that changes the output

- `021_aeroway.sql:535-630`: the runway-count fan-out moves airports between categories. `:511-521` matches airports by name alone, worldwide. `:353` and `:377` take area and length in Web Mercator, which overstates length by sec(latitude).
- `024_cemetery.sql:40`: `RANK()` partitions by `name` where it should partition by `osm_id`, as `012` does; `contained` is always 0.
- `020_pumping_station.sql:27`: `class != 'power'` pulls every utility polygon into pumping stations.
- `003_road.sql:184`: `[A-Z]{2} ` marks NH, SH and similar road refs as US routes. `:71-92`: route-relation members mix node, way and relation ids, because the mapping has no `member_type`. `:134`: a `demolished` branch that can't match.
- `006_geonames_hydrographic.sql:131-144` deduplicates labels by name alone, and `:148` renames Lake Ontario to "Lake America"; confirm that's intended.
- `027_admin.sql:537-540`: adm0 label rows can be duplicated.
- `018`: telecom lines land in the power-line layer. `014`: the trigram `%` operator is used as "contains".
- Units: degrees against metres in `022` and `026`; geodesic against Web Mercator area in `005a_water_polygon.sql:894` and `009_land_cover.sql:480`.
- To confirm: `010`'s `garden` scope and `019`'s `class='power'` scope.
- `import/osm/highway_linestring.yml:28` maps the column `lanes` to the key `lane`. The column isn't exported; fixing it needs a re-import.

### Latent problems and limitations

- **Sequential `carto` never creates the plan's extensions.** `004` and `014` use `pg_trgm`, and no script creates it, so a database made without it fails at `004` in sequential mode (the 8 vCPU default) but not in concurrent mode, which now creates it. Both setup paths create it. Adding `CREATE EXTENSION IF NOT EXISTS pg_trgm` to both scripts would close this.
- **`dblink` connection strings** (`'dbname=%s port=%s ...'`, no user) work only because the role is a superuser and the server lets `postgres`, the user each session logs in as, connect over the local socket without a password: a cluster from `setup_ubuntu.sh`'s plain `initdb` trusts every local connection, and a stock Ubuntu cluster uses `peer`. Adding `user=` would break `peer` authentication on a stock cluster, so this is a documented limitation.
- `000` handles only EPSG:3857 and drops Z and M; `099`'s `ALTER COLUMN TYPE` would fail on a materialized view. Neither is hit today.
- **psycopg2's `with conn:` commits but doesn't close** (R5 of the earlier review, still open): every `PGConfig` query leaks a connection until the process exits.
- **`init.sh` can't restart between download and export.** `--from` takes only `download` or `export`, and `import` won't overwrite an existing OSM import without `--force`, so running it again from the start stops at [2/6].
- **`init.sh` only checks that AWS variables are set.** It requires `AWS_SESSION_TOKEN`, so it rejects instance-role and profile credentials, and temporary credentials can expire during a day-long build, before [6/6]. A live `aws sts get-caller-identity` check would need STS reachable, which a host that reaches S3 only through a VPC endpoint may not have, so the check stayed as it is and the docs describe the risk.
- **The Overture scripts have `shellcheck` findings**, so CI doesn't lint them yet: SC2011 (warning, `ls | xargs`) at `fetch.sh:70`; SC2086 at `fetch.sh:47`; SC1091 at `fetch.sh:14` and `tile.sh:12`; SC2016 at `tile.sh:105` (all informational).
- **Working-directory quirks** (see [Working Directory](../overview/working-directory.md)): `export` writes its `tippecanoe` logs into `logs/<run_id>/fgb/` and leaves `mbtiles/` empty; `vundler` writes its log inside the output tree it produces, and never clears that tree, so bundles from an earlier, higher-zoom conversion stay behind; `tmp/ogr_tmp`, `tmp/tippecanoe_tmp` and `TileLayer.mbtiles_tmp_dir` are created or defined but unused; `bundler` needs a Postgres configuration it never uses; and `run_id` has one-second resolution.
- *(inferred)* `009` and `022` leave logged scratch tables behind.
- From the earlier review: R1–R3 stand by design, and R5 and R7–R10 are open. Zip-flattening collisions are pinned by a test, as intended.

### Unused data

- **imposm tables no script reads (10):** `aerialway_linestring`, `aeroway_point`, `barrier_linestring`, `barrier_point`, `building_relation`, `country_point`, `highway_point`, `mountain_linestring`, `mountain_point`, `state_point`.
- **Aux tables no script reads (5):** `MirtaLocations` (the points; `023` uses the areas), `fieldmaps_adm1_polygons`, `fieldmaps_adm2_polygons`, `osm_coastlines`, `osm_ocean_simplified`.
- **Views built but not tiled:** `export.golf_course` and `export.sports_ground`, from `025`, have no `export/*.json`.
- **The building import**, of which only `017` and `023` read a sliver.

#### A trimmed building mapping

A replacement for `import/osm/building_polygon.yml` that keeps the columns and rows `017` and `023` read. It passes `tests/test_imposm_tags.py`, so every tag `carto` reads, and every filter key, is still kept. It needs a planet re-import to take effect.

```yaml
  building_polygon:
    type: polygon
    columns:
    - name: osm_id
      type: id
    - name: geometry
      type: validated_geometry
    - name: name
      key: name
      type: string
    - name: name_en
      key: name:en
      type: string
    - name: building
      key: building
      type: string
    - name: buildingpart
      key: building:part
      type: string
    - name: height
      key: height
      type: string
    - name: man_made
      key: man_made
      type: string
    - name: tower_type
      key: tower:type
      type: string
    - name: tower_construction
      key: tower:construction
      type: string
    - name: tags
      type: hstore_tags
    filters:
      require:
        building: ["__any__"]
      reject:
        building: ["no", "none", "No"]
        building:part: ["no", "none", "No"]
        location: ["underground"]
        man_made: ["bridge"]
    mapping:
      man_made:
      - storage_tank
      - oil_well
      - petroleum_well
      - offshore_platform
      - lighthouse
      - communications_tower
      - tower
      - mast
      - antenna
      - utility_pole
      - pole
      - water_tower
      - substation
      - transmission
      - silo
      - telescope
      - lock_gate
      tower:type:
      - radar
```

`building` and `building:part` stay columns because the filters use them, and imposm keeps a filter's key only if something else uses it. If `017`'s `man_made` list changes, this list has to change with it.

### Recommended only

- **Untrack `.cursor/plans/`.** `.gitignore` ignores `.cursor/*` except `rules/`, but nine plan files were committed before that rule and are still tracked: `git rm --cached .cursor/plans/*`.
- **Settle on one name.** The README expands ABT as "Releasable/Army Basemap Tiles", the site as "Releasable Basemap Tiles", and the bundler's fallback tileset name is "Army Basemap Tiles". The [Glossary](../overview/glossary.md) explains the current usage.

## Verification

- `abtv2-tools` pytest: 316 passed in the monorepo; in a `git archive` of the standalone mirror, 302 passed and 1 skipped (the duckdb test). Root `tests/`: 15 passed.
- `cargo test --locked` passed, and the golden cross-check: 9 passed.
- `shellcheck` is clean on `init.sh`, `setup_ubuntu.sh` and `.github/scripts/subtree-sync.sh`, and `bash init.sh --help` runs.
- `mkdocs build --strict` passes.
- SQL on the scratch cluster: the B0 and B11 fixtures, `026`'s ranks, the `ST_MakeValid` measurements, and `setup_ubuntu.sh`'s `ALTER SYSTEM` block and its WAL measurement. B8's quoting is round-tripped through libpq's own parser (psycopg2's `parse_dsn`) in the tests.
- `setup_ubuntu.sh`'s tier logic through a harness built from its own lines: 375, 125, 119, 31.3 and 16 GiB hosts, a missing `/proc/meminfo`, an explicit oversize `shared_buffers`, and invalid values.
- `init.sh` with stubbed tools: from a symlink in another directory, with `--no-upload`, with overridden variables, and with missing values, tools and credentials.
- `ogr2ogr` and `tippecanoe` round trips on small fixtures for the staged exports, including a truncated `.fgb`.
