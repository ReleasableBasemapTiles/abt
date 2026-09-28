# Working Directory

Every `abt-tools.py` command takes `-w/--working-dir`: the directory it writes its downloads, intermediate files, tiles and logs into. Commands pass their results to each other through this directory, so give every command of one build the same `-w`. It's separate from the schema directory (`-s/--schema-dir`, normally `rbt-schema/`), which holds the configuration and is only ever read.

The walkthroughs use `~/abt/run-norway` and `~/abt/run-planet`; `init.sh` uses `/rbt/run-planet` for EPSG:3857 and `/rbt/run-planet-<srs>` for each other projection (see [init.sh Orchestrator](../walkthroughs/init-sh.md)).

## Layout

Every command except `vundler` creates the top-level folders below when it starts, and each fills in its own part:

```text
<working_dir>/
├── osm/
│   ├── pbf/<key>-latest.osm.pbf   download: the OSM extract (planet-latest.osm.pbf for -k planet)
│   ├── combined_mapping.yaml      import: every import/osm/*.yml merged into one imposm mapping
│   └── imposm_cache/              import: imposm's node, way and relation cache
├── aux_downloads/
│   ├── <file>                     download: one per import/aux_data/*.json source that has a url
│   ├── <name>_extracted/          download: a zip's contents (<name>_extracted.gdb for a geodatabase)
│   ├── .<name>_extracted.complete download: written once that extraction has finished
│   └── <layer>.fgb                import: a geodatabase layer converted before loading (MIRTA)
├── flatgeobuf/<layer_id>.fgb      export, step 1: ogr2ogr from export.<layer_id>
├── mbtiles/<layer_id>.mbtiles     export, step 2: tippecanoe from the .fgb
├── bundled/
│   ├── joined.mbtiles             bundler (or the name given to -o/--output-name)
│   ├── joined_bundler.log         bundler: tile-join's output
│   └── vundled/p12/               vundler: the Esri Compact Cache V2 tree, with a logs/ folder inside
├── tmp/                           export: scratch space for ogr2ogr and tippecanoe
└── logs/<run_id>/                 every command except vundler: its logs and summary.json
```

`<key>` is the `-k/--osm-key` extract's name as Geofabrik publishes it, e.g. `norway-latest.osm.pbf`.

## Files in progress

Nothing is written straight to its final name, so a killed or failed run never leaves a truncated file that the next run mistakes for a finished one:

