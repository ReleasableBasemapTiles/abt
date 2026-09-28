# Performance & Sizing

This page covers how much hardware you need, how the pipeline tunes itself to it, and how `carto`'s aggressive session-level Postgres tuning interacts with the rest of the box.

## Why `carto` is expensive even for a small extract

The `carto_sql` scripts set aggressive session tuning of their own, most visibly the water/land-cover dissolve scripts (`005a_water_polygon.sql`, `009_land_cover.sql`; `003_road.sql` and `022_dam.sql` set the same `work_mem`/`maintenance_work_mem`):

```sql
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

These scripts also open up to **16 parallel `dblink` worker connections** (`abt.dissolve_shards`) to dissolve water and land-cover polygons. The land-cover dissolve reads only `osm.osm_landcover_polygon`, so it shrinks with the extract. The water script also dissolves the global `aux_data.osm_ocean` polygons, the same size for every extract unless `import --clip-aux` (`-c`) clipped them to its bounding box.

`carto` scales `max_parallel_workers_per_gather` and the dissolve's shard count down automatically (via the `abt.parallel_workers_per_gather`/`abt.dissolve_shards` custom GUCs referenced above) when several concurrent script groups share the box — see [Carto concurrency and its GUCs](#carto-concurrency-and-its-gucs) below.

## Two documented hardware tiers

| Tier | vCPUs | RAM | Disk | Use case |
|---|---|---|---|---|
| **Planet** | 48 | 384 GB | 2+ TB NVMe | Full-planet builds — see the [Planet walkthrough](../walkthroughs/planet.md). This is the tier `abt-tools.py`'s auto-scaled `-n/--num-workers`/`--carto-concurrency` defaults are aimed at, and the one `setup_ubuntu.sh` tunes Postgres for on a host with 128 GB of RAM or more. 32+ vCPUs / 128+ GB RAM is a workable floor, but expect the `import` step alone to take 24+ hours even on hardware this size — the planet PBF alone is 80+ GB, before Postgres or tile output. |
| **Small extract** | 8 | 32 GB | 100 GB SSD | Single-country/small-region test builds — see the [Norway walkthrough](../walkthroughs/norway.md). Fast iteration on schema/SQL changes without planet-scale time or disk cost. |

On the 384 GB tier, Postgres itself should still be configured with a much smaller `shared_buffers`/`effective_cache_size` than the `carto_sql` scripts' own per-session `work_mem`/`maintenance_work_mem` overrides, since those are additive per concurrent `dblink` worker rather than shared:

```conf
# Planet tier (48 vCPU / 384 GB)
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

```conf
# Small-extract tier (8 vCPU / 32 GB)
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

Both tiers also get the [bulk-load profile](#bulk-load-profile) below.

`setup_ubuntu.sh` picks the tier for you: `PG_TIER=auto` (the default) uses the planet values on a host with 128 GB of RAM or more and the small ones otherwise, and shrinks `shared_buffers`/`effective_cache_size` to fit a host with less RAM than its tier assumes. Force a tier with `PG_TIER=planet` or `PG_TIER=small`, and override any single value with its `PG_*` variable:

```bash
export PG_TIER=planet
export PG_SHARED_BUFFERS=64GB              # ~25% of RAM on a 256 GB host
export PG_MAX_CONNECTIONS=400              # covers concurrent carto groups' dblink fan-out + import/export worker pools
./setup_ubuntu.sh
```

`PG_MAX_CONNECTIONS` matters more at this scale than for a small extract: running `carto` with `--carto-concurrency` greater than 1 means several script groups hold their own connection simultaneously, and the water/land-cover scripts each additionally fan out up to 16 `dblink` worker connections from within whichever group is running them.

On the smaller 8 vCPU / 32 GB single-extract tier, `carto` runs its scripts one at a time, so each dissolve gets all 16 `dblink` workers. Every `005a` worker sets `work_mem = 1GB`, and every `009` worker `work_mem = 2GB` and `maintenance_work_mem = 16GB`, inside the SQL itself rather than from `postgresql.conf`. Those are ceilings for each sort or hash, not allocations: a dissolve only gets near them on large inputs, which is why the [Norway walkthrough](../walkthroughs/norway.md) clips its aux data with `import -c`. See [Configuration](configuration.md#setup_ubuntush-environment-variables) for the full `PG_*` environment-variable reference.

## Bulk-load profile

Every stage bulk-loads: imposm and ogr2ogr `COPY` data in, and `carto` builds each `export.*` table with `CREATE TABLE`/`CREATE MATERIALIZED VIEW ... AS` plus its indexes. Postgres's defaults are sized for many small transactions, so `setup_ubuntu.sh` sets, on both tiers:

```conf
max_wal_size = 64GB            # 8GB on the small tier
checkpoint_timeout = 30min
wal_compression = lz4          # pglz on a build without lz4
wal_buffers = 64MB
effective_io_concurrency = 200
maintenance_io_concurrency = 200
jit = off
```

With `PG_BULK_LOAD=true` (the default) it also sets:

```conf
wal_level = minimal
max_wal_senders = 0
synchronous_commit = off
```

Under `wal_level = minimal`, a table created in the same transaction that fills it writes no WAL for the data: on PostgreSQL 18, a 173 MB `CREATE TABLE ... AS` plus its index wrote 69 kB of WAL, against 206 MB at the default `wal_level = replica`. Every `export.*` materialized view `carto` builds, and its indexes, is created that way; the rows the water and land-cover `dblink` workers insert into their intermediate tables are still logged.

!!! warning "`PG_BULK_LOAD=true` rules out replication and WAL archiving"
    `wal_level = minimal` means no streaming replicas, no WAL archiving and no
    replication slots. Postgres refuses to start with `archive_mode` on or a
    replication slot present, so `setup_ubuntu.sh` checks for both first and
    stops if it finds either. `synchronous_commit = off` can lose the last
    moments of commits in a crash, never corrupt data; a pipeline rerun redoes
    them anyway. On a host that replicates or archives, run with
    `PG_BULK_LOAD=false`: the three settings above then go back to Postgres's
    defaults.

## Auto-scaling on large single-host tiers

On a big single box, both the CLI and `carto_sql` itself scale up automatically rather than needing to be babysat per invocation. `-n/--num-workers` and `--carto-concurrency` both derive from `os.cpu_count()`, with a per-command divisor and floor:

| Command | Default formula | Floor |
|---|---|---|
| `download` (`-n`) | `cpu_count // 4` | 4 |
| `import` (`-n`) | `cpu_count // 2` | 4 |
| `export` (`-n`) | `cpu_count // 3` | 4 |
| `carto` (`-n/--carto-concurrency`) | `cpu_count // 6` | 1 |
| `vundler` (`-n`) | `cpu_count // 1` (one worker per core) | 4 |

