# Import Layer Schema Comparison: imposm3 + Auxiliary Sources

**Side A:** `rbt-schema` (this repository)
**Side B:** `rbt-data-generator` ([docs](https://mjj203.github.io/rbt-data-generator/), source: `github.com/MJJ203/rbt-data-generator`)
**Scope:** OSM imposm3 mapping schemas and non-OSM auxiliary source import schemas. Data schemas only — not code, tooling, or execution flow.
**Method:** Source-to-source comparison. The reference repository was cloned, so findings are file-level rather than documentation-derived. Reference-side citations are given as repo-relative paths against `https://github.com/MJJ203/rbt-data-generator` at branch `main`.
**Date:** 2026-07-29

Part 1 of 4. See `README.md` in this directory for the consolidated cross-layer analysis.

---

# OSM/imposm3 + Auxiliary Import Schema Diff
## `rbt-schema` (Side A) vs `rbt-data-generator` (Side B)

### Provenance of evidence

**Both sides were read from actual source files.** The reference repository cloned successfully (it is public: `github.com/mjj203/rbt-data-generator`, GPL-3.0, default branch `main`, last push 2026-07-17), so nothing in this report is inferred from prose documentation except where explicitly flagged in §7.

| Side | Path | Content |
|---|---|---|
| A | `/Users/jonesmj/github/RBT/rbt-schema/import/osm/*.yml` | 38 imposm mapping fragments (one table each) |
| A | `import/aux_data/*.json` | 24 ogr2ogr loader definitions |
| A | `scripts/overture/{fetch,shard,tile}.sh` | Overture buildings path (bypasses PostGIS) |
| B | `setup/data-sources/osm/imposm-mapping.yaml` (reference repo) | 1,893-line consolidated mapping, 29 tables |
| B | `setup/data-sources/osm/imposm-config.json`, `src/rbt/config.py`, `src/rbt/importers/osm.py` | srid, connection prefix, imposm flags |
| B | `src/rbt/importers/{reference,geonames,buildings}.py` | Non-OSM dataset registries |
| B | `setup/data-sources/overture/duckdb-building-export.sql` | Overture buildings schema |

---

## 1. Table / layer inventory diff

**A has 38 imposm tables; B has 29.**

### 1a. Present in both, identical table name (11)

`aeroway_linestring`, `aeroway_polygon`, `builtup_area`, `city_point`, `country_point`, `island_point`, `island_polygon`, `park_polygon`, `shipway_linestring`, `state_point`, `waterway_relation`

### 1b. Present in both but renamed (17 pairs)

A consistently renames to a `<theme>_<geometrytype>` convention; B uses a mix of MVT-layer-style names (`_label`, `_stations`) and bare theme names.

| A (rbt-schema) | B (reference) | Note |
|---|---|---|
| `highway_linestring` | `highway` | |
| `railway_linestring` | `railway` | |
| `waterway_linestring` | `waterway` | |
| `water_polygon` | `water` | |
| `water_point` | `water_label` | |
| `landcover_polygon` | `landcover` | |
| `landuse_polygon` | — | see 1c (A-only) |
| `mountain_point` | `mountain_peak` | |
| `mountain_linestring` | `mountain_label` | B's "label" table is a linestring |
| `barrier_linestring` | `barrier` | |
| `barrier_point` | `barrier_label` | |
| `transportation_point` | `transportation_label` | |
| `transportation_polygon` | `transportation_stations` | |
| `utility_linestring` | `utility_linestrings` | plural on B |
| `utility_polygon` | `utility_stations` | |
| `utility_point` | `utility_stations_label` | |
| `aeroway_point` | `aerodrome_label_point` | structurally different — see §4 |
| `poi_point` | `poi` | |

### 1c. Present only in A (10)

`aerialway_linestring`, `building_polygon`, `building_relation`, `highway_point`, `highway_polygon`, `highway_relation`, `landuse_polygon`, `pier_linestring`, `pier_polygon`, `poi_polygon`

The two most consequential:

- **`building_polygon` / `building_relation`** — B has **no OSM building table at all**. Its `imposm-mapping.yaml` mentions `building` only as a subordinate mapping key inside `poi` and `utility_stations_label`. B sources buildings exclusively from Overture (§5). A keeps a full imposm building schema *and* an Overture path, but has disabled the OSM one downstream (`export/building_polygon.json.skip`, `carto_sql/031_building.sql.skip`).
- **`landuse_polygon`** — A splits landuse into two tables. `builtup_area` keeps the "settled footprint" classes, `landuse_polygon` carries the institutional/cemetery/military/harbour classes plus keys B never maps here (`cemetery: __any__`, `man_made: [works]`, `seamark:type: [harbour, anchorage, radar_station]`, `waterway: [dam]`). B collapses everything into one `builtup_area`.

`highway_polygon` and `pier_polygon`/`pier_linestring` are also new surfaces in A — B has no way to get pedestrian-area or pier polygons out of imposm.

### 1d. Present only in B (1)

`continent_point` — `place: continent`, columns `osm_id, geometry, name, name_en, name_de, tags`, `filters: require: name: [__any__]`. A drops continent labels from the import layer entirely.

---

## 2. Per-table column diffs

### 2.1 Tables with zero column difference

**`water_polygon` (A) ≡ `water` (B)** — identical column list, identical types (including `validated_geometry`), identical `filters: reject: covered: ["yes"]`, identical mapping. Only the table name differs.

**`aeroway_polygon`** — identical column sets (19 columns, ordering differs only). Mappings differ, see §3.

### 2.2 `name_de`: B has it, A almost entirely dropped it

B attaches `*name_de` (`key: name:de`) to `city_point`, `country_point`, `state_point`, `island_point`, `island_polygon`, `continent_point`. A carries `name_de` on exactly one table, `aerialway_linestring`:

```25:27:import/osm/aerialway_linestring.yml
  - key: name:de
    name: name_de
    type: string
```

Since B sets `tags: load_all: true` and both sides keep an `hstore_tags` column, German names remain reachable via `tags->'name:de'` on A — but as a first-class column they are gone.

### 2.3 `intermittent` / `seasonal` / `tunnel` / `bridge` → `is_*` boolean rename

A systematically prefixes booleans with `is_`. This breaks every downstream reference:

| Table | B column | A column |
|---|---|---|
| `waterway`/`waterway_linestring` | `tunnel`, `bridge`, `intermittent` | `is_tunnel`, `is_bridge`, `is_intermittent` |
| `water_label`/`water_point` | `intermittent` | `is_intermittent` |
| `landcover`/`landcover_polygon` | `intermittent`, `seasonal` | `is_intermittent`, `is_seasonal` |

Note the inconsistency: `water_polygon` keeps B's unprefixed `intermittent`, while `water_point` renames it to `is_intermittent`. Same theme, two conventions.

### 2.4 `highway_linestring` (A) vs `highway` (B)

A adds **14 columns** and renames one; B adds none.

Added by A: `usage`, `access`, `toll` (bool), `expressway` (bool), `bicycle`, `foot`, `horse`, `mtb_scale` (`key: mtb:scale`), `sac_scale`, `level`, `is_area`, `is_floating` (`key: floating`), `destroyed_bridge` (`key: destroyed:bridge`), `destroyed_highway` (`key: destroyed:highway`).

Renamed: B's `lane` → A's `lanes`, both reading `key: lane`.

```769:771:import/osm/highway_linestring.yml
    - name: lanes
      key: lane
      type: string
```

(Worth flagging: the OSM tag is `lanes`, not `lane`. Both sides read the wrong key; A's rename fixes the *column* name but not the *tag* key, so the column is still populated from a near-nonexistent tag.)

A also adds `_resolve_wikidata: false`, which B's `highway` lacks.

### 2.5 `railway_linestring` (A) vs `railway` (B)

A adds **8 columns**: `railway` (raw `key: railway` string, alongside the existing `class`/`subclass` mapping columns), `is_ramp`, `is_ford`, `is_oneway` (direction), `is_indoor`, `is_area`, `layer`, `level`. Mappings are byte-identical (21 `railway` values, 8 `route`, 8 `route_master`).

### 2.6 `transportation_polygon` (A) vs `transportation_stations` (B) — A drops the computed area

This is the most significant *regression* in the diff:

| B `transportation_stations` | A `transportation_polygon` |
|---|---|
| `area` — **`type: area`** (imposm-computed polygon area) | absent |
| `z_order` — **`type: wayzorder`** | absent |
| `platforms` | absent |
| `public_transport` | absent |
| `man_made` | absent |
| — | `name_en` added |
| — | `network` added |
| — | `is_area` (bool from the `area` *tag*) added |

A replaced a computed geometric-area column (`type: area`) with a boolean read from the `area=yes` OSM tag (`is_area`). These are unrelated quantities that happen to share a name. Any zoom-based area filter on this table silently loses its input.

The same `type: area` → nothing substitution happens on `utility_polygon` and `utility_linestring`.

### 2.7 `transportation_point` (A) vs `transportation_label` (B)

A adds `name_en`, `network`, `uic_ref`, `funicular`, `is_indoor`. A drops `public_transport` and `man_made`.

### 2.8 `utility_*` family

| | A `utility_point` | B `utility_stations_label` |
|---|---|---|
| `ele` | **`integer`** | `string` |
| `height` | **`integer`** | `string` |
| A-only columns | `seamark_type`, `ref`, `generator_output`, `surface_type` (`key: surface`), `layer`, `level`, `resource`, `mineshaft_type`, `disused` (bool) | |

| | A `utility_polygon` | B `utility_stations` |
|---|---|---|
| `geometry` | **`validated_geometry`** | `geometry` |
| `area` | absent | `type: area` |
| A-only columns | `seamark_type`, `ref`, `access`, `type`, `content`, `surface_type`, `capacity`, `height`, `ele` (integer), `location`, `layer`, `level`, `is_area` | |

| | A `utility_linestring` | B `utility_linestrings` |
|---|---|---|
| `ele` | **`integer`** | `string` |
| `area` | absent | `type: area` |
| A-only columns | `seamark_type`, `surface_type`, `layer`, `level`, `is_area` | |

Two data-quality bugs in A's `utility_point`:

```2338:2340:import/osm/utility_point.yml
    - name: generator_output 
      key: generator:output
      type: string
```

The column name has a **trailing space** — it will become a quoted `"generator_output "` identifier in Postgres. B has no `generator_output` on the label table at all (only on `utility_stations`), so this is a new column introduced with the defect.

Also, `ele` and `height` moved from `string` to `integer`. OSM `ele`/`height` values routinely carry units (`1200 m`, `35 ft`) or decimals; imposm's `integer` type discards non-parsing values as NULL rather than preserving the raw string. Same change applies to `mountain_point.ele` (B: `string`, A: `integer`) and `aeroway_point.ele` (B `aerodrome_label_point`: `string`, A: `integer`) — while `aeroway_polygon.ele` and `aeroway_linestring.ele` stay `string` on both sides, so A is now internally inconsistent about `ele` typing across the aeroway family.

### 2.9 `poi_point` (A) vs `poi` (B) — 6 columns → 16

B's `poi` is minimal:

**Reference** — [`setup/data-sources/osm/imposm-mapping.yaml:1559-1574`](https://github.com/MJJ203/rbt-data-generator/blob/main/setup/data-sources/osm/imposm-mapping.yaml#L1559-L1574)

```yaml
  poi:
    type: point
    columns:
    - name: osm_id
      type: id
    - name: geometry
      type: geometry
    - name: class
      type: mapping_key
    - name: subclass
      type: mapping_value
    - name: name
      key: name
      type: string
    - name: tags
      type: hstore_tags
```

A adds `name_en`, `information`, `ref`, `religion`, `level`, `is_indoor`, `layer`, `sport`, `operator`, `brand` — and duplicates the whole thing into a second `poi_polygon` table with an identical column list and mapping.

### 2.10 `barrier` family

A adds `name`, `name_en`, `wheelchair`, `locked`, `layer` to both `barrier_linestring` and `barrier_point`, plus `is_area` on the linestring. B's `barrier`/`barrier_label` have no name columns at all.

### 2.11 `landcover_polygon` / `mountain_*` / `shipway_linestring`

- `landcover_polygon`: A adds `surface`.
- `mountain_point` and `mountain_linestring`: A adds `wikipedia` and a column literally **named `mapping_key`** of `type: mapping_key`:

```1445:1446:import/osm/mountain_point.yml
    - name: mapping_key
      type: mapping_key
```

Every other table in A names this column `class`. These two tables therefore expose `subclass` + `mapping_key` instead of `subclass` + `class`.

- `shipway_linestring`: A drops B's `z_order` (`type: wayzorder`) and — a bug — declares `layer` with no `key:`:

```1930:1931:import/osm/shipway_linestring.yml
    - name: layer
      type: integer
```

B has `key: layer` via the `*layer` anchor. A's column will always be NULL.

### 2.12 `wayzorder` usage collapsed

B uses `type: wayzorder` on `shipway_linestring` and `transportation_stations`. A uses it on exactly one table, `aerialway_linestring` (which B doesn't have), and nowhere else. Effectively **`wayzorder` disappears from the shared surface**.

### 2.13 Small additive diffs on the "identical-name" tables

- `aeroway_linestring`: A adds `name_en`.
- `builtup_area`: A adds `name_en`, `layer`, `level`.
- `city_point`/`country_point`/`state_point`/`island_*`: A removes `name_de` (§2.2); no other changes.
- `waterway_relation`: columns identical on both sides.

---

## 3. Tag mapping / filter diffs

### 3.1 The headline change: `__any__` catch-alls replaced by curated allow-lists

B leans heavily on `__any__` for POIs and utilities; A replaces those with explicit value lists. This is the single largest semantic difference in the whole import layer.

| Table | B mapping | A mapping |
|---|---|---|
| `poi` / `poi_point` | `amenity: __any__`, `tourism: __any__`, `leisure: __any__`, `sport: __any__`, `shop: __any__`, `office: __any__`, `landuse: __any__`, `historic: __any__`, `building: __any__`, `boundary: __any__` | ~50 `amenity` values, 19 `tourism`, 15 `leisure`, ~90 `sport`, ~100 `shop`, `office: [diplomatic]`, `landuse: [basin, brownfield, cemetery, reservoir, winter_sports]`, `historic: [monument, castle, ruins]`, `building: [dormitory]`, **`boundary:` removed**, **`waterway: [dock]` added** |
| `transportation_label` / `transportation_point` | `highway: __any__`, `railway: __any__`, `public_transport: __any__` | `railway: [halt, station, subway_entrance, train_station_entrance, tram_stop, yard]`, `highway: [bus_stop]`, `public_transport: [platform, station, stop_position]`, **`aerialway: [station]` added** |
| `utility_stations` / `utility_polygon` | `power: __any__`, `pipeline: __any__`, `man_made: __any__` | `power: [station, substation, plant, plant_part, generator]`, `pipeline: [substation]`, `man_made: [pumping_station, silo, wastewater_plant, water_works, storage_tank]`, **`building: [silo, water_tower, storage_tank]` added** |
| `utility_stations_label` / `utility_point` | `power: __any__`, `man_made: __any__` | `power: [line, cable, generator, pole, substation, transmission, tower]`, `man_made:` 17 explicit values incl. `mineshaft, oil_well, petroleum_well, offshore_platform, lighthouse, communications_tower, telescope, lock_gate` |
| `utility_linestrings` / `utility_linestring` | `power: __any__`, `pipeline: __any__`, `man_made: __any__`, `communication: __any__` | `man_made: [pipeline]`, `power: [line, minor_line, cable]`, `communication: [line, cable]`, **`pipeline:` key removed entirely** |

The practical effect is a large reduction in imported row count and a large reduction in `subclass` cardinality. Anything downstream that switched on an unenumerated `subclass` value will now see zero rows.

### 3.2 `aeroway_polygon`: A adds the aerodrome classes

B's polygon mapping comes from a YAML anchor that omits `aerodrome`, `heliport`, `helipad` (they are routed to `aerodrome_label_point`'s `polygons` branch instead) and contains **duplicate entries**:

**Reference** — [`setup/data-sources/osm/imposm-mapping.yaml:4-20`](https://github.com/MJJ203/rbt-data-generator/blob/main/setup/data-sources/osm/imposm-mapping.yaml#L4-L20)

```yaml
def_aeroway_polygon_mapping: &aeroway_polygon_mapping
  - runway
  - taxiway
  - apron
  - runway
  - taxilane
  - taxiway
  ...
```

A's `aeroway_polygon` lists 17 de-duplicated values including `aerodrome`, `heliport`, `helipad`.

### 3.3 `aeroway_point` adds `gate`

A's `aeroway: [aerodrome, heliport, helipad, airstrip, airfield, spaceport, gate]`. B's points branch has the same list minus `gate`. Conversely B's polygons branch has `aeroway:suborbital: [spaceport]`, which A drops.

### 3.4 `island_*`: A adds `islet`

B: `place: [island]`. A: `place: [island, islet]` on both point and polygon.

### 3.5 `park_polygon`: A adds golf features

Columns are identical between the two sides. The only mapping difference is A's added key:

```1531:1534:import/osm/park_polygon.yml
      golf:
      - bunker
      - green
      - fairway
```

### 3.6 `highway`: A adds three values and two keys

A adds highway values `corridor`, `busway`, `bus_guideway`, and two new mapping keys: `man_made: [pier, breakwater, groyne]` and `public_transport: [platform]`. Note this makes `highway_linestring`, `highway_polygon`, and `pier_linestring` all compete for the same `man_made=pier/breakwater/groyne` ways.

### 3.7 `builtup_area`: A removes 5 matchers

A drops `landuse: [cemetery, religious, military]`, `amenity: [grave_yard]`, and `memorial: [graveyard]` from `builtup_area` — all five reappear in A's new `landuse_polygon`. So the classes aren't lost, they moved tables.

### 3.8 `filters:` — A removes three `require: name` guards

| Table | B | A |
|---|---|---|
| `water_label` / `water_point` | `require: name: [__any__]` | **no filters** |
| `mountain_label` / `mountain_linestring` | `require: name: [__any__]` | **no filters** |
| `island_*`, `city_point`, `country_point`, `state_point` | `require: name` | `require: name` (kept) |

Dropping the name requirement on `water_point` and `mountain_linestring` means unnamed water bodies and ridges now enter what are, by B's design, label-only tables. Given both tables exist to carry text labels, this looks unintended.

`filters: reject` blocks:
- `water_polygon`/`water`: identical (`covered: ["yes"]`) on both sides.
- `building_polygon` (A-only): `reject: building: ["no","none","No"]`, `building:part: ["no","none","No"]`, `location: ["underground"]`, `man_made: ["bridge"]`. No B counterpart exists.

### 3.9 `type_mappings` — used only by B

B uses `type_mappings` on exactly one table, `aerodrome_label_point` (§4). A uses `type_mappings` **nowhere**.

### 3.10 `from_member` — used only by A

A's `building_relation` is the only place in either repo using `from_member`, and it uses it to carry member-way tags alongside relation-level tags of the same name:

```500:541:import/osm/building_relation.yml
    - name: building
      from_member: true
      key: building
      type: string
    ...
    - name: relbuildingheight
      key: building:height
      type: string
    - name: relheight
      key: height
      type: string
```

So `height`/`buildingheight`/`levels`/`buildinglevels` come from the member way, while `relheight`/`relbuildingheight`/`rellevels`/`relbuildinglevels` come from the relation. B has no equivalent.

### 3.11 `mapping_key` / `mapping_value` coverage

Both sides use `class: mapping_key` + `subclass: mapping_value` as the standard pair. Differences:

- A's `mountain_point`/`mountain_linestring` name the key column `mapping_key` instead of `class` (§2.11).
- A's `railway_linestring` and `waterway_linestring` carry **both** `class`/`subclass` *and* a raw `railway`/`waterway` string column reading the same tag. B does this for `waterway` but not `railway`.
- B's `aerodrome_label_point` places `subclass`/`class` after the `type_mappings`-driven columns; A's `aeroway_point` uses the ordinary position.

---

## 4. Geometry & projection differences

### 4.1 SRID

- **B pins srid 4326**, non-default for imposm3 (whose default is 3857):

**Reference** — [`src/rbt/config.py:86`](https://github.com/MJJ203/rbt-data-generator/blob/main/src/rbt/config.py#L86)

```python
    osm_srid: int = 4326
```

  passed explicitly on the command line as `-srid 4326` (`src/rbt/importers/osm.py:312-313`), overridable via `OSM_SRID`.

- **A has no srid configuration anywhere in the repository.** There is no `imposm-config.json`, no CLI wrapper, and no environment file. Grepping the whole repo for `srid|3857|4326` returns only the aux-data ogr2ogr options and the Overture shard script. The srid must therefore be supplied by an out-of-repo orchestrator — **this is unverifiable from Side A alone** and is the biggest gap in this comparison. If the caller omits `-srid`, imposm defaults to 3857 and every geometry in A lands in Web Mercator while B's are in WGS84.

### 4.2 `validated_geometry` vs `geometry`

| Table | B | A |
|---|---|---|
| `water` / `water_polygon` | `validated_geometry` | `validated_geometry` |
| `landcover` / `landcover_polygon` | `validated_geometry` | `validated_geometry` |
| `park_polygon` | `validated_geometry` | `validated_geometry` |
| `utility_stations` / `utility_polygon` | `geometry` | **`validated_geometry`** (upgraded) |
| `building_polygon`, `building_relation` | n/a | `validated_geometry` |

All other polygon tables use plain `geometry` on both sides — notably `aeroway_polygon`, `builtup_area`, `island_polygon`, `transportation_polygon`/`transportation_stations`, `highway_polygon`, `landuse_polygon`, `pier_polygon`.

### 4.3 The `areas:` block — B only

B declares a global polygon/line resolution policy that A has no equivalent for:

**Reference** — [`setup/data-sources/osm/imposm-mapping.yaml:22-39`](https://github.com/MJJ203/rbt-data-generator/blob/main/setup/data-sources/osm/imposm-mapping.yaml#L22-L39)

```yaml
areas:
  area_tags:
    - building
    - landuse
    - leisure
    - natural
    - aeroway
    - landcover
    - landform
    - wetland
    - crop
    - water
    - boundary
    - place
  linear_tags:
    - highway
    - railway
    - waterway
```

Without this, closed ways carrying e.g. `landcover=trees` or `place=suburb` are not promoted to polygons by default. Because A's YAML files are per-table fragments with no assembling header in the repo, either the orchestrator injects an `areas:` block or A relies on imposm's built-in defaults — again unverifiable from Side A.

### 4.4 `tags: load_all` — B only

**Reference** — [`setup/data-sources/osm/imposm-mapping.yaml:1-2`](https://github.com/MJJ203/rbt-data-generator/blob/main/setup/data-sources/osm/imposm-mapping.yaml#L1-L2)

```yaml
tags:
  load_all: true
```

Every `hstore_tags` column in B receives the complete tag set. Without this, imposm populates `hstore_tags` only with tags referenced elsewhere in the mapping — which means A's `tags` columns are potentially far sparser than B's, and the `name:de` fallback discussed in §2.2 may not actually work on A.

### 4.5 Point/polygon merging: `type: geometry` + `type_mappings`

B's `aerodrome_label_point` is a single mixed-geometry table:

**Reference** — [`setup/data-sources/osm/imposm-mapping.yaml:441-443`](https://github.com/MJJ203/rbt-data-generator/blob/main/setup/data-sources/osm/imposm-mapping.yaml#L441-L443)

```yaml
  aerodrome_label_point:
    type: geometry
    columns:
```

with a `type_mappings:` block containing separate `points:` and `polygons:` matchers, and an `area` column of `type: area` (meaningful only for the polygon rows). A abandons this pattern entirely: `aeroway_point` is `type: point` with a flat `mapping:` block and no `area` column, while aerodrome polygons are folded into `aeroway_polygon`. A's split is cleaner but the two sides produce structurally incompatible outputs — one table vs two, and B's `aerodrome` column (`key: aerodrome`) is dropped by A.

### 4.6 Relation handling

| | A | B |
|---|---|---|
| `relation_member` tables | `building_relation`, `highway_relation`, `waterway_relation` | `waterway_relation` only |
| `member_id` / `member_role` | all three | yes |
| `from_member` | `building_relation` only | never |
| Geometry on relation table | `building_relation`: `validated_geometry`; `waterway_relation`: `geometry`; **`highway_relation`: no geometry column at all** | `waterway_relation`: `geometry` |

`highway_relation` being geometry-less makes it a pure attribute join table (`osm_id`, `member`, `role`, `network`, `ref`, `route`, `tags`) — a pattern absent from B.

### 4.7 Generalized tables

**Neither side defines `generalized_tables`.** No `generalized_tables:` key exists in A's 38 files or B's `imposm-mapping.yaml`. Both push all simplification into the downstream SQL layer (A: `carto_sql/*.sql`; B: `setup/data-sources/schemas/*/*.sql` materialized views such as `rbt.water_simplified`).

---

## 5. Non-OSM / auxiliary source schema diffs

### 5.1 Mechanism

Both sides use `ogr2ogr` into PostGIS, but the schema-authoring model differs:

- **A**: declarative JSON, one file per source, with raw ogr2ogr flags in an `aux_load_options` string. No target column list, no target table type — the schema is whatever the source file happens to have.
- **B**: a Python `OgrDataset` dataclass registry with typed fields (`schema`, `table`, `nlt`, `a_srs`, `t_srs`, `open_options`, `layer_creation`), and a single canonical command builder that appends `-lco GEOMETRY_NAME=geometry -lco DIM=2 -lco UNLOGGED=ON` to **every** load (`src/rbt/importers/_support.py:103`). A applies `GEOMETRY_NAME=geometry` only to the four text-gazetteer loads and never sets `DIM` or `UNLOGGED`.

### 5.2 Dataset-by-dataset

| Dataset | A → table | B → table | Divergence |
|---|---|---|---|
| FieldMaps ADM0/1/2 polygons | `aux_data.fieldmaps_adm0_polygon` (**singular**), `..._adm1_polygons`, `..._adm2_polygons` | `fieldmap.adm0`, `fieldmap.adm1`, `fieldmap.adm2` | **A reads `.gpkg.zip`; B reads `.parquet`** over `/vsicurl/`. Same upstream editions (ADM0 = `adm0/osm/all`, ADM1/2 = `edge-matched/humanitarian/intl`). |
| FieldMaps lines | `aux_data.fieldmaps_adm{0,1,2}_lines` | `fieldmap.adm{0,1,2}_lines` | |
| FieldMaps points | `aux_data.fieldmaps_adm{0,1,2}_points` | `fieldmap.adm{0,1,2}_labels` | B renames points→labels |
| FieldMaps USA subset | — | `fieldmap.usa` (derived: `ST_Dump(ST_SimplifyPreserveTopology(ST_MakeValid(...,'method=structure'),0.00001))::geometry(Polygon,4326)` for `iso_3 IN ('GUM','PRI','MNP','ASM','UMI','VIR','USA')`) | **B-only** |
| OurAirports airports | `aux_data.ourairports_airports` | `ourairports.airport` | |
| OurAirports runways | `aux_data.ourairports_runways` | `ourairports.runway` | **Different geometry source columns**: A uses `longitude_deg`/`latitude_deg`, B uses `le_longitude_deg`/`le_latitude_deg`. The runways CSV has no plain `longitude_deg` column, so A's runway points are likely geometry-less. |
| Natural Earth | 11 named layers → `aux_data.ne_10m_admin_0_countries`, `ne_10m_glaciated_areas`, `ne_10m_geography_regions_polys`, `ne_10m_antarctic_ice_shelves_polys`, `ne_10m_geography_marine_polys`, `ne_10m_urban_areas`, `ne_10m_land`, `ne_10m_populated_places`, `ne_50m_lakes`, `ne_50m_ocean`, `ne_10m_lakes` | **entire** `natural_earth_vector.gpkg` → `naturalearth.*` (`-lco SCHEMA=naturalearth`, no `-nln`) | A cherry-picks 11 layers; B loads all ~100+. A-only layers: `ne_10m_land`, `ne_10m_populated_places`, `ne_10m_lakes`, `ne_50m_lakes`, `ne_50m_ocean` are explicitly named (B gets them implicitly). |
| NE physical centerlines | `aux_data.ne_physical_centerlines` from local `static_data/ne_physical_centerlines.fgb.zip` | — | **A-only**, and the only load from a vendored file rather than a URL |
| NGA GNS | 3 feature classes → `aux_data.nga_geonames_administrative_regions`, `..._hydrographic`, `..._populated_places` | 9 feature classes → `geonames.administrative_regions`, `hydrographic`, `hypsographic`, `populated_places`, `areas_localities`, `undersea`, `transportation_networks`, `spot_features`, `vegetation` | **B ingests 6 more GNS classes.** B strips the `nga_geonames_` prefix. |
| USGS gazetteer | `aux_data.usgs_domestic_names` from the **DomesticNames** product (`DomesticNames_National_Text.zip`) | `geonames.populatedplaces_national`, `geonames.historicalfeatures_national` from the **Topical** products | **Different USGS products entirely.** Neither side ingests the other's. |
| DOS LSIB | `aux_data.dos_lsib` from `data.geodata.state.gov/LSIB.gpkg`, `-nlt MULTILINESTRING` | — | **A-only.** B references LSIB only as upstream *provenance* of FieldMaps ADM0 (`docs/data-sources.md:80`), never ingests the GeoPackage. |
| DISDI MIRTA | **two** layers: `MirtaLocations` (`-nlt MULTIPOINT`) and `MirtaLocations_A` (`-nlt MULTIPOLYGON`) → `aux_data.mirtalocations`, `aux_data.mirtalocations_a`. URL `datacollects.blob.core.usgovcloudapi.net/abt-data/installations_ranges.zip` | **one** layer: `MirtaLocations_A` (`-nlt GEOMETRY`) → `mirta.us_military_installations`. URL `acq.osd.mil/eie/imr/rpid/disdi/Downloads/installations_ranges.zip` | A keeps the point layer; B drops it. Different hosts. A keeps the raw FileGDB layer names as table names; B renames semantically. |
| OSM water polygons | `aux_data.osm_ocean` | `rbt.osm_ocean` | A `-nlt MULTIPOLYGON`; B `-nlt PROMOTE_TO_MULTI` |
| OSM simplified water | `aux_data.osm_ocean_simplified` | `rbt.osm_ocean_simplified` | both reproject 3857→4326 |
| OSM coastlines | `aux_data.lines` (from `lines.shp`, no `aux_layer_name`) | `rbt.coastline` | A inherits the shapefile's `lines` name; B names it meaningfully |
| OSM Antarctica icesheet | `aux_data.icesheet_polygons` (from `icesheet_polygons.shp`) | `rbt.osm_antarctica_icesheet` | same naming issue |
| **Overture buildings** | **not in PostGIS at all** — `scripts/overture/*` (DuckDB → FlatGeobuf → tippecanoe) | `overture.building`, `overture.buildingpart` (ogr2ogr GeoParquet → PostGIS), **plus** a DuckDB path producing `rbt_building`/`rbt_building_label` | see §5.3 |

### 5.3 Overture buildings schema comparison

Both sides run a DuckDB-based export with nearly the same projection list, but the schemas differ in three ways.

A (`scripts/overture/shard.sh`) — per-file shard, `id, name, subtype, class, has_parts, height, area, geometry`:

```sql
ST_Area_Spheroid(geometry)  AS area,       -- true ground area, m^2
ST_Multi(geometry)          AS geometry     -- uniform MultiPolygon
...
WHERE area >= 1                             -- drop degenerate sub-meter polygons
```

B (`setup/data-sources/overture/duckdb-building-export.sql`) — same columns, but:

```sql
ST_Area(ST_Transform(b.geometry, 'EPSG:4326', 'EPSG:3857')) AS area,
```

| | A | B |
|---|---|---|
| `area` semantics | `ST_Area_Spheroid` — **true m² on the ellipsoid** | `ST_Area` in EPSG:3857 — **m² inflated by sec²(latitude)** |
| Geometry normalization | `ST_Multi(...)` → uniform MultiPolygon | left as-is |
| Row filter | `area >= 1` | none at table level |
| Output projections | 4326 only (`SRS 'EPSG:4326'`) | 3395, 3857, 4326 |
| Zoom variants | none — filtering deferred to a tippecanoe `-j` expression on `area` (≥40000 @ z11, ≥6400 @ z12) | `rbt_building_z10` (≥5000), `_z11` (≥2500), `_z12` (≥1500) views |
| Label points | none | `rbt_building_label` with `ST_PointOnSurface(geometry)::geometry(Point,4326)` |
| Building parts | dropped | `LEFT JOIN` on `type=building_part` distinct `building_id` |
| Release pin | resolved dynamically (`aws s3 ls ... \| tail -1`) | pinned `OVERTURE_RELEASE=2026-06-17.0` |
| PostGIS landing | never | `overture.building`, `overture.buildingpart` |

The `area` unit change is the important one: identical numeric thresholds mean very different real-world areas between the two pipelines, and the discrepancy grows with latitude. A's z11 threshold of 40000 true m² is roughly comparable to B's z10 threshold of 5000 Mercator-m² only near the equator.

### 5.4 Datasets present on exactly one side — summary

| A-only | B-only |
|---|---|
| DOS LSIB (`dos_lsib`) | FieldMaps USA subset (`fieldmap.usa`) |
| NE physical centerlines | 6 extra NGA GNS classes (hypsographic, areas_localities, undersea, transportation_networks, spot_features, vegetation) |
| USGS **DomesticNames** | USGS **Topical** PopulatedPlaces + HistoricalFeatures |
| MIRTA point layer (`MirtaLocations`) | Overture buildings in PostGIS |
| Explicitly-named `ne_10m_land`, `ne_10m_populated_places`, `ne_10m_lakes`, `ne_50m_lakes`, `ne_50m_ocean` | All remaining Natural Earth layers (implicit) |

---

## 6. Naming conventions

### 6.1 Database schema placement

| Layer | A | B |
|---|---|---|
| imposm3 OSM tables | schema **`osm`**, with imposm's **default `osm_` prefix** → `osm.osm_highway_linestring` | schema **`import`** (deployed to `public`), **no prefix** → `import.highway` |
| Non-OSM sources | single **`aux_data`** schema for everything | **per-source schemas**: `fieldmap`, `geonames`, `naturalearth`, `ourairports`, `mirta`, `overture`, `rbt` |
| Derived/tile-ready | `export` schema + per-domain working schemas (`aeroway`, `dam`, `infrastructure`) | single `rbt` schema (~105 views/matviews) |

A's placement is evidenced by 29 distinct `osm.osm_*` references across `carto_sql/*.sql`, e.g. `osm.osm_highway_linestring`, `osm.osm_waterway_relation`, `osm.osm_builtup_area`. B's is evidenced by the connection URL and by 25 distinct `import.*` references in the schema SQL:

**Reference** — [`src/rbt/config.py:124-126`](https://github.com/MJJ203/rbt-data-generator/blob/main/src/rbt/config.py#L124-L126)

```python
            f"postgis://{auth}@{self.database_host}:{self.database_port}"
            f"/{self.database_name}?prefix=NONE"
        )
```

The `prefix=NONE` query parameter is what suppresses the `osm_` prefix on B. **A therefore carries the prefix twice in effect** — schema `osm` *and* table prefix `osm_` — producing the stuttering `osm.osm_*` form.

### 6.2 Table naming style

- **A**: strict `<theme>_<geometry>` — `_point`, `_linestring`, `_polygon`, `_relation`. 36 of 38 tables follow it; the exceptions are `builtup_area` (inherited from B) and `building_relation`/`highway_relation`/`waterway_relation` (which use `_relation` for relation-member tables rather than a geometry suffix).
- **B**: mixed. Bare theme names (`water`, `highway`, `railway`, `waterway`, `landcover`, `barrier`, `poi`), MVT-layer names with `_label` (`water_label`, `mountain_label`, `barrier_label`, `transportation_label`, `utility_stations_label`, `aerodrome_label_point`), functional suffixes (`_stations`), and a few `<theme>_<geometry>` holdovers (`aeroway_polygon`, `shipway_linestring`, `park_polygon`, `island_polygon`).

A's convention is unambiguously more consistent. Note B's `mountain_label` is a `linestring` and `barrier_label` is a `point`, so `_label` on B encodes intent, not geometry.

### 6.3 Singular vs plural

- A: singular geometry suffixes throughout (`utility_linestring`, not `utility_linestrings`).
- B: `utility_linestrings` (plural), `utility_stations` (plural), `transportation_stations` (plural) sit next to singular `shipway_linestring`.
- A has one plural slip in aux data: `fieldmaps_adm0_polygon` while adm1/adm2 are `..._polygons`.

### 6.4 Aux table naming

- A: `<source>_<dataset>` prefixed (`nga_geonames_hydrographic`, `ourairports_airports`, `fieldmaps_adm1_lines`, `usgs_domestic_names`, `dos_lsib`) — the source is in the *table* name because everything shares one schema. Three tables escape the convention because `aux_layer_name` was omitted and the shapefile basename won: `aux_data.lines` (coastlines), `aux_data.icesheet_polygons`, `aux_data.mirtalocations_a`.
- B: source lives in the *schema*, so table names are short and semantic (`geonames.hydrographic`, `ourairports.airport`, `fieldmap.adm1_lines`, `mirta.us_military_installations`). B has no unnamed-shapefile leakage.

### 6.5 Column naming

- Booleans: A prefixes `is_` (`is_tunnel`, `is_bridge`, `is_intermittent`, `is_area`, `is_oneway`, `is_floating`, `is_indoor`, `is_ramp`, `is_ford`, `is_seasonal`). B is inconsistent — `is_tunnel`/`is_bridge`/`is_area` via anchors on some tables, bare `tunnel`/`bridge`/`intermittent`/`seasonal` on others.
- Namespaced tags flattened by replacing `:` with `_`: `seamark:pylon:category` → `seamark_pylon_category`, `plant:source` → `plant_source`, `railway:yard:size` → `yard_size`. Both sides agree on this.
- Mapping columns: `class`/`subclass` on both sides, except A's `mountain_*` tables using `mapping_key` (§2.11).

### 6.6 File organization

- **A**: 38 separate `import/osm/*.yml` fragments, one table per file, no anchors, definitions duplicated verbatim across files. Top-level indentation is **inconsistent** — 34 files are indented 2 spaces (fragments intended to be spliced under a `tables:` key) while 4 start at column 0: `aerialway_linestring.yml`, `pier_linestring.yml`, `pier_polygon.yml`, `transportation_point.yml`. There is no assembling file in the repo, so whatever concatenates these must normalize indentation or the 4 outliers will land at the wrong nesting level.
- **B**: one 1,893-line `imposm-mapping.yaml` with ~60 YAML anchors (`&name`, `&layer`, `&tunnel`, …) aliased across tables, wrapped in `tags:` / `areas:` / `tables:` top-level keys.

---

## 7. Confidence & evidence notes

### High confidence — read directly from source on both sides

Everything in §1, §2, §3, §4.2, §4.3, §4.4, §4.5, §4.6, §4.7, §5, §6.2–§6.6. Both repositories were read file-by-file; the reference clone succeeded so no prose interpretation was needed.

### High confidence — inferred from consistent internal usage

- **A's imposm output is `osm.osm_<table>`.** Not stated in any config (there is none); derived from 29 consistent `osm.osm_*` references in `carto_sql/*.sql`. The `osm_` prefix is imposm3's documented default, and the `osm` schema qualifier appears on every single reference, so both halves are well-supported — but neither is *declared* anywhere in Side A.
- **B's imposm output is `import.<table>` (staged) / `public.<table>` (deployed).** Directly supported by `?prefix=NONE` in `config.py:126`, `-write -diff -optimize` in `osm.py:301-323`, and 25 `import.*` references in the schema SQL. Corroborated by `docs/database-schema.md:22`.

### Unverifiable from Side A — flagged gaps

1. **SRID for A's OSM import.** No `-srid` value exists in the repository. If unset, imposm defaults to 3857 while B explicitly uses 4326. This is a fundamental projection divergence I cannot confirm or rule out. *This is the single most important thing to check outside this repo.*
2. **A's global mapping header.** No `tags: load_all`, no `areas: area_tags/linear_tags`, and no file that assembles the 38 fragments. Consequences: (a) A's `hstore_tags` columns may be far sparser than B's; (b) closed ways with `landcover`/`place`/`water`/`boundary` tags may not be promoted to polygons; (c) the 4 non-indented fragment files may be spliced incorrectly. All three depend on orchestrator behavior not present in the repo.
3. **A's replication/diff settings.** B has `imposm-config.json` with `replication_url`, `replication_interval: 24h`, `diff_state_before: 24h`. A has no equivalent, so continuous-update behavior is unknown.

### Sourced from documentation rather than code (one item only)

The claim that **B does not ingest DOS LSIB** was verified two ways: (a) a repo-wide grep for `lsib|geodata.state.gov` matched only `docs/*.md`, never `src/` or `setup/`; and (b) `docs/data-sources.md:80` explains LSIB appears solely as upstream provenance of the FieldMaps ADM0 edition ("It combines OSM coastlines with U.S. Department of State LSIB boundaries"). I am confident B has no LSIB table, but the *reason* comes from prose.

### Defects noticed in A while diffing (all newly introduced relative to B)

1. `utility_point.yml:2338` — column name `generator_output ` has a trailing space.
2. `shipway_linestring.yml:1930` — `layer` column declared with no `key:`; will always be NULL (B's `*layer` anchor has `key: layer`).
3. `transportation_polygon.yml` / `utility_polygon.yml` / `utility_linestring.yml` — B's computed `area` (`type: area`) column dropped; on `transportation_polygon` it was replaced by a same-root but semantically unrelated `is_area` boolean read from the `area=yes` tag.
4. `water_point.yml` / `mountain_linestring.yml` — B's `filters: require: name: [__any__]` removed from tables whose purpose is text labels.
5. `import/aux_data/fieldmaps_adm2_polygons.json` — `"aux_load_options": "-nlt MULTILINESTRING"` on a polygons dataset (adm0/adm1 polygons correctly use `MULTIPOLYGON`).
6. `import/aux_data/ourairports_runways.json` — `X_POSSIBLE_NAMES=longitude_deg`/`Y_POSSIBLE_NAMES=latitude_deg`; the runways CSV exposes `le_longitude_deg`/`he_longitude_deg`, so runway geometry is likely empty. B uses `le_longitude_deg`/`le_latitude_deg`.
7. `import/aux_data/fieldmaps_adm0_polygons.json` — target `aux_layer_name` is `fieldmaps_adm0_polygon` (singular) while adm1/adm2 are plural.
8. `osm_coastlines.json`, `osm_icesheet.json`, `disdi_mirta.json` — no `aux_layer_name`, so tables inherit source basenames (`lines`, `icesheet_polygons`, `mirtalocations*`) rather than semantic names.

Item 3 is the only one likely to cause silent, hard-to-diagnose behavior downstream: zoom-based area filters on `transportation_polygon`, `utility_polygon`, and `utility_linestring` have lost their input column, and on `transportation_polygon` a column named `is_area` now exists that a reader could easily mistake for the old area value.
