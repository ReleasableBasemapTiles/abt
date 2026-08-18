"""
oracle.py

Independent reader for Esri Compact Cache V2 tile bundles, built directly
from the documented format (header layout, index entry encoding) rather than
by reusing either the Python or Rust writer's own code. Used to verify a
vundler output package -- from either implementation -- against the format
spec itself, and to compare two output packages (e.g. Python vs Rust) for
semantic equality.

Bundle files are NOT expected to be byte-identical between implementations
that write tiles in a different order (offsets shift), so comparison is done
per-tile via each bundle's own index, not by diffing raw file bytes.
"""

import json
import struct
from pathlib import Path
from typing import Dict, Optional, Tuple

BUNDLE_SIZE = 128
TILES_PER_BUNDLE = BUNDLE_SIZE * BUNDLE_SIZE
INDEX_SIZE_BYTES = TILES_PER_BUNDLE * 8
HEADER_SIZE = 64
OFFSET_MASK = (1 << 40) - 1

TileKey = Tuple[int, int, int]  # (zoom, global_row, global_col)


def read_bundle(path: Path) -> Dict[Tuple[int, int], bytes]:
    """Returns {(global_row, global_col): tile_bytes} for one .bundle file.

    global_row/global_col are in the same (already row-flipped) coordinate
    space vundler writes tiles in -- see flip_y in abt/vundler.py.
    """
    name = path.stem  # e.g. "R0000C0080"
    if len(name) != 10 or name[0] != "R" or name[5] != "C":
        raise ValueError(f"{path}: bundle filename doesn't match R####C#### pattern")
    start_row = int(name[1:5], 16)
    start_col = int(name[6:10], 16)

    data = path.read_bytes()
    if len(data) < HEADER_SIZE + INDEX_SIZE_BYTES:
        raise ValueError(f"{path}: truncated bundle ({len(data)} bytes, need >= {HEADER_SIZE + INDEX_SIZE_BYTES})")

    header = struct.unpack_from("<4I3Q6I", data, 0)
    tiles_per_bundle_hdr = header[1]
    index_size_hdr = header[12]
    if tiles_per_bundle_hdr != TILES_PER_BUNDLE:
        raise ValueError(f"{path}: header TILES_PER_BUNDLE={tiles_per_bundle_hdr}, expected {TILES_PER_BUNDLE}")
    if index_size_hdr != INDEX_SIZE_BYTES:
        raise ValueError(f"{path}: header INDEX_SIZE_BYTES={index_size_hdr}, expected {INDEX_SIZE_BYTES}")

    max_size_hdr = header[2]
    total_size_hdr = header[5]
    if total_size_hdr != len(data):
        raise ValueError(f"{path}: header total size={total_size_hdr}, actual file size={len(data)}")

    index = struct.unpack_from(f"<{TILES_PER_BUNDLE}Q", data, HEADER_SIZE)
    out: Dict[Tuple[int, int], bytes] = {}
    observed_max_size = 0
    for local_idx, entry in enumerate(index):
        if entry == 0:
            continue
        offset = entry & OFFSET_MASK
        size = entry >> 40
        if offset + size > len(data):
            raise ValueError(
                f"{path}: index entry {local_idx} out of range "
                f"(offset={offset} size={size} filelen={len(data)})"
            )
        # The 4-byte length prefix immediately precedes the payload the
        # index points at -- cross-check it against the index-encoded size
        # rather than trusting only one of the two redundant encodings.
        prefix = struct.unpack_from("<I", data, offset - 4)[0]
        if prefix != size:
            raise ValueError(
                f"{path}: index entry {local_idx} size={size} disagrees with "
                f"4-byte length prefix={prefix} at offset {offset - 4}"
            )
        local_row = local_idx // BUNDLE_SIZE
        local_col = local_idx % BUNDLE_SIZE
        out[(start_row + local_row, start_col + local_col)] = data[offset:offset + size]
        observed_max_size = max(observed_max_size, size)

    if out and max_size_hdr != observed_max_size:
        raise ValueError(f"{path}: header max_size={max_size_hdr}, observed max tile size={observed_max_size}")

    return out


def read_tree(root: Path) -> Tuple[Dict[TileKey, bytes], Optional[dict]]:
    """Returns ({(zoom, global_row, global_col): tile_bytes}, metadata_or_None)
    for a whole vundler output package: root/tile/L##/R####C####.bundle files
    plus root/metadata.json.
    """
    tiles: Dict[TileKey, bytes] = {}
    tile_root = root / "tile"
    if tile_root.exists():
        for level_dir in sorted(tile_root.iterdir()):
            if not level_dir.is_dir() or not level_dir.name.startswith("L"):
                continue
            zoom = int(level_dir.name[1:])
            for bundle_path in sorted(level_dir.glob("*.bundle")):
                for (row, col), tile_data in read_bundle(bundle_path).items():
                    key = (zoom, row, col)
                    if key in tiles:
                        raise ValueError(f"duplicate tile {key} found in {bundle_path} (already seen elsewhere)")
                    tiles[key] = tile_data

    metadata_path = root / "metadata.json"
    metadata = json.loads(metadata_path.read_text()) if metadata_path.exists() else None
    return tiles, metadata


def compare_trees(a_root: Path, b_root: Path, a_label: str = "A", b_label: str = "B") -> str:
    """Compares two vundler output packages for semantic equality. Returns a
    human-readable summary on success; raises AssertionError on any mismatch.
    """
    a_tiles, a_meta = read_tree(a_root)
    b_tiles, b_meta = read_tree(b_root)

    errors = []
    a_keys, b_keys = set(a_tiles), set(b_tiles)
    if a_keys != b_keys:
        only_a = sorted(a_keys - b_keys)[:10]
        only_b = sorted(b_keys - a_keys)[:10]
        errors.append(
            f"tile key sets differ: {len(a_keys)} ({a_label}) vs {len(b_keys)} ({b_label}); "
            f"only in {a_label} (sample): {only_a}; only in {b_label} (sample): {only_b}"
        )

    common = a_keys & b_keys
    mismatched = [k for k in common if a_tiles[k] != b_tiles[k]]
    if mismatched:
        mismatched.sort()
        sample = mismatched[:5]
        details = "; ".join(f"{k}: {len(a_tiles[k])}B vs {len(b_tiles[k])}B" for k in sample)
        errors.append(f"{len(mismatched)} of {len(common)} common tiles differ in bytes, e.g. {details}")

    if a_meta != b_meta:
        errors.append(f"metadata.json differs:\n  {a_label}: {a_meta!r}\n  {b_label}: {b_meta!r}")

    if errors:
        raise AssertionError("\n".join(errors))

    return (
        f"OK: {len(a_keys)} tiles match byte-for-byte between {a_label} and {b_label} "
        f"({len(a_keys)} common, 0 mismatched); metadata.json matches "
        f"({'present' if a_meta is not None else 'absent in both'})."
    )
