"""
vundler_reference.py

FROZEN ORACLE -- do not edit to make a golden test pass. If a golden test
fails, the bug is in the Rust port, or in this file's transcription of the
original (diff against `git show 9b85f2b:abtv2-tools/abt/vundler.py` to
check) -- not "the reference is out of date". The whole point of a golden
oracle is that it doesn't move.

This is a byte-for-byte transcription of the pre-port Python vundler's
tile-writing logic (`abt/vundler.py` at git commit 9b85f2b, before that
file was rewired to shell out to the abt-vundler Rust binary -- see
../../bench/README.md's "Important" section for why bench/run_python.py
can no longer serve this role).

Two deliberate, output-preserving deviations from the original so this
has zero dependency on the live `abt` package (which needs pydantic) and
can run standalone under pytest:

1. Plain `mbtiles_path`/`output_dir`/`max_zoom` args instead of a
   `VundlerConverter` pydantic model.
2. `convert()` runs each zoom level sequentially in-process instead of via
   `ProcessPoolExecutor`. This cannot change the output: each zoom level
   writes to its own `L{zoom:02d}` subdirectory (no shared file state
   across zooms), and the tile order *within* a zoom is fully determined
   by the frozen `ORDER BY tile_row DESC, tile_column ASC` query below,
   independent of which process/thread executes it. Only wall-clock time
   changes, and the fixtures this runs against (see ../fixtures.py) are
   tiny by design.
"""

import json
import sqlite3
import struct
from pathlib import Path
from typing import List, Optional

BUNDLE_SIZE = 128  # tiles per bundle edge
TILES_PER_BUNDLE = BUNDLE_SIZE ** 2
INDEX_SIZE_BYTES = TILES_PER_BUNDLE * 8


def flip_y(zoom: int, y: int) -> int:
    return (2 ** zoom - 1) - y


class BundleWriter:
    """Writes tiles into Esri Compact Cache V2 .bundle files for one zoom level."""

    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._file = None
        self._name: Optional[str] = None
        self._index: List[int] = []
        self._offset = 0
        self._max_size = 0

    def _init_bundle(self, path: Path) -> None:
        header = struct.pack(
            "<4I3Q6I",
            3, TILES_PER_BUNDLE, 0, 5, 0,
            64 + INDEX_SIZE_BYTES, 40, 20 + INDEX_SIZE_BYTES,
            3, 16, TILES_PER_BUNDLE, 5, INDEX_SIZE_BYTES,
        )
        with path.open("wb") as f:
            f.write(header)
            f.write(struct.pack(f"<{TILES_PER_BUNDLE}Q", *([0] * TILES_PER_BUNDLE)))

    def _open_bundle(self, row: int, col: int) -> None:
        start_row = (row // BUNDLE_SIZE) * BUNDLE_SIZE
        start_col = (col // BUNDLE_SIZE) * BUNDLE_SIZE
        name = f"R{start_row:04x}C{start_col:04x}"
        if name == self._name:
            return
        self.close()

        self._name = name
        path = self.output_dir / f"{name}.bundle"
        if not path.exists():
            self._init_bundle(path)

        self._file = path.open("r+b")
        self._file.seek(8)
        self._max_size = struct.unpack("<I", self._file.read(4))[0]
        self._file.seek(64)
        self._index = list(struct.unpack(f"<{TILES_PER_BUNDLE}Q", self._file.read(INDEX_SIZE_BYTES)))
        self._file.seek(0, 2)
        self._offset = self._file.tell()

    def add_tile(self, row: int, col: int, tile_data: bytes) -> None:
        self._open_bundle(row, col)
        size = len(tile_data)
        self._file.write(struct.pack("<I", size))
        self._file.write(tile_data)
        self._offset += 4
        self._index[(row % BUNDLE_SIZE) * BUNDLE_SIZE + col % BUNDLE_SIZE] = self._offset + (size << 40)
        self._offset += size
        self._max_size = max(self._max_size, size)

    def close(self) -> None:
        if self._file and not self._file.closed:
            self._file.seek(8)
            self._file.write(struct.pack("<I", self._max_size))
            self._file.seek(24)
            self._file.write(struct.pack("<Q", self._offset))
            self._file.seek(64)
            self._file.write(struct.pack(f"<{TILES_PER_BUNDLE}Q", *self._index))
            self._file.close()
        self._name = None


def _convert_level(mbtiles_path: Path, output_dir: Path, zoom: int) -> None:
    """Converts one zoom level -- see module docstring point 2 for why this
    runs sequentially here instead of in its own worker process."""
    con = sqlite3.connect(f"file:{mbtiles_path}?mode=ro", uri=True)
    try:
        writer = BundleWriter(output_dir / "tile" / f"L{zoom:02d}")
        rows = con.execute(
            "SELECT tile_column, tile_row, tile_data FROM tiles "
            "WHERE zoom_level = ? ORDER BY tile_row DESC, tile_column ASC",
            (zoom,),
        )
        for x, y, tile_data in rows:
            writer.add_tile(flip_y(zoom, y), x, tile_data)
        writer.close()
    finally:
        con.close()


def _write_metadata(output_dir: Path, con: sqlite3.Connection) -> None:
    row = con.execute("SELECT value FROM metadata WHERE name = 'json'").fetchone()
    if not row:
        return
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "metadata.json").write_text(
        json.dumps(json.loads(row[0]), ensure_ascii=False)
    )


def convert(mbtiles_path: Path, output_dir: Path, max_zoom: int) -> None:
    """Converts every zoom level up to `max_zoom`, then writes
    metadata.json -- see module docstring for the two deliberate,
    output-preserving deviations from the original (plain args instead of
    VundlerConverter, sequential instead of ProcessPoolExecutor)."""
    con = sqlite3.connect(mbtiles_path)
    try:
        levels = [
            row[0] for row in con.execute("SELECT DISTINCT zoom_level FROM tiles")
            if row[0] <= max_zoom
        ]
    finally:
        con.close()

    if levels:
        (output_dir / "tile").mkdir(parents=True, exist_ok=True)
        for zoom in levels:
            _convert_level(mbtiles_path, output_dir, zoom)

    con = sqlite3.connect(mbtiles_path)
    try:
        _write_metadata(output_dir, con)
    finally:
        con.close()
