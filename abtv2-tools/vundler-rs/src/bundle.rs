//! Esri Compact Cache V2 `.bundle` file writer.
//!
//! Format ported from the Python original's `BundleWriter` (`abt/vundler.py`
//! in the sibling Python package): a 64-byte header, a 128 KiB index of
//! 16,384 `u64` entries (one per tile position in a 128x128 grid), then
//! tile payloads each prefixed with a 4-byte little-endian length.
//!
//! Unlike the Python version -- which opens/closes a bundle file every time
//! iteration crosses into a different 128x128 block, sometimes tens of
//! times per bundle depending on row/column layout -- this writer takes an
//! entire bundle's tiles up front and writes the file in one pass: header,
//! then each tile appended while building the index in memory, then a
//! single seek-back to patch `max_size`/total size/index. Reordering tiles
//! within a bundle changes their byte offsets, so output is not
//! byte-identical to the Python version's -- see bench/oracle.py, which
//! compares tile payloads through each bundle's own index instead of
//! diffing raw bytes.

use std::fs::File;
use std::io::{self, BufWriter, Seek, SeekFrom, Write};
use std::path::Path;

pub const BUNDLE_SIZE: u32 = 128;
pub const TILES_PER_BUNDLE: usize = (BUNDLE_SIZE as usize) * (BUNDLE_SIZE as usize);
pub const INDEX_SIZE_BYTES: usize = TILES_PER_BUNDLE * 8;
pub const HEADER_SIZE: usize = 64;

/// Index entries pack a byte offset into the low bits and a tile size into
/// the high bits: `entry = payload_offset | (size << OFFSET_BITS)`.
const OFFSET_BITS: u32 = 40;

/// One tile to be written into a bundle, keyed by its global (already
/// row-flipped) row/col -- see `flip_y` in the Python original. Row/col
/// here are in the same space bundle filenames (`R####C####`) are named
/// from: row/col divided by `BUNDLE_SIZE`, in hex.
pub struct BundleTile {
    pub global_row: u32,
    pub global_col: u32,
    pub data: Vec<u8>,
}

fn local_index(global_row: u32, global_col: u32) -> usize {
    ((global_row % BUNDLE_SIZE) * BUNDLE_SIZE + (global_col % BUNDLE_SIZE)) as usize
}

/// Writes the 64-byte header plus a blank (all-zero) index, matching the
/// Python original's `_init_bundle` byte-for-byte:
///
/// ```text
/// struct.pack(
///     "<4I3Q6I",
///     3, TILES_PER_BUNDLE, 0, 5, 0,
///     64 + INDEX_SIZE_BYTES, 40, 20 + INDEX_SIZE_BYTES,
///     3, 16, TILES_PER_BUNDLE, 5, INDEX_SIZE_BYTES,
/// )
/// ```
///
/// Field 3 (byte offset 8, a `u32`) is `max_size`, later patched to the
/// largest tile written. Field 6 (byte offset 24, a `u64`) is the total
/// file size, later patched to the real final size. Both start at their
/// "empty bundle" values here and get overwritten once tile sizes are
/// known -- see `write_bundle`.
fn write_header_and_blank_index<W: Write>(w: &mut W) -> io::Result<()> {
    let tiles_per_bundle = TILES_PER_BUNDLE as u32;
    let index_size = INDEX_SIZE_BYTES as u64;

    for v in [3u32, tiles_per_bundle, 0, 5] {
        w.write_all(&v.to_le_bytes())?;
    }
    for v in [0u64, 64 + index_size, 40u64] {
        w.write_all(&v.to_le_bytes())?;
    }
    for v in [
        (20 + INDEX_SIZE_BYTES) as u32,
        3,
        16,
        tiles_per_bundle,
        5,
        INDEX_SIZE_BYTES as u32,
    ] {
        w.write_all(&v.to_le_bytes())?;
    }

    w.write_all(&vec![0u8; INDEX_SIZE_BYTES])?;
    Ok(())
}