Each divisor leaves more headroom for tasks that already spawn their own multi-threaded subprocess per worker (e.g. `tippecanoe` in `export`). All of these remain fully overridable via their `-n` flag; the auto-scaled value is only the default. On the documented 48 vCPU planet tier, `--carto-concurrency` computes to 8; on the 8 vCPU small-extract tier, it computes to 1 (fully sequential, matching pre-concurrency behavior).

## Carto concurrency and its GUCs

`carto` runs `carto_sql/*.sql` in three phases when `carto_sql/execution_plan.yml` is present and `--carto-concurrency` is greater than 1:

1. **Setup and prefix** — `carto` creates the plan's custom schemas and extensions, then runs the prefix scripts sequentially (aux geometry normalization, the `export` schema).
2. **Groups** — independent groups of scripts run concurrently with each other, up to `--carto-concurrency` at a time, started in the order `execution_plan.yml` lists them (longest first). A group's scripts run one after another, each on its own Postgres connection.
3. **Suffix** — runs sequentially, only once every group has succeeded.

See [Carto SQL](../schema/carto-sql.md) for the SQL-script-level mechanics of how `execution_plan.yml` groups scripts.

Because several groups can now share the box at once, `carto` scales down two custom Postgres GUCs for the duration of the groups phase, rather than leaving every group free to claim the same fixed dissolve/parallel-worker counts:

- `abt.dissolve_shards` — the number of `dblink` worker connections a water/land-cover-style dissolve opens (read via `COALESCE(current_setting('abt.dissolve_shards', true)::int, 16)`, falling back to the historical hardcoded `16` if unset).
- `abt.parallel_workers_per_gather` — native Postgres parallel workers per query (same `COALESCE` fallback pattern, historically `10`).

Both come from each group's share of a core budget of `max(cpu_count - 4, cpu_count // 2)`. The groups that start together (the first `--carto-concurrency` groups in the plan) split the budget in proportion to their `weights:` in `execution_plan.yml` (default 1; a group's weight is its heaviest script's), and a group that starts later gets the share its weight would have had among them. `abt.dissolve_shards` is the share and `abt.parallel_workers_per_gather` a quarter of it, each at least 2 and at most the scripts' own sequential defaults (16 and 10). Today `009_land_cover.sql` and `005a_water_polygon.sql` are weighted 2: on the 48 vCPU tier at the default concurrency of 8 they get 8 shards each and every other group 4, where an unweighted plan gives every group 5. This is a starting heuristic, not a precisely-derived optimum — tune via the weights, `--carto-concurrency` and the host's own `postgresql.conf` if a particular run under- or over-subscribes. Each run's `summary.json` records every script's duration in its `carto_scripts` stage, which shows where the long poles are. Scripts that don't read these GUCs are unaffected either way, since every read falls back to its original hardcoded value.

## Where to go next

- [Ubuntu Setup](ubuntu.md) — installing and tuning Postgres itself.
- [Configuration](configuration.md) — the full `setup_ubuntu.sh` environment-variable reference, including every `PG_*` tuning variable.
- [Carto SQL](../schema/carto-sql.md) — `execution_plan.yml`'s format and how scripts are grouped.
- [Planet walkthrough](../walkthroughs/planet.md) and [Norway walkthrough](../walkthroughs/norway.md) — the two worked examples matching these tiers.
