# Auxiliary Data

`import/aux_data/` holds 23 JSON configs, each describing one non-OSM
dataset: where to get it, its format, and which layer(s) inside it to load
into Postgres. Parsed by `AuxDataLayer` (`abtv2-tools/abt/aux_data_model.py`).

## `import/aux_data/*.json` — source configs

| Field | Required | Notes |
|---|---|---|
| `folder_name` | yes | Local download/extraction folder name |
| `url` | one of `url`/`local_path` | Remote source |
| `local_path` | one of `url`/`local_path` | Path relative to this directory's root (see [`static_data/`](#static_data-bundled-local-data-files) below) |
| `type` | yes | `gpkg`, `gdb`, `fgb`, `shp`, `csv`, `txt`, or `overture` |
| `zipped` | yes | Whether the source is a zip archive |
| `overture_params` | no | `{theme, type}`, only for `type: overture` — unused in this schema today; see [Overture Buildings](../pipeline/overture.md) for how Overture data is actually loaded here |
| `aux_load` | yes | List of layers to import from this source |

!!! note "`url` and `local_path` are mutually exclusive"
    Exactly one of the two must be set — `AuxDataLayer` raises otherwise.

Each `aux_load` entry becomes one `ogr2ogr` import into
`aux_data.<aux_layer_name>`:

| Key | Required | Notes |
|---|---|---|
| `aux_file_name` | one of `aux_file_name`/`aux_folder_name` | File within the extracted source |
| `aux_folder_name` | one of `aux_file_name`/`aux_folder_name` | Fallback for both `aux_file_name` and `aux_layer_name` when unset |
| `aux_layer_name` | no (falls back to `aux_folder_name`) | Target table name — `aux_data.<aux_layer_name>` |
| `aux_source_name` | no (defaults to `aux_layer_name`) | Layer name *inside* the source file; supports glob patterns for versioned names |
| `aux_load_options` | no | Raw `ogr2ogr` flags, e.g. `-nlt MULTIPOLYGON` |

Example, a multi-layer remote source (`import/aux_data/ne_vector.json`,
abridged):

```json
{
    "folder_name": "natural_earth_10m",
    "url": "https://naciscdn.org/naturalearth/packages/natural_earth_vector.gpkg.zip",
    "type": "gpkg",
    "zipped": true,
    "aux_load": [
        {
            "aux_file_name": "natural_earth_vector.gpkg",
            "aux_layer_name": "ne_10m_admin_0_countries",
            "aux_load_options": "-nlt MULTIPOLYGON"
        }
    ]
}
```

!!! tip "Glob-matched `aux_source_name`"
    Some sources version their internal layer names — `aux_source_name`
    supports glob patterns to match them. Example
    (`import/aux_data/dos_lsib.json`):

    ```json
    {
        "folder_name": "dos_lsib",
        "url": "https://data.geodata.state.gov/LSIB.gpkg",
        "type": "gpkg",
        "zipped": false,
        "aux_load": [
            {
                "aux_file_name": "LSIB.gpkg",
                "aux_source_name": "Department of State LSIB*",
                "aux_layer_name": "dos_lsib",
                "aux_load_options": "-nlt MULTILINESTRING"
            }
        ]
    }
    ```

All non-OSM data lands in a single `aux_data` schema — table names are
exactly whatever `aux_layer_name` (or its `aux_folder_name` fallback) says.

## `static_data/` — bundled local data files

Not to be confused with `carto_sql/static_data/` (a different, unrelated
concept — see [Carto SQL](carto-sql.md)). This top-level `static_data/`
directory holds raw data files checked directly into git, for sources that
don't need downloading every run. It's referenced via an
`import/aux_data/*.json`'s `local_path`, which resolves relative to
`rbt-schema/`'s root:

```json
{
    "folder_name": "ne_physical_centerlines",
    "local_path": "static_data/ne_physical_centerlines.fgb.zip",
    "type": "fgb",
    "zipped": true,
    "aux_load": [
        {
            "aux_file_name": "ne_physical_centerlines.fgb",
            "aux_layer_name": "ne_physical_centerlines"
        }
    ]
}
```

`local_path` and `url` are mutually exclusive; a `local_path` source skips
the download step but still goes through extraction/import like any other
aux source (`-d aux`/`-d all` during [Import](../pipeline/import.md)). See
that page's `debug_aux_import` command for testing one config file in
isolation.

## See also

- [Schema Reference Overview](index.md)
- [OSM Mappings](osm-mappings.md) — the OSM equivalent of this directory
- [Carto SQL](carto-sql.md) — how `aux_data.*` tables get read and transformed
- [Adding a Layer](adding-a-layer.md) — the full workflow for a new aux-data-derived layer
