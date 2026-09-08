# Repository Tour

A directory-by-directory map of the monorepo. For the conceptual relationship between the two halves, see [Architecture](architecture.md).

## Root of the repo

| Path | What it is |
|---|---|
| `README.md` | The workspace walkthrough: pipeline overview, Ubuntu setup, and full planet + small-extract worked examples. |
| `init.sh` | The production orchestrator that drives the whole pipeline (plus Overture buildings and multi-projection builds) end to end. See [init.sh Orchestrator](../walkthroughs/init-sh.md). |
| `setup_ubuntu.sh` | A ~49 KB idempotent Ubuntu 26.04 bootstrap script, in 11 numbered stages (1: OS check, 1b: ABT root dir, 2: base apt packages, 2b: kernel/ulimit tuning, 3: PostgreSQL + PostGIS via `initdb`/a custom systemd unit, 4 & 5: role/database/extensions/tuning, 6: imposm from source, 7: tippecanoe from source, 7b: AWS CLI v2, 7c: duckdb CLI, 8: clone the monorepo, 9: Rust toolchain + `abt-vundler`, 10: micromamba + `env.yaml` Python env, 11: verification). Every stage self-checks before repeating work, so re-running it is safe. See [Ubuntu Setup](../install/ubuntu.md). |
| `.cursor/plans/` | Internal planning docs — not part of the public site. |

Two separate git repos, one history. `abtv2-tools` and `rbt-schema` used to be independent git repositories and were merged into this single repo with commit history preserved — `git log -- abtv2-tools/` and `git log -- rbt-schema/` both still work. A second git remote named `rbt-schema` (pointing at `git@github.com:ReleasableBasemapTiles/rbt-schema.git`) is kept for periodic history sync, not for live submodule/subtree mounting.

## `abtv2-tools/` — the pipeline engine

| Path | What it is |
|---|---|
| `abt-tools.py` | CLI entrypoint: a Typer app (`app = typer.Typer(add_completion=False)`) with a root `@app.callback()` that raises the process's open-file limit, then mounts seven sub-apps (one per subcommand). |
| `abt/` | The Python package — see the breakdown below. |
| `tests/` | 21 pytest files, mirroring the package roughly 1:1. |
| `vundler-rs/` | A Rust rewrite of the Python `vundler` stage (~1,000 lines across `Cargo.toml` and `src/{main,bundle,db}.rs`), with its own `tests/` (Rust integration tests in `cli.rs` plus Python golden-oracle tests) and a `bench/` directory comparing the Rust port against a frozen pre-port Python reference. See [vundler-rs](../reference/vundler-rs.md). |
| `env.yaml` | micromamba/conda environment spec: Python 3.14, `gdal`, `numpy`, `pyproj`, `psycopg2`, `boto3`, `protobuf`, `pydantic`, `requests`, `click`, `typer`, `rich`, `pyyaml`, `tqdm`, `pyclipper`, `libgdal-arrow-parquet`, `beautifulsoup4`, `pytest` — plus vestigial `sphinx`/`sphinx-rtd-theme`/`sphinx-pydantic` entries that aren't used by any actual docs build in this repo. |
| `requirements-dev.txt` | A pip fallback for tests/CI when a conda env isn't available, kept in sync with `env.yaml`'s non-GDAL dependencies. See [Testing](../project/testing.md). |
| `pyproject.toml` | Pytest-only configuration (`pythonpath=["."]`, `testpaths=["tests"]`) — there's no build metadata here; the package isn't pip-installable today. |

### `abtv2-tools/abt/` package layout

| Subpackage/module | Contents |
|---|---|
| `cli_funcs/` | One module per Typer subcommand: `download.py`, `import_to_pg.py`, `run_carto.py`, `export_tiles.py`, `bundler.py`, `vundler.py`, `import_aux_single.py`, plus shared `cli_helpers.py`. |
| `download/` | `downloader.py`, `planet_mirrors.py` (multi-mirror planet PBF download), `boto_configuration.py`. |
| `export/` | `exporter.py`, `bundler.py`, `bundler_model.py`, `tile_layer_model.py`, `mbtiles_metadata.py`. |
| `importer/` | `importer.py`. |
| `utils/` | Logging, Postgres config, rlimit handling, subprocess helpers, field/zip utilities. |
| Top-level modules | `schema.py` (validates `--schema-dir` layout), `osm_data_model.py`, `aux_data_model.py`, `carto_processing_model.py`, `parallel.py`, `vundler.py`/`vundler_model.py`. |

## `rbt-schema/` — the schema/config content

| Path | What it is |
|---|---|
| `import/osm/` | 38 imposm3 mapping YAML fragments, one per OSM-derived table. |
| `import/aux_data/` | 23 JSON configs for non-OSM sources. |
| `carto_sql/` | 33 active, numbered SQL scripts (including the sequential-suffix `099_update_geometry.sql`), plus one disabled via the `.skip` convention (`031_building.sql.skip`), `execution_plan.yml` (concurrency grouping), and a `static_data/` sub-folder — unrelated to the top-level `static_data/` below — holding manually-run seed SQL. |
| `export/` | 58 active per-layer JSON configs, one disabled via `.skip` (`building_polygon.json.skip`, since that layer comes from the Overture pipeline instead). |
| `static_data/` | Raw data files checked directly into git (e.g. `ne_physical_centerlines.fgb.zip`), referenced by `import/aux_data/*.json` via `local_path`. |
| `tile-metadata/metadata.py` | The `metadata` dict written into the final bundled mbtiles. |
| `scripts/overture/` | A standalone (no Postgres) Overture Maps buildings pipeline: `fetch.sh`, `shard.sh`, `tile.sh`, `lock.sh`, `tag_crs.py`, plus its own README. See [Overture Buildings](../pipeline/overture.md). |

See the [Schema Reference](../schema/index.md) section for the full file-format documentation of each of these directories.

## Where to go next

- [Architecture](architecture.md) — how these two halves compose at runtime.
- [Pipeline](pipeline.md) — the stage-by-stage data flow.
- [Ubuntu Setup](../install/ubuntu.md) — provisioning a host to run this from scratch.
- [Testing](../project/testing.md) — how `abtv2-tools/tests/` and `vundler-rs/tests/`/`bench/` fit together.
