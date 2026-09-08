# Testing

This whole test-harness effort — the Python `abtv2-tools/tests/` suite plus the Rust golden-oracle suite in `vundler-rs/tests/` — originated from a dedicated code review pass. See [Code Review Findings](code-review-findings.md) for the review that produced it, including several bugs it caught and fixed.

!!! note "Nothing here runs in CI today"
    None of these suites run automatically today (see [Contributing](contributing.md)) — they're run locally by contributors.

## `abtv2-tools/tests/`

21 pytest files, mirroring the `abt/` package roughly 1:1:

```text
test_aux_data_model.py         test_export_tile_layer_model.py   test_utils_pg_config.py
test_carto_processing_model.py test_osm_data_model.py            test_utils_rlimit.py
test_cli_entry_point.py        test_parallel.py                  test_utils_run_reporter.py
test_cli_funcs_vundler.py      test_schema.py                    test_utils_subprocess_tools.py
test_download_downloader.py    test_utils_fields.py              test_utils_zip_tools.py
test_download_planet_mirrors.py                                  test_vundler_convert.py
test_export_bundler_model.py
test_export_bundler_trim.py
test_export_exporter.py
test_export_mbtiles_metadata.py
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

## `abtv2-tools/vundler-rs/tests/`

See [vundler-rs](../reference/vundler-rs.md) for full detail. Two halves:

- `cli.rs` — Rust integration tests against the compiled binary, run with `cargo test`.
- `test_golden.py` + `fixtures.py` + `reference/vundler_reference.py` — Python golden-oracle tests comparing the compiled Rust binary against a frozen pre-port Python reference.

## `abtv2-tools/vundler-rs/bench/`

A separate benchmark and semantic-diff harness — wall-clock and RSS comparison between the Rust and pre-port Python implementations — not a correctness test suite. See [vundler-rs](../reference/vundler-rs.md) for the tools it contains and how to run it.

## See also

- [Contributing](contributing.md) — when to run these suites and what "no CI" means in practice today.
- [Code Review Findings](code-review-findings.md) — the review pass that produced this harness.
