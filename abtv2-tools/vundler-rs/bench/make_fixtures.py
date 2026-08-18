"""
make_fixtures.py

Generates small, deterministic synthetic .mbtiles fixtures for fast
correctness-focused iteration (the real-world samples are hundreds of MB and
too slow for a tight edit/verify loop). Each fixture uses the same
map/images/tiles-view schema tippecanoe and tile-join actually produce (see
bench/README.md) -- confirmed locally rather than assumed.

Tile payloads are deterministic pseudo-random bytes of varying length, keyed
on (zoom, x, y), so both a missing tile and a byte-corrupted tile are
detectable by the oracle.
"""

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Dict, Iterable, Optional, Tuple

SCHEMA = """
CREATE TABLE metadata (name text, value text);
CREATE UNIQUE INDEX name on metadata (name);
CREATE TABLE map (zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_id TEXT);
CREATE UNIQUE INDEX map_index ON map (zoom_level, tile_column, tile_row);
CREATE TABLE images (zoom_level integer, tile_data blob, tile_id text);
CREATE UNIQUE INDEX images_id ON images (zoom_level, tile_id);
CREATE VIEW tiles AS SELECT map.zoom_level AS zoom_level, map.tile_column AS tile_column, map.tile_row AS tile_row, images.tile_data AS tile_data FROM map JOIN images ON images.tile_id = map.tile_id and images.zoom_level = map.zoom_level;
"""


def tile_payload(zoom: int, x: int, y: int) -> bytes:
    """Deterministic variable-length payload (17..273 bytes) for one tile."""
    digest = hashlib.sha256(f"{zoom}/{x}/{y}".encode()).digest()
    length = 17 + (digest[0] * (256 - 17)) // 256
    body = (digest * ((length // len(digest)) + 1))[:length]
    return f"z{zoom}x{x}y{y}:".encode() + body


def write_mbtiles(
    path: Path,
    tiles: Iterable[Tuple[int, int, int]],
    metadata: Optional[Dict] = None,
) -> int:
    """Writes tiles (iterable of raw (zoom, tile_column, tile_row) in TMS
    convention, i.e. row 0 = south) into a fresh mbtiles file at `path`.
    Returns the number of tiles written.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    con = sqlite3.connect(path)
    try:
        con.executescript(SCHEMA)
        count = 0
        for i, (zoom, x, y) in enumerate(tiles):
            tile_id = str(i)
            data = tile_payload(zoom, x, y)
            con.execute(
                "INSERT INTO images (zoom_level, tile_data, tile_id) VALUES (?,?,?)",
                (zoom, data, tile_id),
            )
            con.execute(
                "INSERT INTO map (zoom_level, tile_column, tile_row, tile_id) VALUES (?,?,?,?)",
                (zoom, x, y, tile_id),
            )
            count += 1
        if metadata is not None:
            con.execute(
                "INSERT INTO metadata (name, value) VALUES ('json', ?)",
                (json.dumps(metadata, ensure_ascii=False),),
            )
        con.commit()
        return count
    finally:
        con.close()


def full_zoom(zoom: int) -> Iterable[Tuple[int, int, int]]:
    n = 2 ** zoom
    for y in range(n):
        for x in range(n):
            yield (zoom, x, y)


def sparse_zoom(zoom: int, keep_every: int) -> Iterable[Tuple[int, int, int]]:
    n = 2 ** zoom
    for y in range(n):
        for x in range(n):
            if (x * n + y) % keep_every == 0:
                yield (zoom, x, y)


DEFAULT_METADATA = {
    "name": "vundler-rs fixture",
    "description": "synthetic test data, not real map content",
    "format": "pbf",
    "bounds": [-179.99999999999997, -60.0, 179.99999999999997, 83.0],
    "center": [-77.0365, 38.8977, 10],
    "unicode_check": "caf\u00e9 \u65e5\u672c\u8a9e",
}


def build_all(out_dir: Path) -> None:
    fixtures = {}

    # Sub-bundle zooms: every zoom from 0..6 fits inside a single 128x128
    # bundle (2^6 = 64 < 128) -- "a zoom below 8 narrower than one bundle".
    tiles = []
    for z in range(0, 7):
        tiles.extend(full_zoom(z))
    fixtures["tiny_sub_bundle.mbtiles"] = (tiles, DEFAULT_METADATA)

    # Exact bundle-width boundary: zoom 7 is exactly 128x128 (one full
    # bundle), zoom 8 is 256x256 (spans a 2x2 grid of bundles).
    tiles = list(full_zoom(7)) + list(full_zoom(8))
    fixtures["boundary_zoom7_8.mbtiles"] = (tiles, DEFAULT_METADATA)

    # Sparse coverage at higher zooms, like a real point-label layer -- most
    # bundle index slots stay empty (zero) rather than every slot filled.
    tiles = []
    for z in range(4, 11):
        keep_every = max(1, z * 3)
        tiles.extend(sparse_zoom(z, keep_every))
    fixtures["sparse_multizoom.mbtiles"] = (tiles, DEFAULT_METADATA)

    # For --max-zoom truncation: real data up through z12, deliberately run
    # through vundler with a lower --max-zoom in the golden check.
    tiles = []
    for z in range(6, 13):
        keep_every = max(1, z * 2)
        tiles.extend(sparse_zoom(z, keep_every))
    fixtures["truncation_source.mbtiles"] = (tiles, DEFAULT_METADATA)

    # No metadata row at all -- _write_metadata/write_metadata should just
    # skip writing metadata.json rather than erroring.
    fixtures["no_metadata.mbtiles"] = (list(full_zoom(3)), None)

    # Empty (zero tiles) -- convert() must handle "no zoom levels at all"
    # without erroring; metadata.json should still be attempted.
    fixtures["empty.mbtiles"] = ([], DEFAULT_METADATA)

    for filename, (tiles, metadata) in fixtures.items():
        path = out_dir / filename
        count = write_mbtiles(path, tiles, metadata)
        print(f"{path}: {count} tiles")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-dir", type=Path, default=Path(__file__).parent / "fixtures")
    args = ap.parse_args()
    build_all(args.out_dir)
