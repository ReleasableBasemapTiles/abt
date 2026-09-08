# Import

`import` loads what [`download`](download.md) fetched into PostgreSQL: OSM PBF data
via `imposm3`, and/or auxiliary sources via `ogr2ogr`, driven respectively by
`--schema-dir`'s `import/osm/*.yml` [imposm mappings](../schema/osm-mappings.md) and
`import/aux_data/*.json` [aux configs](../schema/aux-data.md). Unlike
[`download`](download.md) and [`export`](export.md), `import` never skips existing
output — every run is a full re-run of whatever `-d/--data-type` selects.

```bash
python abt-tools.py import -w <working_dir> -s <schema_dir> -d {osm,aux,all} [-n workers] [-p pg_config] [-k osm_key] [-f] [-c]
```

## Flags

| Flag | Required | Default | Description |
|---|---|---|---|
| `-w`, `--working-dir` | yes | — | Root directory holding data downloaded by [`download`](download.md). |
| `-s`, `--schema-dir` | yes | — | Schema/config directory (see [Schema Reference](../schema/index.md)). |
| `-d`, `--data-type` | yes | — | `osm`, `aux`, or `all`. `osm` imports via `imposm3`; `aux` imports every `import/aux_data/*.json` source via `ogr2ogr` in parallel across `-n` workers; `all` runs OSM first, then dedicates all workers to the aux import. |
| `-n`, `--num-workers` | no | scaled to host CPU count, minimum 4 | Parallel workers for the aux import step. No effect on the OSM import. |
| `-p`, `--pg-config` | no | `env` | PostgreSQL connection: `env` reads `PGHOST`/`PGPORT`/`PGUSER`/`PGPASSWORD`/`PGDATABASE`, or pass `<host>,<port>,<user>,<password>,<dbname>` directly. |
| `-k`, `--osm-key` | no | `planet` | Geofabrik extract key or `planet` — must match what [`download`](download.md) was run with. |
| `-f`, `--force` | no | off | Re-import OSM data even if the `osm` schema is already populated. |
| `-c`, `--clip-aux` | no | off | Clip aux data imports to the `-k` extract's bounding box. Ignored when `-k` is `planet` or omitted. |

## Notable behavior & edge cases

- **Always a full re-run.** There's no incremental/skip behavior here — re-running
  `import` re-imports everything `-d` selects.
- **OSM import aborts if data already exists**, rather than silently overwriting
  it, because a full re-import can take 24+ hours. Pass `-f`/`--force` to proceed
  anyway.
- **`-c`/`--clip-aux` does both a `-spat` pre-filter and a real `-clipsrc` clip**,
  not just one — a bounding-box filter alone won't shrink a globally-dissolved
  aux layer (e.g. a single dissolved land/water polygon covering the whole
  planet), so a hard clip is needed too. This is meant for fast test builds
  against a small extract, and has no effect when `-k` is `planet` or omitted.
- **`-d all` runs OSM to completion first**, then imports aux data with the full
  `-n` worker count — the two data types are never imported concurrently with
  each other.

!!! warning "`dblink`/superuser requirement carries forward from `import`'s `-p`"
    The same PostgreSQL role used here is later reused by [`carto`](carto.md),
    which needs it to be a superuser (or explicitly trusted in `pg_hba.conf`) for
    `dblink`'s internal connections. See [Configuration](../install/configuration.md).

## Debugging a single aux file

```bash
python abt-tools.py debug_aux_import -w <working_dir> -s <schema_dir> -a <aux_file> [-p pg_config]
```

Imports one aux file in isolation — useful for testing a single
`import/aux_data/*.json` config without running the rest of `import`. `-a`/
`--aux-file` takes the config's base filename without the `.json` extension (it
resolves to `<schema_dir>/import/aux_data/<aux_file>.json`). See
[Auxiliary Data](../schema/aux-data.md) for the config format this reads.

| Flag | Required | Default | Description |
|---|---|---|---|
| `-w`, `--working-dir` | yes | — | Root directory for processed data. |
| `-s`, `--schema-dir` | yes | — | Schema/config directory. |
| `-a`, `--aux-file` | yes | — | Base filename (no `.json`) of one `import/aux_data/*.json` config to import. |
| `-p`, `--pg-config` | no | `env` | PostgreSQL connection — same semantics as `import`'s `-p` above. |

## See also

- [Norway walkthrough](../walkthroughs/norway.md) — full worked example including
  `-c/--clip-aux` on a small extract.
- [Planet walkthrough](../walkthroughs/planet.md) — full-planet import, `-f` and
  `24+ hour` considerations in context.
- [OSM Mappings](../schema/osm-mappings.md) — `import/osm/*.yml` format read by
  the OSM import.
- [Auxiliary Data](../schema/aux-data.md) — `import/aux_data/*.json` format read
  by the aux import and by `debug_aux_import`.
- [Configuration](../install/configuration.md) — PostgreSQL role/extension
  requirements behind `-p/--pg-config`.
- [Download](download.md) — the previous stage; [Carto](carto.md) — the next one.
