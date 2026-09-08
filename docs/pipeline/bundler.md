# Bundler

`bundler` joins every per-layer `mbtiles/*.mbtiles` (or `.btis`) file
[`export`](export.md) produced into a single package via `tile-join`, and stamps
descriptive metadata into the result. Like [`import`](import.md) and
[`carto`](carto.md), it always rebuilds from scratch rather than incrementally
updating an existing bundle.

```bash
python abt-tools.py bundler -w <working_dir> -s <schema_dir> [-p pg_config] [-q path ...] [-o output_name] [-z max_zoom]
```

## Flags

| Flag | Required | Default | Description |
|---|---|---|---|
| `-w`, `--working-dir` | yes | — | Root directory; reads `mbtiles/*` from here, writes to `bundled/`. |
| `-s`, `--schema-dir` | yes | — | Schema/config directory; reads `tile-metadata/metadata.py` from here (required — see below). |
| `-p`, `--pg-config` | no | `env` | PostgreSQL connection — `env` or `<host>,<port>,<user>,<password>,<dbname>`. |
| `-q`, `--additional-mbtiles` | no | none | Path to an externally-produced mbtiles file to fold into the bundle (e.g. contours, or [Overture buildings](overture.md)). Repeatable for more than one. |
| `-o`, `--output-name` | no | `joined.mbtiles` | Overrides the output filename; used exactly as given. |
| `-z`, `--max-zoom` | no | none (no cap) | Caps the bundle at a given zoom level by pre-trimming every input with SQLite before `tile-join` runs — e.g. for a smaller "RBT Small" package. |

## Notable behavior & edge cases

- **Always rebuilds from scratch.** There's no incremental bundling — every run
  re-joins the full set of inputs.
- **Fails on mismatched projections across inputs.** All layers being joined
  need to agree on their CRS.
- **`-q`/`--additional-mbtiles` folds in externally-produced tiles** that
  `abt-tools.py` didn't itself export — this is exactly how the standalone
  [Overture buildings pipeline](overture.md)'s output gets into the final
  package:

    ```bash
    python abt-tools.py bundler -w <working_dir> -s ../rbt-schema -p env \
      -q /path/to/data_dir/building_polygon_3857.mbtiles
    ```

- **`-z`/`--max-zoom` caps by pre-trimming, not by re-tiling.** Every input is
  trimmed to the given zoom level with SQLite before `tile-join` runs, rather
  than tippecanoe re-generating tiles — omit the flag entirely for no cap (full
  resolution).
- **Stamps metadata from `tile-metadata/metadata.py` into the output, and fails
  without it.** See [Tile Metadata](../schema/tile-metadata.md) for that file's
  format. `tile-join` itself only accepts a `-n` name flag on the command line —
  everything else in the joined output's metadata table (description,
  attribution, tags, license, etc.) comes from this schema file.

## See also

- [Overture Buildings](overture.md) — the standalone pipeline whose output is
  typically folded in via `-q/--additional-mbtiles` here (or automatically via
  [`init.sh --overture`](../walkthroughs/init-sh.md)).
- [Tile Metadata](../schema/tile-metadata.md) — the `tile-metadata/metadata.py`
  format this stage requires.
- [Norway walkthrough](../walkthroughs/norway.md) and
  [Planet walkthrough](../walkthroughs/planet.md) — `bundler` in context as part
  of a full run.
- [Export](export.md) — the previous stage; [Vundler](vundler.md) — the next,
  optional one.
