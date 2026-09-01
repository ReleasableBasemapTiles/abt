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

Parts dir is `parts_<srs>` and output is `building_polygon_<srs>.mbtiles`; the
layer name is always `building_polygon`. `shard.sh` skips files already done, so
it's safe to re-run.

`area` is always `ST_Area_Spheroid` off the source WGS84 geometry, so the zoom
filters in `tile.sh` mean the same thing in every projection.

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
