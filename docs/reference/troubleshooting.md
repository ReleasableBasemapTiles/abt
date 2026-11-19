# Troubleshooting

Organized by the stage that fails, then by symptom. Every command except `vundler` prints the path of its `summary.json` when it ends, which names each failed task and its error; the logs are beside it under `<working_dir>/logs/<run_id>/` (see [Working Directory](../overview/working-directory.md#logs)).

## Connecting to Postgres

**`FATAL: Peer authentication failed for user "rbt"`.**

The client connected over the local socket, where a cluster that `setup_ubuntu.sh` created, like a stock Ubuntu cluster, admits a role only for the operating-system user of the same name (`peer`). Connect over TCP instead: `psql -h 127.0.0.1 -U rbt`, or with `-p env`, `PGHOST=127.0.0.1` rather than a socket directory such as `/var/run/postgresql`. `init.sh` connects to `PG_HOST`, which is `127.0.0.1` unless you set it. To connect as `postgres`, use `sudo -u postgres psql`. See [Postgres authentication](../install/ubuntu.md#postgres-authentication).

**`FATAL: password authentication failed for user "rbt"`.**

The client's password isn't the role's. A cluster that `setup_ubuntu.sh` created checks it on every TCP connection (`PG_AUTH_HOST=scram-sha-256`), where a cluster from an older `setup_ubuntu.sh` trusted those connections and never checked it. Pass the `PG_PASSWORD` the host was set up with (`rbt` by default): as `PGPASSWORD` for `-p env`, in the `-p` host string, or as `init.sh`'s `PG_PASSWORD`. Or set the role's password to the one you pass, with `sudo -u postgres psql -c "ALTER ROLE rbt PASSWORD '<password>'"`.

## `carto` stage

!!! warning "`dblink_connect` fails in `carto`"
    The `carto` scripts open `dblink` connections back to their own database with a connection
    string that names only `dbname`, `port`, and `options`: no host, user, or password. That works
    only when both of these hold:

    - **The pipeline's role (`rbt` by default) is a superuser.** `dblink` refuses a password-less
      connection string from any other role with `ERROR: password or GSSAPI delegated credentials
      required`, whatever `pg_hba.conf` says, so no `pg_hba.conf` entry can stand in for this.
      Make the role a superuser with `sudo -u postgres psql -c 'ALTER ROLE rbt SUPERUSER;'` (see
      [Ubuntu Setup](../install/ubuntu.md)).
    - **The server accepts a password-less connection on its local socket.** With no user named,
      each `dblink` session logs in as the operating-system user the server runs as, normally
      `postgres`. A stock Ubuntu cluster and one that `setup_ubuntu.sh` created both let `postgres`
      in through `peer`, and a cluster from an older `setup_ubuntu.sh` trusts every local
      connection. If `pg_hba.conf` asks for a password on local connections instead, the session
      fails with `ERROR: could not establish connection` and `fe_sendauth: no password supplied`.
      An entry for `127.0.0.1/32` or for the pipeline's role doesn't help. Put a
      `local all postgres peer` line ahead of any stricter `local` line, and reload Postgres.

    On a host set up by `setup_ubuntu.sh`, `pg_hba.conf` is in `PG_DATA_DIR` (default
    `/var/lib/postgresql/<version>/main`) and the unit is `postgresql-rbt`:
    `sudo systemctl reload postgresql-rbt`. On a manual install it's
    `/etc/postgresql/<version>/main/pg_hba.conf` and `sudo systemctl reload postgresql`. Naming a
    user in the connection strings would break `peer`; see the `dblink` item under "Report only" in
    the [September 2026 review](../project/code-review-2026-09.md#latent-problems-and-limitations).

**`carto` fails at `004_railway.sql` (or `014_energy.sql`) with `operator does not exist: text % unknown`.**

The database has no `pg_trgm` extension, which supplies the `%` similarity operator those two scripts use. No script creates it. `carto` creates it itself only when it runs script groups concurrently; at `-n 1`, which is the default on a host with fewer than 12 vCPUs, it runs the scripts in filename order and creates no extensions. So this appears on a small host with a database that was made without the extension, typically by a bare `createdb`. Add it, then rerun `carto`:

```bash
sudo -u postgres psql -d <database> -c 'CREATE EXTENSION IF NOT EXISTS pg_trgm'
```

A database needs all four of `postgis`, `hstore`, `dblink` and `pg_trgm`; see [Create a database and role](../install/ubuntu.md#create-a-database-and-role).

**`FATAL: sorry, too many clients already`, from `carto` or any other stage.**

Postgres has run out of connection slots (`max_connections`). `carto` is the heavy user: each group running concurrently holds a connection, and the water and land-cover scripts (`005a`, `009`) each open up to 16 more through `dblink` for their dissolves. Stock Postgres allows 100; both setup paths in [Ubuntu Setup](../install/ubuntu.md) raise it to 400. Check with `psql -h 127.0.0.1 -U rbt -d <database> -c 'SHOW max_connections'`, and look for other sessions holding slots (another build, or idle clients) with `SELECT count(*), state FROM pg_stat_activity GROUP BY state`. Then either raise the limit, which needs a restart:

```bash
sudo -u postgres psql -c 'ALTER SYSTEM SET max_connections = 400'
sudo systemctl restart postgresql-rbt   # postgresql on a manual install
```

or run fewer groups at once with a lower `carto -n`. Rerun `carto` afterwards; it starts from the first script again.

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

Downloads, FlatGeobufs and MBTiles are written under a temporary name (`<file>.part`, `flatgeobuf/.partial/`, `mbtiles/.partial/`) and moved into place only once complete, and an extracted archive gets a `.<folder>.complete` marker beside it. Older versions wrote straight to the final path, so a run that was killed or lost its connection could leave a truncated file there, and every later run skips a file that exists. Extractions without a marker are redone once on their own. If a run with an older version was ever interrupted, delete the files it may have cut short before reusing the directory: the aux downloads and Geofabrik extract it was fetching, and `flatgeobuf/*.fgb` and `mbtiles/*.mbtiles` if it died during `export`. (The planet download is unaffected: aria2c resumes a partial planet file and checks it against its MD5.) `ogrinfo` doesn't catch a truncated `.fgb`, and `tippecanoe` tiles one without complaint.

## `export`

!!! tip "Rebuilding only one export layer"
    Delete its `flatgeobuf/<layer>.fgb` and/or `mbtiles/<layer>.mbtiles`, then re-run `export` (see [Export stage](../pipeline/export.md)). Deleting only the `.mbtiles` (keeping the `.fgb`) skips straight to the `tippecanoe` step.

**Every layer's `tippecanoe` step fails with exit status 111 and `Too many open files`.**

Exit 111 is tippecanoe's "couldn't open a file". It starts one reader per CPU core and opens about ten files for each before it reads any input, so on a many-core host it needs more open files than the limit allows, and every layer fails the same way within seconds. The message is in `logs/<run_id>/fgb/<layer_id>_export_to_mbtiles.log`. `abt-tools.py` already raises its soft limit to the hard limit when it starts, and prints the result as `--- Open file limit: <now> (was <before>) ---`, so what's too low is the hard limit: check it with `ulimit -Hn`.

- On a host `setup_ubuntu.sh` set up, the raised limit applies only to login sessions started after the script ran. Log out and back in (or reconnect SSH), confirm with `ulimit -Hn`, and rerun `export`.
- Elsewhere, raise `nofile` for the user that runs the pipeline in `/etc/security/limits.d/` and log in again, or cap tippecanoe's readers for one run: `TIPPECANOE_MAX_THREADS=16 python abt-tools.py export ...`.

The rerun skips the layers that finished. The Overture `tile.sh` hits the same limit and takes the same two fixes.

## `bundler` and `vundler`

**`bundler` fails with "Missing required environment variables: PGHOST, …".**

`bundler` loads the export layers the same way `export` does, and that needs a Postgres configuration, although `bundler` never queries the database. With the default `-p env`, set the `PG*` variables as you would for the other stages; it doesn't connect. An explicit `-p <host>,<port>,<user>,<password>,<dbname>` is tested with a real connection, so Postgres must be up for that form.

**`vundler` fails with `No such file or directory: 'abt-vundler'`.**

The `abt-vundler` binary isn't on `PATH`. `setup_ubuntu.sh` builds it and installs it to `/usr/local/bin` unless `INSTALL_VUNDLER=false`; on a manual install, see step 7 of [Ubuntu Setup](../install/ubuntu.md#7-rust-and-abt-vundler). `setup_ubuntu.sh` skips the build when `abt-vundler` is already installed, so after changing `vundler-rs/` rerun it with `FORCE_REBUILD_VUNDLER=true`, or rebuild with `cargo build --release` yourself.

## `init.sh`

**`ERROR: another init.sh run is using /rbt/run-planet`.**

`init.sh` allows one run per run directory (`ABT_RUN_DIR`) and the lock is held, either by the run whose PID the message gives or, if that PID has gone, by a stage, Overture script or upload it left running. The message includes the `pgrep` command that finds them. See [One run at a time](../walkthroughs/init-sh.md#one-run-at-a-time).

## Memory and disk

**A stage fails with `Cannot allocate memory`, `out of memory` or `std::bad_alloc` while `free` shows memory to spare.**

`setup_ubuntu.sh` sets `vm.overcommit_memory=2`, which makes the kernel refuse an allocation up front once the memory every process has *reserved* reaches a fixed limit, rather than let the OOM killer pick a victim later. That limit is swap plus `vm.overcommit_ratio` percent of RAM (80 by default), and Postgres's `shared_buffers` counts against it. So a build can be refused memory with plenty of it unused. Postgres reports `ERROR: out of memory` or `could not fork new process for connection: Cannot allocate memory`; tippecanoe and the other tools report `Cannot allocate memory` or `std::bad_alloc`. Compare the two figures:

```bash
grep -E 'CommitLimit|Committed_AS' /proc/meminfo
```

If `Committed_AS` is near `CommitLimit`, reserve less or allow more:

- Run fewer things at once: a lower `-n` for `export` or `carto`, or under `init.sh` a lower `ABT_JOBS` or fewer `--projections` (each projection runs its own `ABT_JOBS` workers).
- Add swap, which raises the limit by its size.
- Raise the ratio: `sudo sysctl vm.overcommit_ratio=90` for now, and `VM_OVERCOMMIT_RATIO=90 ./setup_ubuntu.sh` to keep it (that rerun restarts Postgres, so not during a build). See [Configuration](../install/configuration.md).

Then rerun the stage that failed.

**A stage fails with `No space left on device`.**

The error is in the failed task's log or `summary.json`. From Postgres it reads `could not extend file ... No space left on device`, and from the bundler's SQLite step `database or disk is full`. Find the full filesystem with `df -h <working_dir>` and `df -h` on the Postgres data directory, then `du -sh <working_dir>/*` to see what's using it. With no stage running, these are safe to delete:

- **Unfinished output**: every `.partial/` directory (`flatgeobuf/.partial/`, `mbtiles/.partial/`, `bundled/.partial/`), `tmp/`, `bundled/_tmp/`, and `aux_downloads/*.part`. Keep a partial planet PBF and its `.aria2` file: `download` resumes from them.
- **`osm/imposm_cache/`**, once `import` has finished. Every import rebuilds it.
- **The `backup` schema** in the database. After an `import -f` over an existing import, imposm keeps the previous one there, about as large as the `osm` schema: `psql -h 127.0.0.1 -U rbt -d <database> -c 'DROP SCHEMA IF EXISTS backup CASCADE'`.
- **Overture shards**, once that projection's `building_polygon_<srs>.mbtiles` exists: `<overture dir>/parts/` and `parts_<srs>/`. `init.sh --overture-clean` removes each as it goes. Tiling that projection again means sharding it again.
- **`flatgeobuf/`**, once `mbtiles/` is complete, but only if you won't rerun `export` or use `init.sh --from export`, which both need the `.fgb` files and would export them again.

Then rerun the stage that failed. `download` and `export` skip what they finished. `bundler` builds beside the previous bundle and replaces it only at the end, so rebuilding over an existing bundle needs room for both; delete the old `bundled/joined.mbtiles` first if space is short.

## Geofabrik keys

**Confirming your Geofabrik key.**

The full list of valid `-k`/`--osm-key` values is Geofabrik's live index at `https://download.geofabrik.de/index-v1.json` (each entry's `id` field is a valid key). `download` fetches the PBF named by that entry's `urls.pbf`, which includes the parent regions, e.g. `https://download.geofabrik.de/europe/norway-latest.osm.pbf` for `norway`. `planet` is a special-cased key handled by the multi-mirror `aria2c` path and doesn't appear in that index.