/// Writes one complete `.bundle` file in a single pass. Creates (or
/// truncates) `path` -- each bundle corresponds to exactly one work unit
/// (see `db::enumerate_bundle_keys`), so there's no cross-run merge/append
/// case to support: vundler always redoes the full operation (see the
/// README's "Reuse" section), and within one run a given bundle key is
/// only ever produced once.
pub fn write_bundle(path: &Path, tiles: &[BundleTile]) -> io::Result<()> {
    let file = File::create(path)?;
    let mut writer = BufWriter::new(file);
    write_header_and_blank_index(&mut writer)?;

    let mut index = vec![0u64; TILES_PER_BUNDLE];
    let mut offset: u64 = (HEADER_SIZE + INDEX_SIZE_BYTES) as u64;
    let mut max_size: u32 = 0;

    for tile in tiles {
        let size = tile.data.len() as u32;
        writer.write_all(&size.to_le_bytes())?;
        writer.write_all(&tile.data)?;
        offset += 4; // past the 4-byte length prefix, to the payload start
        index[local_index(tile.global_row, tile.global_col)] =
            offset + ((size as u64) << OFFSET_BITS);
        offset += size as u64;
        max_size = max_size.max(size);
    }

    writer.seek(SeekFrom::Start(8))?;
    writer.write_all(&max_size.to_le_bytes())?;
    writer.seek(SeekFrom::Start(24))?;
    writer.write_all(&offset.to_le_bytes())?;
    writer.seek(SeekFrom::Start(HEADER_SIZE as u64))?;
    for entry in &index {
        writer.write_all(&entry.to_le_bytes())?;
    }
    writer.flush()
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Read;

    const OFFSET_MASK: u64 = (1u64 << OFFSET_BITS) - 1;

    fn scratch_dir(label: &str) -> std::path::PathBuf {
        let dir = std::env::temp_dir().join(format!(
            "abt_vundler_bundle_test_{label}_{}_{:?}",
            std::process::id(),
            std::thread::current().id()
        ));
        std::fs::create_dir_all(&dir).unwrap();
        dir
    }

    #[test]
    fn local_index_covers_all_four_corners() {
        assert_eq!(local_index(0, 0), 0, "top-left");
        assert_eq!(local_index(0, 127), 127, "top-right");
        assert_eq!(local_index(127, 0), 16256, "bottom-left");
        assert_eq!(local_index(127, 127), 16383, "bottom-right (last index)");
    }

    #[test]
    fn local_index_wraps_global_coordinates_via_modulo() {
        // global_row/col are absolute tile coordinates, not pre-masked to
        // [0, 128) -- callers (write_bundle, fed from db::fetch_bundle_tiles)
        // rely on local_index reducing them mod BUNDLE_SIZE itself.
        assert_eq!(local_index(128, 128), local_index(0, 0));
        assert_eq!(local_index(255, 255), local_index(127, 127));
        assert_eq!(local_index(128, 0), local_index(0, 0));
        assert_eq!(local_index(0, 128), local_index(0, 0));
    }

    #[test]
    fn header_layout_matches_python_struct_format() {
        let mut buf = Vec::new();
        write_header_and_blank_index(&mut buf).unwrap();
        assert_eq!(buf.len(), HEADER_SIZE + INDEX_SIZE_BYTES);

        let u32_at = |off: usize| u32::from_le_bytes(buf[off..off + 4].try_into().unwrap());
        let u64_at = |off: usize| u64::from_le_bytes(buf[off..off + 8].try_into().unwrap());

        assert_eq!(u32_at(0), 3);
        assert_eq!(u32_at(4), TILES_PER_BUNDLE as u32);
        assert_eq!(u32_at(8), 0, "max_size placeholder");
        assert_eq!(u32_at(12), 5);
        assert_eq!(u64_at(16), 0);
        assert_eq!(
            u64_at(24),
            (HEADER_SIZE + INDEX_SIZE_BYTES) as u64,
            "total size placeholder"
        );
        assert_eq!(u64_at(32), 40);
        assert_eq!(u32_at(40), (20 + INDEX_SIZE_BYTES) as u32);
        assert_eq!(u32_at(44), 3);
        assert_eq!(u32_at(48), 16);
        assert_eq!(u32_at(52), TILES_PER_BUNDLE as u32);
        assert_eq!(u32_at(56), 5);
        assert_eq!(u32_at(60), INDEX_SIZE_BYTES as u32);

        assert!(
            buf[HEADER_SIZE..].iter().all(|&b| b == 0),
            "index must start all-zero"
        );
    }

    #[test]
    fn write_bundle_roundtrips_single_tile() {
        let path = scratch_dir("single").join("R0000C0000.bundle");
        let tiles = vec![BundleTile {
            global_row: 5,
            global_col: 9,
            data: b"hello".to_vec(),
        }];
        write_bundle(&path, &tiles).unwrap();

        let mut data = Vec::new();
        File::open(&path).unwrap().read_to_end(&mut data).unwrap();

        assert_eq!(
            u32::from_le_bytes(data[8..12].try_into().unwrap()),
            5,
            "max_size"
        );
        assert_eq!(
            u64::from_le_bytes(data[24..32].try_into().unwrap()),
            data.len() as u64,
            "total size must equal actual file size"
        );

        let idx = local_index(5, 9);
        let entry_off = HEADER_SIZE + idx * 8;
        let entry = u64::from_le_bytes(data[entry_off..entry_off + 8].try_into().unwrap());
        let payload_offset = (entry & OFFSET_MASK) as usize;
        let size = (entry >> OFFSET_BITS) as usize;
        assert_eq!(size, 5);
        assert_eq!(&data[payload_offset..payload_offset + 5], b"hello");

        let prefix =
            u32::from_le_bytes(data[payload_offset - 4..payload_offset].try_into().unwrap());
        assert_eq!(prefix, 5, "4-byte length prefix must precede the payload");
    }

    #[test]
    fn write_bundle_multiple_tiles_distinct_offsets_and_max_size() {
        let path = scratch_dir("multi").join("R0000C0000.bundle");
        let tiles = vec![
            BundleTile {
                global_row: 0,
                global_col: 0,
                data: vec![1u8; 10],
            },
            BundleTile {
                global_row: 0,
                global_col: 1,
                data: vec![2u8; 300],
            },
            BundleTile {
                global_row: 127,
                global_col: 127,
                data: vec![3u8; 1],
            },
        ];
        write_bundle(&path, &tiles).unwrap();

        let mut data = Vec::new();
        File::open(&path).unwrap().read_to_end(&mut data).unwrap();
        assert_eq!(
            u32::from_le_bytes(data[8..12].try_into().unwrap()),
            300,
            "max_size across tiles"
        );

        let read_tile = |row: u32, col: u32, expected_len: usize| {
            let idx = local_index(row, col);
            let entry_off = HEADER_SIZE + idx * 8;
            let entry = u64::from_le_bytes(data[entry_off..entry_off + 8].try_into().unwrap());
            let payload_offset = (entry & OFFSET_MASK) as usize;
            let size = (entry >> OFFSET_BITS) as usize;
            assert_eq!(size, expected_len);
            data[payload_offset..payload_offset + size].to_vec()
        };
        assert_eq!(read_tile(0, 0, 10), vec![1u8; 10]);
        assert_eq!(read_tile(0, 1, 300), vec![2u8; 300]);
        assert_eq!(read_tile(127, 127, 1), vec![3u8; 1]);

        // Untouched slots stay zero (no tile written there).
        let untouched_off = HEADER_SIZE + local_index(64, 64) * 8;
        assert_eq!(
            u64::from_le_bytes(data[untouched_off..untouched_off + 8].try_into().unwrap()),
            0
        );
    }
}
