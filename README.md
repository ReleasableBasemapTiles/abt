# ABT (Releasable/Army Basemap Tiles)

ABT turns OpenStreetMap data plus a handful of auxiliary open datasets (Natural Earth, NGA GeoNames, OurAirports, FieldMaps admin boundaries, USGS domestic names, US Dept. of State LSIB, DISDI/MIRTA installations, Overture Maps buildings) into a bundled Mapbox vector tileset (`.mbtiles`), with an optional conversion to an Esri Compact Cache V2 tile bundle.

This monorepo contains two components used together:

- [`abtv2-tools/`](abtv2-tools/) — the Python CLI/orchestration engine (`abt-tools.py`). This is the code that chains external geo tools together.
- [`rbt-schema/`](rbt-schema/) — the schema/config content (imposm mappings, aux-data source configs, SQL transforms, tile export configs) that gets passed to the CLI as `--schema-dir`.

Neither is useful without the other: `abtv2-tools` is a generic pipeline runner, and `rbt-schema` defines the specific dataset it builds. They used to be two separate git repositories and were merged into this single repo with their full commit history preserved — see each subdirectory's own history via `git log -- abtv2-tools/` / `git log -- rbt-schema/`.

## Documentation

Full documentation lives under [`docs/`](docs/index.md) — a MkDocs Material site (see [Building the docs site](#building-the-docs-site) below to render it locally; it isn't published anywhere yet, see [`.github/workflows/docs.yml`](.github/workflows/docs.yml) for why):

- **New here?** Start with the [Repository Tour](docs/overview/repo-tour.md) and [Architecture](docs/overview/architecture.md).
- **Setting up a host?** [Ubuntu Setup](docs/install/ubuntu.md) and [Performance & Sizing](docs/install/performance.md).
- **Running the pipeline?** [Norway walkthrough](docs/walkthroughs/norway.md) (fast, single-country) or [Planet walkthrough](docs/walkthroughs/planet.md) (full-scale), or the all-in-one [`init.sh` orchestrator](docs/walkthroughs/init-sh.md) for production runs.
- **Working on the schema?** [Schema Reference](docs/schema/index.md) and the generated [Layer Registry](docs/schema/layers.md).
- **Something broken?** [Troubleshooting](docs/reference/troubleshooting.md).
- **Contributing?** [Contributing](docs/project/contributing.md) and [Testing](docs/project/testing.md).

## Quick start

```bash
git clone git@github.com:ReleasableBasemapTiles/abt.git
cd abt
./setup_ubuntu.sh                 # fresh Ubuntu 26.04 host -- see docs/install/ubuntu.md
cd abtv2-tools
python abt-tools.py download -w ~/abt/run-norway -s ../rbt-schema -d all -k norway -n 4
```

See the [Norway walkthrough](docs/walkthroughs/norway.md) for the full, copy-pasteable sequence through `import`/`carto`/`export`/`bundler`, or the [Planet walkthrough](docs/walkthroughs/planet.md) for a full-scale build.

## Building the docs site

```bash
pip install -r requirements-docs.txt
pip install -r abtv2-tools/requirements-dev.txt   # needed for the generated CLI reference page
mkdocs serve
```

## License and attribution

See [Data Sources & Licensing](docs/overview/data-sources.md) for the full list of data sources and their license terms — notably OpenStreetMap, FieldMaps, and Overture Maps buildings under ODbL (share-alike, attribution required). This repository does not currently include a code `LICENSE` file; see [Contributing](docs/project/contributing.md).
