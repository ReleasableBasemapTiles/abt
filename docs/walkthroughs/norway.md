# Norway Walkthrough (Small Extract)

For fast iteration on schema/SQL changes — without planet-scale time or disk cost — the same pipeline can build a single Geofabrik extract instead. This walks through Norway (Geofabrik key `norway`, PBF currently ~1.4 GB); swap in any other Geofabrik key for a different extract (see "Confirming your Geofabrik key" in [Troubleshooting](../reference/troubleshooting.md)).

!!! note "Prerequisites"
    This walkthrough assumes the 8 vCPU / 32 GB tier from [Performance & Sizing](../install/performance.md), on a host set up either by [`setup_ubuntu.sh`](../install/ubuntu.md#automated-setup-setup_ubuntush) or by hand with [Ubuntu Setup](../install/ubuntu.md). Both leave a superuser role named `rbt` (password `rbt`), which is all the first step below needs.

For the full-scale version of this same sequence, see the [Planet walkthrough](planet.md). For the production, multi-projection, S3-uploading path that wraps all of these stages into one script, see [init.sh Orchestrator](init-sh.md).

## Create the database

The walkthrough builds into a database of its own, `rbt_norway`, so it can coexist with a planet build in `rbt` on the same host. Create it with the four extensions the pipeline needs ([Configuration](../install/configuration.md) says what each is for):

```bash
sudo -u postgres createdb -O rbt rbt_norway
sudo -u postgres psql -d rbt_norway <<'SQL'
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS hstore;
CREATE EXTENSION IF NOT EXISTS dblink;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
SQL
```

Skip this if `rbt_norway` already exists. To build into another database, such as the `rbt` one both setups create, set `PGDATABASE` to it below instead; it needs the same four extensions.

## Configure the database connection

Activate the Python environment and `cd` into the checkout's `abtv2-tools/`. The paths on this page assume the repo is cloned to `~/abt`, with each run's working directory inside the clone.

=== "After `setup_ubuntu.sh`"

    ```bash
    micromamba activate abtv2
    cd ~/abt/abtv2-tools
    ```

    Use the `abtv2-tools/` of the checkout you ran the script from: `/rbt/abtv2-tools` if you cloned to `/rbt`.

=== "After the manual setup"

    ```bash
    conda activate abtv2
    cd ~/abt/abtv2-tools
    ```

Then export the connection. `rbt` is the default role and password on both paths; use your own if you set `PG_USER` or `PG_PASSWORD`.

```bash
export PGHOST=127.0.0.1
export PGPORT=5432
export PGUSER=rbt
export PGPASSWORD=rbt
export PGDATABASE=rbt_norway
```

With these exported, every command below can use `-p env` for `--pg-config`.

## Download

```bash
python abt-tools.py download \
  -w ~/abt/run-norway \
  -s ../rbt-schema \
  -d all \
  -k norway \
  -n 4
```

!!! warning "Don't omit `-k`"
    `-k norway` selects Norway from Geofabrik's live index instead of the default `planet` — do not omit `-k`, or this becomes a full-planet download.

- `-d all` downloads the Norway PBF and every auxiliary dataset.
- Output: `~/abt/run-norway/osm/pbf/norway-latest.osm.pbf` and `~/abt/run-norway/aux_downloads/`. Safe to re-run if interrupted.
- `-n 4` matches this tier's (8 vCPU) auto-computed default; scales up on its own on bigger hosts.

## Import

```bash
python abt-tools.py import \
  -w ~/abt/run-norway \
  -s ../rbt-schema \
  -d all \
  -n 4 \
  -p env \
  -k norway \
  -c
```

- `-c`/`--clip-aux` clips the globally-scoped aux datasets (Natural Earth, coastlines, etc.) to Norway's bounding box before loading — this is what keeps a "small area" build fast; ignored if `-k` is `planet` or omitted.
- OSM via `imposm import` into the `osm` schema; aux via `ogr2ogr` in parallel into the `aux_data` schema (dropped/recreated first).
- Re-running after OSM already loaded aborts unless `-f`/`--force`.

## Carto (SQL transform)

```bash
python abt-tools.py carto \
  -w ~/abt/run-norway \
  -s ../rbt-schema \
  -p env
```

Same as the [planet walkthrough](planet.md), but on an 8 vCPU host `--carto-concurrency` computes to 1 (fully sequential), matching pre-concurrency behavior. See [Carto SQL](../schema/carto-sql.md) for the concurrency mechanics.

## Export to tiles

```bash
python abt-tools.py export \
  -w ~/abt/run-norway \
  -s ../rbt-schema \
  -n 4 \
  -p env \
  -z 13
```

## Bundle

```bash
python abt-tools.py bundler \
  -w ~/abt/run-norway \
  -s ../rbt-schema \
  -p env
```

Writes `~/abt/run-norway/bundled/joined.mbtiles`. For a smaller "RBT Small" build, add a zoom cap and an output name of its own, since the bundler rebuilds its output from scratch and `-z` alone would overwrite the full-resolution `joined.mbtiles`:

```bash
python abt-tools.py bundler \
  -w ~/abt/run-norway \
  -s ../rbt-schema \
  -p env \
  -z 8 \
  -o rbt_small.mbtiles
```

## (Optional) Vundler

```bash
python abt-tools.py vundler \
  -w ~/abt/run-norway \
  -z 13
```

See [vundler-rs](../reference/vundler-rs.md) for internals.

## Check the results

```bash
cat ~/abt/run-norway/logs/*/summary.json
```

```bash
sqlite3 ~/abt/run-norway/bundled/joined.mbtiles \
  "SELECT name, value FROM metadata;"
```
