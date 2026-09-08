# Adding a Layer

## The `.skip` convention

Appending `.skip` to a `carto_sql/*.sql` or `export/*.json` filename removes
it from `abt-tools.py`'s glob (`*.sql`/`*.json`) without deleting the file —
useful for disabling a layer while keeping its SQL/config around for
reference or future re-enabling.

!!! note "Currently used for exactly this reason"
    `carto_sql/031_building.sql.skip` and `export/building_polygon.json.skip`
    disable the OSM-derived `building_polygon` layer in favor of the
    [Overture Buildings](../pipeline/overture.md) pipeline.

`execution_plan.yml` validation (see [Carto SQL](carto-sql.md)) treats a
`.skip`'d script the same as a deleted one — it must not appear in the plan
either.

## Adding or changing a layer

**New OSM-derived layer:**

1. Add `import/osm/<table>.yml` (imposm mapping — see
   [OSM Mappings](osm-mappings.md)).
2. Add a numbered `carto_sql/NNN_<name>.sql` reading `osm.osm_<table>`,
   producing `export.<layer_id>` as a materialized view with a `gist` index
   on `geometry`.
3. Add it to `carto_sql/execution_plan.yml` (own group, unless it shares a
   table with another script — see that file's own "How to update" guidance
   in [Carto SQL](carto-sql.md)).
4. Add `export/<layer_id>.json` with a matching `layer_id` (see the
   [Layer Registry](layers.md)).

**New aux-data-derived layer:** same, but add `import/aux_data/<name>.json`
instead of an imposm mapping (see [Auxiliary Data](aux-data.md)), and
reference `aux_data.<aux_layer_name>` from your `carto_sql` script.

**Changing only how a layer tiles** (zoom range, attributes, filter): edit
its `export/<layer_id>.json` only — no `carto_sql` or database change
needed, since [Export](../pipeline/export.md) reads straight from the
already-built `export.<layer_id>` view.

**Disabling a layer:** rename its `carto_sql/*.sql` and/or `export/*.json`
to add a trailing `.skip`, and remove it from `execution_plan.yml` if
present.

!!! tip "Validate with a small extract, not a full planet build"
    See [Norway](../walkthroughs/norway.md) for a complete,
    copy-pasteable `download`/`import`/`carto`/`export` sequence, and
    `abt-tools.py debug_aux_import` (see [Import](../pipeline/import.md))
    to test one `import/aux_data/*.json` file in isolation.

## An `export/*.json` file, illustrated

Each `export/*.json` config feeds `TileLayer`
(`abtv2-tools/abt/export/tile_layer_model.py`), which builds the `ogr2ogr`
and `tippecanoe` commands for that layer. A trimmed shape, loosely based on
`export/water_polygon.json` (the full per-field reference lives on the
generated [Layer Registry](layers.md)):

```json
{
    "layer_id": "water_polygon",
    "description": "",
    "geometry_type": "polygon",
    "attributes": [
        {"name": "subclass", "type": "string", "description": ""},
        {"name": "z_level",  "type": "int",    "description": ""}
    ],
    "source_attribution": "",
    "tippecanoe_options": {
        "minimum_zoom": 0,
        "maximum_zoom": 13,
        "additional_flags": "--simplify-only-low-zooms --hilbert",
        "filter": {
            "*": ["all", [">=", "$zoom", 0], ["==", "z_level", 1]]
        }
    },
    "ogr_export_options": {
        "additional_flags": "-lco SPATIAL_INDEX=NO -nlt PROMOTE_TO_MULTI"
    }
}
```

`layer_id` must match the `export.<layer_id>` materialized view
`carto_sql` built for it — see
[More views than are tiled](carto-sql.md#more-views-than-are-tiled) for what
happens when it doesn't.

## See also

- [Schema Reference Overview](index.md)
- [OSM Mappings](osm-mappings.md) and [Auxiliary Data](aux-data.md) — the two ways a layer's source data can enter Postgres
- [Carto SQL](carto-sql.md) — the transform step every layer passes through
- [Norway walkthrough](../walkthroughs/norway.md) — the recommended way to validate a change
