# Testing

This whole test-harness effort — the Python `abtv2-tools/tests/` suite plus the Rust golden-oracle suite in `vundler-rs/tests/` — originated from a dedicated code review pass. See [Code Review Findings](code-review-findings.md) for the review that produced it, including several bugs it caught and fixed.

!!! note "CI"
    The **Tests** workflow (`.github/workflows/tests.yml`) runs every suite below, plus `shellcheck` on `init.sh`, `setup_ubuntu.sh` and the subtree-sync script, on pushes to `main` and on pull requests that touch `abtv2-tools/`, `rbt-schema/`, `tests/` or those scripts. Run them locally before opening a PR too.

## `abtv2-tools/tests/`

27 pytest files, mirroring the `abt/` package roughly 1:1:

```text
test_aux_data_model.py          test_download_planet_mirrors.py        test_parallel.py
test_carto_processing_model.py  test_export_bundler_model.py           test_schema.py
test_cli_entry_point.py         test_export_bundler_trim.py            test_utils_fields.py
test_cli_funcs_download.py      test_export_exporter.py                test_utils_pg_config.py
test_cli_funcs_export_tiles.py  test_export_mbtiles_metadata.py        test_utils_rlimit.py
test_cli_funcs_import_to_pg.py  test_export_tile_layer_model.py        test_utils_run_reporter.py
test_cli_funcs_run_carto.py     test_importer_importer.py              test_utils_subprocess_tools.py
test_cli_funcs_vundler.py       test_osm_data_model.py                 test_utils_zip_tools.py
test_download_downloader.py     test_overture_check_proj_agreement.py  test_vundler_convert.py
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

Checks that need both `abtv2-tools/` and `rbt-schema/`, so they live outside both [mirrored](mirrors.md) directories:

- `test_imposm_tags.py`, with `imposm_tag_filter.py`, its model of imposm's read-time tag filter: every OSM tag key that `carto_sql` reads, and every mapping filter key, survives imposm's read, so none is silently NULL.
- `test_schema_guards.py`: every export `layer_id` names an `export.*` relation that `carto_sql` creates; no script that reads `abt.dissolve_shards` shards by a literal count; `execution_plan.yml` covers every `carto_sql` script, with weights only for scripts it lists; and group scripts create only the schemas and extensions the plan creates up front.

Run them from the repository root, with the same `requirements-dev.txt`:

```bash
pytest tests
```

## `abtv2-tools/vundler-rs/tests/`

See [vundler-rs](../reference/vundler-rs.md) for full detail. Two halves:

- `cli.rs` — Rust integration tests against the compiled binary, run with `cargo test`.
- `test_golden.py` + `fixtures.py` + `reference/vundler_reference.py` — Python golden-oracle tests comparing the compiled Rust binary against a frozen pre-port Python reference.

## `abtv2-tools/vundler-rs/bench/`

A separate benchmark and semantic-diff harness — wall-clock and RSS comparison between the Rust and pre-port Python implementations — not a correctness test suite. See [vundler-rs](../reference/vundler-rs.md) for the tools it contains and how to run it.

## See also

- [Contributing](contributing.md) — running these suites before a PR, and the CI that runs them.
- [Code Review Findings](code-review-findings.md) — the review pass that produced this harness.
