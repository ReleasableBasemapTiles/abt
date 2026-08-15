# Tile Output Schema Comparison: tippecanoe / MVT Layers

**Side A:** `rbt-schema` (this repository) — `export/*.json` layer configs, `tile-metadata/`
**Side B:** `rbt-data-generator` ([docs](https://mjj203.github.io/rbt-data-generator/), source: `github.com/MJJ203/rbt-data-generator`) — `config/layers.yml` declarative layer registry
**Scope:** MVT layer names, per-layer attribute sets and declared types, zoom windows, projections, tile metadata, feature filters. Data schemas only — not code, tooling, or execution flow.
**Method:** Source-to-source comparison. The reference repository was cloned, so findings are file-level rather than documentation-derived. Reference-side citations are given as repo-relative paths against `https://github.com/MJJ203/rbt-data-generator` at branch `main`.
**Date:** 2026-07-29

Part 3 of 4. See `README.md` in this directory for the consolidated cross-layer analysis.

---

# Tile-Output Schema Comparison: `rbt-schema` vs `rbt-data-generator`

## 0. Evidence base

**The reference clone succeeded**, so this is a source-to-source comparison, not a docs-based inference.

| Side | Artifact | Path / URL |
|---|---|---|
| A (local) | 58 active layer configs + 1 disabled | `/Users/jonesmj/github/RBT/rbt-schema/export/*.json`, `export/building_polygon.json.skip` |
| A | Source view DDL (attribute provenance) | `carto_sql/0*.sql` (creates `export.<layer_id>` matviews) |
| A | Tile metadata | `tile-metadata/metadata.py` |
| A | Standalone Overture buildings tiler | `scripts/overture/{fetch,shard,tile}.sh` |
| B (reference) | **Declarative layer registry (798 lines)** | `config/layers.yml` (reference repo) |
| B | Attribute sets (column lists per layer) | `setup/data-sources/schemas/{physical,cultural}/*.sql` (7,007 lines) |
| B | Command construction | `src/rbt/tiles/{tippecanoe,gdal_mvt,tile_join,btis,exporter}.py` |
| B | Buildings | `setup/data-sources/overture/duckdb-building-export.sql`, `docs/duckdb-buildings.md`, `docs/database-schema.md` |

---

## 1. The single most consequential difference: attribute whitelisting

This shapes every per-layer diff below, so it comes first.

**Side A declares an explicit, typed attribute allowlist per layer.** Every `export/*.json` carries an `attributes[]` array with `name` / `type` / `description`:

```5:34:export/adm0_labels.json
    "layer_id": "adm0_label",
    "description": "",
    "geometry_type": "point",
    "attributes": [
        {
            "name": "area",
            "type": "float",
```

**Side B passes no attribute include/exclude flags at all.** `build_tippecanoe_command` emits only `-T` type coercions — there is no `-y` or `-x` anywhere in `src/` or `config/`:

**Reference** — [`src/rbt/tiles/tippecanoe.py:45-56`](https://github.com/MJJ203/rbt-data-generator/blob/main/src/rbt/tiles/tippecanoe.py#L45-L56)

```python
    for option in layer.tippecanoe.options:
        cmd.append(option)

    for attr in layer.tippecanoe.int_attrs:
        cmd += ["-T", f"{attr}:int"]
    for attr in layer.tippecanoe.float_attrs:
        cmd += ["-T", f"{attr}:float"]
```

**Consequence:** every column of B's source view lands in the tile — including internal identifiers (`osm_id`, `fid`, `id`), staging/dedup helpers (`area_part`, `contained`, `overlap`, `geom_len`, `name_len`), and raw **hstore `tags`** columns on `lock`, `lock_label`, `yard_label`, `grain_srf`, `grain_srf_pnt`, `grain_point`. B's per-layer attribute sets are typically 2–6× wider than A's, and in one case (`mountain_label`) 6× wider because 25 localized `name_*` columns pass straight through.

A second-order effect: B's `int_attrs` include names that **don't exist** in the target view, so those coercions are silent no-ops — `mountain_label` coerces `elevation` (not a column of `rbt.mountain_label`), `runway_curve` coerces `aerodrome_id`, `aeroway_surface` coerces `osm_runway_id`.

---

## 2. Tile layer inventory diff

### 2.1 Counts and structural philosophy

| | Side A (`rbt-schema`) | Side B (`rbt-data-generator`) |
|---|---|---|
| Active tile layers | **58** (+1 disabled `building_polygon`) | **56** (44 cultural + 12 physical) |
| Naming convention | `<theme>_<geometry>`: `_polygon` / `_line` / `_point` / `_label` | Bare theme name + `_surface` / `_curve` / `_label` / `_labels` |
| Grouping | Flat directory, no theme partition | Two-level: `cultural:` / `physical:` sections, then `category:` (aeroway, boundary, building, cemetery, geonames, transportation, utilities, other / builtuparea, contour, glacier, landcover, mountain, park, water, water_label, waterway, inland_water) |
| Layer name source | `layer_id` field in each JSON | YAML key, overridable by `layer_name:` and `mbtiles_name:` |

**Both sides split geometry types into separate layers** — this is not a difference. A uses `dam_polygon` / `dam_line` / `dam_label`; B uses `dam_surface` / `dam_curve` / `dam_label`. The split is identical in structure, only the suffix vocabulary differs (`_polygon`↔`_surface`, `_line`↔`_curve`).

Where they genuinely diverge structurally:

- **Ocean.** A emits `ocean_polygon` as a **distinct MVT layer** separate from `water_polygon`. B folds ocean into the single `water` layer via a `UNION ALL` against `rbt.valid_ocean` inside the matview, distinguished only by the `subclass` attribute.
- **Hydrographic labels.** A merges four sources (NGA GeoNames + USGS Domestic Names + NE marine polys + NE lakes) into **one** `hydrographic_label` layer. B splits these across **two** layers: `geonames_hydrographic` (GNS) and `ne_water_labels` (Natural Earth marine).
- **Physical labels.** A's `physical_labels` is a single NE-centerline layer covering all physical features; B's equivalent is narrowly scoped as `mountain_label`.
- **Label/polygon pairing.** B pairs but does not always name consistently: `stadium_surface`/`stadium_labels` (singular vs plural), `us_military_installations`/`us_military_installations_labels`.

### 2.2 Layers only in A (not in the reference registry)

| Layer | Geometry | Zoom | Notes |
|---|---|---|---|
| `ocean_polygon` | polygon | 0–13 | B has no standalone ocean layer |
| `road_polygon` | polygon | 12–13 | Pedestrian areas, footways, platforms as polygons — no B equivalent |
| `pier_line` | linestring | 12–13 | pier / breakwater / groyne |
| `pier_polygon` | polygon | 12–13 | |
| `culvert_point` | point | 9–13 | |
| `poi_point` | point | 11–13 | B's nearest analogues (`sports_ground`, `golf_course`) exist as views but are **not registered as tile layers** |
| `physical_labels` | linestring | 3–13 | Maps loosely to B's `mountain_label` but broader source scope |

### 2.3 Layers only in B (not in `rbt-schema`)

| Layer | Geometry | Zoom | Projections | Notes |
|---|---|---|---|---|
| `contour` | linestring | 9–13 | **3857, 3395 only** | Externally generated elevation contours; `nth_line` decimation |
| `contour_glacier` | linestring | 9–13 | **3857, 3395 only** | |
| `ne_water_labels` | point | 0–13 | **3857, 3395 only** | Folded into A's `hydrographic_label` |

A has no contour pipeline at all — this is the largest single thematic gap.

### 2.4 Equivalent-but-renamed layer mapping (common surface)

| Side A layer | Side B layer | Rename class |
|---|---|---|
| `adm0_label` / `adm1_label` / `adm2_label` | `adm0_labels` / `adm1_labels` / `adm2_labels` | singular ↔ plural |
| `adm0_line` / `adm1_line` / `adm2_line` | `adm0_lines` / `adm1_lines` / `adm2_lines` | singular ↔ plural |
| `airport_label` | `airports` | |
| `heliport_point` | `heliports` | |
| `airport_polygon` | `aeroway_surface` | scope also differs (B includes aprons) |
| `runway_line` | `runway_curve` (**MBTiles file** `aeroway_curve`) | `_line` ↔ `_curve`; B's file name ≠ layer name |
| `road_line` | `highway` | |
| `rail_line` | `railway` | |
| `transportation_station` | `railway_station` | note A's polygon config file is `transportation_station_polygon.json` but its `layer_id` is `transportation_station` — filename/layer-name mismatch |
| `transportation_station_label` | `railway_station_label` | |
| `ferry_line` | `ferry` | |
| `lock_line` | `lock` | |
| `port_polygon` | `port_surface` | |
| `water_polygon` + `ocean_polygon` | `water` | 2 → 1 |
| `water_line` | `waterway` | |
| `inland_water_intermittent_polygon` | `inland_water_intermittent` | |
| `hydrographic_label` | `geonames_hydrographic` + `ne_water_labels` | 1 → 2 |
| `physical_labels` | `mountain_label` | |
| `place_labels` | `populated_places` | |
| `landcover_polygon` / `landcover_label` | `landcover` / `landcover_labels` | |
| `builtup_polygon` | `builtuparea` | |
| `glacier_polygon` | `glacier` | |
| `park_polygon` | `park` | |
| `cemetery_polygon` | `cemetery` | |
| `stadium_polygon` / `stadium_label` | `stadium_surface` / `stadium_labels` | |
| `us_military_installations_polygon` / `_label` | `us_military_installations` / `_labels` | |
| `dam_polygon` / `dam_line` | `dam_surface` / `dam_curve` | |
| `energy_polygon` / `energy_label` | `hydrocarbon_field` / `hydrocarbon_label` | **thematic rename** — A generalizes to "energy" (adds mineshafts) |
| `grain_polygon` / `grain_point` | `grain_srf` / `grain_srf_pnt` (**4326 targets** `grain_elevator_srf` / `grain_elevator`) | B's 4326 layer names differ from its own 3857 names |
| `power_station_polygon` | `power_station` | |
| `pumping_station_polygon` | `pumping_station` | |
| `powerline_line` | `powerline` | |
| `pipeline_line` | `pipeline` | |
| `radar_label` | `radar_point` | `_label` ↔ `_point` |
| `building_polygon` (disabled + standalone) | `building` | see §7 |

### 2.5 A within-B naming inconsistency worth flagging

B's own two backends disagree on layer names for three layers, so a client consuming 3857 and 4326 tiles from the reference sees **different layer names for the same data**:

| Layer | 3857/3395 (tippecanoe) name | 4326 (GDAL MVT) target name |
|---|---|---|
| grain silos, polygon | `grain_srf` | `grain_elevator_srf` |
| grain silos, point | `grain_srf_pnt` | `grain_elevator` |
| NE water labels | `ne_water_labels` | `ne_water_label` |

A has no such split (single output path), so its layer names are internally consistent.

---

## 3. Per-layer attribute (field) diffs

Reading key: **A-only** = present in A's whitelist, absent from B's source view. **B-only** = present in B's view (therefore in B's tiles, since no `-y`) and absent from A's whitelist.

### 3.1 Transportation

**`road_line` (A, 11 attrs) ↔ `highway` (B, 16 attrs)**

| | Attributes |
|---|---|
| Shared | `brunnel`, `brunnel_name`, `lifecycle_type`, `name`, `ref`, `ref_len`, `ref_number`, `ref_number_len`, `route_type`, `subclass`, `surface` |
| B-only | `osm_id`, `name_len`, `ref_multi`, `lane`, `geom_len` |
| **Type conflict** | `ref_len`, `ref_number_len`: A declares **float**; B coerces **int** (`int_attrs: [name_len, ref_len, ref_number_len, lane, geom_len, osm_id]`) |

**`rail_line` (A, 8) ↔ `railway` (B, 18)**

| | Attributes |
|---|---|
| Shared | `brunnel`, `dps_type`, `lifecycle_desc`, `lifecycle_type`, `name`, `service`, `subclass`, `tracks` |
| B-only | `osm_id`, `name_en`, `ref`, `voltage`, `frequency`, `network`, `usage`, `electrified`, `gauge`, `geom_len` |

Notably A retains B's styling key `dps_type` — evidence of shared lineage.

**`transportation_station` / `_label` (A, 7 each) ↔ `railway_station` / `_label` (B, 10 each)**

Shared: `subclass`, `name`, `operator`, `station`, `service`, `platforms`, `area`. B-only: `id`, `osm_id`, `class`. A declares `platforms` as **string** and `area` as **float**; B applies no `-T` here, so both inherit PostgreSQL types via the FGB intermediate.

**`ferry_line` (A, 1) ↔ `ferry` (B, 9)** — A keeps only `name`; B adds `osm_id`, `is_bridge`, `is_tunnel`, `name_en`, `short_name`, `service`, `usage`, `subclass`.

**`lock_line` (A, 2) ↔ `lock` (B, 9)** — B-only: `osm_id`, `class`, `intermittent`, `name_en`, `lock`, `lock_name`, **`tags` (hstore)**.
**`lock_label` (A, 1: `name`) ↔ `lock_label` (B, 12)** — B-only: `osm_id`, `class`, `subclass`, `name_en`, `operator`, `seamark_name`, `service`, `access`, `lock`, `gate_category`, **`tags`**.

**`yard_label` (A, 2: `yard_size`, `name`) ↔ `yard_label` (B, 11)** — B-only: `osm_id`, `class`, `subclass`, `operator`, `ref`, `service`, `usage`, `yard_purpose`, **`tags`**.

**`port_polygon` (A, 2) ↔ `port_surface` (B, 13)** — A: `area`, `subclass`. B: `fid`, `osm_id`, `name`, `class`, `subclass`, `industrial`, `port`, `cargo`, `access`, `port_type`, `area`, `rank`, `overlap`.
**`port_label` (A, 6) ↔ `port_label` (B, 12)** — A-only: `area_part`, `contained` (dedup helpers). B-only: `osm_id`, `class`, `industrial`, `port`, `cargo`, `access`, `port_type`, `overlap`. Both sides leak internal dedup artifacts, just different ones.

### 3.2 Aviation

**`airport_label` (A, 11) ↔ `airports` (B, 27)** — the widest type-coercion conflict in the comparison:

| Attribute | A type | B type |
|---|---|---|
| `category` | **float** | **int** |
| `rank` | **string** | **int** |
| `elevation_ft` | **string** | **int** |
| `runway_length_ft` | **string** | **int** |
| `osm_aerodrome_area` | float | float ✓ |

B-only (16): `airport_id`, `ident`, `runway_width_ft`, `runway_lighted`, `runway_closed`, `runway_le_ident`, `runway_le_heading`, `runway_he_ident`, `runway_he_heading`, `continent`, `iso_country`, `iso_region`, `municipality`, `scheduled_service`, `osm_id_aerodrome`, `osm_id_runway`.

A stores measurements as **strings**, B as **ints**. A client written against one side's tiles will get string/number type errors against the other for `rank`, `elevation_ft`, `runway_length_ft`, and `category`.

**`heliport_point` (A, 8) ↔ `heliports` (B, 10)** — same string↔int conflict on `rank` and `elevation_ft`. B-only: `airport_ident`, `scheduled_service`.

**`airport_polygon` (A, 3) ↔ `aeroway_surface` (B, 13)** — A: `area`(float), `subclass`, `surface`. B-only: `osm_id`, `name`, `name_en`, `aerodrome_type`, `amenity`, `ele`, `iata`, `icao`, `military`, `operator`.

**`runway_line` (A, 3) ↔ `runway_curve` (B, 13)** — A: `class`, `subclass`, `surface`. B-only: `osm_id`, `ref`, `icao`, `iata`, `width`, `ele`, `length`, `military`, `name`, `operator`.

### 3.3 Water & hydrography

**`water_polygon` (A) ↔ `water` (B)**

```1640:1643:export/water_polygon.json
    "attributes": [
        {"name": "subclass", "type": "string",  "description": ""},
        {"name": "z_level",  "type": "int",     "description": ""}
    ],
```

B's `rbt.water` matview emits **only** `subclass` + geometry:

**Reference** — [`setup/data-sources/schemas/physical/water-features.sql:726-736`](https://github.com/MJJ203/rbt-data-generator/blob/main/setup/data-sources/schemas/physical/water-features.sql#L726-L736)

```sql
    SELECT 
        subclass::text,
        ST_MakeValid(geometry, 'method=structure') as geometry
    FROM valid_inland
    UNION ALL
    SELECT 
        subclass::text,
        ST_MakeValid(geometry, 'method=structure') as geometry
    FROM rbt.valid_ocean
```

**`z_level` is A's defining schema innovation and has no B counterpart.** A precomputes a per-feature minimum-zoom integer in SQL and then uses it as a tippecanoe filter key (§6). It appears on `water_polygon`, `ocean_polygon`, `water_line`, `landcover_polygon`, `landcover_label`. B instead materializes separate zoom-variant *views* (`landcover_z4`, `water_simplified`, …) that only the **4326 GDAL-MVT backend** consumes — B's 3857/3395 tippecanoe layers read the base view and rely on tippecanoe's internal drop strategies. So `z_level` is present in A's tiles as a queryable attribute and entirely absent from B's.

**`water_line` (A, 4) ↔ `waterway` (B, 4)** — near-parity in width, different content: shared `name`, `intermittent`, `subclass`; A-only `z_level` (int), B-only `geom_len` (real).

**`inland_water_intermittent_polygon` (A, **0 attributes**) ↔ `inland_water_intermittent` (B, 6)**

```650:653:export/inland_water_intermittent_polygon.json
    "layer_id": "inland_water_intermittent_polygon",
    "description": "",
    "geometry_type": "polygon",
    "attributes": [],
```

A emits a **geometry-only layer**; B emits `osm_id`, `name`, `name_en`, `subclass`, `area`, `intermittent`. A also declares `us_military_installations_polygon` with an empty `attributes[]` — the only two attribute-free layers on either side.

**`hydrographic_label` (A, 5) ↔ `geonames_hydrographic` (B, 7)** — A: `class`, `desig_cd`, `name`, `scalerank`(int), `min_label`(float). B (via `geonames_hydrographic_enhanced`): `name`, `desig_cd`, `class`, `name_rank`, `display`, `osm_intersect`, `area`. A-only: `scalerank`, `min_label` (its zoom-stepping keys). B-only: `name_rank`, `display`, `osm_intersect`, `area` (its filter key).

**`ne_water_labels` (B only, 3)**: `featurecla`, `name`, `area`.

### 3.4 Landcover, terrain, land use

**`landcover_polygon` (A, 6) ↔ `landcover` (B, 10)** — Shared: `subclass`, `leaf_type`, `leaf_cycle`, `intermittent`, `area`. A-only: `z_level`(int). B-only: `osm_id`, `name`, `name_en`, `rank`, `area_part`. **Type conflict on `area`:** A declares **int**; B's view produces `real` and applies no coercion. (A itself is inconsistent here — `landcover_label` declares `area` as **float** while `landcover_polygon` declares the same field **int**.)

**`landcover_label` (A, 8) ↔ `landcover_labels` (B, 8)** — equal width. A-only: `z_level` (documented in-file: *"Minimum zoom for this label point, derived from feature area"*). B-only: `osm_id`.

**`builtup_polygon` (A, 1: `class`) ↔ `builtuparea` (B, 3: `class`, `subclass`, `area`)** — A keeps only the NE/OSM discriminator it needs for its filter.

**`glacier_polygon` (A, 2) ↔ `glacier` (B, 2)** — **the only exact attribute match in the entire comparison**: both emit `name` + `source`.

**`park_polygon` (A, 4) ↔ `park` (B, 9)** — Shared: `area`, `subclass`, `name`, `protect_class`. B-only: `osm_id`, `access`, `class`, `iucn_level`, `name_en`.

**`physical_labels` (A, 6) ↔ `mountain_label` (B, 38)** — the most extreme width gap. A: `featurecla`, `max_label`, `min_label`, `name`, `name_en`, `scalerank`. B's `rbt.mountain_label` selects the full Natural Earth column set, so its tiles carry `ne_id`, `label`, `length`, `namealt`, `region`, `subregion`, plus **25 localized name columns** (`name_ar`, `name_bn`, `name_de`, `name_el`, `name_es`, `name_fa`, `name_fr`, `name_he`, `name_hi`, `name_hu`, `name_id`, `name_it`, `name_ja`, `name_ko`, `name_nl`, `name_pl`, `name_pt`, `name_ru`, `name_sv`, `name_tr`, `name_uk`, `name_ur`, `name_vi`, `name_zh`, `name_zht`).

### 3.5 Places & boundaries

**`place_labels` (A, 5) ↔ `populated_places` (B, 7)** — Shared: `class`, `capital`, `name`, `name_en`, `rank`. B-only: `ne_id`, `population`. A explicitly types `capital` and `rank` as **int**.

**`adm0_label` (A, 5) ↔ `adm0_labels` (B, 13)**

| | Attributes |
|---|---|
| Shared | `adm0_name`, `status_cd`, `gns_full_name`, `area` |
| **A-only** | `gns_short_name` — B has no short-name column |
| B-only | `adm0_name1`, `status_nm`, `gns_name_rank`, `gns_desig_cd`, `ne_abbrev`, `ne_formal_en`, `ne_name`, `ne_name_en`, `ne_name_long` |
| Type | A declares `status_cd` as **float** (unusual for a code); B applies no coercion |

**`adm0_line` (A, 1: `status`) ↔ `adm0_lines` (B, 7)** — B-only: `cc1`, `cc2`, `country1`, `country2`, `label`, `rank`.
**`adm1_label` (A, 2) ↔ `adm1_labels` (B, 7)** — B-only: `adm1_id`, `adm1_name1`, `src_lang`, `src_lang1`, `area`.
**`adm2_label` (A, 2) ↔ `adm2_labels` (B, 6)** — B-only: `adm2_id`, `adm2_name1`, `src_lang`, `src_lang1`.
**`adm1_line` / `adm2_line`** — both sides emit exactly `iso_3`. Second and third exact matches.

### 3.6 Utilities & infrastructure

**`utility_point` (A, 14) ↔ `utility_point` (B, 32)**

| | Attributes |
|---|---|
| Shared | `class`, `content`, `generator_source`, `height`, `mast_type`, `name`, `name_en`, `pumping_station`, `seamark_platform_category`, `subclass`, `substance`, `substation`, `tower_type` |
| **A-only** | `shore` |
| B-only | `osm_id`, `operator`, `plant_source`, `plant_method`, `plant_storage`, `plant_output`, `generator_method`, `generator_type`, `generator_plant`, `seamark_pylon_category`, `seamark_production_area_category`, `seamark_name`, `seamark_platform_height`, `tower_construction`, `rotor_diameter`, `service`, `capacity`, `location`, `access` |
| Type | A coerces `height` to **int**; B applies no `-T` to `utility_point` at all |

**`energy_polygon` / `energy_label` (A) ↔ `hydrocarbon_field` / `hydrocarbon_label` (B)** — A has broadened the theme beyond hydrocarbons:

```436:439:export/energy_label.json
        {"name": "resource",      "type": "string",  "description": "resource= tag (mineshaft)"},
        {"name": "mineshaft_type","type": "string",  "description": "mineshaft:type= tag"},
        {"name": "disused",       "type": "bool",    "description": "true if disused=yes"},
        {"name": "area",          "type": "float",   "description": "area in m² (polygon features only)"}
```

A-only: `resource`, `mineshaft_type`, `disused` (**bool**). B-only: `id`, `osm_id`, `class`, `ref`, `access`, `type`.

**`power_station_polygon` (A, 2: `area`, `subclass`) ↔ `power_station` (B, 16)** — B-only: `id`, `osm_id`, `name`, `name_en`, `operator`, `plant_source`, `plant_method`, `plant_storage`, `plant_output`, `generator_source`, `generator_method`, `generator_type`, `generator_output`, `generator_plant`.
**`power_station_label` (A, 5) ↔ `power_station_label` (B, 16)** — A keeps `area`, `generator_source`, `name`, `plant_source`, `subclass`; B emits the same 16 columns as its polygon layer (label and polygon are attribute-identical in B).

**`pumping_station_polygon` (A, 2) / `_label` (A, 4) ↔ `pumping_station` / `_label` (B, 10 each)** — B-only: `id`, `osm_id`, `name`, `name_en`, `operator`. A's label keeps `pumping_station`, `substance`, `subclass`, `area`.

**`powerline_line` (A, 3) ↔ `powerline` (B, 12)** — A: `usage`, `location`, `subclass`. B-only: `osm_id`, `class`, `name`, `cable_overhead_category`, `cable_submarine_category`, `voltage`, `operator`, `cables`, `wires`.

**`pipeline_line` (A, 2) ↔ `pipeline` (B, 20)** — A keeps only `substance`, `location`. B-only (18): `osm_id`, `class`, `subclass`, `name`, `usage`, `diameter`, `flow_direction`, `operator`, `pipeline_submarine_category`, `pipeline_submarine_product`, `pipeline_overhead_category`, `pipeline_overhead_product`, `product`, `content`, `height`, `ele`, `operational_status`, `condition`.

**`radar_label` (A, 6) ↔ `radar_point` (B, 18)** — Shared: `description`, `name`, `operator`, `seamark_name`, `subclass`, `tower_type`. B-only: `osm_id`, `class`, `name_en`, `tower_construction`, `mast_type`, `service`, `height`, `access`, `military`, `ele`, `airmark`, `radar`.

**Dams** — attribute-name divergence, not just width:

| Layer | A attributes | B attributes |
|---|---|---|
| polygon / surface | `area`, `name`, `surface` | `name`, `name_en`, **`fclass`**, `surface`, `area` |
| line / curve | `length`, `name`, `surface` | `name`, `name_en`, **`fclass`**, `surface`, `length` |
| label | `dam_srf_crv_intersect`, `surface`, `water_intersect` — **no `name`** | `fid`, `name`, `name_en`, `fclass`, `water_intersect`, `dam_srf_crv_intersect` — **no `surface`** |

A's `dam_label` carries the two intersection flags but drops the feature name; B's carries the name but drops `surface`. These label layers are mutually incompatible.

**`grain_polygon` (A, 1: `area`) / `grain_point` (A, 4) ↔ `grain_srf` (B, 9) / `grain_srf_pnt` (B, 9)** — B-only: `osm_id`, `class`, `subclass`, `height`, **`tags` (hstore)**.

### 3.7 Land use & other

**`cemetery_polygon` (A, 2) ↔ `cemetery` (B, 12)** — A: `subclass`, `area`. B-only: `fid`, `osm_id`, `name`, `class`, `religion`, `denomination`, `cemetery`, `area_part`, `rank`, `contained`.
**`cemetery_label` (A, 7) ↔ `cemetery_label` (B, 12)** — A carries `area`, `area_part`, `contained`, `name`, `rank`, `religion`, `subclass`; B adds `fid`, `osm_id`, `class`, `denomination`, `cemetery`. Here A's whitelist is unusually wide (it retains the `area_part`/`contained`/`rank` dedup triplet).

**`stadium_polygon` / `_label` (A, 2 / 3) ↔ `stadium_surface` / `stadium_labels` (B, 6 each)** — B-only: `osm_id`, `name_en`, `class`; B's polygon and label layers are attribute-identical.

**`us_military_installations_polygon` (A, **0**) / `_label` (A, 2) ↔ `us_military_installations` / `_labels` (B, 7 each)** — A's polygon is geometry-only; A's label keeps `area`, `sitename`. B emits `area`, `component`, `country`, `jointbase`, `operstatus`, `sitename`, `state` on **both**.

### 3.8 A-only layers' attributes (no B counterpart)

| Layer | Attributes |
|---|---|
| `road_polygon` | `name`, `name_en`, `subclass` (*pedestrian, footway, steps, path, cycleway, bridleway, corridor, platform*), `area`(float) |
| `pier_line` | `name`, `class` (*man_made or highway*), `subclass` (*pier/breakwater/groyne*), `is_floating`(**bool**) |
| `pier_polygon` | same + `area`(float) |
| `culvert_point` | `name`, `name_en`, `subclass` |
| `poi_point` | `name`, `name_en`, `class`, `subclass`, `religion` |
| `ocean_polygon` | `subclass`, `z_level`(int) |

### 3.9 Declared type systems

| Type | Side A usage | Side B usage |
|---|---|---|
| `string` | Default for most attributes | `string_attrs` used **once** — `building`: `class`, `subtype`, `id` |
| `float` | Widely used for `area`, `length`, `rank`, `status_cd`, `category`, `min_label` | `float_attrs`: `aeroway_surface.area`, `airports.{runway_le_heading, runway_he_heading, osm_aerodrome_area}`, `adm1_labels.area`, `building.{height, area}` |
| `int` | `z_level`, `scalerank`, `capital`, `rank` (places), `height` (utility), `area` (landcover polygon) | `int_attrs` on `aeroway_surface`, `airports`, `heliports`, `runway_curve`, `building`(—), `highway`, `contour`, `mountain_label` |
| `bool` | `energy_label.disused`, `pier_line.is_floating`, `pier_polygon.is_floating` | `bool_attrs` used **once** — `building.has_parts` |

A's type system is declared per-attribute and near-universal; B's is sparse and opt-in, leaving most attributes at whatever type the FlatGeoBuf intermediate carries out of PostgreSQL.

---

## 4. Zoom window diffs

Side A's `maximum_zoom` is **13 for all 58 layers**, with no exceptions. Side B's `max_zoom` defaults to 13 and **no layer overrides it**. So all differences are in **minzoom** — but B has *two independent minzoom systems*: `min_zoom` in `layers.yml` (used by the tippecanoe 3857/3395 backend) and per-source-table `minzoom` in the `gdal_mvt:` section (used by the 4326 backend). These frequently disagree with each other.

| A layer → B layer | A Z | B Z (3857/3395) | B Z (4326) | Verdict |
|---|---|---|---|---|
| `adm0_label` → `adm0_labels` | 0–13 | 0–13 | 0–13 | ✅ match |
| `adm0_line` → `adm0_lines` | 0–13 | 0–13 | 0–13 | ✅ match |
| `adm1_label`/`_line` → `adm1_labels`/`_lines` | 3–13 | 3–13 | 3–13 | ✅ match |
| `adm2_label`/`_line` → `adm2_labels`/`_lines` | **11**–13 | **6**–13 | 6–13 | ❌ A 5 zooms later |
| `road_line` → `highway` | 6–13 | 6–13 | **4**–13 | ⚠️ B's 4326 starts 2 earlier |
| `rail_line` → `railway` | **8**–13 | **6**–13 | 6–13 | ❌ |
| `ferry_line` → `ferry` | **8**–13 | **4**–13 | 4–13 | ❌ 4-zoom gap |
| `transportation_station` → `railway_station` | **11**–13 | **10**–13 | **9**–13 | ❌ |
| `transportation_station_label` → `railway_station_label` | 11–13 | **10**–13 | 11–13 | ⚠️ |
| `yard_label` → `yard_label` | 10–13 | 10–13 | 11–13 | ✅ / ⚠️ |
| `lock_line` → `lock` | **9**–13 | **10**–13 | **11**–13 | ❌ A earlier |
| `lock_label` → `lock_label` | **9**–13 | **10**–13 | 11–13 | ❌ A earlier |
| `port_polygon` → `port_surface` | **9**–13 | **6**–13 | 7–13 | ❌ |
| `port_label` → `port_label` | **9**–13 | **6**–13 | 7–13 | ❌ |
| `airport_label` → `airports` | **8**–13 | **5**–13 | 5–13 | ❌ |
| `heliport_point` → `heliports` | **9**–13 | **5**–13 | 5–13 | ❌ 4-zoom gap |
| `airport_polygon` → `aeroway_surface` | **11**–13 | **8**–13 | 8–13 | ❌ |
| `runway_line` → `runway_curve` | **11**–13 | **8**–13 | 8–13 | ❌ |
| `water_polygon` → `water` | 0–13 | 0–13 | 0–9 (`water_simplified`) + 10–13 | ✅ |
| `ocean_polygon` → *(folded into `water`)* | 0–13 | — | — | — |
| `water_line` → `waterway` | 6–13 | 6–13 | **5**–13 | ✅ / ⚠️ |
| `inland_water_intermittent_polygon` → `inland_water_intermittent` | 8–13 | 8–13 | 8–13 | ✅ match |
| `hydrographic_label` → `geonames_hydrographic` | **0**–13 | **1**–13 | 1–13 | ⚠️ 1 zoom |
| *(none)* → `ne_water_labels` | — | 0–13 | 0–13 | B-only |
| `physical_labels` → `mountain_label` | **3**–13 | **6**–13 | **2**–13 | ❌ all three differ |
| `place_labels` → `populated_places` | 3–13 | 3–13 | 3–13 | ✅ match |
| `landcover_polygon` → `landcover` | **4**–13 | **3**–13 | 4–13 | ⚠️ |
| `landcover_label` → `landcover_labels` | **4**–13 | **5**–13 | 4–13 | ⚠️ A earlier than B-3857 |
| `builtup_polygon` → `builtuparea` | **4**–13 | **3**–13 | 3–13 | ⚠️ |
| `glacier_polygon` → `glacier` | **0**–13 | **3**–13 | **0**–13 | ❌ vs B-3857 |
| `park_polygon` → `park` | **9**–13 | **3**–13 | 6–13 | ❌ **6-zoom gap — largest** |
| `cemetery_polygon`/`_label` → `cemetery`/`_label` | **9**–13 | **8**–13 | 8–13 | ❌ |
| `stadium_polygon`/`_label` → `stadium_surface`/`_labels` | **9**–13 | **10**–13 | **7**–13 | ❌ A between B's two |
| `us_military_installations_polygon`/`_label` | **9**–13 | **6**–13 | 4 / 6–13 | ❌ |
| `dam_polygon`/`_line`/`_label` → `dam_surface`/`_curve`/`_label` | **9**–13 | **8**–13 | 7–13 | ❌ |
| `energy_polygon`/`_label` → `hydrocarbon_field`/`_label` | **9**–13 | **6**–13 | 8–13 | ❌ |
| `grain_polygon`/`_point` → `grain_srf`/`_srf_pnt` | **9**–13 | **10**–13 | **8**–13 | ❌ A between B's two |
| `power_station_polygon` → `power_station` | **9**–13 | **10**–13 | 8–13 | ❌ |
| `power_station_label` → `power_station_label` | 9–13 | **10**–13 | 9–13 | ⚠️ |
| `pumping_station_polygon` → `pumping_station` | **9**–13 | **10**–13 | 8–13 | ❌ |
| `pumping_station_label` | 9–13 | **10**–13 | 9–13 | ⚠️ |
| `powerline_line` → `powerline` | **9**–13 | **8**–13 | 9–13 | ⚠️ |
| `pipeline_line` → `pipeline` | **9**–13 | **6**–13 | 9–13 | ❌ vs B-3857 |
| `utility_point` → `utility_point` | **9**–13 | **6**–13 | 6–13 | ❌ |
| `radar_label` → `radar_point` | 8–13 | 8–13 | 7–13 | ✅ / ⚠️ |
| `building_polygon` → `building` | **11**–13 | **10**–13 | 10–13 | ❌ |
| `poi_point` | 11–13 | — | — | A-only |
| `culvert_point` | 9–13 | — | — | A-only |
| `pier_line`/`pier_polygon` | 12–13 | — | — | A-only |
| `road_polygon` | 12–13 | — | — | A-only |
| *(none)* → `contour` / `contour_glacier` | — | 9–13 | 8/10/12–13 | B-only |

**Summary:** only 6 of ~48 mappable layers have identical zoom windows (`adm0_*`, `adm1_*`, `water`, `inland_water_intermittent`, `populated_places`, `radar_point`). A's dominant pattern is a **z9 floor for the entire utilities/other family** (17 layers at exactly 9–13), where B spreads those same layers across z6/z8/z10. A also uses **z11–13 for detail-only layers** (adm2, airport polygons, runways, POI, transportation stations) and **z12–13 for the finest** (piers, road polygons) — a granularity band B does not use at all (B's highest floor is z10).

---

## 5. Projection / output-format diffs

### 5.1 Side A: one implied projection, no projection declaration

**No `export/*.json` contains any projection field.** The complete `ogr_export_options` surface across all 58 configs is exactly two variants:

```42:44:export/adm0_labels.json
    "ogr_export_options": {
        "additional_flags": "-lco SPATIAL_INDEX=NO"
    }
```

…and for polygon layers, `"-lco SPATIAL_INDEX=NO -nlt PROMOTE_TO_MULTI"`. There is no `-t_srs`, no `crs`, no projection list. `tile-metadata/metadata.py` carries no `crs` key. The only executable tiler in the repo (`scripts/overture/tile.sh`) passes no `-s` flag, so tippecanoe assumes EPSG:4326 input and emits a standard Web Mercator pyramid.

**Inference (flagged):** Side A emits **EPSG:3857 only**, as MBTiles. No 3395, no 4326.

### 5.2 Side B: three projections, two backends, per-layer subsets

**Reference** — [`config/layers.yml:33-36`](https://github.com/MJJ203/rbt-data-generator/blob/main/config/layers.yml#L33-L36)

```yaml
  defaults:
    projection_list: [3857, 3395, 4326]
    min_zoom: 0
    max_zoom: 13
```

Five layers override the default and are emitted in **only 2 of 3** projections:

| Layer | `projections:` | Missing |
|---|---|---|
| `contour` | `[3857, 3395]` | 4326 (tippecanoe); *but the `gdal_mvt` section does define `contour` 4326 targets* |
| `contour_glacier` | `[3857, 3395]` | same |
| `ne_water_labels` | `[3857, 3395]` | same |
| `waterway` | `[3857, 3395]` | same |
| `inland_water_intermittent` | `[3857, 3395]` | same |

All other 51 layers are emitted in all three.

**Two structurally different backends:**

| | 3857 / 3395 | 4326 |
|---|---|---|
| Tool | `tippecanoe` per layer + `tile-join -f -pk` merge | single multi-table `ogr2ogr -f MVT` |
| Container | **MBTiles** (`cultural_3857.mbtiles`, `physical_3395.mbtiles`) | **tile directory** (`{z}/{x}/{y}.pbf` + `metadata.json`) |
| Tiling scheme | Mercator default | `TILING_SCHEME="EPSG:4326,-180,180,360"` |
| Zoom source | `min_zoom`/`max_zoom` per layer | per-source-table `minzoom`/`maxzoom` in `gdal_mvt.datasets` |
| Size guards | `-pk`, `--no-tile-size-limit` | `MAX_SIZE=900000`, `MAX_FEATURES=500000` |
| Trick | `-s EPSG:3857` is passed **even for 3395** — the FGB is already reprojected, so tippecanoe is told the coordinates are Web Mercator to make it cut a 3395 pyramid | true `-t_srs EPSG:4326` |

**Reference** — [`src/rbt/tiles/tippecanoe.py:28-31`](https://github.com/MJJ203/rbt-data-generator/blob/main/src/rbt/tiles/tippecanoe.py#L28-L31)

```python
        "-s",
        "EPSG:3857",  # tippecanoe expects 3857 source even when target_srs is different
```

**Schema implications of the format split:** B's 4326 output has no MBTiles `metadata` table at all — no `json`/`vector_layers` block, no `bounds`, no `center`, and no BTIS keys (BTIS is applied only to mercator MBTiles). A consumer reading B's 4326 tiles gets a hand-written `metadata.json` with a completely different field set (§6). B's 4326 layer set is also *not* the same as its 3857 layer set: three layer names are remapped (§2.5) and highway/building/landcover/geonames are blended from multiple pre-simplified views into one target layer per zoom band.

### 5.3 Geometry-type normalization difference

A forces `-nlt PROMOTE_TO_MULTI` on every polygon layer, so its polygon layers are uniformly MultiPolygon in the FGB intermediate. B never passes `-nlt`, and its `ogr2ogr` invocation is minimal:

**Reference** — [`src/rbt/tiles/exporter.py:59-65`](https://github.com/MJJ203/rbt-data-generator/blob/main/src/rbt/tiles/exporter.py#L59-L65)

```python
    cmd = ["ogr2ogr"]
    if not layer.ogr.spatial_index:
        cmd += ["-lco", "SPATIAL_INDEX=NO"]
    cmd += ["-t_srs", projection.epsg, str(tmp), settings.ogr_pg_connection(), layer.source_table]
```

Also inverted defaults: A sets `SPATIAL_INDEX=NO` on **all 58** layers; B defaults `spatial_index: true` and **no layer sets it false** — so B writes a spatial index into every intermediate FGB. (No effect on tile contents; noted for completeness since it's the one `ogr2ogr` flag both sides parameterize.)

---

## 6. Tile metadata / TileJSON schema diffs

### 6.1 Side A: `tile-metadata/metadata.py`

A rich, publication-oriented metadata dict. Notably, **the file defines only a dict** — it imports `json` and `sqlite3` but contains no function that writes anything, so the write path is external to this repo.

| Key | Value |
|---|---|
| `name` | `"Releasable Basemap Tiles (RBT)"` |
| `version` | `"2.0-dev"` |
| `production_date` | `"2023-10-01T00:00:00.000Z"` (hardcoded) |
| `description` | `""` (empty) |
| `attribution` | 8 HTML anchors: AGC, OpenStreetMap, FieldMaps, Natural Earth, Overture, USGS, NGA, OurAirports |
| `tags` | 13-element array |
| `source` | `"https://www.agc.army.mil/"` |
| `license` | **array of 5 objects** (`{name, license, url}`) — ODbL 1.0 ×3, Public Domain ×2 |
| `creators` | `{creators:name: "Team SACI", creators:websites: …}` |
| `format` | `"pbf"` |
| `bounds` | `[-179.99999999999997, -60.0, 179.99999999999997, 83.0]` |
| `center` | `[0.0, 0.0, 2]` |

### 6.2 Side B: two disjoint metadata schemas

**Mercator MBTiles — BTIS keys only** (`src/rbt/tiles/btis.py`). B *adds* six keys and **deletes** two that tippecanoe wrote:

**Reference** — [`src/rbt/tiles/btis.py:39-52`](https://github.com/MJJ203/rbt-data-generator/blob/main/src/rbt/tiles/btis.py#L39-L52)

```python
        for name, value in (
            ("crs", projection.epsg),
            ("tile_origin_upper_left_x", projection.tile_origin_x),
            ("tile_origin_upper_left_y", projection.tile_origin_y),
            ("tile_dimension_zoom_0", projection.tile_dimension_zoom_0),
            ("btp_schema_version", btp_schema_version),
            ("changelog_url", changelog_url),
        ):
...
        conn.execute("DELETE FROM metadata WHERE name = 'generator_options'")
        conn.execute("DELETE FROM metadata WHERE name = 'strategies'")
```

Values come from `layers.yml`: `tile_origin_x: "-20037508.343"`, `tile_origin_y: "20037508.343"`, `tile_dimension_zoom_0: "40075016.686"` for both 3857 and 3395; `"-180"/"90"/"360"` for 4326. `btp_schema_version: "1.0.0"`.

**4326 tile directory — hand-written `metadata.json`** (`gdal_mvt.write_metadata`): `name`, `description`, `version: "1.0"`, `minzoom`, `maxzoom`, `format: "pbf"`, `type: "baselayer"`, `attribution: "Generated from PostgreSQL RBT schema"`, `created` (runtime ISO timestamp), `projection`, `tiling_scheme`, `selected_layers`, `layer_count`, `categories` (category → target layer names), `tables_processed`.

### 6.3 Field-by-field metadata diff

| Field | A | B (mercator MBTiles) | B (4326 dir) |
|---|---|---|---|
| `name` | "Releasable Basemap Tiles (RBT)" | tippecanoe `-n <layer_name>`, then per-layer name survives tile-join | `"physical"` / `"cultural"` |
| `description` | `""` | not set | `"Physical vector tiles dataset"` etc. |
| `version` | `"2.0-dev"` | not set | `"1.0"` |
| `attribution` | **8 HTML source links** | **not set at all** | `"Generated from PostgreSQL RBT schema"` |
| `license` | **5-object array** | absent | absent |
| `tags`, `source`, `creators`, `production_date` | present | absent | absent |
| `format` | `"pbf"` | tippecanoe default `pbf` | `"pbf"` |
| `type` | absent | tippecanoe default | `"baselayer"` |
| `bounds` | **explicit** `[-180, -60, 180, 83]` | tippecanoe-computed from data | **absent** |
| `center` | **explicit** `[0, 0, 2]` | tippecanoe-computed | **absent** |
| `minzoom` / `maxzoom` | absent | tippecanoe-computed | explicit (0 / 13) |
| `crs` | **absent** | **`EPSG:3857` / `EPSG:3395`** | `projection: "EPSG:4326"` |
| `tile_origin_upper_left_x/y`, `tile_dimension_zoom_0` | **absent** | **present (BTIS)** | absent |
| `btp_schema_version`, `changelog_url` | **absent** | **present (BTIS)** | absent |
| `tiling_scheme` | absent | absent | `"EPSG:4326,-180,180,360"` |
| `vector_layers` / `json` | neither side writes it explicitly | tippecanoe auto-generates | GDAL auto-generates |
| `generator_options`, `strategies` | n/a | **explicitly DELETEd** | n/a |
| `selected_layers`, `layer_count`, `categories`, `tables_processed` | absent | absent | **present** |

**The two metadata schemas are essentially disjoint.** A is provenance/licensing-oriented and BTIS-blind; B is BTIS-compliant and provenance-thin (a single generic attribution string). Only `format: "pbf"` is common to all three. A's `bounds`/`center`/`license`/`attribution`/`tags`/`creators` have no B counterpart; B's entire BTIS key set (`crs`, tile origin, tile dimension, `btp_schema_version`) has no A counterpart despite A's `metadata.py` clearly targeting the same MBTiles `metadata` table (it imports `sqlite3`).

Side note on serving: B ships `config/tile-server.json` registering only `physical-3857` and `cultural-3857` — its Tileserver-GL surface exposes 2 of the 6 mercator datasets it can produce.

---

## 7. Feature-filtering / densification attribute diffs

### 7.1 Filter architecture

| | Side A | Side B |
|---|---|---|
| Location | **Inline per layer** in each JSON's `tippecanoe_options.filter` | **Centralized** `filters:` section, referenced by `filter_ref:` |
| Count | **13 of 58** layers carry a non-empty filter | **5 named filters** shared by **6 layers** |
| Filter keys | Precomputed SQL attributes: `z_level`, `min_label`, `rank`, `class`, `source`, plus `subclass` and `area` | `service`, `class`, `area`, `rank`, `subclass` |
| Zoom generalization strategy | **Attribute-driven filters in tippecanoe** | **Zoom-variant SQL views**, consumed only by the 4326 backend |

### 7.2 Side A's filtered layers

| Layer | Filter key | Mechanism |
|---|---|---|
| `builtup_polygon` | `class` | NE at z≤8, OSM at z≥8 |
| `glacier_polygon` | `source` | NE at z≤7, OSM at z≥7 |
| `ocean_polygon` | `z_level` | `z_level=0` for z0–4, `z_level=1` for z≥5 |
| `water_polygon` | `z_level` | 9-step ladder z0→z12 |
| `water_line` | `z_level` | 8-step ladder z6→z13, with upper bounds `<=$zoom,9` on the low tiers |
| `landcover_polygon` | `z_level` | 10 steps using **`==$zoom`** (exact-match, not `>=`) |
| `landcover_label` | `z_level` | 9 steps using `>=$zoom` |
| `hydrographic_label` | `min_label` | 9-step ladder z0→z9 |
| `physical_labels` | `min_label` | 5 steps (3/5/7/9/11) |
| `place_labels` | `rank` | 7 steps, `rank<=4` at z3 → `rank>=11` at z12 |
| `road_line` | `subclass` | **9-step whitelist of road classes** (~30 values by z12) |
| `rail_line` | `service` | `!=yard` at z≥6, all at z≥13 |
| `utility_point` | `subclass` | poles excluded until z13, towers until z12 |
| `transportation_station` | `subclass` + **`area`** | `area>=625` at z11–12; adds `platform` at z13 |
| `building_polygon` (disabled) | `area` | `>5000`/`>2500`/`>1500` at z10/11/12 |

### 7.3 Side B's five shared filters

**Reference** — [`config/layers.yml:47-84`](https://github.com/MJJ203/rbt-data-generator/blob/main/config/layers.yml#L47-L84)

```yaml
  building: |
    {"*":["any",
      ["all",[">=","$zoom",10],[">","area",5000]],
      ["all",[">=","$zoom",11],[">","area",2500]],
      ["all",[">=","$zoom",12],[">","area",1500]],
      ["all",[">=","$zoom",13]]
    ]}
  railway: |
    {"*":["any",
      ["all",[">=","$zoom",6],["!=","service","yard"]],
      ["all",[">=","$zoom",13]]
    ]}
```

Applied to: `building`→`building`, `railway`→`railway`, `hydrographic`→`geonames_hydrographic`, `populated_places`→`populated_places`, `utility`→`utility_point` **and `dam_surface`** (the `dam_surface` layer references `filter_ref: utility`, filtering dam polygons by `subclass in (utility_pole, pole, tower)` — almost certainly a copy-paste bug, since dam polygons have no such subclasses; effect is that dams pass at z≥6 and z≥12 and z≥13 unconditionally).

**Direct filter comparisons on shared layers:**

| Layer | A filter | B filter | Agreement |
|---|---|---|---|
| `rail_line`/`railway` | `!=service,yard` at z≥6; all at z≥13 | **identical** | ✅ **exact match** |
| `utility_point` | 3 tiers: `!in(utility_pole,pole,tower)` z≥6; `==tower` z≥12; `in(utility_pole,pole)` z≥13 | 3 tiers: `!in(utility_pole,pole,tower)` z≥6; `!in(utility_pole,pole)` z≥12; all z≥13 | ⚠️ equivalent outcome, different phrasing |
| `place_labels`/`populated_places` | 7 tiers, mixed `<=`/`==`/`>=` on `rank` | 4 tiers: `rank<8` z3, `<11` z7, `<12` z9, all z12 | ❌ substantially different density curve |
| `hydrographic_label`/`geonames_hydrographic` | 9 tiers on **`min_label`** | 10 tiers on **`class` + `area`** (thresholds down to 12.4 billion m²) | ❌ different key entirely |
| `building_polygon`/`building` | `>5000`/`>2500`/`>1500` @ z10/11/12 | **identical thresholds** | ✅ (but A's config is disabled — see §8) |

### 7.4 Densification / feature-survival flags

| Flag family | Side A | Side B |
|---|---|---|
| Point thinning | `--drop-rate=1` on **21 label/point layers**; `-r1` on `us_military_installations_label` | `-r 1` on **all label/point layers** (same flag, long vs short form) |
| Density-based dropping | **none** — no `--drop-densest-as-needed` anywhere | `--drop-densest-as-needed` on `airports`, `heliports`; `--drop-smallest-as-needed` on **14 layers**; `--coalesce-smallest-as-needed` on `building` |
| Size/feature limits | `--no-feature-limit --no-tile-size-limit` on **only 2** layers (`landcover_polygon`, `ocean_polygon`) | `-pk -pf` on **~30** layers (all labels + highway/railway/ferry) |
| Coalescing | `--coalesce` on **7** layers (`builtup`, `glacier`, `water_polygon`, `ocean`, `landcover_polygon`, `inland_water_intermittent`, `us_military_installations_polygon`, `transportation_station` uses `--hilbert` only) | `--coalesce` on **1** (`inland_water_intermittent`), plus `--reorder`, `-X` |
| Simplification | `--simplify-only-low-zooms` on ~30 layers; `--no-tiny-polygon-reduction-at-maximum-zoom` on ~16 | `--simplify-only-low-zooms` on ~18; `--no-simplification-of-shared-nodes` on ~10 (**A uses this on zero layers**) |
| Extra detail | **`max_detail_const: 14`** on `pier_polygon` only — a key that appears nowhere else in either repo and has no tippecanoe equivalent | `--extra-detail=13` on **~22 layers**; `-D 11` on highway |
| Coordinate precision | not specified → **double** | **`--single-precision`** global default |
| Ordering | `--hilbert` on 6 layers | not used |
| Longitude wraparound | `--detect-longitude-wraparound` on 5 polygon layers | on `inland_water_intermittent` only |

**Schema-relevant consequences:**
- **A's `--coalesce` on 7 polygon layers merges adjacent features sharing identical attributes**, so per-feature attribute variance is lost in those layers in a way it isn't in B.
- **B's `--single-precision` global default** means B's tiles carry float32 coordinates; A's carry float64 — a wire-level difference in every tile on every layer.
- **B's `--no-simplification-of-shared-nodes` on boundary/road/rail layers** preserves topology that A does not; A's `adm0_lines`/`adm1_lines`/`adm2_lines` instead pass `"--simplify-only-low-zooms -pS"`, where **`-pS` is the short form of `--simplify-only-low-zooms`** — the flag is specified twice, redundantly, and no shared-node protection is applied.
- **`--drop-smallest-as-needed`/`--drop-densest-as-needed` on 16 B layers is entirely absent from A**, so under tile-size pressure the two pipelines shed different features (A relies on `-pk`-less defaults and its z_level filters).

---

## 8. Buildings

Three distinct building paths exist across the two repos, and **no two agree**.

### 8.1 Side A, path 1 — disabled PostGIS/OSM config

`export/building_polygon.json.skip` (`.skip` suffix = excluded from the pipeline) and `carto_sql/031_building.sql.skip`:

```1700:1712:export/building_polygon.json.skip
    "layer_id": "building_polygon",
    "geometry_type": "polygon",
    "attributes": [
        {"name": "area",  "type": "float",  "description": ""}
    ],
    "tippecanoe_options": {
        "minimum_zoom": 11,
        "maximum_zoom": 13,
        "additional_flags": "--simplify-only-low-zooms --no-tiny-polygon-reduction-at-maximum-zoom",
        "filter": {"*":["any",["all",[">=","$zoom",10],[">","area",5000]],["all",[">=","$zoom",11],[">","area",2500]],["all",[">=","$zoom",12],[">","area",1500]],["all",[">=","$zoom",13]]]}
```

Source is **OSM**, not Overture:

```14:19:carto_sql/031_building.sql.skip
CREATE MATERIALIZED VIEW export.building_polygon AS
SELECT
    osm_id,
    ST_Area(ST_Transform(geometry, 3857))::real                         AS area,
    geometry
FROM osm.osm_building_polygon;
```

Attribute set in tiles: **`area` only**. Note the filter's `z10` tier is dead code — `minimum_zoom` is 11.

### 8.2 Side A, path 2 — active standalone Overture tiler

`scripts/overture/{fetch,shard,tile}.sh` (commits "Added standalone Overture buildings scripts", "Overture buildings tippecanoe flag adjustment"). DuckDB reads Overture GeoParquet from S3 → per-shard FlatGeobuf:

```shard.sh (DuckDB SELECT)
id, names.primary AS name, subtype, class, has_parts, height,
ST_Area_Spheroid(geometry) AS area,   -- true ground area, m^2
ST_Multi(geometry) AS geometry
WHERE area >= 1
```

Then tiled directly:

```tile.sh
tippecanoe -o building_polygon.mbtiles -l building_polygon -P \
  -y area -y subtype -y has_parts -y height \
  -T area:int -T has_parts:bool -T height:int \
  --minimum-zoom=11 --maximum-zoom=13 --extra-detail=14 \
  --no-tiny-polygon-reduction-at-maximum-zoom \
  --no-feature-limit --no-tile-size-limit \
  -j '{"*":["any",
        ["all",[">=","$zoom",11],[">=","area",40000]],
        ["all",[">=","$zoom",12],[">=","area",6400]],
        [">=","$zoom",13]]}'
```

**Tile attributes: exactly `area`(int), `subtype`, `has_parts`(bool), `height`(int).** The `-y` allowlist means `id`, `name`, and `class` are present in the FGB but **deliberately excluded from tiles** — the only place in Side A where `-y` is explicit rather than declarative.

### 8.3 Side B — registry layer + DuckDB export

**Reference** — [`config/layers.yml:173-186`](https://github.com/MJJ203/rbt-data-generator/blob/main/config/layers.yml#L173-L186)

```yaml
  building:
    category: building
    source_table: rbt.building
    min_zoom: 10
    tippecanoe:
      options: [--extra-detail=13, -pk, --coalesce-smallest-as-needed,
                --simplify-only-low-zooms, --no-simplification-of-shared-nodes,
                --no-tiny-polygon-reduction-at-maximum-zoom]
      float_attrs: [height, area]
      bool_attrs: [has_parts]
      string_attrs: [class, subtype, id]
      filter_ref: building
```

Since B passes no `-y`, its tiles carry **every** column of `rbt.building`. The (commented-out) DDL selects `id, names, class, level, has_parts, height, num_floors` — so if enabled, B's tiles would additionally carry `names`, `level`, `num_floors` and would **not** have `subtype` or `area` from that DDL, even though `layers.yml` coerces both. The DuckDB export path supplies a different column set: `id, subtype, class, has_parts, height, area` (no `name` — explicitly documented as dropped from the `COPY` lists).

### 8.4 Buildings diff summary

| Aspect | A (Overture script, active) | A (`.skip`, disabled) | B (`building`) |
|---|---|---|---|
| Layer name | `building_polygon` | `building_polygon` | `building` |
| Source | Overture GeoParquet → DuckDB → FGB | `osm.osm_building_polygon` | `rbt.building` (Overture via PostGIS; **DDL commented out**) or DuckDB `.fgb` |
| Zoom | **11**–13 | 11–13 | **10**–13 |
| Tile attributes | `area`, `subtype`, `has_parts`, `height` | `area` | `id`, `class`, `subtype`, `has_parts`, `height`, `area` (+ `names`, `level`, `num_floors` if PG DDL enabled) |
| `area` type | **int** | float | **float** |
| `has_parts` | **bool** | — | **bool** ✅ |
| `height` | **int** | — | **float** |
| `class` / `id` in tiles | **excluded via `-y`** | — | **included** (`string_attrs`) |
| Area computation | `ST_Area_Spheroid` (true ground area) | `ST_Area(ST_Transform(…,3857))` | `ST_Area(ST_Transform(…,3857))` |
| Area prefilter | `area >= 1` at shard time | none | none |
| Zoom/area thresholds | **z11: ≥40000, z12: ≥6400, z13: all** | z10:>5000, z11:>2500, z12:>1500 | **z10:>5000, z11:>2500, z12:>1500** |
| Detail | `--extra-detail=14`, `--no-feature-limit`, `--no-tile-size-limit` | — | `--extra-detail=13`, `-pk`, `--coalesce-smallest-as-needed` |
| Projections | 3857 only | — | 3857, 3395, 4326 (4326 blends `building_z10/z11/z12/building`) |

**The two live building schemas are the most divergent layer pair in the comparison.** A's active path starts a full zoom later (11 vs 10) and applies area cutoffs **8× and 4.3× stricter** than B's at the overlapping zooms (40000 vs 2500 at z11; 6400 vs 1500 at z12) — B's tiles will contain vastly more small buildings. The `area` and `height` type declarations are also directly incompatible (int vs float), and `area` is computed on a spheroid in A versus a Web Mercator plane in B, so the same building gets **different numeric `area` values** on the two sides (Mercator area is inflated by roughly 1/cos²(latitude), i.e. ~2× at 45°, ~4× at 60°) — meaning the two pipelines' area *thresholds* aren't even comparable in the same units.

---

## 9. Confidence & evidence notes

### High confidence — read directly from source files on both sides

- **Everything in §1–§8 about layer names, attribute allowlists, declared types, zoom windows, tippecanoe flags, filters, projection lists, and metadata fields.** The clone of `MJJ203/rbt-data-generator` succeeded, so `config/layers.yml` (798 lines), the eight schema SQL files (7,007 lines), and the `src/rbt/tiles/*.py` command builders were all read in full. No documentation prose was needed for any structural claim.
- **Side B's attribute sets** were derived by parsing the final top-level `SELECT` of each `CREATE VIEW/MATERIALIZED VIEW rbt.<layer>` statement, then hand-resolving the `SELECT *` cases (`highway_z*`→`highway`, `landcover_z*`→`landcover`, `utility_point_z*`→`utility_point`, `railway_z6`→`railway`, `geonames_hydrographic`→`geonames_hydrographic_enhanced`, `port_surface`→`port_surface_enhanced`, `aeroway_surface`/`waterway`/`inland_water_intermittent`/`dam_label`/`yard_label` read directly). Combined with the verified absence of `-y`/`-x` in B's codebase, these column lists **are** B's tile attribute sets.
- **The absence of `--accumulate-attribute` on both sides** — grepped, zero hits in either repo. No attribute aggregation on either side.

### Medium confidence — one inferential step

- **Side A's `attributes[]` → tippecanoe `-y` mapping.** The `export/*.json` schema is clearly declarative (`layer_id`, `geometry_type`, `attributes[]` with types, `tippecanoe_options`, `ogr_export_options`), and the one hand-written tiler in the repo (`scripts/overture/tile.sh`) uses `-y`/`-T` in exactly the shape those fields describe. But **no code in `rbt-schema` reads `export/*.json`** — the only `scripts/` content is the three Overture shell scripts. The consumer is external to this repo, so the exact flag mapping (`attributes[].name` → `-y`, `attributes[].type` → `-T`) is inferred, not observed.
- **Side A's source view per layer.** `layer_id` matches a `export.<layer_id>` materialized view in `carto_sql/` for all 58 layers (verified by cross-listing both name sets), so the source binding is by convention rather than by an explicit `source_table` field like B's.

### Low confidence / flagged unknowns

- **Side A emits only EPSG:3857.** Inferred from three negatives: no projection field in any `export/*.json`, no `crs` in `metadata.py`, no `-s`/`-t_srs` anywhere in the repo. If the external consumer injects `-t_srs`/`-s` per run, A could emit 3395/4326 too — the *schema files* carry no projection information either way. This is the largest open question in the comparison.
- **`max_detail_const: 14`** appears in `export/pier_polygon.json` and nowhere else in either repo. Not a tippecanoe option name; likely intended as `--extra-detail`/`-D`. Effect unknown without the external consumer.
- **Side A's `physical_labels` ↔ B's `mountain_label` mapping** is a judgment call. A's source is `aux_data.ne_physical_centerlines` (all NE physical centerlines); B's is `naturalearth.ne_10m_geography_regions_polys` via `CG_ApproximateMedialAxis` (mountain ranges specifically). Overlapping but not co-extensive; the shared attribute vocabulary (`featurecla`, `min_label`, `max_label`, `scalerank`, `name`, `name_en`) supports the pairing.
- **`airport_polygon` ↔ `aeroway_surface`** is likewise approximate — B explicitly unions aprons from `import.aeroway_polygon` alongside aerodrome polygons; A's 3-attribute config doesn't reveal its scope.

### Pre-existing defects on the reference side (affect what its tiles can contain)

Documented in the reference's own `docs/database-schema.md` and confirmed against the SQL:

1. **`rbt.building` DDL is commented out** (`cultural-core.sql` lines 806–830) while `layers.yml` still registers `rbt.building`/`_z10`/`_z11`/`_z12` as tile sources. B's building tiles depend on a pre-existing table or the DuckDB path.
2. **`rbt.populated_places*` query a nonexistent `import.places` table** (imposm creates `city_point`, with `place` instead of `class` and no `ne_id`), so `rbt schema run cultural` cannot create those views against a current database — B's `populated_places` layer is unbuildable as written.
3. **`dam_surface` references `filter_ref: utility`**, applying a pole/tower subclass filter to dam polygons — near-certainly a copy-paste error.
4. **Three `int_attrs` coercions target nonexistent columns** (`mountain_label.elevation`, `runway_curve.aerodrome_id`, `aeroway_surface.osm_runway_id`) — silent no-ops.
5. **hstore `tags` columns reach tiles** on `lock`, `lock_label`, `yard_label`, `grain_srf`, `grain_srf_pnt` because no `-x` excludes them.

### Symmetric finding worth noting

Both sides independently define **`sports_ground` and `golf_course` views that are not registered as tile layers** — A has `export.sports_ground` / `export.golf_course` matviews in `carto_sql` with no matching `export/*.json`; B has `rbt.sports_ground` / `rbt.golf_course` absent from `layers.yml`. Strong evidence of shared lineage and parallel abandonment of the same two layers.
