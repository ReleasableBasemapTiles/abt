"""
fixtures.py

Tiny, deterministic .mbtiles fixtures for the golden cross-check
(test_golden.py). Deliberately small (dozens of tiles, not tens of
thousands) -- edge-case coverage comes from placing tiles AT bundle
boundaries rather than filling whole zoom levels, unlike
../bench/make_fixtures.py's fixtures (which are realistic-sized, up to
222 MB -- fine for bench/'s manual benchmarking use, but far too large to
generate on every test run or commit to git; see ../bench/.gitignore).

Uses the same map/images/tiles-view schema tippecanoe/tile-join actually
produce -- see ../bench/README.md, confirmed locally rather than assumed.
"""

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Callable, Dict, Iterable, Optional, Tuple

SCHEMA_CORE = """
CREATE TABLE map (zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_id TEXT);
CREATE UNIQUE INDEX map_index ON map (zoom_level, tile_column, tile_row);
CREATE TABLE images (zoom_level integer, tile_data blob, tile_id text);
CREATE UNIQUE INDEX images_id ON images (zoom_level, tile_id);
CREATE VIEW tiles AS SELECT map.zoom_level AS zoom_level, map.tile_column AS tile_column, map.tile_row AS tile_row, images.tile_data AS tile_data FROM map JOIN images ON images.tile_id = map.tile_id and images.zoom_level = map.zoom_level;
"""

SCHEMA_METADATA = """
CREATE TABLE metadata (name text, value text);
CREATE UNIQUE INDEX name on metadata (name);
"""

DEFAULT_METADATA = {
    "name": "vundler-rs test fixture",
    "description": "synthetic test data, not real map content",
    "format": "pbf",
    "bounds": [-179.99999999999997, -60.0, 179.99999999999997, 83.0],
    "unicode_check": "caf\u00e9 \u65e5\u672c\u8a9e",
}


