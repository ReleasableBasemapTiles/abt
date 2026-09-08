# ABT Tools (abtv2-tools)

Modular pipeline for building vector tilesets from OpenStreetMap and other open data. Chains together open-source utilities (imposm3, GDAL/`ogr2ogr`, tippecanoe, `tile-join`, and a Rust `vundler`) to produce Mapbox vector tilesets (`.mbtiles`) and Esri Vector Tile Package-like bundles.

Entry point: `python abt-tools.py <command> [options]`

This directory is one half of the monorepo: the generic pipeline runner, paired with the sibling [`../rbt-schema/`](../rbt-schema/) schema/config directory passed in as `--schema-dir`. See the workspace [`README.md`](../README.md) for the end-to-end pipeline overview, Ubuntu provisioning, and full worked walkthroughs (a small extract and a full planet build).

## Documentation

Full documentation for this directory lives under the workspace [`docs/`](../docs/index.md):

- [`abt-tools` CLI Reference](../docs/reference/cli.md) — every command, every flag, generated from the CLI's own `--help` text.
- [Pipeline Stages](../docs/pipeline/download.md) — one page per stage: [download](../docs/pipeline/download.md), [import](../docs/pipeline/import.md), [carto](../docs/pipeline/carto.md), [export](../docs/pipeline/export.md), [bundler](../docs/pipeline/bundler.md), [vundler](../docs/pipeline/vundler.md).
- [Performance & Sizing](../docs/install/performance.md), [Configuration](../docs/install/configuration.md).
- [vundler-rs](../docs/reference/vundler-rs.md) — the Rust binary `vundler` shells out to (`vundler-rs/`, below).
- [Testing](../docs/project/testing.md) — this package's pytest suite and `vundler-rs`'s golden-oracle tests.
- [Troubleshooting](../docs/reference/troubleshooting.md).

## Dependencies

Python 3.14, PostgreSQL >=16 / PostGIS >=3.4, GDAL (`ogr2ogr`) >=3.9.2, imposm3 >=0.14, tippecanoe >=2.76, `aria2` (`aria2c`, only needed for `download -k planet`). Python packages: [`env.yaml`](env.yaml) (conda/micromamba) or [`requirements-dev.txt`](requirements-dev.txt) (pip). For a from-scratch Ubuntu 26.04 host, [`../setup_ubuntu.sh`](../setup_ubuntu.sh) automates all of this — see [Ubuntu Setup](../docs/install/ubuntu.md).

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

See [Testing](../docs/project/testing.md) for the full breakdown, including the Rust `vundler-rs/` golden-oracle suite (`cargo test`).
