# Vundler

`vundler` is the final, optional pipeline stage. It converts the bundled mbtiles
file [`bundler`](bundler.md) produced into Esri Compact Cache V2 tile bundles —
`.bundle` files per zoom level, plus a bare `metadata.json` — with zoom levels
converted concurrently. It is **not** a complete `.vtpk`: no `conf.xml`, `root.json`,
or styles are produced.

```bash
python abt-tools.py vundler -w <working_dir> [-i input_path] [-o output_dir] [-z max_zoom] [-n workers]
```

## Flags

| Flag | Required | Default | Description |
|---|---|---|---|
| `-w`, `--working-dir` | yes | — | Root directory; used to resolve the default input/output paths below. |
| `-i`, `--input-path` | no | `bundled/joined.mbtiles` (or `bundled/joined.btis`, if present) | Source bundled mbtiles file. |
| `-o`, `--output-dir` | no | `bundled/vundled/p12` | Output package directory. |
| `-z`, `--max-zoom` | no | `13` | Highest zoom level to convert. |
| `-n`, `--num-workers` | no | one per available core | Number of worker threads converting bundles concurrently. Passed straight through to the `abt-vundler` binary's own `--num-workers`. |

## Notable behavior & edge cases

- **Always rebuilds from scratch**, like `import`/`carto`/`bundler` — there's no
  incremental conversion.
- **Delegates the actual conversion to a Rust binary, `abt-vundler`**, built from
  `abtv2-tools/vundler-rs/`, rather than converting in pure Python. The Python
  `vundler` command here just builds the `abt-vundler` subprocess invocation and
  passes `--num-workers` through — it does no tile conversion itself.
- **Why the Rust rewrite:** the original pure-Python implementation measured
  ~40x redundant bundle-index rewrites (row-major tile iteration reopens the
  same bundle file once per tile row it contains), and a parallelism ceiling
  around 2x on real data — one zoom level alone accounted for 48% of all tiles,
  capping per-zoom-level task parallelism regardless of available cores. The
  Rust binary is restructured around per-bundle work units instead of
  per-zoom-level tasks to remove that ceiling.
- **Full Rust-side internals live elsewhere.** `abt-vundler`'s own CLI flags,
  its test/benchmark harness, and file-format details are documented on
  [vundler-rs](../reference/vundler-rs.md) rather than duplicated here — see
  that page for anything beyond what the Python `vundler` command itself
  exposes.

## See also

- [vundler-rs](../reference/vundler-rs.md) — the Rust binary this command
  delegates to: its own flags, internals, and test/benchmark harness.
- [Bundler](bundler.md) — the previous, required stage that produces this
  command's input.
- [Norway walkthrough](../walkthroughs/norway.md) and
  [Planet walkthrough](../walkthroughs/planet.md) — `vundler` in context as part
  of a full run.
