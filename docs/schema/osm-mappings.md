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

Every mapping needs `type` (`point`/`linestring`/`polygon`), `columns`, and
`mapping` — `ImposmMappingFile` (`abtv2-tools/abt/osm_data_model.py`) raises
if any is missing:

| Key | Purpose |
|---|---|
| `type` | Geometry type: `point`, `linestring`, or `polygon` |
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

## See also

- [Schema Reference Overview](index.md)
- [Auxiliary Data](aux-data.md) — the non-OSM equivalent of this directory
- [Adding a Layer](adding-a-layer.md) — the full workflow for a new OSM-derived layer
