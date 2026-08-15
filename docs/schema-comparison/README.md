# Data Schema Comparison: `rbt-schema` vs `rbt-data-generator`

**Side A:** `rbt-schema` (this repository)
**Side B:** `rbt-data-generator` ([docs](https://mjj203.github.io/rbt-data-generator/), source: `github.com/MJJ203/rbt-data-generator`)
**Scope:** Data schemas at three boundaries — imposm3 import, PostGIS/SQL views, and tippecanoe/MVT tile output. Deliberately excludes differences in code, tooling, CLI design, orchestration, and execution flow.
**Method:** Source-to-source comparison. The reference repository is public and was cloned, so findings are file-level rather than derived from documentation prose.
**Date:** 2026-07-29

## Contents

| Document | Boundary | Side A artifacts | Side B artifacts |
|---|---|---|---|
| `README.md` (this file) | Consolidated cross-layer analysis | — | — |
| `01-imposm-import-schema.md` | OSM + auxiliary import | `import/osm/*.yml` (38), `import/aux_data/*.json` (24) | `setup/data-sources/osm/imposm-mapping.yaml` (29 tables), `src/rbt/importers/` |
| `02-sql-view-schema.md` | PostGIS transformation | `carto_sql/*.sql` (33) | `setup/data-sources/schemas/{physical,cultural}/*.sql` |
| `03-tile-output-schema.md` | MVT tile output | `export/*.json` (58), `tile-metadata/` | `config/layers.yml` |

---

## The headline

This is not the reference schema with drift. It is a deliberate rebuild that shares clear lineage — the same OurAirports runway-surface vocabulary, the same `dps_type` styling key, the same railway service filter, and both projects independently abandoned the same two layers (`sports_ground`, `golf_course`). But at every one of the three boundaries the data contract has been re-cut: the imposm tables are renamed and re-typed, the output namespace moved from `rbt.*` to `export.*`, and the tile attribute payloads narrowed by a factor of two to six.

The direction of change is consistent across all three layers. This repository trades the reference's breadth for explicitness: fewer attributes in tiles but declared types on all of them, one geometry per view instead of ~30 zoom-variant views, systematic naming instead of ad-hoc suffixes, and staging schemas that keep intermediates out of the output namespace. What it gives up is the entire terrain/contour domain, localized name columns, and three projections.

---

## 1. Namespace and naming: the whole addressing scheme changed

| Boundary | This repo | Reference |
|---|---|---|
| OSM import | `osm.osm_highway_linestring` | `import.highway` |
| Auxiliary data | single `aux_data` schema | `fieldmap`, `geonames`, `naturalearth`, `ourairports`, `mirta`, `overture` |
| Tile-ready output | `export.*`, 66 materialized views | `rbt.*`, mixed views and matviews |
| Tile layer names | `dam_polygon` / `dam_line` / `dam_label` | `dam_surface` / `dam_curve` / `dam_label` |

Two details matter beyond the renames. First, this repository carries the imposm prefix twice — schema `osm` *and* imposm's default `osm_` table prefix — producing the stuttering `osm.osm_*` form, where the reference suppresses it with `?prefix=NONE`. Second, this repository's naming is genuinely more systematic: `<theme>_<geometry>` throughout, versus the reference's mix of bare names (`water`), `_surface`/`_curve`, and inconsistent pluralization (`stadium_surface` paired with `stadium_labels`).

The reference also has an internal inconsistency this repository avoids: its 3857 and 4326 backends emit *different layer names* for the same data (`grain_srf` vs `grain_elevator_srf`, `ne_water_labels` vs `ne_water_label`).

The `abt_` prefix is absent from both sides; the reference never used one.

---

## 2. Tag capture narrowed from catch-all to allow-list

This is the largest semantic difference in the import layer. The reference maps `amenity: __any__`, `shop: __any__`, `power: __any__`, `man_made: __any__` and similar; this repository replaces those with curated explicit lists — roughly 50 `amenity` values, ~100 `shop`, ~90 `sport`, five specific `power` values.

The effect is a large reduction in both row count and `subclass` cardinality. Anything keyed on an unenumerated value now returns zero rows.

Alongside that, this repository splits landuse into two tables (`builtup_area` keeps the settled footprint; a new `landuse_polygon` takes the institutional/cemetery/military/harbour classes), adds `islet` to islands, adds golf features to parks, and adds pedestrian-area, pier, and POI-polygon surfaces the reference has no way to produce.

---

## 3. Column-level divergence

Two systematic renames break every downstream reference: booleans gained an `is_` prefix (`tunnel`→`is_tunnel`, `intermittent`→`is_intermittent`, `seasonal`→`is_seasonal`), and `lane`→`lanes`. The rename is incomplete — `water_polygon` kept the unprefixed `intermittent` while `water_point` renamed it, so the same concept uses two conventions within one theme.

The reference's `name_de` columns were dropped from the six place tables. German names remain reachable through the `tags` hstore *in principle*, but see §9 — that fallback may not actually work here.

Two type changes warrant attention. `ele` and `height` moved from `string` to `integer` on `utility_point`, `mountain_point`, and `aeroway_point`. OSM values routinely carry units (`1200 m`, `35 ft`), which imposm's integer type discards as NULL rather than preserving. It is also now inconsistent: `aeroway_polygon.ele` and `aeroway_linestring.ele` remain `string`.

Notably, the SQL views moved in the *opposite* direction from the tiles. `export.road_line` emits 31 columns against the reference's 17 (adding `network`, `is_us`, `layer`, `level`, `access`, `toll`, `bicycle`, `foot`, `horse`, and more), yet `export/road_line.json` whitelists only 11 attributes for tiles. The schema got wider in the database and narrower at the tile boundary.

---

## 4. Zoom logic moved from schema structure into row data

The reference encodes zoom as ~30 separate views — `highway_z4` through `z12`, `landcover_z4/6/9/10`, `geonames_hydrographic_z2` through `z10`, `building_z10/11/12`, `water_simplified`. This repository collapses all of that into a single `z_level` integer column on five views (`water_polygon`, `ocean_polygon`, `water_line`, `landcover_polygon`, `landcover_label`), with zoom selection pushed into per-layer tippecanoe filter expressions.

`z_level` has no counterpart on the reference side, and it is queryable in the tiles. Related label-stepping keys (`min_label`, `scalerank`) were added to `hydrographic_label` and `physical_labels`, replacing the reference's `area`-threshold filtering.

Actual zoom windows agree on only 6 of ~48 mappable layers. Maxzoom is 13 everywhere on both sides; all divergence is in minzoom. The dominant pattern here is a hard z9 floor for 17 utility/infrastructure layers, where the reference spread the same layers across z6, z8, and z10. This repository also uses a z11–z13 detail band and a z12–13 band (piers, road polygons) that the reference never goes below z10 to reach. The largest single gap is parks: z9 here versus z3 in the reference.

---

## 5. Attribute payloads: explicit whitelist vs. everything

The reference passes no `-y` or `-x` to tippecanoe at all, so every column of every source view lands in its tiles — including `osm_id`, `fid`, staging helpers such as `area_part`/`contained`/`geom_len`, and raw hstore `tags` on five layers. This repository declares a typed allow-list per layer.

Illustrative widths: `pipeline_line` 2 attributes vs 20; `power_station_polygon` 2 vs 16; `physical_labels` 6 vs 38 (the reference passes through 25 localized `name_*` columns); `utility_point` 14 vs 32. Two layers here are geometry-only (`inland_water_intermittent_polygon`, `us_military_installations_polygon`), which the reference never does.

Type declarations conflict on several shared layers in ways that would break a client written against one side:

| Layer | Attribute | Here | Reference |
|---|---|---|---|
| `airport_label` | `rank`, `elevation_ft`, `runway_length_ft` | string | int |
| `airport_label` | `category` | float | int |
| `road_line` | `ref_len`, `ref_number_len` | float | int |
| `landcover_polygon` | `area` | int | real |
| buildings | `area`, `height` | int, int | float, float |

`dam_label` deserves a specific callout: this repository carries the two intersection flags but drops the feature `name`, while the reference carries `name` but drops `surface`. Those two label layers are mutually incompatible.

---

## 6. Attributes that are numerically incomparable

Three independent places where the same-named column means something different:

**Airport and runway geometry.** The reference computed `aeroway_surface.area` and `runway_curve.length` with `ST_Area`/`ST_Length` directly on 4326 geometry, yielding square and linear *degrees*. This repository transforms to 3857 first, giving meters, and renames to `length_m`. That is a correctness fix on this side, but no threshold tuned against one works against the other.

**Overture buildings.** This repository uses `ST_Area_Spheroid` (true geodetic m²); the reference uses `ST_Area` after transforming to 3857 (Mercator-inflated, off by roughly 1/cos²(latitude) — about 2× at 45°, 4× at 60°). Combined with different thresholds (z11 ≥40000 / z12 ≥6400 here, versus z10 >5000 / z11 >2500 / z12 >1500 there), the two building layers are comparable in neither units nor density. This is the most divergent layer pair in the comparison, and it also starts a full zoom later (11 vs 10).

**Airport `category`.** The reference's CASE had an operator-precedence error where runway conditions only gated the `IS NULL` branch, so any airport with a small aerodrome polygon fell to category 2. This repository re-parenthesizes it. Correct now, but the two pipelines assign different `category` values to the same airport.

---

## 7. What each side has that the other does not

**Removed here entirely:** the terrain/contour domain — `rbt.contour` and `rbt.contour_glacier` with `elevation`, `nth_line`, `negative` columns, six zoom views, and two tile layers. Nothing in `carto_sql/` or `export/` produces contour data. This is the largest thematic gap, and it is a removal rather than a rename. Also gone: `ne_water_label` (explicitly dropped and folded into `hydrographic_label`), `water_surface_label`, the fuzzy-search functions, and the reference's `continent_point` import table.

**Added here:** `ocean_polygon` as a standalone tile layer (the reference folds ocean into `water`, distinguished only by `subclass`), plus `road_polygon`, `pier_line`, `pier_polygon`, `culvert_point`, and `poi_point` with a new 10-value `poi.classify()` vocabulary. On the data-source side: DOS LSIB for adm0 recognition filtering, USGS DomesticNames, Natural Earth physical centerlines, and the MIRTA point layer. The reference adds six extra NGA GeoNames feature classes and a FieldMaps USA subset that this side lacks.

**Two layers changed what they describe.** `physical_labels` replaced `mountain_label`, but the reference derived label lines from medial axes of Natural Earth *geography regions* (mountain ranges) carrying 28 name columns, while this repository reads a bundled static table whose own header identifies it as `ne_10m_rivers_lake_centerlines` — 460 river/drainage features — projecting only `name` and `name_en`. Worth confirming this is intentional, since the layer name suggests broader physical coverage than rivers.

Similarly, `energy_polygon` replaced `hydrocarbon_field`, switching from `pg_trgm` fuzzy name matching to explicit OSM tag classification and broadening scope to mineshafts, so the same refinery can land in a different `subclass` on each side.

---

## 8. Projection and metadata

The reference emits three projections (3857/3395 via tippecanoe then `tile-join`, 4326 via GDAL MVT) with five layers restricted to two. Its 4326 output is a tile directory with a hand-written `metadata.json` carrying a completely different field set from its MBTiles — no `bounds`, no `center`, no `vector_layers`.

This repository appears to emit 3857 only, but that is an inference from three negatives: no projection field in any `export/*.json`, no `crs` in `tile-metadata/metadata.py`, and no `-s`/`-t_srs` anywhere in the repository. The schema files carry no projection information either way.

The metadata schemas are essentially disjoint — only `format: "pbf"` is common. This side is provenance-oriented (eight attribution links, a five-object `license` array, `tags`, `creators`, explicit `bounds` and `center`) and carries none of the reference's BTIS keys (`crs`, `tile_origin_upper_left_x/y`, `tile_dimension_zoom_0`, `btp_schema_version`, `changelog_url`). If BTIS compliance is a requirement, that is a concrete gap, and `metadata.py` already imports `sqlite3`, suggesting it targets the same MBTiles metadata table.

---

## 9. Open questions not closable from the repository alone

**SRID for the OSM import.** The reference pins `osm_srid: 4326` explicitly. Nothing in this repository declares an SRID — there is no imposm config file and no CLI wrapper, so the value comes from an orchestrator outside the repository. Evidence leans toward 4326: the ubiquitous `ST_Area(ST_Transform(geometry, 3857))` idiom throughout `carto_sql/` only makes sense if stored geometry is 4326. But `099_update_geometry.sql` and `000_update_aux_geom.sql` also contain a defensive 3857→4326 reprojection, so verify the actual `-srid` flag rather than relying on inference. If it is absent, imposm defaults to 3857 and every geometry diverges from the reference.

**The global mapping header.** The reference declares `tags: load_all: true` and an `areas:` block listing `area_tags`/`linear_tags`. This repository's 38 per-table fragments have no assembling file, so neither exists here. Two consequences if the orchestrator does not inject them: `hstore_tags` columns will be far sparser than the reference's (which undercuts the `name:de` fallback in §3), and closed ways tagged `landcover`/`place`/`water`/`boundary` will not be promoted to polygons. Separately, 34 of the 38 fragments are indented two spaces while four (`aerialway_linestring`, `pier_linestring`, `pier_polygon`, `transportation_point`) start at column zero, so whatever concatenates them must normalize indentation.

**Whether `export/*.json` is consumed as assumed.** No code in this repository reads those files, so the `attributes[].name` → `-y` and `attributes[].type` → `-T` mapping is inferred from the shape of the data plus how `scripts/overture/tile.sh` uses those flags by hand.

---

## 10. Defects surfaced while diffing

Not schema-design differences, but they change what data actually lands, so they are separated out here.

**On this side:** the computed `area` column (`type: area`) was dropped from `transportation_polygon`, `utility_polygon`, and `utility_linestring`, and on the first was replaced by an unrelated `is_area` boolean read from the `area=yes` tag — so zoom-based area filters on those tables silently lost their input, and a similarly-named column now exists that a reader could mistake for the old one. Also:

- `utility_point`'s `generator_output` column name has a trailing space
- `shipway_linestring.layer` is declared with no `key:` and will always be NULL
- `fieldmaps_adm2_polygons.json` passes `-nlt MULTILINESTRING` on a polygon dataset
- `ourairports_runways.json` looks for `longitude_deg`/`latitude_deg` when the runways CSV exposes `le_longitude_deg`/`he_longitude_deg`, so runway geometry is likely empty
- three aux loads omit `aux_layer_name` and inherit shapefile basenames (`aux_data.lines`, `icesheet_polygons`, `mirtalocations_a`)
- `water_point` and `mountain_linestring` lost the reference's `require: name` guard despite being label-only tables

**On the reference side**, for context on how much of its schema is actually buildable: `rbt.building`'s DDL is commented out while `layers.yml` still registers it; `rbt.populated_places` queries a nonexistent `import.places` table; `dam_surface` references `filter_ref: utility`, applying a pole/tower subclass filter to dam polygons; and three `int_attrs` coercions target columns that do not exist.
