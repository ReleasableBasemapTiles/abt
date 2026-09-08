# Download

`download` is the first pipeline stage. It fetches the raw OpenStreetMap PBF extract
and/or the auxiliary source files listed under `--schema-dir`'s `import/aux_data/`,
staging them under `--working-dir` for the [`import`](import.md) stage to load into
PostgreSQL. It's one of only two `abt-tools.py` commands (the other is
[`export`](export.md)) that skip work it's already done — a file already present on
disk is left alone rather than re-downloaded.

```bash
python abt-tools.py download -w <working_dir> -s <schema_dir> -d {osm,aux,all} [-n workers] [-k osm_key]
```

## Flags

| Flag | Required | Default | Description |
|---|---|---|---|
| `-w`, `--working-dir` | yes | — | Root directory for downloaded/extracted data; created automatically if missing. |
| `-s`, `--schema-dir` | yes | — | Schema/config directory (`--schema-dir` of [`rbt-schema`](../schema/index.md)). |
| `-d`, `--data-type` | yes | — | `osm`, `aux`, or `all`. `osm` downloads the Geofabrik/planet PBF; `aux` downloads (and extracts, if zipped) every source under `import/aux_data/`, in parallel across `-n` workers; `all` runs OSM first, then dedicates all workers to the aux download. |
| `-n`, `--num-workers` | no | scaled to host CPU count, minimum 4 | Parallel workers for the aux download/extraction step. Has no effect on the OSM download, which is always a single stream (or, for `-k planet`, a single coordinated `aria2c` invocation — see below). |
| `-k`, `--osm-key` | no | **`planet`** | Geofabrik extract key (e.g. `norway`) or `planet` for a full-planet PBF. |

!!! warning "`-k`/`--osm-key` defaults to `planet`"
    Omitting `-k` downloads the entire planet PBF, not a small extract. Always pass an
    explicit Geofabrik key (e.g. `-k norway`) unless a full-planet download is actually
    intended — see the [Norway walkthrough](../walkthroughs/norway.md) for a small-extract
    example and the [Planet walkthrough](../walkthroughs/planet.md) for the full build.

## Notable behavior & edge cases

- **Skips existing files.** `download` (like `export`) only ever fills in what's
  missing under `--working-dir`; re-running it after a partial or interrupted run
  resumes rather than restarting.
- **`-k planet` goes through `aria2c`, not a plain HTTP GET.** Geofabrik extracts
  publish exactly one URL each, so any non-`planet` key keeps using the original
  single-stream `requests` downloader. For `planet` specifically,
  `abt/download/planet_mirrors.py` queries the ~11 known public planet mirrors
  concurrently, cross-checks their reported MD5/date/size to agree on one current
  file, and hands every URL serving it to `aria2c` at once — which downloads
  segments from all of them in parallel, aggregating their bandwidth instead of
  being capped by any single mirror.
- **MD5 verification is mandatory for `planet`.** If the mirrors can't be
  reconciled into one trustworthy hash, the download fails outright rather than
  proceeding unverified.
- **Requires the `aria2` package — but only for `-k planet`.** `setup_ubuntu.sh`
  installs it as part of provisioning; see [Ubuntu Setup](../install/ubuntu.md).
  A non-`planet` download has no `aria2c` dependency.

!!! tip "Confirming a Geofabrik key"
    The full set of valid `-k`/`--osm-key` values is Geofabrik's live index at
    `https://download.geofabrik.de/index-v1.json` (each entry's `id` field is a
    valid key); the corresponding PBF is published at
    `https://download.geofabrik.de/<id>-latest.osm.pbf`.

## See also

- [Norway walkthrough](../walkthroughs/norway.md) — full worked example against a
  small Geofabrik extract.
- [Planet walkthrough](../walkthroughs/planet.md) — full worked example of a
  planet-scale `-k planet` build.
- [Ubuntu Setup](../install/ubuntu.md) — installs the `aria2` package this stage
  needs for `-k planet`.
- [Auxiliary Data](../schema/aux-data.md) — the `import/aux_data/*.json` config
  format this stage downloads sources for.
- [Import](import.md) — the next pipeline stage, which loads what `download` fetched.
