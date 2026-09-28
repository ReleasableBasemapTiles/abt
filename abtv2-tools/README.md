# ABT Tools (abtv2-tools)

> **Source of truth:** this directory is developed in [ReleasableBasemapTiles/abt](https://github.com/ReleasableBasemapTiles/abt/tree/main/abtv2-tools) and mirrored to [ReleasableBasemapTiles/abtv2-tools](https://github.com/ReleasableBasemapTiles/abtv2-tools) on every merge to `main`. Open issues and pull requests against abt.

Modular pipeline for building vector tilesets from OpenStreetMap and other open data. Chains together open-source utilities (imposm3, GDAL/`ogr2ogr`, tippecanoe, `tile-join`, and a Rust `vundler`) to produce Mapbox vector tilesets (`.mbtiles`) and Esri Vector Tile Package-like bundles.

Entry point: `python abt-tools.py <command> [options]`

This directory is one half of the monorepo: the generic pipeline runner, paired with the sibling [`rbt-schema/`](https://github.com/ReleasableBasemapTiles/abt/tree/main/rbt-schema) schema/config directory passed in as `--schema-dir`. See the workspace [`README.md`](https://github.com/ReleasableBasemapTiles/abt/blob/main/README.md) for the end-to-end pipeline overview, Ubuntu provisioning, and full worked walkthroughs (a small extract and a full planet build).

## Documentation

Full documentation for this directory lives under the workspace [`docs/`](https://ReleasableBasemapTiles.github.io/abt/):

- [`abt-tools` CLI Reference](https://ReleasableBasemapTiles.github.io/abt/reference/cli/) — every command, every flag, generated from the CLI's own `--help` text.
- [Pipeline Stages](https://ReleasableBasemapTiles.github.io/abt/pipeline/download/) — one page per stage: [download](https://ReleasableBasemapTiles.github.io/abt/pipeline/download/), [import](https://ReleasableBasemapTiles.github.io/abt/pipeline/import/), [carto](https://ReleasableBasemapTiles.github.io/abt/pipeline/carto/), [export](https://ReleasableBasemapTiles.github.io/abt/pipeline/export/), [bundler](https://ReleasableBasemapTiles.github.io/abt/pipeline/bundler/), [vundler](https://ReleasableBasemapTiles.github.io/abt/pipeline/vundler/).
- [Performance & Sizing](https://ReleasableBasemapTiles.github.io/abt/install/performance/), [Configuration](https://ReleasableBasemapTiles.github.io/abt/install/configuration/).
- [vundler-rs](https://ReleasableBasemapTiles.github.io/abt/reference/vundler-rs/) — the Rust binary `vundler` shells out to (`vundler-rs/`, below).
- [Testing](https://ReleasableBasemapTiles.github.io/abt/project/testing/) — this package's pytest suite and `vundler-rs`'s golden-oracle tests.
- [Troubleshooting](https://ReleasableBasemapTiles.github.io/abt/reference/troubleshooting/).

## Dependencies

Python 3.14, PostgreSQL >=16 / PostGIS >=3.4, GDAL (`ogr2ogr`) >=3.9.2, imposm3 >=0.14, tippecanoe >=2.76, `aria2` (`aria2c`, only needed for `download -k planet`). Python packages: [`env.yaml`](env.yaml) (conda/micromamba) or [`requirements-dev.txt`](requirements-dev.txt) (pip). For a from-scratch Ubuntu 26.04 host, [`setup_ubuntu.sh`](https://github.com/ReleasableBasemapTiles/abt/blob/main/setup_ubuntu.sh) automates all of this — see [Ubuntu Setup](https://ReleasableBasemapTiles.github.io/abt/install/ubuntu/).

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

See [Testing](https://ReleasableBasemapTiles.github.io/abt/project/testing/) for the full breakdown, including the Rust `vundler-rs/` golden-oracle suite (`cargo test`).
