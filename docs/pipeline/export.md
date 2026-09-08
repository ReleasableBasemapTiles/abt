# Export

`export` turns the `export.*` materialized views [`carto`](carto.md) built into
per-layer tile files. For every layer defined under `--schema-dir`'s `export/*.json`
it runs two steps in sequence: PostgreSQL → FlatGeobuf via `ogr2ogr`, then
FlatGeobuf → MBTiles via `tippecanoe`. Like [`download`](download.md), it's one of
the two commands that skip work already done — each step is skipped individually if
its output file already exists.

```bash
python abt-tools.py export -w <working_dir> -s <schema_dir> [-n workers] [-p pg_config] [-z max_zoom] [--projection-override EPSG:code]
```

## Flags

| Flag | Required | Default | Description |
|---|---|---|---|
| `-w`, `--working-dir` | yes | — | Root directory; writes `flatgeobuf/*.fgb` and `mbtiles/*.mbtiles` here. |
| `-s`, `--schema-dir` | yes | — | Schema/config directory; reads `export/*.json` per-layer configs. |
| `-n`, `--num-workers` | no | scaled to host CPU count, minimum 4 | Parallel workers for both the FlatGeobuf export and the MBTiles conversion. |
| `-p`, `--pg-config` | no | `env` | PostgreSQL connection — `env` or `<host>,<port>,<user>,<password>,<dbname>`. |
| `-z`, `--max-zoom` | no | `13` | Caps the maximum zoom level generated. Hard-capped at 15 per the per-layer `tippecanoe_options.maximum_zoom` cap described in [Layer Registry](../schema/layers.md). |
| `--projection-override` | no | none (Web Mercator) | Advanced/non-standard CRS override — see below and `export --help` for the full explanation. |

## Notable behavior & edge cases

- **Skips either step independently.** If a layer's `.fgb` already exists, the
  ogr2ogr step is skipped for it; if its `.mbtiles` already exists, the
  tippecanoe step is skipped. This is what makes the [Reuse](#rebuilding-a-single-layer)
  workflow below possible.
- **`-z`/`--max-zoom` is a ceiling, not a fixed zoom** — the effective max zoom
  per layer is `min(-z value, that layer's own tippecanoe_options.maximum_zoom)`,
  so a layer configured for a lower max zoom in its `export/*.json` is unaffected
  by a higher `-z`.
- **`--projection-override` is advanced/non-standard.** It reprojects a layer's
  geometry to the given `EPSG:code` in PostGIS, then tells tippecanoe it's
  already receiving EPSG:3857 data so it skips its normal reprojection — an
  undocumented tippecanoe compatibility trick. Output still uses the
  `.mbtiles` extension, but the result won't conform to the MBTiles 1.3 spec.
  Run `export --help` for the full callout, including that it only makes sense
  for a target projection using meters as its unit (e.g. `EPSG:3395`), and that
  passing a degrees-based or otherwise incompatible EPSG code silently produces
  garbled tiles rather than an error.

## Rebuilding a single layer

Only `export` and [`download`](download.md) skip existing outputs — `import`,
`carto`, `bundler`, and `vundler` always redo the full operation. To rebuild one
layer's tiles:

1. Delete its `flatgeobuf/<layer>.fgb` and/or `mbtiles/<layer>.mbtiles` (or
   `.btis`, if present).
2. Re-run `export`.

Deleting only the mbtiles file (keeping the `.fgb`) skips straight to the
tippecanoe step, since the FlatGeobuf export is still considered up to date.

## See also

- [Layer Registry](../schema/layers.md) — the generated reference for every
  layer's `export/*.json` config, including its `tippecanoe_options.maximum_zoom`.
- [Carto SQL](../schema/carto-sql.md) — how the `export.*` views this stage reads
  are built.
- [Norway walkthrough](../walkthroughs/norway.md) and
  [Planet walkthrough](../walkthroughs/planet.md) — `export` in context as part
  of a full run.
- [Carto](carto.md) — the previous stage; [Bundler](bundler.md) — the next one.
