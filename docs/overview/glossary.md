# Glossary

Terms these docs and the code use, in alphabetical order.

**ABT**
:   The pipeline, its CLI (`abt-tools.py`, the `abt` Python package) and this repository. The README expands it as Releasable/Army Basemap Tiles; the bundler still names a tileset "Army Basemap Tiles (Build: <date>)" when `tile-metadata/metadata.py` doesn't set a name. See also **RBT**.

**`abt-vundler`**
:   The Rust binary, built from `abtv2-tools/vundler-rs/`, that the `vundler` command runs. It has to be on `PATH`. See [vundler-rs](../reference/vundler-rs.md).

**`abtv2-tools/`**
:   The Python CLI and its tests; one of the monorepo's two halves, published to its own repository too (see **Mirror**).

**Aux data**
:   Every source that isn't OSM: Natural Earth, NGA GeoNames, OurAirports, FieldMaps boundaries, USGS names, LSIB, DISDI/MIRTA and others. Each has a JSON config in `rbt-schema/import/aux_data/`, `import` loads it into the `aux_data` Postgres schema with `ogr2ogr`, and `import -c/--clip-aux` clips it to the extract's bounding box. See [Auxiliary Data](../schema/aux-data.md).

**Bulk-load profile**
:   The Postgres settings `setup_ubuntu.sh` applies unless `PG_BULK_LOAD=false`: `wal_level=minimal`, `max_wal_senders=0` and `synchronous_commit=off`, so tables carto creates and fills in one transaction skip the WAL. It rules out replication and WAL archiving. See [Performance & Sizing](../install/performance.md#bulk-load-profile).

**Bundle (Esri)**
:   One `.bundle` file of up to 128×128 tiles in a **Compact Cache V2** tree. `abt-vundler` converts bundles concurrently. Not to be confused with the **bundler**.

**Bundler**
:   The `bundler` command. It joins every layer's `.mbtiles` (plus any `-q/--additional-mbtiles`, such as contours or Overture buildings) into one tileset with `tile-join`, `bundled/joined.mbtiles` by default, and writes its metadata. See [Bundler](../pipeline/bundler.md).

**Carto**
:   The `carto` command and the `rbt-schema/carto_sql/*.sql` scripts it runs, which turn the imported `osm.*` and `aux_data.*` tables into one `export.*` materialized view per layer. See [Carto](../pipeline/carto.md) and [Carto SQL](../schema/carto-sql.md).

**Compact Cache V2**
:   Esri's tile-cache layout, `tile/L<zoom>/R<row>C<col>.bundle`, used inside a `.vtpk`. `vundler` writes the tiles and a bare `metadata.json`, not a complete `.vtpk`.

**Dissolve shards**
:   How many `dblink` worker connections the water (`005a`) and land-cover (`009`) scripts split their polygon dissolves across: the `abt.dissolve_shards` setting. It's 16 when `carto` runs sequentially; when groups run concurrently, `carto` sets it for each group from that group's share of the host's CPUs.

**Execution plan**
:   `rbt-schema/carto_sql/execution_plan.yml`. It lists the scripts `carto` runs first (the **prefix**), the independent **groups** it may run concurrently, and the scripts it runs last (the **suffix**), with the schemas and extensions to create up front and optional `weights:` for heavy groups. Without it, or with `--carto-concurrency 1`, scripts run one at a time in filename order.

**Export layer, `layer_id`**
:   One tile layer, configured by one of the 58 `rbt-schema/export/*.json` files. Its `layer_id` names the `export.<layer_id>` view that carto builds, the layer inside the tiles, and the files `flatgeobuf/<layer_id>.fgb` and `mbtiles/<layer_id>.mbtiles`. See [Layer Registry](../schema/layers.md).

**FlatGeobuf (`.fgb`)**
:   The file `export` writes from each `export.*` view with `ogr2ogr`, and then tiles with `tippecanoe`.

**Geofabrik key**
:   A `-k/--osm-key` value such as `norway`: the `id` of an extract in Geofabrik's index. `planet` means the whole-world file instead. See [Troubleshooting](../reference/troubleshooting.md#geofabrik-keys).

**GUC**
:   A Postgres configuration setting. `carto` passes custom ones, `abt.dissolve_shards` and `abt.parallel_workers_per_gather`, to each group's scripts to share the host's CPUs between concurrent groups.

**imposm**
:   The Go tool `import` runs to load the OSM PBF into the `osm` Postgres schema, following the table mappings in `rbt-schema/import/osm/*.yml`. See [OSM Mappings](../schema/osm-mappings.md).

**MBTiles (`.mbtiles`)**
:   A SQLite file of vector tiles. `export` writes one per layer, and `bundler` joins them into one.

**Mirror**
:   `abtv2-tools/` and `rbt-schema/` are developed here and published on every merge to `main` to the separate repositories they came from. See [Upstream Mirrors](../project/mirrors.md).

**Overture buildings**
:   Building footprints from Overture Maps, fetched and tiled by the scripts in `rbt-schema/scripts/overture/` (run by `init.sh --overture`) and folded into the bundle with `-q`. See [Overture Buildings](../pipeline/overture.md).

**Planet**
:   The whole-world OSM file, `-k planet`. `download` fetches it from several mirrors at once with `aria2c` and checks its MD5.

**Prefix, groups, suffix**
:   `carto`'s phases under an **execution plan**: the prefix scripts run one at a time first, then the independent groups up to `-n/--carto-concurrency` at a time, then the suffix once every group has succeeded.

**Projection override**
:   `export --projection-override EPSG:<code>`: tiles in a metres-based CRS other than Web Mercator (EPSG:3857). `init.sh` builds 3857, 3395 and 4087 by default, each other than 3857 in its own `<run dir>-<srs>` working directory.

**RBT**
:   Releasable Basemap Tiles: the tileset this repository's schema defines. It names `rbt-schema/`, the tileset's metadata (`"Releasable Basemap Tiles (RBT)"`), `init.sh`'s `RBT.mbtiles` bundles, the Postgres role and database `setup_ubuntu.sh` creates (`rbt`), and the GitHub organization.

**RBT Small**
:   A zoom-capped copy of the bundle, built from the same layer tiles with `bundler -z 8 -o rbt_small.mbtiles`. Give it its own `-o`, or it replaces `joined.mbtiles`.

**Run ID**
:   The `YYYY-MM-DD_HHMMSS` time a command started, which names its `logs/<run_id>/` folder. See [Working Directory](working-directory.md#logs).

**Schema directory**
:   The `-s/--schema-dir` every command reads its configuration from, normally `rbt-schema/`: OSM mappings, aux-data sources, `carto_sql/`, export layer configs and tile metadata. Commands never write to it.

**Tier**
:   One of the two documented host sizes: planet (48 vCPU, 384 GB) and small extract (8 vCPU, 32 GB). `setup_ubuntu.sh`'s `PG_TIER` picks the Postgres settings for one, and the CLI's worker defaults scale with the CPU count. See [Performance & Sizing](../install/performance.md).

**`tippecanoe`, `tile-join`**
:   The C++ tools that build each layer's MBTiles from its FlatGeobuf, and join layer MBTiles into one.

**Vundler**
:   The `vundler` command, which converts `bundled/joined.mbtiles` into a **Compact Cache V2** tree at `bundled/vundled/p12/` by running `abt-vundler`. See [Vundler](../pipeline/vundler.md).

**Working directory**
:   The `-w/--working-dir` every command writes its downloads, intermediate files, tiles and logs into. See [Working Directory](working-directory.md).
