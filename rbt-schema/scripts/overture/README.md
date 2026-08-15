# Overture buildings pipeline

Standard (EPSG:3857):
```bash
./fetch.sh /path/to/data_dir [jobs] [shard_threads]
./tile.sh /path/to/data_dir
# -> data_dir/building_polygon_3857.mbtiles
```

EPSG:3395 (reprojected, then tippecanoe is told it's already 3857 so it doesn't reproject again):
```bash
mkdir -p /path/to/data_dir/parts_3395
export SHARD_THREADS=1 TARGET_SRS=3395
ls /path/to/data_dir/overture-buildings/*.parquet | xargs -P 24 -n 1 bash shard.sh /path/to/data_dir/parts_3395
./tile.sh /path/to/data_dir 3395
# -> data_dir/building_polygon_3395.mbtiles
```

Layer name is always `building_polygon` either way. `shard.sh` skips files already done, so it's safe to re-run.
