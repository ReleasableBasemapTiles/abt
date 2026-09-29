# Carto

`carto` transforms the raw `osm.*`/`aux_data.*` tables [`import`](import.md) loaded
into the `export.*` materialized views that [`export`](export.md) tiles. It does
this by running every SQL script in `--schema-dir`'s `carto_sql/*.sql`, either
sequentially in filename order or — when `carto_sql/execution_plan.yml` is
present and `-n` is above 1 — grouped and partially parallelized. Like
[`import`](import.md), it always redoes the full stage from scratch; every
script must be safe to re-run.

```bash
python abt-tools.py carto -w <working_dir> -s <schema_dir> [-p pg_config] [-n carto_concurrency]
```

## Flags

| Flag | Required | Default | Description |
|---|---|---|---|
| `-w`, `--working-dir` | yes | — | Root directory for logs/run output. |
| `-s`, `--schema-dir` | yes | — | Schema/config directory; `carto_sql/*.sql` (and optionally `carto_sql/execution_plan.yml`) live under here. |
| `-p`, `--pg-config` | no | `env` | PostgreSQL connection — `env` or `<host>,<port>,<user>,<password>,<dbname>`. |
| `-n`, `--carto-concurrency` | no | scaled to host CPU count (`1`, i.e. fully sequential, on the documented 8 vCPU tier) | Caps how many independent `carto_sql/execution_plan.yml` groups run concurrently against Postgres. `1` forces the historical, fully-sequential behavior regardless of `execution_plan.yml`. |

## Notable behavior & edge cases

- **Always re-runs everything.** There's no partial/incremental `carto` — every
  script's own `DROP ... IF EXISTS ... CASCADE` at the top of each block is what
  makes a full re-run safe.
- **Three-phase execution when `execution_plan.yml` is present and `-n` is
  above 1:**
    1. **Sequential prefix** — aux-geometry normalization and the `export`
       schema. It runs first, right after `carto` creates the plan's custom
       schemas and extensions.
    2. **Concurrent groups** — independent groups of scripts run up to
       `-n`/`--carto-concurrency` at a time, started in `execution_plan.yml`
       order (longest first), each sized by its `weights:` share of the host.
    3. **Sequential suffix** — final normalization over every `export.*` table,
       and only runs if every group in phase 2 succeeded.
- **A script failing inside a concurrent group only aborts that group** — other
  independent groups still run to completion. The prefix and suffix, by
  contrast, abort the *whole* run if they fail. See
  [Troubleshooting](../reference/troubleshooting.md) for the exact failure/error
  behavior and recovery steps.
- **Every script is timed.** The run's `summary.json` has a `carto_scripts`
  stage with each script's `duration_s` (a script that failed included), and
  `carto` prints the 10 slowest when it finishes. Use them to re-check
  `execution_plan.yml`'s longest-first order and its `weights:`.
- **Falls back to strict sequential filename order** if `-s/--schema-dir`'s
  `carto_sql/execution_plan.yml` is absent, or if `-n` is 1, whether passed
  explicitly or by default below 12 vCPUs. In that mode `carto` never checks
  the plan against the files.
- This page covers the CLI command itself; for how scripts are grouped, numbered,
  and validated against `execution_plan.yml`, see [Carto SQL](../schema/carto-sql.md).
  For sizing `-n`/`--carto-concurrency` against available cores/RAM, see
  [Performance & Sizing](../install/performance.md).

## See also

- [Carto SQL](../schema/carto-sql.md) — the SQL-script-level mechanics:
  `execution_plan.yml` format, script numbering, and the `.skip` convention.
- [Performance & Sizing](../install/performance.md) — sizing `-n/--carto-concurrency`
  and the per-group Postgres GUCs it scales down.
- [Troubleshooting](../reference/troubleshooting.md) — what happens when one
  `carto` script/group fails, and how to recover.
- [Norway walkthrough](../walkthroughs/norway.md) and
  [Planet walkthrough](../walkthroughs/planet.md) — `carto` in context as part of
  a full run.
- [Import](import.md) — the previous stage; [Export](export.md) — the next one.
