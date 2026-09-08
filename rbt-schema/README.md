# rbt-schema

The schema/config half of the ABT monorepo: imposm mappings, auxiliary-data source configs, the `carto_sql` SQL transform layer, per-layer tile export configs, and bundle metadata for the Releasable Basemap Tiles (RBT) vector tileset. It contains **no executable pipeline code** of its own (a couple of standalone shell scripts aside) — everything here is read by the [`abtv2-tools`](../abtv2-tools/) CLI (`abt-tools.py`), passed in as `--schema-dir`. Neither half is useful alone: this directory defines *what* dataset gets built; `abtv2-tools` is the generic engine that builds it.

## Documentation

Full documentation for this directory lives under the workspace [`docs/`](../docs/schema/index.md):

- [Schema Reference](../docs/schema/index.md) — layout and data flow.
- [OSM Mappings](../docs/schema/osm-mappings.md), [Auxiliary Data](../docs/schema/aux-data.md), [Carto SQL](../docs/schema/carto-sql.md), [Tile Metadata](../docs/schema/tile-metadata.md).
- [Layer Registry](../docs/schema/layers.md) — every tile layer, generated from `export/*.json`.
- [Adding a Layer](../docs/schema/adding-a-layer.md) — the workflow for adding, changing, or disabling a layer.
- [Overture Buildings](../docs/pipeline/overture.md) — the standalone `scripts/overture/` pipeline.
- [Data Sources & Licensing](../docs/overview/data-sources.md) — every source and its license terms, generated from `import/aux_data/*.json` and `tile-metadata/metadata.py`.

See the workspace [`README.md`](../README.md) for the end-to-end pipeline overview and worked walkthroughs, and [`abtv2-tools/README.md`](../abtv2-tools/README.md) for the CLI/flag reference.

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

`import/`, `import/osm/`, `import/aux_data/`, `export/`, and `carto_sql/` are required — [`DataSchema`](../abtv2-tools/abt/schema.py) validates their existence before anything runs. See [Schema Reference](../docs/schema/index.md) for the full data-flow diagram and file-format documentation of each directory above.
