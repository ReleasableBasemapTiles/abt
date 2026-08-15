# SQL / PostGIS View Schema Comparison

**Side A:** `rbt-schema` (this repository) — `carto_sql/`, output namespace `export.*`
**Side B:** `rbt-data-generator` ([docs](https://mjj203.github.io/rbt-data-generator/), source: `github.com/MJJ203/rbt-data-generator`) — output namespace `rbt.*`
**Scope:** View and table definitions, output columns, attribute-value classification logic, zoom/rank attributes, geometry handling, schema namespaces. Data schemas only — not code, tooling, or execution flow.
**Method:** Source-to-source comparison. The reference repository was cloned, so findings are file-level rather than documentation-derived. Reference-side citations are given as repo-relative paths against `https://github.com/MJJ203/rbt-data-generator` at branch `main`.
**Date:** 2026-07-29

Part 2 of 4. See `README.md` in this directory for the consolidated cross-layer analysis.

---

# Data Schema Comparison: `rbt-schema` (Side A) vs `rbt-data-generator` (Side B)

**Evidence basis:** Both sides were read from **actual SQL source files**, not documentation. The reference repo cloned successfully (`git clone https://github.com/MJJ203/rbt-data-generator.git`, branch `main`), so every Side B claim below is backed by a file path and line, not the docs site. The only Side B artifact I treated as authoritative-but-non-SQL is `config/layers.yml`, which is the repo's own declared "single source of truth for layer definitions" and enumerates exactly which `rbt.*` views feed tiles.

**Files read**

| Side | Paths |
|---|---|
| A | `carto_sql/*.sql` (all 32 files + `031_building.sql.skip`), `carto_sql/static_data/ne_physical_centerlines.sql`, `export/*.json` (58), `import/osm/*.yml`, `import/aux_data/*.json`, `scripts/overture/*.sh` |
| B | `setup/data-sources/schemas/physical/{physical-core,landcover,water-features,terrain}.sql`, `setup/data-sources/schemas/cultural/{cultural-core,transportation,transportation-railway,infrastructure}.sql`, `setup/data-sources/overture/duckdb-building-export.sql`, `config/layers.yml` |

---

## 0. The single most consequential structural difference

Side B encodes zoom behavior **as separate database views**. Side A encodes it **as a column value on the row** (or pushes it entirely out of SQL into the tippecanoe filter).

Side B, `config/layers.yml:670-680`:

```yaml
landcover:
  rbt.landcover_z4: {target: landcover, minzoom: 4, maxzoom: 13}
  rbt.landcover_z6: {target: landcover, minzoom: 6, maxzoom: 13}
  rbt.landcover_z9: {target: landcover, minzoom: 9, maxzoom: 13}
  rbt.landcover_z10: {target: landcover, minzoom: 10, maxzoom: 13}
  rbt.landcover: {target: landcover, minzoom: 12, maxzoom: 13}
```

Side A instead materializes one view carrying a `z_level` integer, and the zoom logic moves to the layer JSON (`export/water_polygon.json`):

```json
"filter": { "*": [ "any",
  ["all", [">=", "$zoom", 0], ["<=", "$zoom", 4], ["==", "z_level", 1]],
  ["all", [">=", "$zoom", 5],  ["==", "z_level", 5]],
  ...
]}
```

Consequence for schema shape: Side B has **~30 extra `_zN` views** that simply don't exist in Side A (`highway_z4…z12`, `railway_z6`, `landcover_z4/6/9/10`, `landcover_labels_z4/6/9/10`, `geonames_hydrographic_z2…z10`, `populated_places_z3/z7/z9`, `utility_point_z6/z12`, `waterway_z8`, `contour_z8/10/12`, `contour_glacier_z8/10/12`, `building_z10/11/12`, `water_simplified`). Side A has **one `z_level` column** on `water_polygon`, `ocean_polygon`, `water_line`, `landcover_polygon`, and `landcover_label`, and nothing else.

---

## 1. View/table inventory diff

### 1.1 Namespaces

| | Side A | Side B |
|---|---|---|
| Output namespace | `export.*` (all **MATERIALIZED VIEWs**) | `rbt.*` (mix of `VIEW` and `MATERIALIZED VIEW`) |
| Staging namespaces | `water`, `landcover`, `landuse`, `transportation`, `infrastructure`, `aeroway`, `dam`, `poi` | mostly inside `rbt.*` itself; plus `utility`, `ourairports` |
| OSM input | `osm.osm_*` | `import.*` |
| Auxiliary input | `aux_data.*` (single schema) | `naturalearth.*`, `geonames.*`, `ourairports.*`, `mirta.*`, `overture.*`, `public.*` (multiple schemas) |

Verified created objects on Side A (`rg -o "CREATE ... [a-z_.]+" carto_sql/*.sql`): 66 `export.*` MVs, 7 `infrastructure.*`, 6 `aeroway.*`, plus `water.*`, `landcover.*`, `landuse.*`, `transportation.*`, `dam.*` staging tables. Zero `VIEW` objects — Side A is 100% materialized.

### 1.2 Renamed / mapped equivalents

Side A adopted a strict `<feature>_<geometry-type>` convention. Side B used ad-hoc suffixes (`_surface`, `_curve`, plural `_labels`, bare names).

| Side A (`export.*`) | Side B (`rbt.*`) | Change |
|---|---|---|
| `road_line` | `highway` | renamed |
| `rail_line` | `railway` | renamed |
| `transportation_station` | `railway_station` | renamed + generalized (`class` added) |
| `transportation_station_label` | `railway_station_label` | renamed |
| `yard_label` | `yard_label` | unchanged |
| `water_polygon` | `water` / `water_simplified` | 2 views collapsed to 1 + `z_level` |
| `ocean_polygon` | (inside `rbt.water`) | promoted to its own layer |
| `inland_water_intermittent_polygon` | `inland_water_intermittent` | renamed |
| `water_line` | `waterway` (+`waterway_z8`) | renamed |
| `hydrographic_label` | `geonames_hydrographic` (+`_enhanced`, +`_z2…z10`) | renamed, 11 views → 1 |
| `builtup_polygon` | `builtuparea` | renamed |
| `glacier_polygon` | `glacier` | renamed |
| `landcover_polygon` / `landcover_label` | `landcover` / `landcover_labels` | renamed |
| `park_polygon` | `park` | renamed |
| `physical_labels` | `mountain_label` | **replaced** (see §3.7) |
| `place_labels` | `populated_places` (+`_z3/_z7/_z9`) | renamed + expanded |
| `energy_polygon` / `energy_label` | `hydrocarbon_field` / `hydrocarbon_label` | **renamed domain concept** |
| `airport_polygon` | `aeroway_surface` | renamed |
| `airport_label` | `airports` | renamed |
| `heliport_point` | `heliports` | renamed |
| `runway_line` | `runway_curve` | renamed |
| `dam_line` / `dam_polygon` | `dam_curve` / `dam_surface` | renamed |
| `dam_label` | `dam_label` | unchanged |
| `port_polygon` | `port_surface` | renamed |
| `port_label` | `port_label` | unchanged |
| `lock_line` | `lock` | renamed |
| `lock_label` | `lock_label` | unchanged |
| `radar_label` | `radar_point` | renamed |
| `grain_polygon` / `grain_point` | `grain_srf` / `grain_srf_pnt` | renamed |
| `stadium_polygon` / `stadium_label` | `stadium_surface` / `stadium_labels` | renamed |
| `cemetery_polygon` | `cemetery` | renamed |
| `cemetery_label` | `cemetery_label` | unchanged |
| `us_military_installations_polygon` | `us_military_installations` | suffix added |
| `us_military_installations_label` | `us_military_installations_labels` | de-pluralized |
| `adm{0,1,2}_line` / `_label` | `adm{0,1,2}_lines` / `_labels` | de-pluralized |
| `power_station_polygon`, `pumping_station_polygon` | `power_station`, `pumping_station` | suffix added |
| `power_station_label`, `pumping_station_label` | same | unchanged |
| `utility_point`, `powerline_line`, `pipeline_line`, `ferry_line` | `utility_point`, `powerline`, `pipeline`, `ferry` | `_line` suffix added |

### 1.3 Present in Side A only

| Side A view | Source | Note |
|---|---|---|
| `export.road_polygon` | `osm.osm_highway_polygon` | pedestrian areas / platforms — **entirely new layer** |
| `export.pier_line`, `export.pier_polygon` | `osm.osm_pier_{linestring,polygon}` | pier / breakwater / groyne — new |
| `export.poi_point` | `osm.osm_poi_{point,polygon}` | new; new `poi` schema + `poi.classify()` |
| `export.culvert_point` | `osm.osm_water_point` | new |
| `export.ocean_polygon` | `aux_data.ne_50m_ocean` ∪ `water.valid_ocean` | ocean promoted to its **own export layer**; on Side B ocean lived inside `rbt.water` |
| `export.physical_labels` | `aux_data.ne_physical_centerlines` | replacement for `mountain_label`, different lineage |
| `landcover.dissolve_level` (procedure), `landcover.z4…z13` unlogged tables, `landcover.leveled`, `landcover.dissolve_jobs` | — | dissolve machinery has no Side B counterpart |
| `water.dissolve_src/pass1/touching`, `water.water_surface_clean`, `water.waterway_relation_union` | — | `water_surface_clean` exists on B as `rbt.water_surface_clean`, but the parallel `dblink` grid-dissolve tables are A-only |
| `transportation.usa_boundary`, `transportation.railway_normalized` | — | new staging layer |
| `dam.label_tmp_point_labels`, `dam.label_tmp_surface_points` | — | new label de-dup staging |
| `landuse.tmp_cemetery_ranked` | — | new |
| `aeroway.*` (6 MVs) | — | B kept the same pipeline but under `ourairports.*` / `import.*` |
| `public.ZRes(int)` | `carto_sql/001_set_schema.sql` | tile-resolution helper, A-only |

### 1.4 Present in Side B only

| Side B view | Removed from A | Evidence |
|---|---|---|
| `rbt.contour`, `rbt.contour_glacier`, `contour_z8/z10/z12`, `contour_glacier_z8/z10/z12` | **Entire terrain/contour domain gone.** No `contour`/`elevation`/`nth_line` anywhere in `carto_sql/` or `export/`. | `setup/data-sources/schemas/physical/terrain.sql:131` |
| `rbt.ne_water_label` | **Explicitly dropped** in A and folded into `hydrographic_label` | A: `DROP MATERIALIZED VIEW IF EXISTS export.ne_water_label CASCADE;` in `005a_water_polygon.sql`; B: `water-features.sql:912` |
| `rbt.mountain_label` | Replaced by `physical_labels` | `physical-core.sql:277` |
| `rbt.water_simplified` | Collapsed into `water_polygon.z_level` | `water-features.sql` |
| `rbt.water_surface_label` | No A equivalent | `water-features.sql` |
| `rbt.osm_ocean`, `rbt.osm_ocean_simplified`, `rbt.sound_ocean` | Reworked into `water.valid_ocean` + `export.ocean_polygon` | `water-features.sql` |
| `rbt.inland_water_intermittent_dissolved` | A has no dissolved variant of intermittent water | `config/layers.yml:693` |
| `rbt.building`, `building_z10/11/12` | A's equivalent is **disabled** (`031_building.sql.skip`, `export/building_polygon.json.skip`) | see §7.1 |
| `rbt.grain_all_points`, `rbt.grain_point` (as separate objects) | A merged into `infrastructure.grain_srf_pnt` → `export.grain_point` | `cultural-core.sql` |
| `utility.station` | A folded this into `export.utility_point` directly | `cultural-core.sql` |
| `rbt.ourairports_osm_aerodrome_runway_join` | A renamed to `aeroway.ourairports_osm_join` | `infrastructure.sql` |
| all `_zN` views (§0) | Replaced by `z_level` / JSON filters | `config/layers.yml` |
| `search_water_features_fuzzy`, `search_features_by_partial_name`, `find_similar_place_names` | Removed. A keeps only `classify_water_type` and `safe_simplify_geometry`. | `water-features.sql` |

### 1.5 Inventory self-consistency notes on Side A

Two naming drifts between the SQL objects and the layer configs, worth flagging since Side A layer JSON names map to `export.<layer_id>` by convention:

- SQL creates `export.adm0_line` / `export.adm0_label`; configs are `export/adm0_lines.json` / `adm0_labels.json` (same for adm1/adm2).
- SQL creates `export.transportation_station`; config is `export/transportation_station_polygon.json`.
- `export.sports_ground` and `export.golf_course` are created in `025_sports.sql` but have **no** `export/*.json`. Side B is symmetric here: `rbt.sports_ground` / `rbt.golf_course` exist in `cultural-core.sql` but are absent from `config/layers.yml`. Both sides treat these as DB-only.

---

## 2. Per-view column diffs

### 2.1 `export.road_line` vs `rbt.highway`

Side B (`transportation.sql`) emits 17 columns:
`osm_id, route_type, name, brunnel_name, name_len, subclass, ref, ref_len, ref_number, ref_number_len, ref_multi, brunnel, surface, lifecycle_type, lane, geom_len, geometry`

Side A (`003_road.sql:214-292`) emits 31:

```sql
base AS (
    SELECT
        osm_id, geometry, geom_len, brunnel, brunnel_name, subclass,
        name, name_en, name_len, ref, ref_len, ref_number,
        length(ref_number) AS ref_number_len, ref_multi,
        network, is_us, surface, lifecycle_type,
        CASE ... END AS route_type,
        lane, layer, level, service, access, toll, expressway,
        bicycle, foot, horse, is_oneway, is_ramp
    FROM enriched
)
```

**Added (14):** `name_en`, `network`, `is_us`, `layer`, `level`, `service`, `access`, `toll`, `expressway`, `bicycle`, `foot`, `horse`, `is_oneway`, `is_ramp`. **Removed:** none. Type change: `geom_len` is `::int` on A (`ST_Length(ST_Transform(h.geometry, 3857))::int`), `::real` on B.

Note `export/road_line.json` only declares 11 attributes and omits `network`, `is_us`, `layer`, `level`, `access`, `toll`, `is_oneway`, etc. — the MV is wider than the declared tile attribute set.

### 2.2 `export.rail_line` vs `rbt.railway`

Both carry the same core (`name, name_en, ref, voltage, frequency, network, service, usage, electrified, tracks, gauge, lifecycle_type, lifecycle_desc, subclass, geom_len, geometry, dps_type`). Side A adds `osm_id`, `brunnel`, `bridge_name`, `tunnel_name`, `layer`, `level`, `is_oneway`, `is_ramp`, and moves classification out into a dedicated staging MV `transportation.railway_normalized`, which Side B does not have (B computes everything inline in one 700-line view).

### 2.3 `export.hydrographic_label` vs `rbt.geonames_hydrographic_enhanced`

Side B (`cultural-core.sql:394-520`) emits:
`name, desig_cd, class, name_rank, display, osm_intersect, area, geometry`

with `area` computed as the feature's own area **plus** the area of every intersecting water polygon:

```sql
CASE WHEN w_intersect.water_area_sum IS NOT NULL THEN 'Y' ELSE 'N' END AS osm_intersect,
ST_Area(ST_Transform(h.geometry, 3857))::real + COALESCE(w_intersect.water_area_sum, 0) AS area,
...
LEFT JOIN LATERAL (
    SELECT SUM(ST_Area(ST_Transform(w.geometry, 3857))::real) AS water_area_sum
    FROM rbt.water w WHERE ST_Intersects(h.geometry, w.geometry)
) w_intersect ON true
```

Side A (`006_geonames_hydrographic.sql`) emits:
`name, name_en, desig_cd, class, name_rank, display, scalerank, min_label, geometry`

**Removed:** `osm_intersect`, `area` (and with them the whole `rbt.water` lateral-join dependency). **Added:** `name_en`, `scalerank`, `min_label`. The `class` CASE over `desig_cd` is essentially identical between the two (same ~120 GeoNames designation codes, same string outputs like `'bay(s)'`, `'intermittent wetland'`).

**Source-set change:** B reads only `geonames.hydrographic`. A unions four sources:

```sql
WITH geonames_hydro AS (... FROM aux_data.nga_geonames_hydrographic h WHERE h.nt IN ('N','C','D') ...),
     usgs_hydro     AS (... FROM aux_data.usgs_domestic_names u ...),
     ne_water       AS (... FROM aux_data.ne_10m_geography_marine_polys n ...),
     ne_lakes       AS (... FROM aux_data.ne_10m_lakes l ...),
     combined       AS (...)
```

This is why `rbt.ne_water_label` was dropped: its source (`ne_10m_geography_marine_polys`) is now a CTE inside `hydrographic_label`.

### 2.4 `export.place_labels` vs `rbt.populated_places`

Side B (`cultural-core.sql:787-798`) is a thin passthrough over an already-ranked import table:

```sql
CREATE VIEW rbt.populated_places AS
SELECT ne_id, NULLIF(name, '') as name, NULLIF(name_en, '') as name_en,
       NULLIF(class, '') as class, NULLIF(rank, '') as rank,
       NULLIF(capital, '') as capital, NULLIF(population, '') as population, geometry
FROM import.places
where class in ('city', 'town', 'village', 'hamlet');
```

Side A (`026_places.sql`) emits `osm_id, name, name_en, class, capital, rank, geometry` and **computes** the rank in SQL from a three-source join (OSM place nodes × GeoNames `desig_cd` × Natural Earth `rank_max`/`pop_max`):

```sql
COALESCE(
    CASE
        WHEN ne.rank_max >= 14                        THEN 1
        WHEN g.desig_cd = 'PPLC' AND ne.rank_max >= 13 THEN 1
        WHEN ne.rank_max = 13                          THEN 2
        WHEN g.desig_cd = 'PPLC'                       THEN 2
        WHEN o.capital = 'yes'                         THEN 2
        WHEN o.name_en ILIKE 'Brussels'                THEN 2
        ...
        WHEN g.display_max >= 5                        THEN 10
    END,
    CASE o.place WHEN 'city' THEN 10 WHEN 'town' THEN 10 ELSE 12 END
) AS rank
```

**Column diffs:** `ne_id` → `osm_id`; `population` **removed**; `capital` retyped from text passthrough to a derived integer 2–6:

```sql
CASE WHEN o.capital = 'yes' THEN 2
     WHEN o.capital IN ('2','3','4','5','6') THEN o.capital::int END AS capital
```

### 2.5 `export.airport_label` vs `rbt.airports`

Column lists are **identical** (27 columns: `airport_id, ident, runway_length_ft, runway_width_ft, runway_surface, runway_lighted, runway_closed, runway_le_ident, runway_le_heading, runway_he_ident, runway_he_heading, type, name, elevation_ft, continent, iso_country, iso_region, municipality, scheduled_service, icao, iata, local_code, osm_id_aerodrome, osm_id_runway, osm_aerodrome_area, category, rank, geometry`). The `runway_surface_mapping` vocabularies are also identical — both emit exactly the same 21 standardized codes (`ASP, BIT, BRI, CLA, COM, CON, COR, GRE, GRS, GVL, ICE, MAC, PER, PSP, SAN, SNO, TURF, U, UNPAVED, WAT, WOOD`) with the same 3 ILIKE patterns (`ALUM%→ALUM-DECK`, `%asphalt%→ASP`, `%concrete%→CON`).

Two real differences:

1. **A fixes a `category` operator-precedence bug.** Side B (`infrastructure.sql:939`) wrote `WHEN (a.osm_aerodrome_area < 2500000) OR (a.osm_aerodrome_area IS NULL AND (...runway conditions...)) THEN 2` — the runway conditions only apply to the `IS NULL` branch, so *any* airport with a small aerodrome polygon falls to category 2. Side A (`021_aeroway.sql:660-675`) re-parenthesizes so runway counts gate both cases: `WHEN (a.osm_aerodrome_area < 2500000 OR a.osm_aerodrome_area IS NULL) AND (b.l_runway_count = b.runway_count OR ...) THEN 2`. **The two sides emit different `category` values for the same airport.**
2. A adds a spatial guard on the OurAirports input, dropping null-island records: `WHERE NOT ST_Contains(ST_MakeEnvelope(-2,-2,2,2,4326), a.geometry)`. Side B has no such filter (`infrastructure.sql:1128` reads `FROM ourairports.airport` unfiltered).

### 2.6 `export.airport_polygon` vs `rbt.aeroway_surface`

Same 14 columns, but two schema-level differences:

- **`area` units differ.** B: `ST_Area(geometry) AS area` on 4326 geometry → **square degrees** (`infrastructure.sql:1065`). A: `ST_Area(ST_Transform(geometry, 3857))::real AS area` → **square meters** (`021_aeroway.sql:604`). Any downstream area threshold is incomparable across the two.
- **Source consolidation.** B unions `import.aerodrome_label_point WHERE ST_GeometryType(geometry) != 'Point'` with `import.aeroway_polygon`, and extracts `name_en`/`aerodrome_type` from hstore (`NULLIF((tags -> 'name:en'), 'NULL')`). A reads only `osm.osm_aeroway_polygon` with `name_en` promoted to a real column by the importer, so the hstore extraction disappears from SQL.
- **NULL sentinel changes.** B guards against the literal string `'NULL'` (`NULLIF(name, 'NULL')`); A guards against empty string (`NULLIF(name, '')`). Same for `rbt.runway_curve` vs `export.runway_line`. This is an importer-contract change reflected in every column of every view.

### 2.7 `export.runway_line` vs `rbt.runway_curve`

Same columns, one renamed and re-unitized: B `ST_Length(geometry) as length` (degrees), A `ST_Length(ST_Transform(geometry, 3857))::real AS length_m` (meters).

### 2.8 `export.pier_*`, `export.poi_point`, `export.culvert_point` — new column sets

```sql
-- 030_pier.sql
SELECT osm_id, NULLIF(name,'') AS name, class, subclass,
       CASE WHEN is_floating THEN true ELSE NULL END AS is_floating,
       ST_Area(ST_Transform(geometry, 3857))::real AS area, geometry
FROM osm.osm_pier_polygon
```

```sql
-- 033_culvert.sql
SELECT osm_id, NULLIF(name,'') AS name, NULLIF(name_en,'') AS name_en, subclass, geometry
FROM osm.osm_water_point
WHERE subclass = 'culvert' OR tunnel = 'culvert';
```

Note the `CASE WHEN <bool> THEN true ELSE NULL END` idiom on A: booleans are emitted as `true`-or-`NULL` rather than `true`/`false`, so the attribute is omitted from tiles when absent. Side B has no analogous pattern.

---

## 3. Classification / attribute-value diffs

These are the cases where the two schemas emit **different attribute values for the same real-world feature**.

### 3.1 `energy_*` vs `hydrocarbon_*` — different classification mechanism entirely

Side B (`cultural-core.sql`) classified hydrocarbon facilities by **fuzzy name matching** using `pg_trgm` indexes over `import.builtup_area` names. Side A (`014_energy.sql`) classifies from **OSM tags** on `osm.osm_utility_polygon` + `osm.osm_landuse_polygon`, emitting an explicit subclass vocabulary (`oil_terminal`, `oil_refinery`, `oilfield`, …) via a `CASE` on tag values. Same real-world refinery can therefore land in a different `subclass` on each side, and the layer name changed too (`hydrocarbon_field` → `energy_polygon`).

### 3.2 Water type vocabulary — same function, different placement

Both sides define `classify_water_type(text)` in PL/pgSQL with the same controlled vocabulary (`basin, canal, ditch, dock, drain, lake, pond, reservoir, river, stream, ocean, …`). A namespaces it as `water.classify_water_type` (`005a_water_polygon.sql`), B leaves it unqualified in the default schema (`water-features.sql`). Same for `safe_simplify_geometry`. **No value-level divergence found here.**

Where they *do* diverge is intermittency. Side A splits on it explicitly at the polygon level:

```sql
-- water.water_surface: permanent only
WHERE intermittent = 'f'
-- export.inland_water_intermittent_polygon: seasonal only
WHERE intermittent = 't' OR <subclass indicates intermittency>
```

Side B carried `intermittent` through `rbt.waterway` as a passthrough column and had a separate `rbt.inland_water_intermittent`, but `rbt.water` did not exclude marine types the way A's `water.water_surface_clean` does ("marine types excluded" before the grid dissolve). Result: **ocean/sea polygons appear in `rbt.water` on B but are routed to a dedicated `export.ocean_polygon` on A.** A feature tagged `natural=water` + `water=ocean` gets a different layer assignment on each side.

### 3.3 Road `route_type` — same vocabulary, different gating

Both emit `Interstate`, `Interstate Business`, `Interstate Other`, `US Hwy`, `US Hwy Business`, `US Hwy Other`, `State Hwy`, `State Hwy Business`, `State Hwy Other`, `Other`, `NULL`. But Side A introduces two new gate columns that change *when* a route_type is assigned at all:

```sql
(hf.id IS NOT NULL) AS in_usa,
(hf.id IS NOT NULL)
    OR hr.network LIKE 'US:%'
    OR h.network LIKE 'US:%'
    OR NULLIF(TRIM(h.ref), '') ~ '^(I |US |[A-Z]{2} )'  AS is_us,
...
CASE WHEN is_us AND NOT ref_multi THEN ... 
     WHEN in_usa OR rel_network LIKE 'US:%' THEN 'Other'
     ELSE NULL END AS route_type
```

`in_usa` comes from a spatial join against a new A-only staging table `transportation.usa_boundary`. Side B had no US-boundary table, so a US highway whose `ref` doesn't match the regex and whose relation network is absent would get `NULL` on B but `'Other'` on A.

### 3.4 Road `surface` — normalized vocabulary on A

Side A normalizes free-text OSM `surface` into 4 values (`003_road.sql:171-177`):

```sql
CASE
    WHEN h.surface IS NULL OR TRIM(h.surface) = '' THEN 'paved_unknown'
    WHEN lower(h.surface) ~ '(asphalt|asfalt|tarmac|concrete|cement|cobblestone|sett|paving_stone|brick|...)'
         OR h.surface ~* 'tar.*road' THEN 'paved'
    WHEN lower(h.surface) ~ '(unpaved|dirt|gravel|sand|earth|mud|grass|ground|clay|soil|compacted|...)' THEN 'unpaved'
    ELSE 'unknown'
END AS surface
```

Side B derived surface via a separate `import.highway_surface_subclass` materialized view. Same intent; the A version is inline and the enumerated output is explicitly 4-valued, including a distinct `'paved_unknown'` for missing tags (rather than `NULL`).

### 3.5 Road `lifecycle_type` — expanded vocabulary on A

A emits `construction, proposed, planned, destroyed, demolished, razed, removed, disused, abandoned` and additionally detects lifecycle **prefix tags** from hstore, which B did not:

```sql
WHEN NULLIF(h.tags->'demolished:highway','') IS NOT NULL
  OR NULLIF(h.tags->'demolished','')         IS NOT NULL  THEN 'demolished'
WHEN NULLIF(h.tags->'razed:highway','')      IS NOT NULL  THEN 'razed'
```

A road tagged `demolished:highway=residential` gets `lifecycle_type='demolished'` on A and no lifecycle value on B.

### 3.6 POI classification — A-only vocabulary

`032_poi.sql` introduces a new `poi` schema and an immutable classifier that is the entire definition of the layer's `class`:

```sql
CREATE OR REPLACE FUNCTION poi.classify(subclass text, mapping_key text)
RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
SELECT CASE
    WHEN subclass = 'hospital'                  THEN 'hospital'
    WHEN subclass = 'police'                    THEN 'police'
    WHEN subclass = 'fire_station'              THEN 'fire_station'
    WHEN subclass IN ('school','kindergarten')  THEN 'school'
    WHEN subclass IN ('university','college')   THEN 'college'
    WHEN subclass = 'townhall'                  THEN 'townhall'
    WHEN subclass = 'courthouse'                THEN 'courthouse'
    WHEN subclass = 'public_building'           THEN 'public_building'
    WHEN subclass = 'diplomatic'                THEN 'diplomatic'
    WHEN subclass = 'place_of_worship'          THEN 'place_of_worship'
    ELSE NULL
END; $$;
```

Enumerated `class` values: 10. No Side B counterpart.

### 3.7 `physical_labels` vs `mountain_label` — different features, different geometry, different name columns

This is the largest single-layer replacement.

Side B (`physical-core.sql:277-337`) derived label lines from **polygon medial axes** of `naturalearth.ne_10m_geography_regions_polys` using SFCGAL, keeping the longest segment per feature, and carried **28 language name columns**:

```sql
CREATE MATERIALIZED VIEW rbt.mountain_label AS
WITH medial_axis AS (
    SELECT featurecla, label, max_label, min_label, name,
           name_ar, name_bn, name_de, name_el, name_en, name_es, name_fa,
           name_fr, name_he, name_hi, name_hu, name_id, name_it, name_ja,
           name_ko, name_nl, name_pl, name_pt, name_ru, name_sv, name_tr,
           name_uk, name_ur, name_vi, name_zh, name_zht,
           namealt, ne_id, region, scalerank, subregion,
           CG_ApproximateMedialAxis(geometry) as medial_geom
    FROM naturalearth.ne_10m_geography_regions_polys
    ...
```

Side A (`029_physical_labels.sql`) reads a **pre-computed static centerline table** and exposes 7 columns:

```sql
CREATE MATERIALIZED VIEW export.physical_labels AS
SELECT NULLIF(name,'') AS name, NULLIF(name_en,'') AS name_en,
       NULLIF(featurecla,'') AS featurecla, scalerank, min_label, max_label, geometry
FROM aux_data.ne_physical_centerlines
WHERE NULLIF(name,'') IS NOT NULL;
```

Differences that matter:

- **Feature domain changed.** B labeled mountain/geography *regions*. A's static table is `ne_10m_rivers_lake_centerlines` — 460 features, per its own header: *"Natural Earth ne_10m_rivers_lake_centerlines (static, bundled). 460 features."* These are **river/drainage** labels, not mountain labels. The two layers do not describe the same real-world features.
- **Name column set collapsed from 28 to 2** (`name`, `name_en`). The underlying static table still *stores* 25+ `name_XX` columns (`carto_sql/static_data/ne_physical_centerlines.sql:25-45`) but the export view does not project them.
- **Removed columns:** `label`, `namealt`, `ne_id`, `region`, `subregion`, `segment_length`, plus the 26 non-English name columns. **Added:** `max_label` is retained; `elevation` (declared as an int attr in B's `layers.yml:491`) is gone.
- **SFCGAL dependency removed** — `CG_ApproximateMedialAxis` no longer appears anywhere on Side A.

### 3.8 `transportation_station` generalization

Side A adds a `class` column alongside `subclass` and drops the railway-specific naming, so bus/ferry/tram stations can share the layer:

```sql
-- 004_railway.sql: export.transportation_station / _label
SELECT osm_id, class, subclass, name, platforms, operator, station, service, area, geometry
```

Side B's `rbt.railway_station` had no `class`. Same station node can therefore carry an extra classifying attribute on A.

### 3.9 Small but real: hardcoded exception removed

Side B's `rbt.railway` contained a hardcoded feature exception for the *Francis Scott Key Bridge* (`transportation-railway.sql`). No such literal exists in `carto_sql/004_railway.sql`. Side A's `026_places.sql` has its own hardcoded literals instead (`o.name_en ILIKE 'Brussels' THEN 2`, `o.name_en NOT ILIKE 'Irvine'`).

---

## 4. Zoom / scale-rank / filtering attributes

### 4.1 `z_level` — the new A-only attribute

Present on 5 Side A views. Derived from area or length, e.g. `export.water_polygon`:

```sql
-- z_level derived from projected area, combining NE lakes with dissolved OSM water
CREATE MATERIALIZED VIEW export.water_polygon AS
SELECT ... , <CASE over area> AS z_level, geometry
FROM aux_data.ne_50m_lakes ... UNION ALL ... FROM water.water_surface_clean ...
```

and `export.water_line` derives it from `geom_len` plus subclass. `export.landcover_polygon` / `landcover_label` derive it from `area` over `landcover.leveled`. There is **no `z_level` column anywhere in Side B.**

### 4.2 Ranking attributes

| Attribute | Side A | Side B |
|---|---|---|
| `rank` on places | derived 1–12 from NE `rank_max`/`pop_max` + GeoNames `desig_cd` in SQL | passthrough `import.places.rank` |
| `rank` on airports | `CASE WHEN type='closed' THEN 2 ELSE 1 END` | identical |
| `rank` on heliports | 1–4 from `type` × `hospital` | identical |
| `rank` on islands | area-bucketed 5/6/7 (`ST_Area(geometry::geography) >= 1e8 → 5`) | absent (no island features) |
| `rank` on island groups | `scalerank + 1` from NE | absent |
| `scalerank`, `min_label`, `max_label` | on `physical_labels`; `scalerank`/`min_label` newly added to `hydrographic_label` | on `mountain_label` only |
| `rank`, `overlap`, `contained` on ports | `infrastructure.port_surface_enhanced` (`ST_ClusterWithin` + `RANK() OVER (PARTITION BY osm_id ORDER BY area DESC)`) | `rbt.port_surface_enhanced`, same logic |
| `area` on hydrographic labels | **removed** | present, used as the zoom filter key |
| `category` 1–4 on airports | present, **different precedence** (§2.5) | present |
| `name_rank`, `display` | both sides | both sides |
| `elevation`, `nth_line`, `negative` | absent (contours gone) | on `rbt.contour*` |

### 4.3 Thresholds baked into views

Both sides bake `osm_aerodrome_area >= 2500000` and runway-length buckets (`>4000`, `1500..4000`, `<1500` ft) into the airport `category`. Side A adds new SQL-level thresholds absent on B:

- `WHERE area >= 1` in the Overture shard step (drops sub-meter polygons) — `scripts/overture/shard.sh:39`
- Island rank buckets at `1e8` / `1e7` m² (geography, not 3857) — `026_places.sql`
- Landcover simplification tolerance per zoom via `ST_SimplifyVW` across `landcover.z13_source` → `z4_simplified`

Side B's thresholds that vanished from A's SQL: the hydrographic `area >= 12417500000 … >= 11804400` ladder became a tippecanoe filter in A (`export/hydrographic_label.json`), and the building `area` ladder moved from `rbt.building_z10/11/12` views into `scripts/overture/tile.sh` filter JSON with **different values** — B used `5000/2500/1500`, A uses `40000/6400` (`tile.sh:26-27`).

---

## 5. Geometry handling in the schema

Fundamentally the same model, with A adding a normalization pass.

| Aspect | Side A | Side B |
|---|---|---|
| Storage SRID | 4326 everywhere, enforced by a dedicated normalization step | 4326, assumed |
| Column name | `geometry`, enforced by rename | `geometry` by convention |
| Metric SRID | `ST_Transform(..., 3857)` for area/length | mostly 3857; **but `rbt.aeroway_surface` uses `ST_Area(geometry)` and `rbt.runway_curve` uses `ST_Length(geometry)` on 4326 — degree units** |
| Multiple projections materialized? | **No.** One 4326 geometry per view. | **No.** 3857/3395/4326 are tile-generation outputs (`config/layers.yml:780-798`), not stored columns. |
| Point derivation for labels | `ST_PointOnSurface(ST_MakeValid(geometry))::geometry(Point, 4326)` | `ST_PointOnSurface(geometry)::geometry(Point, 4326)` — no `ST_MakeValid` |
| Validity | `water.safe_simplify_geometry()` + explicit `ST_MakeValid` at label sites; `water.valid_ocean` subdivided | `safe_simplify_geometry()` only |
| Indexes | GIST on `geometry` for essentially every export MV; BTREE on `subclass`/`class`/`area`/`rank`; partial BTREEs `WHERE <col> IS NOT NULL`; one UNIQUE (`idx_road_line_osm_id`) | GIST + BTREE, `CREATE INDEX CONCURRENTLY` in terrain.sql; `pg_trgm` GIN indexes on `import.builtup_area` tags for fuzzy classification |

Side A adds two normalization scripts with no Side B analogue — `000_update_aux_geom.sql` (for `aux_data`) and `099_update_geometry.sql` (for `export`) — which rename any geometry column to `geometry`, reproject 3857 → 4326, and create the GIST index. This makes the "4326 + `geometry`" contract enforced rather than conventional.

Side A also drops `pg_trgm`-based fuzzy geometry/name matching from the classification path (used by B for hydrocarbon and yard-size classification), reducing the extension surface to `hstore`, `postgis`, and `dblink` (the last used only by A's parallel dissolve workers).

---

## 6. Schema namespaces & naming conventions

- **`abt_` prefix: absent from both sides.** `rg -ni "abt_"` returns zero matches in `/Users/jonesmj/github/RBT/rbt-schema` (excluding `.git`) and zero across the reference repo checkout. The referenced commit ("Removed abt_ prefix from metadata.py") is fully applied; `tile-metadata/metadata.py` carries no such prefix, and the reference never used one. No residual `abt_`-prefixed table, view, column, or layer id exists on either side.
- **`carto.` schema: does not exist on either side.** The name only appears as the *directory* `carto_sql/` on Side A.
- **`aux.` vs `aux_data.`:** Side A consolidates every non-OSM input into a single `aux_data` schema (`aux_data.ne_50m_ocean`, `aux_data.nga_geonames_hydrographic`, `aux_data.usgs_domestic_names`, `aux_data.ourairports_airports`, `aux_data.mirtalocations_a`, `aux_data.dos_lsib`, `aux_data.fieldmaps_admX_*`, `aux_data.ne_physical_centerlines`). Side B scattered the same data across `naturalearth`, `geonames`, `ourairports`, `mirta`, `overture`, `fieldmap`, `public`. **This is the biggest namespace change.**
- **`osm.` vs `import.`:** Side A uses `osm.osm_<feature>_<geomtype>` (`osm.osm_highway_linestring`, `osm.osm_water_polygon`, `osm.osm_utility_point`). Side B used `import.<feature>` (`import.highway`, `import.water`, `import.utility_stations_label`). A's names encode geometry type; B's did not.
- **Output namespace:** `export.*` (A) vs `rbt.*` (B). The "curated set of `rbt.*` views" language from the reference docs no longer applies to Side A at all.
- **Layer naming convention:** A is systematic — `<feature>_{polygon,line,point,label}`. B was not (`_surface`, `_curve`, bare, plural). See the mapping table in §1.2. Three A-side drifts from its own convention are noted in §1.5.
- **Staging convention:** A introduces per-domain staging schemas (`water`, `landcover`, `landuse`, `transportation`, `infrastructure`, `aeroway`, `dam`, `poi`) so intermediates never pollute the output namespace. B put intermediates in `rbt.*` alongside outputs (`rbt.water_surface`, `rbt.port_surface_enhanced`, `rbt.geonames_hydrographic_enhanced`), which is why B's `layers.yml` needs an explicit allow-list to distinguish tile sources from intermediates.
- **Materialization:** A = 100% `MATERIALIZED VIEW` for exports. B = mixed; e.g. `rbt.airports`, `rbt.aeroway_surface`, `rbt.heliports`, `rbt.runway_curve`, `rbt.populated_places`, `rbt.ne_water_label`, `rbt.waterway`, all `adm*`, and all `_zN` views are plain `VIEW`s. This changes the physical shape of the schema (indexes can exist on A's exports; on B's plain views they cannot).

---

## 7. Layers/attributes existing on one side only

### 7.1 Overture buildings — present on both, but not as PostGIS views on either

Neither side shapes buildings in PostGIS. Side B does it in **DuckDB** (`setup/data-sources/overture/duckdb-building-export.sql:36-80`):

```sql
CREATE OR REPLACE TABLE rbt_building AS
SELECT b.id, b.names.primary AS name, b.subtype, b.class, b.has_parts, b.height,
       ST_Area(ST_Transform(b.geometry, 'EPSG:4326', 'EPSG:3857')) AS area, b.geometry
FROM read_parquet(... 'theme=buildings/type=building/*' ...) b
LEFT JOIN (SELECT DISTINCT building_id FROM read_parquet(... 'type=building_part/*' ...)) bp
  ON b.id = bp.building_id;

CREATE OR REPLACE TABLE rbt_building_label AS
SELECT id, name, subtype, class, has_parts, height, area,
       ST_PointOnSurface(geometry)::geometry(Point,4326) as geometry FROM rbt_building;

CREATE OR REPLACE VIEW rbt_building_z10 AS SELECT * FROM rbt_building WHERE area >= 5000;
CREATE OR REPLACE VIEW rbt_building_z11 AS SELECT * FROM rbt_building WHERE area >= 2500;
CREATE OR REPLACE VIEW rbt_building_z12 AS SELECT * FROM rbt_building WHERE area >= 1500;
```

Side B *also* has a commented-out PostGIS path in `cultural-core.sql:806-829` (`-- CREATE TABLE rbt.building AS ... FROM overture.building b LEFT JOIN overture.buildingpart bp`) that would have carried `names`, `level`, `num_floors` — never enabled.

Side A does it in DuckDB too (`scripts/overture/shard.sh:26-39`), with three schema differences:

```sql
SELECT id, names.primary AS name, subtype, class, has_parts, height,
       ST_Area_Spheroid(geometry) AS area,      -- true ground area, m^2 (not 3857)
       ST_Multi(geometry)         AS geometry   -- uniform MultiPolygon
FROM read_parquet('${infile}')
WHERE area >= 1
```

**Differences:** `ST_Area_Spheroid` (true geodetic m²) vs `ST_Transform`-to-3857 (Mercator-inflated m²) — these disagree by a latitude-dependent factor, so `area` is not comparable across sides; `ST_Multi` normalization is A-only; `area >= 1` degeneracy filter is A-only; and A drops `rbt_building_label` entirely (no building label point layer). A has no `_zN` variants; thresholds moved to `scripts/overture/tile.sh` and changed to `40000/6400`.

Separately, A's **PostGIS** building layer is disabled: `carto_sql/031_building.sql.skip` and `export/building_polygon.json.skip`. Its content is a 3-column MV:

```sql
CREATE MATERIALIZED VIEW export.building_polygon AS
SELECT osm_id, ST_Area(ST_Transform(geometry, 3857))::real AS area, geometry
FROM osm.osm_building_polygon;
```

Note this OSM-derived variant carries **no** `name`, `class`, `subtype`, `height`, or `has_parts` — it is not a drop-in for the Overture layer.

### 7.2 A-only data sources

| Source table | Consumed by | Side B equivalent |
|---|---|---|
| `aux_data.usgs_domestic_names` | `export.hydrographic_label` (US domestic names, where NGA defers to USGS/BGN) | **none** |
| `aux_data.ne_10m_lakes` | `export.hydrographic_label`, `export.water_polygon` | partial (`rbt.water` only) |
| `aux_data.dos_lsib` | `027_admin.sql` — LSIB recognition filtering for adm0 | **none** |
| `aux_data.ne_physical_centerlines` (bundled static, 460 features) | `export.physical_labels` | **none** |
| `aux_data.ne_10m_geography_regions_polys` filtered to `featurecla = 'Island group'` | `export.place_labels` island groups | used by B for `mountain_label`, different purpose |
| `osm.osm_island_polygon`, `osm.osm_island_point` | `export.place_labels` island features | **none** |
| `osm.osm_pier_linestring`, `osm.osm_pier_polygon` | `export.pier_*` | **none** |
| `osm.osm_poi_point`, `osm.osm_poi_polygon` | `export.poi_point` | **none** |
| `osm.osm_water_point` | `export.culvert_point` | **none** |
| `osm.osm_highway_polygon` | `export.road_polygon` | **none** |
| `transportation.usa_boundary` | road `in_usa` / `is_us` | **none** |

### 7.3 Present on both

`aux_data.mirtalocations_a` (DISDI MIRTA) → `export.us_military_installations_{polygon,label}` on A; `mirta.us_military_installations` → `rbt.us_military_installations{,_labels}` on B. Same dataset, same two-layer split, renamed schema and de-pluralized label view. Grain storage exists on both. OurAirports exists on both. Natural Earth `ne_50m_ocean`, `ne_10m_admin_0_countries`, `nga_geonames_administrative_regions`, `fieldmaps_admX_*` exist on both.

### 7.4 B-only domain

**Terrain/contours.** `rbt.contour` and `rbt.contour_glacier` with `elevation`, `nth_line`, `negative` columns and 6 zoom views (`terrain.sql:131-140`), plus their `projections: [3857, 3395]` restriction. Nothing in Side A produces contour data, and no `export/*.json` declares a contour layer. This is a complete domain removal, not a rename.

### 7.5 Attributes added across many A views

Two patterns recur and are worth calling out as schema-wide, not per-layer:

- **`name_en` added broadly** — `hydrographic_label`, `road_line`, `road_polygon`, `culvert_point`, `poi_point`, `ferry_line`, `park_polygon`, `lock_*`, `place_labels`. Side B carried `name_en` on fewer views and often extracted it from hstore inline (`NULLIF((tags -> 'name:en'), 'NULL')`); on A it is a first-class importer-provided column.
- **`osm_id` added broadly** — e.g. `rail_line`, `yard_label`, `place_labels` (replacing `ne_id`). Side B omitted it on several views.
- **No `int_name`** on either side. Neither schema exposes an `int_name` column anywhere.

---

## 8. Confidence & evidence notes

**High confidence (read directly from SQL source on both sides):**

- All view/table names, column lists, and `CREATE` statements on both sides. Side B cloned successfully; nothing in this report relies on the docs site.
- `abt_` prefix absence on both sides — verified by exhaustive `rg -ni "abt_"` across both trees.
- Numbering gaps 002, 016, 031: `git log --diff-filter=D --name-only -- carto_sql/` returns **empty**, so 002 and 016 were **never committed** — they are reserved/unused slots, not removed layers. 031 is a **present-but-disabled** file (`031_building.sql.skip` + `export/building_polygon.json.skip`), which is a deliberate opt-out rather than a deletion.
- `rbt.ne_water_label` removal is confirmed by an explicit `DROP MATERIALIZED VIEW IF EXISTS export.ne_water_label CASCADE;` still present in `carto_sql/005a_water_polygon.sql` — i.e. Side A actively tears down the old object.
- The `category` precedence divergence (§2.5) and the degree-vs-meter `area`/`length` divergences (§2.6, §2.7) are read verbatim from both files and would produce measurably different tile attribute values.

**Medium confidence:**

- The Side B tile-source view list comes from `config/layers.yml`, which the file itself declares as the source of truth and which cross-checks cleanly against the `CREATE VIEW` statements in the four schema SQL files. I treated any `rbt.*` object defined in SQL but absent from `layers.yml` as an intermediate rather than an output.
- Column *types* are inferred from expressions (`::real`, `::int`, `ST_Area(...)`, `NULLIF(text,'')`) rather than read from a live catalog. Where a column is a bare passthrough (e.g. `layer`, `level`, `service` on `road_line`) its type depends on the importer YAML, which I read for column presence but did not fully type-map.
- Side A's `export/*.json` files declare no `source_table`, so the `layer_id` → `export.<view>` mapping is inferred by convention. That inference is what surfaces the three naming drifts in §1.5; if the consuming CLI (which lives outside this repo) applies an explicit mapping, those are non-issues.

**Flagged as not verifiable here:**

- Whether Side B's `import.*` tables carry `name_en`, `layer`, `level`, `access`, `toll`, `is_oneway` as real columns or only inside `tags` hstore. B's views read some of these from hstore, which suggests the importer differed, but I did not read B's importer mapping files. This affects how much of §7.5's "added attributes" is a *view* change versus an *importer* change.
- Row counts / actual emitted value distributions. Every classification claim is derived from reading `CASE`/`WHERE` logic, not from querying a populated database.
- Whether B's `import.places.rank` was itself computed by a comparable three-source ranking upstream. If so, §2.4's difference is a relocation of logic into SQL rather than a new ranking; the *emitted* rank values could still differ, but I cannot confirm the magnitude without B's importer.
