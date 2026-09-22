# ABT (Releasable Basemap Tiles)

ABT turns OpenStreetMap data plus a handful of authoritative auxiliary open datasets — Natural Earth, NGA GeoNames, OurAirports, FieldMaps administrative boundaries, USGS domestic names, US Dept. of State LSIB, DISDI/MIRTA installations, and Overture Maps building footprints — into a bundled Mapbox vector tileset (`.mbtiles`), with an optional conversion to an Esri Compact Cache V2 tile bundle. A single Python CLI, `abt-tools.py`, drives every stage.

[Start with the Norway walkthrough](walkthroughs/norway.md){ .md-button .md-button--primary }
[Read the architecture](overview/architecture.md){ .md-button }

## Choose your path

<div class="grid cards" markdown>

- **New engineer**

    ---

    Get oriented in the repository, then see how the two halves of the monorepo fit together.

    [Repository Tour](overview/repo-tour.md) · [Architecture](overview/architecture.md)

- **Operator**

    ---

    Provision a fresh Ubuntu host, then run a small extract or a full planet build.

    [Ubuntu Setup](install/ubuntu.md) · [Norway Walkthrough](walkthroughs/norway.md) · [Planet Walkthrough](walkthroughs/planet.md)

- **Data engineer**

    ---

    The schemas behind the tiles, the layer registry, and where every dataset comes from.

    [Schema Overview](schema/index.md) · [Layer Registry](schema/layers.md) · [Data Sources & Licensing](overview/data-sources.md)

- **Contributor**

    ---

    Conventional Commits, tests, and what's still missing from the project's process.

    [Contributing](project/contributing.md) · [abt-tools CLI Reference](reference/cli.md)

</div>

## Highlights

- **Two-repo monorepo** — [`abtv2-tools/`](overview/repo-tour.md) is a generic pipeline runner (download → import → carto → export → bundler → optional vundler); [`rbt-schema/`](schema/index.md) is the schema/config content — imposm mappings, SQL transforms, and per-layer tile definitions — passed to it as `--schema-dir`. Neither is useful alone.
- **Concurrent `carto`** — independent `carto_sql/*.sql` scripts run against Postgres at once, grouped by [`execution_plan.yml`](schema/carto-sql.md), with concurrency auto-scaled to the host's CPU count.
- **Multi-projection tiling** — [`init.sh`](walkthroughs/init-sh.md) runs `export`/`bundler` for several EPSG codes (3857, 3395, 4087 by default) in parallel and can fold in [Overture Maps buildings](pipeline/overture.md) and externally-produced contours.
- **Esri bundle output** — [`vundler`](pipeline/vundler.md) converts the joined `.mbtiles` into an Esri Compact Cache V2 tile bundle via a Rust binary, [`abt-vundler`](reference/vundler-rs.md), ported from the original pure-Python implementation for better parallelism.
- **~58 declared tile layers** — every layer's zoom range, attributes, and tippecanoe/ogr2ogr options live in one `rbt-schema/export/*.json` file each; inspect them all on the generated [Layer Registry](schema/layers.md).

## Requirements at a glance

The pipeline shells out to PostgreSQL/PostGIS, GDAL/OGR, imposm3, tippecanoe, and (for planet-scale downloads) aria2. See [Ubuntu Setup](install/ubuntu.md) for a from-scratch install (manual or via [`setup_ubuntu.sh`](install/ubuntu.md)), and [Performance & Sizing](install/performance.md) for hardware guidance from a single-country extract up to a full-planet build.

## License and attribution

The code in this repository is a work of the United States Government and is dedicated to the public domain under [CC0 1.0](https://github.com/ReleasableBasemapTiles/abt/blob/main/LICENSE). See [NOTICE](https://github.com/ReleasableBasemapTiles/abt/blob/main/NOTICE) for the MIT-licensed planet-mirror code adapted from openmaptiles-tools. Generated tiles stay under their source-data licenses: see [Data Sources & Licensing](overview/data-sources.md), notably OpenStreetMap, FieldMaps, and Overture Maps buildings under ODbL (share-alike, attribution required).
