# Planet Walkthrough

This builds a complete tileset for the entire planet (Geofabrik/OSM key `planet`, PBF currently 80+ GB).

!!! note "Prerequisites"
    This walkthrough assumes you've already provisioned a host per [Ubuntu Setup](../install/ubuntu.md), and it's written against the 48 vCPU / 384 GB tier described in [Performance & Sizing](../install/performance.md). Every `-n`/worker-count and timing figure below is calibrated to that tier — scale them down for smaller hardware.

For a much faster, lower-cost way to exercise this exact same pipeline on a single small extract instead, see the [Norway walkthrough](norway.md). For the production, multi-projection, S3-uploading path that wraps all of the stages below into one script, see [init.sh Orchestrator](init-sh.md).

## Configure the database connection

```bash
conda activate abtv2
cd ~/abt/abtv2-tools

export PGHOST=127.0.0.1
export PGPORT=5432
export PGUSER=abt
export PGPASSWORD=abt
export PGDATABASE=abt_planet
```

With these exported, every command below can use `-p env` for `--pg-config`.

## Download

```bash
python abt-tools.py download \
  -w ~/abt/run-planet \
  -s ../rbt-schema \
  -d all \
  -k planet \
  -n 12
```

- `-k planet` is actually the default `--osm-key` and could be omitted, but it's spelled out for clarity.
- `-d all` downloads both the planet PBF and every auxiliary dataset (Natural Earth, NGA GeoNames, OurAirports, FieldMaps boundaries, USGS names, DoS LSIB, DISDI/MIRTA, OSM coastline/ocean extracts) — none get clipped for a planet build.

!!! tip "Multi-mirror planet download"
    For `-k planet`, the OSM PBF download goes through `aria2c` instead of a plain HTTP GET: `planet_mirrors.py` queries the ~11 known public planet mirrors concurrently, cross-checks their reported MD5/date/size to agree on one current file, and hands every URL serving it to `aria2c` at once, aggregating bandwidth across mirrors instead of being capped by a single one. Checksum verification is mandatory — the download fails outright rather than proceeding on an unverified file if mirrors can't be reconciled into one trustworthy hash.

- Output: `~/abt/run-planet/osm/pbf/planet-latest.osm.pbf` (80+ GB) and `~/abt/run-planet/aux_downloads/`.
- Skips files that already exist, so it's safe to re-run if interrupted; `aria2c` itself resumes a partial download and re-validates its checksum on resume.
- `-n/--num-workers` (`12`) matches this tier's auto-computed default for `download` (`cpu_count // 4`); it's optional everywhere below — `import` defaults to `cpu_count // 2`, `export` to `cpu_count // 3`.

## Import

```bash
python abt-tools.py import \
  -w ~/abt/run-planet \
  -s ../rbt-schema \
  -d all \
  -n 24 \
  -p env \
  -k planet
```

- No `-c`/`--clip-aux` — it's a no-op for `-k planet` (there's no bounding box to clip aux data against for the whole planet).
- OSM data goes in via `imposm import` into the `osm` schema; aux data via `ogr2ogr` in parallel into the `aux_data` schema (dropped and recreated first).

!!! warning "Longest step of a planet build"
    Expect 24+ hours even on the 48 vCPU / 384 GB tier. Re-running `import` after OSM data has already loaded aborts with an error unless `-f`/`--force` is added.

## Carto (SQL transform)

```bash
python abt-tools.py carto \
  -w ~/abt/run-planet \
  -s ../rbt-schema \
  -p env
```

Runs every file in `rbt-schema/carto_sql/*.sql`, building the `export` schema from `osm`/`aux_data` — independent scripts run concurrently by default (see [Performance & Sizing](../install/performance.md) and [Carto SQL](../schema/carto-sql.md)), defaulting to 8 groups at once on this tier's 48 vCPUs; pass `-n 1` for one-at-a-time. Always re-runs from scratch; aborts on the first prefix/suffix failure or if any concurrent group fails — see [Troubleshooting](../reference/troubleshooting.md).

## Export to tiles

```bash
python abt-tools.py export \
  -w ~/abt/run-planet \
  -s ../rbt-schema \
  -n 16 \
  -p env \
  -z 13
```

For each of the ~58 layers defined in `rbt-schema/export/*.json`: `export.<layer>` → `flatgeobuf/<layer>.fgb` (via `ogr2ogr`) → `mbtiles/<layer>.mbtiles` (via `tippecanoe`, up to zoom 13). Both steps skip if their output file already exists — a partial re-run only redoes missing layers.

!!! warning "Disk budget"
    This is the most disk-hungry step at global scale (`flatgeobuf/` and `mbtiles/` each hold a full planet's worth of geometry per layer) — budget against the 2+ TB NVMe in [Performance & Sizing](../install/performance.md).

## Bundle

```bash
python abt-tools.py bundler \
  -w ~/abt/run-planet \
  -s ../rbt-schema \
  -p env
```

Runs `tile-join` across every per-layer `.mbtiles` file, stamping metadata from `rbt-schema/tile-metadata/metadata.py`, and writes `~/abt/run-planet/bundled/joined.mbtiles`. Reads every layer's full-planet `.mbtiles` at once and always rebuilds from scratch — budget real time and disk headroom.

Add `-z`/`--max-zoom` (e.g. `-z 8`) for a smaller, zoom-capped "RBT Small" package — each input is pre-trimmed with SQLite before `tile-join` runs.

## (Optional) Vundler — Esri tile bundle

```bash
python abt-tools.py vundler \
  -w ~/abt/run-planet \
  -z 13
```

Converts `bundled/joined.mbtiles` into an Esri Compact Cache V2 bundle tree at `bundled/vundled/p12/`, converting zoom levels concurrently (one worker per core by default — 48 here). This is not a complete `.vtpk` (no `conf.xml`/`root.json`/styles), just the raw tile bundle structure plus a bare `metadata.json`. See [vundler-rs](../reference/vundler-rs.md) for internals.

## Check the results

```bash
cat ~/abt/run-planet/logs/*/summary.json
```

```bash
sqlite3 ~/abt/run-planet/bundled/joined.mbtiles \
  "SELECT name, value FROM metadata;"
```

Or open `bundled/joined.mbtiles` in any MBTiles-aware viewer (QGIS, tileserver-gl, Mapbox Studio's local preview) to visually confirm global coverage.