| Output | While it's being written | Moved into place |
|---|---|---|
| A download | `<file>.part` beside it (for the planet, aria2c's `<file>.aria2` control file, which it resumes from) | once the whole body has arrived (and, for the planet, matched its MD5) |
| An extraction | `<name>_extracted.partial/` beside it | once every member is extracted; the `.complete` marker follows |
| A FlatGeobuf | `flatgeobuf/.partial/<layer_id>.fgb` | once `ogr2ogr` exits 0 |
| An MBTiles | `mbtiles/.partial/<layer_id>.mbtiles` | once `tippecanoe` exits 0 and its metadata is set |

A working directory from before this staging can still hold truncated files. See [Troubleshooting](../reference/troubleshooting.md#download-and-import) for which ones to delete.

## What reruns skip

| Command | Skips | Redoes |
|---|---|---|
| `download` | a download whose final file exists (aria2c instead resumes and re-checks a planet file); an extraction whose `.complete` marker exists | everything else |
| `import` | nothing. With `-d osm` or `-d all` it won't start while the `osm` schema has any table, unless `-f/--force`. | every source |
| `carto` | nothing | every script |
| `export` | an `.fgb` that exists; an `.mbtiles` that holds tiles | everything else |
| `bundler` | nothing: it deletes and rebuilds its output | the join |
| `vundler` | nothing, but it writes into the existing tree without clearing it | every bundle this conversion covers; bundles only an earlier conversion wrote (at a higher `-z`, say) stay |

To redo one download or one layer, delete its file and rerun the command. Delete `bundled/vundled/p12/` before rerunning `vundler` at a lower zoom. `bundler -z` without `-o` replaces `joined.mbtiles`, so give a zoom-capped bundle its own name, e.g. `-z 8 -o rbt_small.mbtiles`. `vundler` reads `bundled/joined.mbtiles` unless `-i/--input-path` names another file.

## Logs

Each command run (except `vundler`) writes into a new `logs/<run_id>/` folder, where `<run_id>` is the time it started, as `YYYY-MM-DD_HHMMSS`. A full build therefore leaves one folder per command, and two commands started in the same second share one.

| Folder | Written by | Holds |
|---|---|---|
| `download/` | `download` | one log per source, including `planet_download.log` with every mirror a planet download queried |
| `import/` | `import` | one log per source, and imposm's log |
| `carto/` | `carto` | the connection log, and the group scheduler's log when groups run concurrently. A script's SQL error is in `summary.json` and on the console. |
| `fgb/` | `export` | each layer's `ogr2ogr` log (`<layer_id>_export_to_fgb.log`) and its `tippecanoe` log (`<layer_id>_export_to_mbtiles.log`) |
| `mbtiles/` | nothing yet | created for every run, but `export` writes its `tippecanoe` logs into `fgb/` |

`bundler` writes `tile-join`'s log into `bundled/` rather than into `logs/`, and `vundler` writes its log into the output tree, at `bundled/vundled/p12/logs/`. Leave that folder out of anything you ship.

## `summary.json`

Every command except `vundler` ends by writing `logs/<run_id>/summary.json` and printing its path. It records every task the command ran, grouped by stage. An abridged example from an `export` run where one layer's `ogr2ogr` failed:

```json
{
  "run_id": "2026-09-28_101500",
  "invoked_command": "abt export",
  "started_at": "2026-09-28T10:15:00.482113",
  "finished_at": "2026-09-28T11:02:41.090645",
  "overall_status": "PARTIAL_FAILURE",
  "stages": [
    {
      "stage": "export_to_fgb",
      "status": "PARTIAL_FAILURE",
      "tasks": [
        {"task": "water_polygon", "status": "SUCCESS", "duration_s": 812.402},
        {"task": "road_line", "status": "FAILED", "duration_s": 3.215,
         "error": "Command '['ogr2ogr', ...]' returned non-zero exit status 1."}
      ]
    },
    {
      "stage": "export_to_mbtiles",
      "status": "PARTIAL_FAILURE",
      "tasks": [
        {"task": "water_polygon", "status": "SUCCESS", "duration_s": 2410.87},
        {"task": "road_line", "status": "FAILED", "error": "not attempted (export_to_fgb failed)"}
      ]
    }
  ]
}
```

- A stage's `status` is `SUCCESS` when all its tasks succeeded, `FAILED` when all failed, and `PARTIAL_FAILURE` otherwise. `overall_status` combines the stages the same way.
- `duration_s` is each task's wall-clock time in seconds. A task that was never started, because an earlier step of it failed, has no duration and the error `not attempted (<stage> failed)`.
- Passwords are redacted from every recorded command.

| Command | Stages it records |
|---|---|
| `download` | `download` (one task per source, the OSM extract included) and `aux_extraction` |
| `import` | `import` (one task per source) |
| `carto` | `carto` (one task, `process_sql`) and `carto_scripts` (one task per script, which is where to look for the slow ones) |
| `export` | `export_to_fgb` and `export_to_mbtiles` (one task per layer in each) |
| `bundler` | `bundle` (one task, `tile_join`) |

Every command exits non-zero when any of its tasks failed, so a script or `init.sh` running them stops at the first failed command. `carto` and `export` also print their ten slowest tasks.

## See also

- [Pipeline](pipeline.md): what each command reads and writes.
- [Troubleshooting](../reference/troubleshooting.md): finding the log for a failure.
- [Configuration](../install/configuration.md): the Postgres and environment settings the commands read.
