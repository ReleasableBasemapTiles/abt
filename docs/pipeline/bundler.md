# Bundler

`bundler` joins every per-layer `mbtiles/*.mbtiles` (or `.btis`) file
[`export`](export.md) produced into a single package via `tile-join`, and stamps
descriptive metadata into the result. Like [`import`](import.md) and
[`carto`](carto.md), it always rebuilds from scratch rather than incrementally
updating an existing bundle.

```bash
python abt-tools.py bundler -w <working_dir> -s <schema_dir> [-p pg_config] [-q path ...] [-o output_name] [-z max_zoom] [--data-version YYYY-MM-DD.N]
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
| `--data-version` | no | the UTC date the bundler starts on, plus `.0` (e.g. `2026-10-08.0`) | Version stamped on the bundle, as `YYYY-MM-DD.N`: the build date and a counter for rebuilds on the same day (`.1`, `.2`). Also read from the `ABT_DATA_VERSION` environment variable; the flag wins. A malformed value fails before anything runs. |

## Notable behavior & edge cases

- **Always rebuilds from scratch.** There's no incremental bundling — every run
  re-joins the full set of inputs.
- **Fails on mismatched projections across inputs.** All layers being joined
  need to agree on their CRS.
- **Skips missing and empty inputs instead of failing.** Three kinds of input
  are left out of the join, and each kind prints its own `NOTE: skipping` line
  naming what it dropped:
    - a layer with neither `mbtiles/<layer_id>.mbtiles` nor `.btis` on disk,
      listed by `layer_id`
    - a `-q` path that doesn't exist, listed by path
    - an input with no populated `tiles` table, listed by file name

    The rest are joined and the run still succeeds, so check the bundler
    output for these notes before shipping a bundle. [`export`](export.md)
    moves a layer's file into place only once tippecanoe succeeds, and
    tippecanoe fails a layer with no features, so a layer listed as not found
    failed to export, had no features, or was never exported. The export run's
    `summary.json` and that layer's log say which.

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
  format. `tile-join` has flags for a few of these rows (`-n` name,
  `-N` description, `-A` attribution), but not for tags, license and the rest, so
  the bundler writes all of the joined output's descriptive metadata from this
  schema file after `tile-join` runs, passing only the name as `-n`.
- **`version` is the data version, and the bundler sets it.** The schema file
  has no `version` (one there would be replaced). The bundler writes the UTC
  date it started on with a counter, `2026-10-08.0` for the first build of that
  day, so a bundle says when it was built. Pass `--data-version 2026-10-08.1`
  (or set `ABT_DATA_VERSION`) to name a rebuild the same day. Bundlers started
  together for several projections agree unless they start either side of
  midnight UTC; to guarantee it, set `ABT_DATA_VERSION` once for the whole run.

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
