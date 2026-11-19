# Testing

This whole test-harness effort — the Python `abtv2-tools/tests/` suite plus the Rust golden-oracle suite in `vundler-rs/tests/` — originated from a dedicated code review pass. See [Code Review Findings](code-review-findings.md) for the review that produced it, including several bugs it caught and fixed.

!!! note "CI"
    The **Tests** workflow (`.github/workflows/tests.yml`) runs every suite below, plus `shellcheck` on `init.sh`, `setup_ubuntu.sh` and the subtree-sync script, on pushes to `main` and on pull requests that touch `abtv2-tools/`, `rbt-schema/`, `tests/` or those scripts. Run them locally before opening a PR too.

## Running the suites locally

None of the suites needs Postgres, GDAL, tippecanoe or network access, so they run on macOS or any Linux, with no need for the [Ubuntu setup](../install/ubuntu.md) the pipeline itself needs. Use Python 3.13, the version CI and `env.yaml` use. From the repository root:

```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r abtv2-tools/requirements-dev.txt
(cd abtv2-tools && pytest)
pytest tests
```

For the Rust suite, install Rust with [rustup](https://rustup.rs), then, with the same environment active:

```bash
cd abtv2-tools/vundler-rs
cargo test
cargo build
python -m pytest tests/test_golden.py
```

The shell checks need `shellcheck` (`brew install shellcheck` on macOS, `sudo apt install shellcheck` on Ubuntu):

```bash
shellcheck init.sh setup_ubuntu.sh .github/scripts/subtree-sync.sh
```

To build these docs as well, `pip install -r requirements-docs.txt` into the same environment and run `mkdocs serve` (or `mkdocs build --strict`, as the Docs workflow does).

The build rewrites five committed pages from code and schema: `reference/cli.md`, `schema/layers.md`, `overview/data-sources.md`, `schema/database.md`, and a block of `schema/carto-sql.md`. On a pull request the Docs workflow then runs `git diff --exit-code -- docs/` and fails if any of them changed, which means the pull request edited a source (a CLI help string, an `export/*.json`, a `carto_sql` header) without committing the page it generates. To fix it, run `mkdocs build --strict` and commit what changes under `docs/`. Build with Python 3.13 or newer: older versions ignore the `PYTHON_CPU_COUNT` the CLI reference is rendered with, so its worker defaults would follow your machine's core count.

Two tests in `test_overture_check_proj_agreement.py` also need `duckdb` or `ogr2ogr` on `PATH`, and skip themselves without it.

## `abtv2-tools/tests/`

The pytest files mirror the `abt/` package roughly 1:1. Two of them test code
outside the package: `test_cli_entry_point.py` tests the `abt-tools.py` entry
point, and `test_overture_check_proj_agreement.py` tests
`rbt-schema/scripts/overture/check_proj_agreement.py`:

```text
test_aux_data_model.py          test_download_planet_mirrors.py  test_overture_check_proj_agreement.py
test_carto_processing_model.py  test_export_bundler_metadata.py  test_parallel.py
test_cli_entry_point.py         test_export_bundler_model.py     test_schema.py
test_cli_funcs_bundler.py       test_export_bundler_staging.py   test_utils_fields.py
test_cli_funcs_download.py      test_export_bundler_trim.py      test_utils_pg_config.py
test_cli_funcs_export_tiles.py  test_export_exporter.py          test_utils_rlimit.py
test_cli_funcs_import_to_pg.py  test_export_mbtiles_metadata.py  test_utils_run_reporter.py
test_cli_funcs_run_carto.py     test_export_tile_layer_model.py  test_utils_subprocess_tools.py
test_cli_funcs_vundler.py       test_importer_importer.py        test_utils_zip_tools.py
test_download_downloader.py     test_osm_data_model.py           test_vundler_convert.py
```

Configuration lives in `abtv2-tools/pyproject.toml`:

```toml
[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
```

Run from inside `abtv2-tools/`:

```bash
pip install -r requirements-dev.txt   # or: conda env create -f env.yaml && conda activate abtv2
pytest
```

`requirements-dev.txt` exists specifically because pytest needs to import every module under test, and several of those modules import third-party packages (`pydantic`, `typer`, `psycopg2-binary`, `boto3`, `requests`, `PyYAML`, `tqdm`, `beautifulsoup4`, `pyproj`) that don't have reliable wheels for GDAL/numpy-adjacent packages on every platform. This file is the plain pip/venv fallback to the conda `env.yaml`, kept in sync with it — see [Configuration](../install/configuration.md).

!!! note "Scope of DB-, network-, and S3-touching code"
    Code paths that touch Postgres, the network, or S3 (`PGConfig`'s connection methods, live Geofabrik-index HTTP calls, S3 calls, real downloads) are exercised only up to their pure/mockable boundary. There is no live Postgres, network, or S3 access in this suite.

`test_overture_check_proj_agreement.py` tests a script in `rbt-schema/scripts/overture/`, so in the standalone `abtv2-tools` mirror, which has no `rbt-schema/`, it skips itself.

## `tests/` (repository root)

The tests that belong to neither [mirrored](mirrors.md) directory. Two files check `abtv2-tools/` and `rbt-schema/` against each other:

- `test_imposm_tags.py`, with `imposm_tag_filter.py`, its model of imposm's read-time tag filter: every OSM tag key that `carto_sql` reads, and every mapping filter key, survives imposm's read, so none is silently NULL.
- `test_schema_guards.py`: every export `layer_id` names an `export.*` relation that `carto_sql` creates; no script that reads `abt.dissolve_shards` shards by a literal count; `execution_plan.yml` covers every `carto_sql` script, with weights only for scripts it lists; and group scripts create only the schemas and extensions the plan creates up front.

The rest run one of the repository's shell scripts, or a function lifted out of one, in a temporary directory with stand-ins on `PATH` for the tools it calls, so none needs Postgres, tippecanoe or AWS:

- `test_init_workspace_lock.py` runs the real `init.sh` with a stand-in for `python abt-tools.py`: a second run on the same run directory stops before it starts any stage, whatever its data root; a run whose `ABT_RUN_DIR` is elsewhere needs nothing at `ABT_WORKSPACE_DIR`; and a finished run records its PID and releases the lock for the next one.
- `test_overture_tile_staging.py` runs `rbt-schema/scripts/overture/tile.sh` with a stand-in `tippecanoe`: a tiling run that fails, or whose output can't be tagged with its CRS, leaves no `building_polygon_<srs>.mbtiles` for a rerun to skip on and doesn't disturb one already in place, and a finished tileset isn't corrupted by a SQLite journal an earlier killed run left beside its name.
- `test_setup_role_sql.py` checks the SQL `setup_ubuntu.sh` generates for the Postgres role: a role name or password containing a quote, `$$`, a backslash or shell syntax stays inside its literal.
- `test_setup_log_file.py` checks how `setup_ubuntu.sh` prepares its run log: a new or existing log ends up readable by its owner only, and a `LOG_FILE` that isn't a regular file, such as `/dev/null`, keeps its mode.

`flock` ships with Linux and not macOS, so on a host without it the first two put a stand-in on `PATH`; CI runs them against the real one.

Run them from the repository root, with the same `requirements-dev.txt`:

```bash
pytest tests
```

## `abtv2-tools/vundler-rs/tests/`

See [vundler-rs](../reference/vundler-rs.md) for full detail. Two halves:

- `cli.rs` — Rust integration tests against the compiled binary, run with `cargo test`.
- `test_golden.py` + `fixtures.py` + `reference/vundler_reference.py` — Python golden-oracle tests comparing the compiled Rust binary against a frozen pre-port Python reference.

## `abtv2-tools/vundler-rs/bench/`

A separate benchmark and semantic-diff harness, not a correctness test suite. It was written to compare the Rust port with the pre-port Python; now that `abt/vundler.py` calls the binary, its `run_python.py` times the same binary through the Python wrapper. See [vundler-rs](../reference/vundler-rs.md) for the tools it contains and how to run it.

## See also

- [Contributing](contributing.md) — running these suites before a PR, and the CI that runs them.
- [Code Review Findings](code-review-findings.md) — the review pass that produced this harness.
