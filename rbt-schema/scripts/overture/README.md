# Overture buildings pipeline

Standard (EPSG:3857):
```bash
./fetch.sh /path/to/data_dir [jobs] [shard_threads]
./tile.sh /path/to/data_dir
# -> data_dir/building_polygon_3857.mbtiles
```

Any other projected SRS (reprojected in `shard.sh`, then tippecanoe is told it's
already 3857 so it doesn't reproject again). Substitute the EPSG code — e.g. 3395
(World Mercator) or 4087 (World Equidistant Cylindrical):
```bash
SRS=4087
mkdir -p /path/to/data_dir/parts_$SRS
export SHARD_THREADS=1 TARGET_SRS=$SRS
ls /path/to/data_dir/overture-buildings/*.parquet | xargs -P 24 -n 1 bash shard.sh /path/to/data_dir/parts_$SRS
./tile.sh /path/to/data_dir $SRS
# -> data_dir/building_polygon_4087.mbtiles
```

`fetch.sh` itself can drive several projections in one call instead of the manual
sharding above -- set `SRS_LIST` to a space-separated list (default `"3857"`) and
it shards once per entry, into `parts/` for `3857` and `parts_<srs>/` for anything
else:
```bash
SRS_LIST="3857 3395 4087" ./fetch.sh /path/to/data_dir [jobs]
./tile.sh /path/to/data_dir 3857
./tile.sh /path/to/data_dir 3395
./tile.sh /path/to/data_dir 4087
```
[`init.sh --overture`](../../../init.sh) runs this exact combination in the
background, for whichever projections `--projections` lists (default: all
three), and feeds each output to its matching bundler run automatically.
`--overture` also accepts the list directly as its own argument, as
shorthand for passing both flags -- `--overture "3857 4087"` is equivalent
to `--overture --projections "3857 4087"`. `--overture-clean` takes the
same shorthand.

`fetch.sh` re-resolves the latest Overture release from S3 on every run -- set
`OVERTURE_RELEASE=<release>` to pin one instead and skip that lookup entirely. It
refuses to `sync` into a `data_dir` already populated from a *different* release,
so mixing two releases' parquet together takes an explicit `OVERTURE_RELEASE`
(or clearing the directory), not an accident.

Any non-3857 build ends by running `tag_crs.py`, which writes a `crs` key into the
mbtiles metadata -- the header itself says 3857, so downstream has no other way to
know. It touches only that key; tippecanoe's `bounds`/`center` are left alone.
Standard library only, so it runs under any python3 -- set `PYTHON` to pick a
different interpreter. To re-tag without rebuilding:
```bash
python3 tag_crs.py 4087 /path/to/data_dir/building_polygon_4087.mbtiles
```

[`init.sh --contours`](../../../init.sh) reuses this same script to tag
externally-produced, reprojected `contours_<srs>.mbtiles` files before
bundling -- see the top-level [README.md](../../README.md) for that flag.

Parts dir is `parts_<srs>` and output is `building_polygon_<srs>.mbtiles` -- every
projection uses the same extension, so it's the `crs` metadata row `tag_crs.py`
writes (see above), not the filename, that marks a build as not web mercator. The
layer name is always `building_polygon`. `shard.sh` skips files already done, and
`fetch.sh`'s S3 download is an `aws s3 sync` rather than a plain recursive copy,
so the whole pipeline is safe to re-run after an interruption -- see
"Concurrency" below for what that guarantee depends on.

`area` is always `ST_Area_Spheroid` off the source WGS84 geometry, so the zoom
filters in `tile.sh` mean the same thing in every projection.

Both `shard.sh`'s `TARGET_SRS` and `tile.sh`'s `srs` argument accept any numeric
EPSG code, not just 3395/4087 -- each rejects a non-numeric value outright rather
than silently mishandling a typo.

## Concurrency

`fetch.sh` and `tile.sh` coordinate through a single `flock` on
`<data_dir>/.lock` (see `lock.sh`): `fetch.sh` takes it **exclusive** (it's
the only writer to the parts dirs), `tile.sh` takes it **shared** (parallel
`tile.sh` runs for different projections have always been safe -- see the
examples above -- but neither may overlap with a `fetch.sh` pass, which
would still be reading/writing the same parts dir). Acquiring the lock
fails fast rather than blocking, so a second run against the same data dir
gets an immediate, actionable error instead of silently interleaving with
the first one and corrupting its `.fgb` shards:

```
ERROR: could not acquire the exclusive lock on '/path/to/data_dir' (held by PID 12345).
       A concurrent fetch.sh/tile.sh run against this data dir corrupts its parts/*.fgb shards.
       See the 'Concurrency' section of rbt-schema/scripts/overture/README.md.
```

If you see this, there really is another run in progress against the same
data dir. Find it and either wait for it to finish or kill it:
```bash
pgrep -af 'fetch.sh|shard.sh|tile.sh|duckdb|tippecanoe'
```

[`init.sh --overture`](../../../init.sh) starts this pipeline in the
background and kills it (and its whole process tree, not just the
immediate subshell) if `init.sh` itself exits early for any other reason --
including a failure hours later at `[4/6] export` -- so that no longer
leaves an orphaned `fetch.sh` running behind it to collide with a
subsequent re-run. That protection only covers `init.sh` exiting normally
enough to run its own trap (including Ctrl-C), though; a `kill -9` on
`init.sh`'s own process, or a host crash, still bypasses it and can leave
the background pipeline running as an orphan. The lock above is what turns
that edge case into the loud error shown above on the next run, instead of
a second, silently corrupting writer.

A hard kill (`kill -9`, OOM, power loss) partway through a single `shard.sh`
worker is the ordinary case the "safe to re-run" claim above is about, and
needs no manual cleanup: `shard.sh`'s per-process temp file
(`.<name>.<pid>.tmp`) is simply left behind, and the next `fetch.sh` sweeps
any such leftovers for a projection before resharding it, since holding the
exclusive lock guarantees nothing else can be writing one at the same time.

## Reclaiming disk

There is one parts dir per projection and each holds a full FlatGeobuf copy of
every building footprint, so at planet scale they dominate the pipeline's disk
use. `CLEAN_PARTS=true` makes `tile.sh` delete the parts dir it just consumed:
```bash
CLEAN_PARTS=true ./tile.sh /path/to/data_dir 4087   # removes parts_4087/ on success
```
It runs only after tiling (and `tag_crs.py`) succeed, so a failed build keeps its
shards to retry from. Nothing regenerates them afterwards, though -- re-tiling
that projection later means re-sharding first, which is why this is opt-in rather
than the default. `overture-buildings/` (the downloaded parquet) is never touched:
it is shared by every projection, and re-downloading it costs far more than
re-sharding.

[`init.sh --overture-clean`](../../../init.sh) turns this on for every listed
projection. It shrinks the footprint left behind during bundling, but not the
peak -- `fetch.sh` shards every listed projection before tiling begins, so all
of them still coexist during that phase.

## Tuning

`shard.sh` runs one single-file duckdb job per input; `xargs -P` sets how many run
at once. Three env vars per worker:

| var | default | notes |
|---|---|---|
| `SHARD_THREADS` | 4 | duckdb threads *per worker*. Keep at 1 when `-P` is high. |
| `SHARD_MEM` | 8GB | duckdb `memory_limit` *per worker*. |
| `SHARD_TMP` | `<datadir>/duck_tmp` | duckdb spill dir, derived from the parts dir's parent. |

`SHARD_MEM` matters: duckdb's own default is ~80% of **system** RAM, which every
concurrent worker would claim in full, so they exhaust RAM before any of them
spills. Budget roughly `RAM / -P` and leave headroom.

`tile.sh` raises its own open-file limit (soft `ulimit -n`) before invoking
tippecanoe, and logs the result to stderr. tippecanoe opens roughly ten
descriptors per reader while it sets up, one reader per host CPU, so a
many-core box can need more than the usual default of 1024 -- without this,
tippecanoe dies partway through setup with `open vertexfile ...: Too many
open files` (exit 111) before reading a single feature. Same fix as
`abt/utils/rlimit.py` applies for the Python CLI. If a host's hard limit
still can't go high enough, set `TIPPECANOE_MAX_THREADS` to cap tippecanoe's
reader pool (and so its descriptor use) directly instead:
```bash
TIPPECANOE_MAX_THREADS=32 ./tile.sh /path/to/data_dir
```
