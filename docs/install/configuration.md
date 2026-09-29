# Configuration

This page covers the two configuration surfaces you'll touch before running any pipeline stage: the PostgreSQL connection, and the `--schema-dir` you point the CLI at. It also documents every environment variable [`setup_ubuntu.sh`](ubuntu.md#automated-setup-setup_ubuntush) accepts.

## PostgreSQL connection

Every stage that talks to Postgres (`import`, `carto`, `export`, `bundler`) takes a `-p/--pg-config` flag with two forms:

- `-p env` — read the connection from environment variables: `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, `PGPASSWORD`.
- `-p "<host>,<port>,<username>,<password>,<database_name>"` — an explicit connection string in that exact comma-separated order.

The [Norway walkthrough](../walkthroughs/norway.md) and [Planet walkthrough](../walkthroughs/planet.md) both export the five `PG*` variables once per shell session and then pass `-p env` to every command, e.g.:

```bash
export PGHOST=127.0.0.1
export PGPORT=5432
export PGUSER=rbt
export PGPASSWORD=rbt
export PGDATABASE=rbt
```

See those pages for the full command sequence; this page only covers the connection mechanism itself.

## `--schema-dir` layout

`--schema-dir` (in practice your `rbt-schema` checkout) is validated by `DataSchema.validate_data_schema_directories` (in `abtv2-tools/abt/schema.py`) before any stage runs. It requires `import/`, `import/osm/`, `import/aux_data/`, `export/`, and `carto_sql/` to all exist:

```python
        required_subdirectories = [
            self.base_schema_dir / "import",
            self.base_schema_dir / "import" / "osm",
            self.base_schema_dir / "import" / "aux_data",
            self.base_schema_dir / "export",
            self.base_schema_dir / "carto_sql"
        ]
        missing = [str(d) for d in required_subdirectories if not d.exists()]
        if missing:
            error_string = f"The following directories are missing: {', '.join(missing)}"
            raise ValueError(f"Data schema directories are invalid.\n{error_string}\n{DataSchemaErrorMessage}")
        return self
