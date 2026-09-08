# Troubleshooting

Merged from the root `README.md` and `abtv2-tools/README.md` troubleshooting sections, organized by symptom.

## `carto` stage

!!! warning "`ERROR: password is required` / `dblink_connect` fails in `carto`"
    The `abt`/pipeline role isn't a superuser, or `pg_hba.conf` doesn't trust its local connections. Re-run the `CREATE ROLE ... SUPERUSER` step (see [Ubuntu Setup](../install/ubuntu.md)), or add a `trust`/`scram-sha-256` entry for the role on `127.0.0.1/32` in `pg_hba.conf` and `sudo systemctl reload postgresql`.

**`carto` fails partway through, referencing `aux_data.mirtalocations_a` (in `023_military.sql`) or another `aux_data.*` table that "doesn't exist".**

The corresponding aux source failed to download or import — check `<working_dir>/logs/<run_id>/download/` and `.../import/` for that source's log. The MIRTA/DISDI installations dataset in particular is fetched from `datacollects.blob.core.usgovcloudapi.net` (see `rbt-schema/import/aux_data/disdi_mirta.json`) and may be unreachable from some networks; a failed download here doesn't surface as an error until `carto` runs `023_military.sql` and finds the table missing. `carto_sql` scripts are idempotent, so once the underlying aux data is fixed (re-run `download`/`import` for just that source, or use `debug_aux_import` — see [Import stage](../pipeline/import.md)), just re-run `carto` — it always starts from `000_*.sql` again.

**One `carto` script/group fails — does the whole run abort?**

The sequential prefix (`000`/`001`) and suffix (`099`) still abort the whole run if they fail. In between, each independent group (see [Carto SQL](../schema/carto-sql.md) and [Performance & Sizing](../install/performance.md)) fails on its own — other groups still run to completion, and the error names the failing group, e.g. `1 of 29 carto group(s) failed, suffix not run: 023_military: ...`. Fix the root cause, then simply re-run `carto` — every script drops/recreates its own tables, so re-running the whole stage (including groups that already succeeded) is safe, just not the cheapest option if only one layer needs a fix.

## `download` and `import`

!!! warning "Pulling the entire planet when you only wanted a small extract"
    `-k`/`--osm-key` defaults to `planet` when omitted. Always pass `-k norway` (or your target Geofabrik key) explicitly — see the [Norway walkthrough](../walkthroughs/norway.md).

**Is a planet `download` actually pulling from multiple mirrors, or just one?**

Check the `download` stage's log for `planet` under `logs/<run_id>/download/` — `abt/download/planet_mirrors.py`'s `discover_planet_sources` logs every mirror it queried and which URLs it ultimately handed to `aria2c`. If too few mirrors respond, or they disagree on the file's MD5/timestamp/size, the download raises rather than silently falling back to a single unverified source — checksum verification is mandatory for `-k planet`.

**`import` aborts with "OSM schema already contains data".**

This is a safety check — a full re-import can take a long time, especially for the planet. Pass `-f`/`--force` to proceed anyway.

## `export`

!!! tip "Rebuilding only one export layer"
    Delete its `flatgeobuf/<layer>.fgb` and/or `mbtiles/<layer>.mbtiles`, then re-run `export` (see [Export stage](../pipeline/export.md)). Deleting only the `.mbtiles` (keeping the `.fgb`) skips straight to the `tippecanoe` step.

## Geofabrik keys

**Confirming your Geofabrik key.**

The full list of valid `-k`/`--osm-key` values is Geofabrik's live index at `https://download.geofabrik.de/index-v1.json` (each entry's `id` field is a valid key); the corresponding PBF lives at `https://download.geofabrik.de/<id>-latest.osm.pbf`. `planet` is a special-cased key handled by the multi-mirror `aria2c` path and doesn't appear in that index.
