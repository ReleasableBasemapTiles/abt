"""
vundler.py

Converts an mbtiles database into Esri's Compact Cache V2 tile bundle format
(one .bundle file per 128x128 tile block, per zoom level). Ported from the
standalone `Vundler` tool. Produces the raw tile-bundle folder structure and a
bare metadata.json -- not a complete, packaged .vtpk (no conf.xml/root.json).
"""

import json
import sqlite3
import struct
from pathlib import Path
from typing import List, Optional

from .vundler_model import VundlerConverter

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


def _convert_level(converter: VundlerConverter, con: sqlite3.Connection, zoom: int) -> None:
    writer = BundleWriter(converter.output_dir / "tile" / f"L{zoom:02d}")
    rows = con.execute(
        "SELECT tile_column, tile_row, tile_data FROM tiles "
        "WHERE zoom_level = ? ORDER BY tile_row DESC, tile_column ASC",
        (zoom,),
    )
    for x, y, tile_data in rows:
        writer.add_tile(flip_y(zoom, y), x, tile_data)
    writer.close()


def _write_metadata(converter: VundlerConverter, con: sqlite3.Connection) -> None:
    row = con.execute("SELECT value FROM metadata WHERE name = 'json'").fetchone()
    if not row:
        return
    converter.output_dir.mkdir(parents=True, exist_ok=True)
    (converter.output_dir / "metadata.json").write_text(
        json.dumps(json.loads(row[0]), ensure_ascii=False)
    )


def convert(converter: VundlerConverter) -> None:
    con = sqlite3.connect(converter.mbtiles_path)
    try:
        levels = [
            row[0] for row in con.execute("SELECT DISTINCT zoom_level FROM tiles")
            if row[0] <= converter.max_zoom
        ]
        for zoom in levels:
            _convert_level(converter, con, zoom)
        _write_metadata(converter, con)
    finally:
        con.close()
