# Troubleshooting

Merged from the root `README.md` and `abtv2-tools/README.md` troubleshooting sections, organized by symptom.

## `carto` stage

!!! warning "`ERROR: password is required` / `dblink_connect` fails in `carto`"
    The pipeline's role (`rbt` by default) isn't a superuser, or `pg_hba.conf` doesn't trust its local connections. Re-run the `CREATE ROLE ... SUPERUSER` step (see [Ubuntu Setup](../install/ubuntu.md)), or add a `trust`/`scram-sha-256` entry for the role on `127.0.0.1/32` in `pg_hba.conf` and reload Postgres. On a host set up by `setup_ubuntu.sh`, `pg_hba.conf` is in `PG_DATA_DIR` (default `/var/lib/postgresql/<version>/main`) and the unit is `postgresql-rbt`: `sudo systemctl reload postgresql-rbt`. On a manual install it's `/etc/postgresql/<version>/main/pg_hba.conf` and `sudo systemctl reload postgresql`.

**`carto` fails partway through, referencing `aux_data.mirtalocations_a` (in `023_military.sql`) or another `aux_data.*` table that "doesn't exist".**

The corresponding aux source failed to download or import — check `<working_dir>/logs/<run_id>/download/` and `.../import/` for that source's log. Either stage exits non-zero and records the source as `FAILED` in its `summary.json` when a source fails, but running the next stage anyway leaves the gap for `carto` to find. The MIRTA/DISDI installations dataset in particular is fetched from `www.acq.osd.mil` (see `rbt-schema/import/aux_data/disdi_mirta.json`) and may be unreachable from some networks. `carto_sql` scripts are idempotent, so once the underlying aux data is fixed (re-run `download`/`import` for just that source, or use `debug_aux_import` — see [Import stage](../pipeline/import.md)), just re-run `carto` — it always starts from `000_*.sql` again.

**One `carto` script/group fails — does the whole run abort?**

The sequential prefix (`000`/`001`) and suffix (`099`) still abort the whole run if they fail. In between, each independent group (see [Carto SQL](../schema/carto-sql.md) and [Performance & Sizing](../install/performance.md)) fails on its own — other groups still run to completion, and the error names the failing group, e.g. `1 of 29 carto group(s) failed, suffix not run: 023_military: ...`. Fix the root cause, then simply re-run `carto` — every script drops/recreates its own tables, so re-running the whole stage (including groups that already succeeded) is safe, just not the cheapest option if only one layer needs a fix.

## `download` and `import`

!!! warning "Pulling the entire planet when you only wanted a small extract"
    `-k`/`--osm-key` defaults to `planet` when omitted. Always pass `-k norway` (or your target Geofabrik key) explicitly — see the [Norway walkthrough](../walkthroughs/norway.md).

**Is a planet `download` actually pulling from multiple mirrors, or just one?**

Check the `download` stage's log for `planet` under `logs/<run_id>/download/` — `abt/download/planet_mirrors.py`'s `discover_planet_sources` logs every mirror it queried and which URLs it ultimately handed to `aria2c`. If too few mirrors respond, or they disagree on the file's MD5/timestamp/size, the download raises rather than silently falling back to a single unverified source — checksum verification is mandatory for `-k planet`.

**`download` fails with `CERTIFICATE_VERIFY_FAILED` for one source.**

Downloads verify TLS certificates. A host that sends an incomplete certificate chain fails that check even though a browser, which fetches the missing intermediate itself, loads the page fine: `www.acq.osd.mil`, the MIRTA host, is one. If the chain is broken on the server's side, set `"verify_tls": false` in that source's `import/aux_data/*.json`, as `disdi_mirta.json` does (see [Auxiliary Data](../schema/aux-data.md)); `download` then logs a warning for that source on every run. `ABT_INSECURE_DOWNLOADS=1` turns verification off for every source, so keep it to a one-off run.

**`import` aborts with "OSM schema already contains data".**

This is a safety check — a full re-import can take a long time, especially for the planet. Pass `-f`/`--force` to proceed anyway. `init.sh` never passes `--force`, so running it a second time from the start stops here, at [2/6]. After a complete run, use `init.sh --from export`; otherwise run the remaining stages with `abt-tools.py` yourself (see the [Planet walkthrough](../walkthroughs/planet.md)).

**Reusing a working directory from an older abt-tools.**

Downloads, FlatGeobufs and MBTiles are written under a temporary name (`<file>.part`, `flatgeobuf/.partial/`, `mbtiles/.partial/`) and moved into place only once complete, and an extracted archive gets a `.<folder>.complete` marker beside it. Older versions wrote straight to the final path, so a run that was killed or lost its connection could leave a truncated file there, and every later run skips a file that exists. Extractions without a marker are redone once on their own. If a run with an older version was ever interrupted, delete the files it may have cut short before reusing the directory: the aux downloads and Geofabrik extract it was fetching, and `flatgeobuf/*.fgb` and `mbtiles/*.mbtiles` if it died during `export`. (The planet download is checksummed, so a truncated planet file fails rather than being reused.) `ogrinfo` doesn't catch a truncated `.fgb`, and `tippecanoe` tiles one without complaint.

## `export`

!!! tip "Rebuilding only one export layer"
    Delete its `flatgeobuf/<layer>.fgb` and/or `mbtiles/<layer>.mbtiles`, then re-run `export` (see [Export stage](../pipeline/export.md)). Deleting only the `.mbtiles` (keeping the `.fgb`) skips straight to the `tippecanoe` step.

## `bundler` and `vundler`

**`bundler` fails with "Missing required environment variables: PGHOST, …".**

`bundler` loads the export layers the same way `export` does, and that needs a Postgres configuration, although `bundler` never queries the database. With the default `-p env`, set the `PG*` variables as you would for the other stages; it doesn't connect. An explicit `-p <host>,<port>,<user>,<password>,<dbname>` is tested with a real connection, so Postgres must be up for that form.

**`vundler` fails with `No such file or directory: 'abt-vundler'`.**

The `abt-vundler` binary isn't on `PATH`. `setup_ubuntu.sh` builds it and installs it to `/usr/local/bin` unless `INSTALL_VUNDLER=false`; on a manual install, see step 7 of [Ubuntu Setup](../install/ubuntu.md#7-rust-and-abt-vundler). `setup_ubuntu.sh` skips the build when `abt-vundler` is already installed, so after changing `vundler-rs/` rerun it with `FORCE_REBUILD_VUNDLER=true`, or rebuild with `cargo build --release` yourself.

## Geofabrik keys

**Confirming your Geofabrik key.**

The full list of valid `-k`/`--osm-key` values is Geofabrik's live index at `https://download.geofabrik.de/index-v1.json` (each entry's `id` field is a valid key). `download` fetches the PBF named by that entry's `urls.pbf`, which includes the parent regions, e.g. `https://download.geofabrik.de/europe/norway-latest.osm.pbf` for `norway`. `planet` is a special-cased key handled by the multi-mirror `aria2c` path and doesn't appear in that index.
