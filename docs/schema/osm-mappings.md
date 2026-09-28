# OSM Mappings

`import/osm/` holds 38 [imposm3 mapping](https://imposm.org/docs/imposm3/latest/mapping.html)
fragments, one per output table.

## One file per table

The filename (minus extension) doubles as the YAML's top-level key and the
imposm table name. `abt-tools.py` combines every file in this directory into
one combined mapping and imports OSM data into schema `osm` — imposm's own
default `osm_` table prefix means `water_polygon.yml` becomes
`osm.osm_water_polygon`.

Example (`import/osm/water_polygon.yml`, abridged):

```yaml
water_polygon:
  type: polygon
  columns:
  - name: osm_id
    type: id
  - name: geometry
    type: validated_geometry
  - name: name
    key: name
    type: string
  - name: class
    type: mapping_key
  - name: subclass
    type: mapping_value
  - name: tags
    type: hstore_tags
  filters:
    reject:
      covered:
      - "yes"
  mapping:
    natural:
    - water
    - bay
    waterway:
    - __any__
    place:
    - sea
    - ocean
```

## Required keys

Every mapping needs `type`, `columns`, and `mapping` — `ImposmMappingFile`
(`abtv2-tools/abt/osm_data_model.py`) raises if any is missing:

| Key | Purpose |
|---|---|
| `type` | Table type: `point` (12 tables), `linestring` (10), `polygon` (13), or `relation_member` (3: `building_relation`, `highway_relation`, `waterway_relation`) |
| `columns` | Output columns for the table, each with a `name` and a `type` |
| `mapping` | OSM tag keys/values that select which features load into this table |

## Column type vocabulary

These are imposm3's own vocabulary, not something `rbt-schema` defines — see
imposm3's [mapping documentation](https://imposm.org/docs/imposm3/latest/mapping.html)
for the full spec. Column `type` values used across this schema:

| Type | Notes |
|---|---|
| `id` | The OSM object ID |
| `validated_geometry` / `geometry` | The feature's geometry |
| `string` | Text value, usually paired with a `key:` |
| `bool` | Boolean value |
| `integer` | Integer value |
| `area` | Computed area |
| `direction` | Directional value |
| `hstore_tags` | All remaining OSM tags as a Postgres `hstore` column |
| `mapping_key` / `mapping_value` | The OSM tag key/value that matched under `mapping` |
| `member_id`, `member_role`, `relation_member` | Relation-only types |
| `wayzorder` | Way rendering z-order |

!!! note "`hstore_tags` requires the `hstore` extension"
    Any table with an `hstore_tags` column needs the `hstore` extension
    enabled on the target database. See [Ubuntu Setup](../install/ubuntu.md).

## Which tags imposm keeps: `import/imposm_base.yml`

imposm drops every tag it doesn't need while it reads the PBF, before
anything is cached or written to Postgres. A tag survives only if:

- some table maps its key (with that value, or `__any__`) under `mapping`,
- some table uses its key for a column (`key:` or `keys:`), or
- it is listed in the top-level `tags: include:` setting.

Filter keys (`require` / `reject`) are **not** on that list. So a
`tags -> 'key'` lookup in `carto_sql`, or a `reject:` filter on a key no
table maps, silently sees NULL: there is no error, just missing data.

`import/imposm_base.yml` (optional, beside `import/osm/` rather than in it)
holds imposm's top-level mapping settings. `abt-tools.py` merges it into the
combined mapping next to the per-table files. It must not define `tables`.
rbt-schema uses it for `tags: include:`, listing the lifecycle-prefixed keys
(`razed:railway`, `disused:power`, …), `dam:type`, `airmark`, and `covered`:

```yaml
tags:
  include:
    - razed:railway
    - covered   # for water_polygon.yml's `reject: covered: ["yes"]`
```

`tests/test_imposm_tags.py` (at the repo root) models imposm's tag filter
and fails if a key read by `carto_sql` or used in a filter isn't loaded.
Changes here only take effect on a fresh import (`imposm -read`).

## See also

- [Schema Reference Overview](index.md)
- [Auxiliary Data](aux-data.md) — the non-OSM equivalent of this directory
- [Adding a Layer](adding-a-layer.md) — the full workflow for a new OSM-derived layer
