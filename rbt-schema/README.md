# rbt-schema

> **Source of truth:** this directory is developed in [ReleasableBasemapTiles/abt](https://github.com/ReleasableBasemapTiles/abt/tree/main/rbt-schema) and mirrored to [ReleasableBasemapTiles/rbt-schema](https://github.com/ReleasableBasemapTiles/rbt-schema) on every merge to `main`. Open issues and pull requests against abt.

The schema/config half of the ABT monorepo: imposm mappings, auxiliary-data source configs, the `carto_sql` SQL transform layer, per-layer tile export configs, and bundle metadata for the Releasable Basemap Tiles (RBT) vector tileset. It contains **no executable pipeline code** of its own (a couple of standalone shell scripts aside) — everything here is read by the [`abtv2-tools`](https://github.com/ReleasableBasemapTiles/abt/tree/main/abtv2-tools) CLI (`abt-tools.py`), passed in as `--schema-dir`. Neither half is useful alone: this directory defines *what* dataset gets built; `abtv2-tools` is the generic engine that builds it.

## Documentation

Full documentation for this directory lives under the workspace [`docs/`](https://ReleasableBasemapTiles.github.io/abt/schema/):

- [Schema Reference](https://ReleasableBasemapTiles.github.io/abt/schema/) — layout and data flow.
- [OSM Mappings](https://ReleasableBasemapTiles.github.io/abt/schema/osm-mappings/), [Auxiliary Data](https://ReleasableBasemapTiles.github.io/abt/schema/aux-data/), [Carto SQL](https://ReleasableBasemapTiles.github.io/abt/schema/carto-sql/), [Tile Metadata](https://ReleasableBasemapTiles.github.io/abt/schema/tile-metadata/).
- [Layer Registry](https://ReleasableBasemapTiles.github.io/abt/schema/layers/) — every tile layer, generated from `export/*.json`.
- [Adding a Layer](https://ReleasableBasemapTiles.github.io/abt/schema/adding-a-layer/) — the workflow for adding, changing, or disabling a layer.
- [Overture Buildings](https://ReleasableBasemapTiles.github.io/abt/pipeline/overture/) — the standalone `scripts/overture/` pipeline.
- [Data Sources & Licensing](https://ReleasableBasemapTiles.github.io/abt/overview/data-sources/) — every source and its license terms, generated from `import/aux_data/*.json` and `tile-metadata/metadata.py`.

See the workspace [`README.md`](https://github.com/ReleasableBasemapTiles/abt/blob/main/README.md) for the end-to-end pipeline overview and worked walkthroughs, and [`abtv2-tools/README.md`](https://github.com/ReleasableBasemapTiles/abt/blob/main/abtv2-tools/README.md) for the CLI/flag reference.

## Layout

```
import/osm/        imposm3 mapping YAML — one file per OSM-derived table
import/aux_data/   Non-OSM source configs (download URL/local file, format, layers to load)
static_data/       Raw data files checked into git, referenced by import/aux_data/*.json via local_path
carto_sql/         SQL transform scripts that turn osm.*/aux_data.* into export.* materialized views
export/            Per-layer tippecanoe/ogr2ogr export configs, one JSON file per tile layer
tile-metadata/     metadata.py — descriptive metadata written into the final bundled mbtiles
scripts/overture/  Standalone Overture buildings pipeline; bypasses abt-tools.py/Postgres entirely
```

`import/`, `import/osm/`, `import/aux_data/`, `export/`, and `carto_sql/` are required — [`DataSchema`](https://github.com/ReleasableBasemapTiles/abt/blob/main/abtv2-tools/abt/schema.py) validates their existence before anything runs. See [Schema Reference](https://ReleasableBasemapTiles.github.io/abt/schema/) for the full data-flow diagram and file-format documentation of each directory above.
