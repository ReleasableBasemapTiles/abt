# Performance & Sizing

This page covers how much hardware you need, how the pipeline tunes itself to it, and how `carto`'s aggressive session-level Postgres tuning interacts with the rest of the box.

## Why `carto` is expensive regardless of extract size

The `carto_sql` scripts hardcode aggressive session tuning and a fixed degree of parallelism, most visibly in the water/land-cover dissolve scripts (`005a_water_polygon.sql`, `009_land_cover.sql`):

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

These scripts also open up to **16 parallel `dblink` worker connections** to dissolve global water/land-cover polygons. This cost is driven by the *source* data's global extent, not by `-k`/`--osm-key` — it's roughly the same whether `carto` is building the full planet or a single small country, since the dissolve operates over globally-scoped source layers either way.

`carto` scales `max_parallel_workers_per_gather` and the dissolve's shard count down automatically (via the `abt.parallel_workers_per_gather`/`abt.dissolve_shards` custom GUCs referenced above) when several concurrent script groups share the box — see [Carto concurrency and its GUCs](#carto-concurrency-and-its-gucs) below.

## Two documented hardware tiers

| Tier | vCPUs | RAM | Disk | Use case |
|---|---|---|---|---|
| **Planet** | 48 | 384 GB | 2+ TB NVMe | Full-planet builds — see the [Planet walkthrough](../walkthroughs/planet.md). This is the tier `setup_ubuntu.sh`'s default `PG_*` tuning and `abt-tools.py`'s auto-scaled `-n/--num-workers`/`--carto-concurrency` defaults are aimed at. 32+ vCPUs / 128+ GB RAM is a workable floor, but expect the `import` step alone to take 24+ hours even on hardware this size — the planet PBF alone is 80+ GB, before Postgres or tile output. |
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
max_connections = 400
max_files_per_process = 4096
random_page_cost = 1.1
```

```conf
# Small-extract tier (8 vCPU / 32 GB)
shared_buffers = 8GB
effective_cache_size = 24GB
maintenance_work_mem = 2GB
max_worker_processes = 10
max_parallel_workers = 10
max_parallel_workers_per_gather = 4
random_page_cost = 1.1
```

`setup_ubuntu.sh` already defaults to the planet-tier tuning; override the `PG_*` env vars before running it only if your host's specs differ meaningfully from 48 vCPU / 384 GB:

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

`PG_MAX_CONNECTIONS` matters more at this scale than for a small extract: running `carto` with `--carto-concurrency` greater than 1 means several script groups hold their own connection simultaneously, and the water/land-cover scripts each additionally fan out up to 16 `dblink` worker connections from within whichever group is running them.

For the smaller 8 vCPU / 32 GB single-extract tier, scale all of the above down instead — see the small-extract `postgresql.conf` block above. The 16 concurrent `dblink` workers each requesting up to 1 GB of `work_mem` (set inside the SQL itself, not from `postgresql.conf`) are comfortably inside 32 GB at that tier, since the dissolve operates on a small, already-clipped set of polygons. See [Configuration](configuration.md#setup_ubuntush-environment-variables) for the full `PG_*` environment-variable reference.

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

1. **Prefix** — runs sequentially (schema setup, aux geometry normalization).
2. **Groups** — independent groups of scripts run concurrently with each other, up to `--carto-concurrency` at a time, one Postgres connection per group.
3. **Suffix** — runs sequentially, only once every group has succeeded.

See [Carto SQL](../schema/carto-sql.md) for the SQL-script-level mechanics of how `execution_plan.yml` groups scripts.

Because several groups can now share the box at once, `carto` scales down two custom Postgres GUCs for the duration of the groups phase, rather than leaving every group free to claim the same fixed dissolve/parallel-worker counts:

- `abt.dissolve_shards` — the number of `dblink` worker connections a water/land-cover-style dissolve opens (read via `COALESCE(current_setting('abt.dissolve_shards', true)::int, 16)`, falling back to the historical hardcoded `16` if unset).
- `abt.parallel_workers_per_gather` — native Postgres parallel workers per query (same `COALESCE` fallback pattern, historically `10`).

Both are derived roughly proportional to `(available cores) / --carto-concurrency`: a per-group core budget is computed as `max(cpu_count - 4, cpu_count // 2)` divided by the number of concurrently-running groups, then `abt.dissolve_shards` is that per-group budget (minimum 2) and `abt.parallel_workers_per_gather` is a quarter of it (minimum 2). This is a starting heuristic, not a precisely-derived optimum — tune via `--carto-concurrency` and the host's own `postgresql.conf` if a particular run under- or over-subscribes. Scripts that don't read these GUCs are unaffected either way, since every read falls back to its original hardcoded value.

## Where to go next

- [Ubuntu Setup](ubuntu.md) — installing and tuning Postgres itself.
- [Configuration](configuration.md) — the full `setup_ubuntu.sh` environment-variable reference, including every `PG_*` tuning variable.
- [Carto SQL](../schema/carto-sql.md) — `execution_plan.yml`'s format and how scripts are grouped.
- [Planet walkthrough](../walkthroughs/planet.md) and [Norway walkthrough](../walkthroughs/norway.md) — the two worked examples matching these tiers.
