# Tile Metadata

`tile-metadata/metadata.py` is a plain Python module — not JSON, it's
imported directly — read once by [Bundler](../pipeline/bundler.md) and
written into the joined `mbtiles`' `metadata` table:

```python
def _load_metadata(schema_dir: Path) -> dict:
    metadata_path = schema_dir / "tile-metadata" / "metadata.py"
    if not metadata_path.exists():
        raise FileNotFoundError(f"No metadata.py found at {metadata_path}")
    spec = importlib.util.spec_from_file_location("tile_metadata", metadata_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.metadata
```

## The `metadata` dict

The module must define a module-level `metadata` dict. This schema's
includes:

| Key | Notes |
|---|---|
| `name` | Tileset display name |
| `version` | Tileset version string |
| `production_date` | Computed at load time, UTC |
| `description` | Free text |
| `attribution` | HTML attribution string |
| `tags` | List of descriptive tags |
| `source` | Source URL |
| `license` | List of `{name, license, url}` entries — see [Data Sources & Licensing](../overview/data-sources.md) |
| `creators` | Creator/attribution metadata |
| `format` | Tile format |
| `bounds` | `[minLon, minLat, maxLon, maxLat]` |
| `center` | `[lon, lat, zoom]` |
| `type` | e.g. `baselayer` |

!!! warning "`bounds`, `center`, and `format` are overwritten by `bundler`"
    Regardless of what's set here, those three fields are computed from the
    actual joined tiles, not user-configurable.

A trimmed example of the current file's shape (values omitted or shortened
where they'd duplicate the generated
[Data Sources & Licensing](../overview/data-sources.md) page):

```python
metadata = {
    "name": "Releasable Basemap Tiles (RBT)",
    "version": "2.0.0",
    "production_date": production_date,
    "description": "",
    "attribution": "...",
    "tags": ["Army", "Basemap", "Tiles", "Vector", "..."],
    "source": "https://www.agc.army.mil/",
    "license": [
        {"name": "OpenStreetMap", "license": "ODbL 1.0", "url": "https://www.openstreetmap.org/copyright"},
        # ... additional sources, see Data Sources & Licensing
    ],
    "creators": {
        "creators:name": "...",
        "creators:websites": "...",
    },
    "format": "pbf",
    "bounds": [-179.99999999999997, -60.0, 179.99999999999997, 83.0],
    "center": [-77.0365, 38.8977, 10],
    "type": "baselayer",
}
```

For the exact current field values, read
`rbt-schema/tile-metadata/metadata.py` directly — this page intentionally
doesn't reproduce the full attribution/license list; that's generated at
[Data Sources & Licensing](../overview/data-sources.md).

## See also

- [Schema Reference Overview](index.md)
- [Bundler](../pipeline/bundler.md) — where this file is loaded and written into the joined mbtiles
- [Data Sources & Licensing](../overview/data-sources.md) — the full, generated attribution/license table
