# ABT Tools (abtv2-tools)

Modular pipeline for building vector tilesets from OpenStreetMap and other open data. Chains together open-source utilities to produce Mapbox vector tilesets (.mbtiles) and Esri Vector Tile Packages (.vtpk).

Entry point: `python abt-tools.py <command> [options]`

## Dependencies

ABT was developed in Python 3.12 and tested on Rocky Linux 9.

- Python 3.12+
- PostgreSQL >=16 / PostGIS >=3.4
- GDAL (ogr2ogr) >=3.9.2
- imposm3 >=0.14
- tippecanoe >=2.76

Python packages: `env.yaml`. PostgreSQL connection: `PGHOST`/`PGPORT`/`PGDATABASE`/
`PGUSER`/`PGPASSWORD` env vars, or `--pg-config`.

## Pipeline

```
download -> import -> carto -> export -> bundler -> vundler (optional)
```

All commands take `-w/--working-dir` (output) and `-s/--schema-dir` (input config).

`--schema-dir` (you provide this):
```
import/osm/        imposm mapping YAML
import/aux_data/   aux data JSON configs
export/            per-layer export JSON configs
carto_sql/         SQL scripts, run in filename order
```

## Commands

```
download -w <dir> -s <dir> -d {osm,aux,all} [-n workers] [-k osm_key]
```
Downloads OSM PBF and/or aux files. Skips files that already exist.

```
import -w <dir> -s <dir> -d {osm,aux,all} -n <workers> [-p pg_config] [-k osm_key] [-f] [-c]
```
Imports OSM (imposm) and/or aux data (ogr2ogr) into PostgreSQL. Always full re-run.
If OSM data already exists, the whole command aborts with an error rather than
overwriting it (a full re-import can take 24+ hours) -- pass `-f/--force` to proceed
anyway. `-c/--clip-aux` clips aux data imports to the `-k` GeoFabrik extract's
bounding box (both a `-spat` pre-filter and a real `-clipsrc` clip, since a
bbox filter alone won't shrink a globally-dissolved layer) -- for fast test
builds; ignored when `-k` is `planet` or omitted.

```
carto -w <dir> -s <dir> [-p pg_config]
```
Runs every `carto_sql/*.sql` file in order. Always re-runs everything; scripts must
be safe to re-run.

```
export -w <dir> -s <dir> [-n workers] [-p pg_config] [-z max_zoom] [--projection-override EPSG:code]
```
Per layer: PostgreSQL -> FlatGeobuf (ogr2ogr) -> MBTiles (tippecanoe). Skips either
step if its output file already exists. `--projection-override` is advanced/
non-standard (`export --help` for details); output becomes `.btis` instead of
`.mbtiles`.

```
bundler -w <dir> -s <dir> [-p pg_config] [-q path ...] [-o output_name]
```
Joins all `mbtiles/*.mbtiles`/`.btis` into one package via tile-join. Always
rebuilds from scratch. Fails on mismatched projections across inputs. Output
defaults to `joined.mbtiles` (`joined.btis` under `--projection-override`);
`-o/--output-name` overrides this and is used exactly as given (no auto-renaming).
`-q/--additional-mbtiles` folds in an externally-produced mbtiles file (e.g.
contours); repeatable for more than one.

```
vundler -w <dir> [-i input_path] [-o output_dir] [-z max_zoom]
```
Converts a bundled mbtiles file into Esri Compact Cache V2 tile bundles
(`.bundle` files per zoom level, plus a bare `metadata.json`). Not a complete
`.vtpk` -- no `conf.xml`/`root.json`/styles. `-i/--input-path` defaults to
`bundled/joined.mbtiles` or `joined.btis`; `-o/--output-dir` defaults to
`bundled/vundled/p12`.

## Reuse

Only `export` and `download` skip existing outputs. `import`, `carto`,
`bundler`, and `vundler` always redo the full operation.

To rebuild one layer: delete its `flatgeobuf/<layer>.fgb` and/or
`mbtiles/<layer>.mbtiles`/`.btis`, then re-run `export`. Deleting only the mbtiles
file (keeping the fgb) skips straight to the tippecanoe step.

## Debug

```
debug_aux_import -w <dir> -s <dir> -a <aux_file> [-p pg_config]
```
Imports a single aux file in isolation.