```

`tile-metadata/` isn't in this required list, but is required in practice — `bundler` fails outright if `tile-metadata/metadata.py` is missing. `static_data/` and `scripts/` (used by `rbt-schema` specifically) are conventions of that particular schema dir, not something the CLI itself enforces.

See the [Schema Reference overview](../schema/index.md) for the full file-format documentation of each subdirectory.

## Python environment: conda vs. pip

There are two ways to get a working Python environment for `abtv2-tools`:

| File | Purpose |
|---|---|
| `env.yaml` | The primary path — a micromamba/conda environment spec (Python 3.13, `gdal`, `proj>=9.8`, `pyproj`, `psycopg2`, `boto3`, and more). Used by both the manual [Ubuntu Setup](ubuntu.md#6-gdal-python-environment) conda/Miniforge steps and by `setup_ubuntu.sh`'s micromamba stage. The pipeline runs only GDAL's command-line tools, but it needs them built against PROJ 9.8 or later for the non-3857 projections, which this env pins. |
| `requirements-dev.txt` | A pip fallback listing pytest plus every third-party package `abt/` imports (excluding GDAL/numpy), for use in a plain pip/venv environment when a conda env isn't available or convenient — e.g. CI. Kept in sync with `env.yaml`'s non-GDAL dependencies by convention, not by tooling. |

See [Testing](../project/testing.md) for how `requirements-dev.txt` is actually used to run the test suite.

## Required Postgres extensions

| Extension | Why it's required |
|---|---|
| `postgis` | The pipeline is geospatial end to end — required throughout `import`, `carto`, and `export`. |
| `hstore` | imposm mappings store OSM tags in an `hstore_tags` column (see `rbt-schema/import/osm/*.yml`). |
| `dblink` | The water/land-cover dissolve scripts in `carto_sql` open parallel `dblink` worker connections to fan out a global polygon dissolve. `dblink` accepts their password-less connection strings only from a superuser, whatever `pg_hba.conf` says, so the pipeline's Postgres role must be one. |
| `pg_trgm` | Supplies the `%` similarity operator used across `carto_sql` for fuzzy-matching OSM tag values (e.g. typo-tolerant matching). |

See [Ubuntu Setup](ubuntu.md#create-a-database-and-role) for the `CREATE ROLE`/`CREATE EXTENSION` statements that set these up.

## `setup_ubuntu.sh` environment variables

All configuration for `setup_ubuntu.sh` is via environment variables — every one is optional. The defaults mostly match the manual [Ubuntu Setup](ubuntu.md) walkthrough; [How `setup_ubuntu.sh` differs](ubuntu.md#how-setup_ubuntush-differs) lists where they don't. Set any of them before invoking `./setup_ubuntu.sh`.

### Workspace & repo

| Variable | Default | Purpose |
|---|---|---|
| `ABT_WORKSPACE_DIR` | `/rbt` | Root dir for the repo checkout + run data. |
| `ABT_RUN_DIR` | `$ABT_WORKSPACE_DIR/run-planet` | Working directory for the default (Web Mercator) build. |
| `ABT_RUN_DIR_3395` | `${ABT_RUN_DIR}-3395` | Separate working directory for an EPSG:3395 (World Mercator) `--projection-override` build — kept distinct from `ABT_RUN_DIR` since intermediate `.fgb` filenames don't encode projection. |
| `ABT_MONOREPO_DIR` | The script's own directory, if `abtv2-tools/`/`rbt-schema/` already sit next to it; otherwise `$ABT_WORKSPACE_DIR/rbt` | Where the monorepo checkout lives (or already lives). |
| `ABT_REPO` | `git@abt:ReleasableBasemapTiles/abt.git` | Clone URL — the `abt` host is expected to be an SSH config `Host` alias for a deploy key (see [Ubuntu Setup](ubuntu.md#5-clone-the-repo)); override to a plain HTTPS URL or a different alias as needed. |
| `CLONE_REPO` | `true` | Set `false` to skip cloning `ABT_REPO` entirely. |
| `PIPELINE_USER` / `PIPELINE_GROUP` | The invoking user (or `$SUDO_USER`) / that user's primary group | Owner of `ABT_WORKSPACE_DIR`/`ABT_RUN_DIR` and everything cloned/written into them. |

### PostgreSQL role & database

| Variable | Default | Purpose |
|---|---|---|
| `PG_DB` / `PG_USER` / `PG_PASSWORD` / `PG_PORT` | `rbt` / `rbt` / `rbt` / `5432` | Pipeline's database/role. `init.sh` reads the same variables, and it has to pass the same `PG_PASSWORD`, which `PG_AUTH_HOST=scram-sha-256` checks. |
| `PG_SERVICE_NAME` | `postgresql-rbt` | Name of the custom systemd unit wrapping `initdb`/`pg_ctl` (the script bypasses Debian's `postgresql-common` cluster tooling entirely). |
| `PG_DATA_DIR` | `/var/lib/postgresql/<major>/main` | PostgreSQL data directory — override to point at a mounted NVMe device. |
| `FORCE_REINIT_POSTGRES` | `false` | Set `true` to allow wiping a non-empty `PG_DATA_DIR` before running `initdb` fresh; left `false` so the script fails loudly instead of silently deleting existing data. |
| `PG_AUTH_LOCAL` / `PG_AUTH_HOST` | `peer` / `scram-sha-256` | How a fresh cluster's `pg_hba.conf` authenticates connections over the local socket and over TCP from `127.0.0.1`/`::1`: a stock Ubuntu cluster's rules. `initdb` writes them, so they don't change an existing cluster. `trust` for both brings back an older `setup_ubuntu.sh`'s rules, which let any local user connect as any role without a password. `PG_AUTH_LOCAL` takes only `peer` or `trust`, because `carto`'s `dblink` sessions log in as `postgres` over the socket without a password, and `PG_AUTH_HOST` only `scram-sha-256` or `trust`. See [Postgres authentication](ubuntu.md#postgres-authentication). |

### PostgreSQL tuning

`PG_TIER` picks which of the two [documented hardware tiers](performance.md#two-documented-hardware-tiers) the defaults below come from. Any variable you set yourself wins over its tier default.

| Variable | Planet default | Small default | Purpose |
|---|---|---|---|
| `PG_TIER` | `auto` | `auto` | `planet` (48 vCPU / 384 GB), `small` (8 vCPU / 32 GB), or `auto`: planet on a host with 128 GB of RAM or more (a `MemTotal` of at least 120 GiB), else small. |
| `PG_SHARED_BUFFERS` | `96GB` | `8GB` | ~25% of the tier's RAM, and never more than 30% of this host's. The script stops before installing anything if this is over 40% of RAM, since Postgres would then fail to start. |
| `PG_EFFECTIVE_CACHE_SIZE` | `192GB` | `24GB` | A planner hint, not an allocation; never more than 80% of this host's RAM. |
| `PG_MAINTENANCE_WORK_MEM` | `8GB` | `2GB` | |
| `PG_MAX_WORKER_PROCESSES` | `44` | `10` | Leaves a few cores for the OS/other daemons. |
| `PG_MAX_PARALLEL_WORKERS` | `40` | `10` | |
| `PG_MAX_PARALLEL_WORKERS_PER_GATHER` | `8` | `4` | |
| `PG_MAX_PARALLEL_MAINTENANCE_WORKERS` | `8` | `2` | Parallel workers per `CREATE INDEX` (B-tree, BRIN and GIN; GiST builds are single-threaded). |
| `PG_MAX_WAL_SIZE` | `64GB` | `8GB` | Postgres's default of 1GB forces a checkpoint every few minutes during a bulk load. |
| `PG_CHECKPOINT_TIMEOUT` | `30min` | `30min` | |
| `PG_WAL_BUFFERS` | `64MB` | `64MB` | |
| `PG_IO_CONCURRENCY` | `200` | `200` | Sets both `effective_io_concurrency` and `maintenance_io_concurrency`; sized for SSD/NVMe. |
| `PG_BULK_LOAD` | `true` | `true` | Also sets `wal_level=minimal`, `max_wal_senders=0` and `synchronous_commit=off` — see [Performance & Sizing](performance.md#bulk-load-profile). Set `false` on a host that replicates or archives WAL; a rerun then resets those three to Postgres's defaults. |
| `PG_MAX_CONNECTIONS` | `400` | `400` | Raised unconditionally from Postgres's factory default (100) since concurrent `carto` groups can each open up to ~16 additional `dblink` worker connections for the water/land-cover dissolves; a too-low ceiling fails hard (`FATAL: sorry, too many clients already`) deep into a run rather than at startup. |
| `PG_MAX_FILES_PER_PROCESS` | `4096` | `4096` | Matches the `NOFILE_LIMIT` ulimit tuning below. |

The script also always sets `random_page_cost = 1.1`, `jit = off`, and `wal_compression` to `lz4` (or `pglz` on a build without lz4).

### Kernel & ulimit tuning

| Variable | Default | Purpose |
|---|---|---|
| `KERNEL_TUNE` | `true` | Set `false` to skip all of the `/etc/sysctl.d`, `/etc/security/limits.d`, and systemd `LimitNOFILE` tuning below. |
| `VM_SWAPPINESS` | `1` | Kept above 0 (rather than fully disabled) since an outright swap-averse kernel makes the OOM killer more likely to strike instead. |
| `VM_OVERCOMMIT_MEMORY` | `2` | Strict memory accounting, per PostgreSQL's own recommendation, to keep the OOM killer from targeting the postmaster. |
| `VM_OVERCOMMIT_RATIO` | `80` | Caps allocations at swap + this percentage of RAM. |
| `VM_DIRTY_BACKGROUND_RATIO` / `VM_DIRTY_RATIO` | `3` / `10` | Flush dirty pages earlier and in smaller batches than Ubuntu's defaults (10%/20%), so large `COPY`/import bursts don't build up a huge writeback backlog. |
| `FS_FILE_MAX` / `FS_AIO_MAX_NR` | `2097152` / `1048576` | System-wide ceilings on open file descriptors and in-flight async I/O requests (relevant to PostgreSQL 18's `io_uring` support). |
| `NOFILE_LIMIT` / `NPROC_LIMIT` | `1048576` / `65536` | Per-process/user open-file and process limits (`ulimit -n`/`ulimit -u`). |

### Tool build refs

| Variable | Default | Purpose |
|---|---|---|
| `IMPOSM_REF` / `TIPPECANOE_REF` | `master` / `main` | Git ref each tool is built from. |
| `FORCE_REBUILD_IMPOSM` / `FORCE_REBUILD_TIPPECANOE` | `false` | Rebuild even if a binary is already installed — useful since building from a moving branch has no fixed version to compare against for the usual "already installed, skip" check. |
| `RUSTUP_HOME` / `CARGO_HOME` | `/opt/rust/rustup` / `/opt/rust/cargo` | Shared (not per-user) Rust toolchain location, so the build works regardless of which user runs the script. |
| `FORCE_REBUILD_VUNDLER` | `false` | Rebuild `abt-vundler` (the Rust rewrite, see [vundler-rs](../reference/vundler-rs.md)) even if already built. |
| `DUCKDB_VERSION` | `latest` | duckdb CLI release to install. |
| `FORCE_REINSTALL_AWSCLI` / `FORCE_REINSTALL_DUCKDB` | `false` | Reinstall even if already present. |

!!! note "AWS CLI v2 and duckdb are for Overture, not `abt-tools.py`"
    Both are only needed by `init.sh --overture` (S3 access for Overture's own fetch, plus `init.sh`'s own upload step) — not by `abt-tools.py` itself. See [Overture Buildings](../pipeline/overture.md).

### Conda/Python environment

| Variable | Default | Purpose |
|---|---|---|
| `MAMBA_ROOT_PREFIX` | `/opt/micromamba` | A single well-known, system-wide micromamba install location, regardless of which user runs the script or later activates the env. |
| `CONDA_ENV_NAME` | `abtv2` | micromamba environment name. |

### Stage toggles

Set any of these to `false` to skip that stage entirely:

| Variable | Default |
|---|---|
| `INSTALL_POSTGRES` | `true` |
| `CONFIGURE_POSTGRES` | `true` |
| `INSTALL_IMPOSM` | `true` |
| `INSTALL_TIPPECANOE` | `true` |
| `INSTALL_VUNDLER` | `true` |
| `INSTALL_AWSCLI` | `true` |
| `INSTALL_DUCKDB` | `true` |
| `INSTALL_CONDA` | `true` |

For the exact reasoning behind any default, read the "Configuration" block at the top of `setup_ubuntu.sh` itself — every variable there has an inline comment explaining why its default is what it is.

## Where to go next

- [Ubuntu Setup](ubuntu.md) — the manual and automated provisioning steps these variables configure.
- [Performance & Sizing](performance.md) — how the Postgres tuning variables above map onto the two documented hardware tiers.
- [Schema Reference overview](../schema/index.md) — the full `--schema-dir` file-format documentation.