def tile_payload(zoom: int, x: int, y: int) -> bytes:
    """Deterministic variable-length payload (17..273 bytes) for one tile
    -- same construction as bench/make_fixtures.py's tile_payload, so a
    missing or corrupted tile is detectable by the oracle."""
    digest = hashlib.sha256(f"{zoom}/{x}/{y}".encode()).digest()
    length = 17 + (digest[0] * (256 - 17)) // 256
    body = (digest * ((length // len(digest)) + 1))[:length]
    return f"z{zoom}x{x}y{y}:".encode() + body


def full_zoom(zoom: int) -> Iterable[Tuple[int, int, int]]:
    """Every (zoom, x, y) tile at `zoom`, TMS convention. Only safe for
    small zooms (<=6, i.e. <=4096 tiles) -- see sparse_sample for higher
    zooms."""
    n = 2 ** zoom
    for y in range(n):
        for x in range(n):
            yield (zoom, x, y)


def sparse_sample(zoom: int, count: int) -> Iterable[Tuple[int, int, int]]:
    """`count` deterministic, well-spread (zoom, x, y) coordinates within
    zoom's full 2**zoom square, WITHOUT enumerating the whole (potentially
    huge) grid -- unlike bench/make_fixtures.py's sparse_zoom (which
    is only affordable there because that module's fixtures are allowed
    to be large). Coordinates aren't guaranteed unique for small `count`
    relative to a huge n, but collisions are harmless (sqlite dedupes via
    the `map_index` unique constraint, so the caller may get slightly
    fewer than `count` tiles -- fine for "sparse coverage", not fine for
    exact-count assertions).
    """
    n = 2 ** zoom
    seen = set()
    for i in range(count):
        digest = hashlib.sha256(f"sparse/{zoom}/{i}".encode()).digest()
        x = int.from_bytes(digest[0:4], "big") % n
        y = int.from_bytes(digest[4:8], "big") % n
        if (x, y) in seen:
            continue
        seen.add((x, y))
        yield (zoom, x, y)


def write_mbtiles(
    path: Path,
    tiles: Iterable[Tuple[int, int, int]],
    metadata: Optional[Dict] = None,
    orphan_map_rows: Iterable[Tuple[int, int, int]] = (),
    include_metadata_table: bool = True,
) -> int:
    """Writes `tiles` (iterable of raw (zoom, tile_column, tile_row) in TMS
    convention, i.e. row 0 = south) into a fresh mbtiles file at `path`.

    `orphan_map_rows` inserts `map` rows with NO matching `images` row --
    real tippecanoe/tile-join output never produces this, but it exercises
    the known map-vs-tiles-view enumeration divergence between the Rust
    and Python implementations (see docs/code-review-findings.md).

    `include_metadata_table=False` omits the `metadata` table entirely --
    distinct from a present-but-empty table, or a present table with no
    'json' row (pass `metadata=None` with the default `True` for that).

    Returns the number of real (non-orphan) tiles written.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    con = sqlite3.connect(path)
    try:
        con.executescript(SCHEMA_CORE)
        if include_metadata_table:
            con.executescript(SCHEMA_METADATA)

        count = 0
        next_id = 0
        for zoom, x, y in tiles:
            tile_id = str(next_id)
            next_id += 1
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

        for zoom, x, y in orphan_map_rows:
            tile_id = f"orphan{next_id}"
            next_id += 1
            con.execute(
                "INSERT INTO map (zoom_level, tile_column, tile_row, tile_id) VALUES (?,?,?,?)",
                (zoom, x, y, tile_id),
            )

        if include_metadata_table and metadata is not None:
            con.execute(
                "INSERT INTO metadata (name, value) VALUES ('json', ?)",
                (json.dumps(metadata, ensure_ascii=False),),
            )
        con.commit()
        return count
    finally:
        con.close()


def _single_tile_z0(path: Path) -> None:
    """One tile at zoom 0 -- the whole world is a single tile, far
    narrower than one 128x128 bundle."""
    write_mbtiles(path, [(0, 0, 0)], DEFAULT_METADATA)


def _sub_bundle_zoom(path: Path) -> None:
    """Zoom 6 is 64x64 -- fits entirely inside a single 128x128 bundle."""
    write_mbtiles(path, list(full_zoom(6)), DEFAULT_METADATA)


def _bundle_seam(path: Path) -> None:
    """Zoom 8 is 256x256 (a 2x2 grid of bundles) -- places tiles at
    columns/rows 0, 127, 128, and 255 so every bundle-boundary seam is
    exercised without filling the whole 65,536-tile zoom."""
    seam_coords = [0, 127, 128, 255]
    tiles = [(8, x, y) for x in seam_coords for y in seam_coords]
    write_mbtiles(path, tiles, DEFAULT_METADATA)


def _sparse_high_zoom(path: Path) -> None:
    """Sparse coverage at a higher zoom, like a real point-label layer --
    most bundle index slots stay empty (zero) rather than every slot
    filled."""
    write_mbtiles(path, list(sparse_sample(12, count=24)), DEFAULT_METADATA)


def _multi_zoom_for_truncation(path: Path) -> None:
    """Spans zooms 5..9 so a lower --max-zoom demonstrably truncates
    output rather than trivially converting everything."""
    tiles = []
    for z in range(5, 10):
        tiles.extend(sparse_sample(z, count=6))
    write_mbtiles(path, tiles, DEFAULT_METADATA)


def _orphan_map_row(path: Path) -> None:
    """A `map` row with no matching `images` row alongside one real tile
    at the same zoom -- exercises the known enumeration divergence
    between the Rust binary (discovers bundle keys from `map` directly)
    and the Python reference (only ever sees the `tiles` view's inner
    join). See docs/code-review-findings.md."""
    write_mbtiles(
        path,
        tiles=[(9, 10, 10)],
        metadata=DEFAULT_METADATA,
        orphan_map_rows=[(9, 200, 200)],
    )


def _no_metadata_row(path: Path) -> None:
    """`metadata` table present but with no 'json' row."""
    write_mbtiles(path, list(full_zoom(3)), metadata=None)


def _no_metadata_table(path: Path) -> None:
    """`metadata` table absent entirely -- a pre-existing, shared
    limitation (not a Rust-port regression): neither implementation
    guards against this. See docs/code-review-findings.md."""
    write_mbtiles(path, list(full_zoom(3)), metadata=None, include_metadata_table=False)


def _empty(path: Path) -> None:
    """Zero tiles at all -- convert() must handle "no zoom levels" without
    erroring; metadata.json should still be attempted."""
    write_mbtiles(path, [], DEFAULT_METADATA)


FIXTURES: Dict[str, Callable[[Path], None]] = {
    "single_tile_z0": _single_tile_z0,
    "sub_bundle_zoom": _sub_bundle_zoom,
    "bundle_seam": _bundle_seam,
    "sparse_high_zoom": _sparse_high_zoom,
    "multi_zoom_for_truncation": _multi_zoom_for_truncation,
    "orphan_map_row": _orphan_map_row,
    "no_metadata_row": _no_metadata_row,
    "no_metadata_table": _no_metadata_table,
    "empty": _empty,
}


def build(name: str, out_dir: Path) -> Path:
    """Builds the named fixture (see FIXTURES) into out_dir and returns
    its path."""
    path = out_dir / f"{name}.mbtiles"
    FIXTURES[name](path)
    return path
