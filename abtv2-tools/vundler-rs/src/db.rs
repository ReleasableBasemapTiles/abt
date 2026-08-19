//! SQLite access for the source mbtiles file: zoom-level and bundle-key
//! enumeration, per-bundle tile fetches, and metadata lookup.
//!
//! Enumeration deliberately avoids touching the `images` table (where tile
//! blobs live) wherever possible -- tippecanoe/tile-join (vundler's actual
//! production input; confirmed by inspecting their real output, not
//! assumed) always produce the normalized `map`/`images` schema with a
//! `tiles` view joining them, so bundle keys can be discovered by querying
//! `map` alone. A plain-`tiles`-table mbtiles (no `map`/`images` split) is
//! also supported as a fallback, just without that optimization.

use std::path::Path;

use anyhow::Result;
use rusqlite::{Connection, OpenFlags, OptionalExtension, params};

use crate::bundle::BundleTile;

/// Opens `path` read-only via SQLite's URI syntax (`file:...?mode=ro`),
/// matching the Python original's `sqlite3.connect(f"file:{path}?mode=ro",
/// uri=True)`. `SQLITE_OPEN_NO_MUTEX` is safe here because each connection
/// is only ever touched by the single thread that opened it -- see
/// `ThreadConnection` below.
pub fn open_readonly(path: &Path) -> Result<Connection> {
    let uri = format!("file:{}?mode=ro", path.display());
    let flags = OpenFlags::SQLITE_OPEN_READ_ONLY
        | OpenFlags::SQLITE_OPEN_URI
        | OpenFlags::SQLITE_OPEN_NO_MUTEX;
    Ok(Connection::open_with_flags(uri, flags)?)
}

pub fn has_table(conn: &Connection, name: &str) -> Result<bool> {
    let count: i64 = conn.query_row(
        "SELECT count(*) FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?1",
        [name],
        |row| row.get(0),
    )?;
    Ok(count > 0)
}

/// Every distinct zoom level present, at or below `max_zoom`. Queries `map`
/// directly when present so this never has to read a tile blob just to
/// discover which zoom levels exist.
pub fn list_zoom_levels(conn: &Connection, max_zoom: i64, has_map: bool) -> Result<Vec<i64>> {
    let table = if has_map { "map" } else { "tiles" };
    let sql = format!(
        "SELECT DISTINCT zoom_level FROM {table} WHERE zoom_level <= ?1 ORDER BY zoom_level"
    );
    let mut stmt = conn.prepare(&sql)?;
    let rows = stmt.query_map([max_zoom], |row| row.get::<_, i64>(0))?;
    Ok(rows.collect::<rusqlite::Result<Vec<_>>>()?)
}

/// A single bundle's identity: which zoom level, and its position in the
/// 128x128 bundle grid in the *flipped* (XYZ-style) row space bundle
/// filenames use -- see `flip_y` in the Python original and `bundle.rs`'s
/// module docs. `bundle_col` is not flipped (columns are the same in TMS
/// and XYZ conventions).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct BundleKey {
    pub zoom: i64,
    pub bundle_row: i64,
    pub bundle_col: i64,
}

/// Every distinct bundle key present at `zoom`, discovered from `map`
/// alone (falling back to `tiles` if there's no separate `map` table) --
/// no blob column is touched.
///
/// `tile_column/128` and `(m - tile_row)/128` are both non-negative-operand
/// integer divisions (tile_row is always <= m for a valid tile), so
/// SQLite's truncating `/` matches Rust/Python's floor `/`/`//` exactly.
pub fn enumerate_bundle_keys(
    conn: &Connection,
    zoom: i64,
    has_map: bool,
) -> Result<Vec<BundleKey>> {
    let m = (1i64 << zoom) - 1;
    let table = if has_map { "map" } else { "tiles" };
    let sql = format!(
        "SELECT DISTINCT (tile_column/128) AS bc, ((?1 - tile_row)/128) AS br \
         FROM {table} WHERE zoom_level = ?2"
    );
    let mut stmt = conn.prepare(&sql)?;
    let rows = stmt.query_map(params![m, zoom], |row| {
        let bundle_col: i64 = row.get(0)?;
        let bundle_row: i64 = row.get(1)?;
        Ok(BundleKey {
            zoom,
            bundle_row,
            bundle_col,
        })
    })?;
    Ok(rows.collect::<rusqlite::Result<Vec<_>>>()?)
}

/// Fetches every tile belonging to one bundle. The `tile_column`/`tile_row`
/// bounds are index-friendly ranges against `map_index (zoom_level,
/// tile_column, tile_row)` -- ordered by neither column, since a bundle's
/// index is built in memory keyed by position, not by fetch order (unlike
/// the Python original, which relied on `ORDER BY tile_row DESC,
/// tile_column ASC` and paid for a temp b-tree sort over every zoom
/// level's tiles as a result -- see db.rs tests for the EXPLAIN QUERY PLAN
/// confirming that sort no longer happens here).
pub fn fetch_bundle_tiles(conn: &Connection, key: &BundleKey) -> Result<Vec<BundleTile>> {
    let m = (1i64 << key.zoom) - 1;
    let col_lo = key.bundle_col * 128;
    let col_hi = col_lo + 127;
    let row_lo = m - (key.bundle_row * 128 + 127);
    let row_hi = m - key.bundle_row * 128;

    let mut stmt = conn.prepare(
        "SELECT tile_column, tile_row, tile_data FROM tiles \
         WHERE zoom_level = ?1 AND tile_column BETWEEN ?2 AND ?3 AND tile_row BETWEEN ?4 AND ?5",
    )?;
    let rows = stmt.query_map(params![key.zoom, col_lo, col_hi, row_lo, row_hi], |row| {
        let tile_column: i64 = row.get(0)?;
        let tile_row: i64 = row.get(1)?;
        let tile_data: Vec<u8> = row.get(2)?;
        Ok((tile_column, tile_row, tile_data))
    })?;

    let mut tiles = Vec::new();
    for r in rows {
        let (tile_column, tile_row, data) = r?;
        tiles.push(BundleTile {
            global_row: (m - tile_row) as u32,
            global_col: tile_column as u32,
            data,
        });
    }
    Ok(tiles)
}

/// The raw `metadata` `json` row's text, if present -- matches the Python
/// original's `_write_metadata` (`SELECT value FROM metadata WHERE name =
/// 'json'`), returning `None` when absent so the caller can skip writing
/// metadata.json entirely rather than writing an empty/null file.
pub fn read_metadata_json(conn: &Connection) -> Result<Option<String>> {
    Ok(conn
        .query_row(
            "SELECT value FROM metadata WHERE name = 'json'",
            [],
            |row| row.get::<_, String>(0),
        )
        .optional()?)
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Builds an in-memory mbtiles with the real map/images/tiles-view
    /// schema (confirmed against actual tippecanoe/tile-join output, not
    /// assumed) and inserts the given (zoom, tile_column, tile_row, data)
    /// rows.
    fn build_fixture(conn: &Connection, tiles: &[(i64, i64, i64, &[u8])]) {
        conn.execute_batch(
            "CREATE TABLE map (zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_id TEXT);
             CREATE UNIQUE INDEX map_index ON map (zoom_level, tile_column, tile_row);
             CREATE TABLE images (zoom_level INTEGER, tile_data BLOB, tile_id TEXT);
             CREATE UNIQUE INDEX images_id ON images (zoom_level, tile_id);
             CREATE VIEW tiles AS SELECT map.zoom_level AS zoom_level, map.tile_column AS tile_column, \
                map.tile_row AS tile_row, images.tile_data AS tile_data FROM map \
                JOIN images ON images.tile_id = map.tile_id AND images.zoom_level = map.zoom_level;
             CREATE TABLE metadata (name TEXT, value TEXT);",
        )
        .unwrap();
        for (i, (zoom, col, row, data)) in tiles.iter().enumerate() {
            let tile_id = i.to_string();
            conn.execute(
                "INSERT INTO images (zoom_level, tile_data, tile_id) VALUES (?1, ?2, ?3)",
                params![zoom, data, tile_id],
            )
            .unwrap();
            conn.execute(
                "INSERT INTO map (zoom_level, tile_column, tile_row, tile_id) VALUES (?1, ?2, ?3, ?4)",
                params![zoom, col, row, tile_id],
            )
            .unwrap();
        }
    }

    /// Builds an in-memory mbtiles with a plain single `tiles` table (no
    /// `map`/`images` split) -- the fallback path exercised when
    /// `has_map` is false. Real tippecanoe/tile-join output always uses
    /// the map/images split (see `build_fixture`'s docs); this schema
    /// represents any other producer that writes a spec-conformant plain
    /// mbtiles instead.
    fn build_plain_tiles_fixture(conn: &Connection, tiles: &[(i64, i64, i64, &[u8])]) {
        conn.execute_batch(
            "CREATE TABLE tiles (zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_data BLOB);
             CREATE UNIQUE INDEX tile_index ON tiles (zoom_level, tile_column, tile_row);
             CREATE TABLE metadata (name TEXT, value TEXT);",
        )
        .unwrap();
        for (zoom, col, row, data) in tiles {
            conn.execute(
                "INSERT INTO tiles (zoom_level, tile_column, tile_row, tile_data) VALUES (?1, ?2, ?3, ?4)",
                params![zoom, col, row, data],
            )
            .unwrap();
        }
    }

    #[test]
    fn plain_tiles_table_fallback_when_has_map_is_false() {
        let conn = Connection::open_in_memory().unwrap();
        build_plain_tiles_fixture(&conn, &[(7, 5, 3, b"abc"), (7, 5, 4, b"def")]);

        assert!(!has_table(&conn, "map").unwrap());
        assert!(has_table(&conn, "tiles").unwrap());

        let zooms = list_zoom_levels(&conn, 13, false).unwrap();
        assert_eq!(zooms, vec![7]);

        let keys = enumerate_bundle_keys(&conn, 7, false).unwrap();
        assert_eq!(
            keys,
            vec![BundleKey {
                zoom: 7,
                bundle_row: 0,
                bundle_col: 0
            }]
        );

        let tiles = fetch_bundle_tiles(&conn, &keys[0]).unwrap();
        assert_eq!(tiles.len(), 2, "both rows share the one (0,0) bundle");
    }

    #[test]
    fn zoom_zero_is_a_single_tile_covering_the_whole_world() {
        let conn = Connection::open_in_memory().unwrap();
        build_fixture(&conn, &[(0, 0, 0, b"world")]);

        let keys = enumerate_bundle_keys(&conn, 0, true).unwrap();
        assert_eq!(
            keys,
            vec![BundleKey {
                zoom: 0,
                bundle_row: 0,
                bundle_col: 0
            }]
        );

        let tiles = fetch_bundle_tiles(&conn, &keys[0]).unwrap();
        assert_eq!(tiles.len(), 1);
        assert_eq!(tiles[0].global_row, 0);
        assert_eq!(tiles[0].global_col, 0);
        assert_eq!(tiles[0].data, b"world");
    }

    #[test]
    fn enumerate_and_fetch_roundtrip_with_row_flip() {
        let conn = Connection::open_in_memory().unwrap();
        // Zoom 7: m = 127. Tile (x=5, y_tms=3) should land in bundle
        // (bc=0, br=0) at flipped row 127-3=124.
        build_fixture(&conn, &[(7, 5, 3, b"abc"), (7, 5, 3 + 1, b"def")]);

        assert!(has_table(&conn, "map").unwrap());
        assert!(!has_table(&conn, "nonexistent").unwrap());

        let zooms = list_zoom_levels(&conn, 13, true).unwrap();
        assert_eq!(zooms, vec![7]);

        let keys = enumerate_bundle_keys(&conn, 7, true).unwrap();
        assert_eq!(
            keys,
            vec![BundleKey {
                zoom: 7,
                bundle_row: 0,
                bundle_col: 0
            }]
        );

        let tiles = fetch_bundle_tiles(&conn, &keys[0]).unwrap();
        assert_eq!(tiles.len(), 2);
        let mut by_row: Vec<_> = tiles
            .iter()
            .map(|t| (t.global_row, t.global_col, t.data.clone()))
            .collect();
        by_row.sort();
        assert_eq!(
            by_row,
            vec![
                (123, 5, b"def".to_vec()), // y_tms=4 -> flipped 127-4=123
                (124, 5, b"abc".to_vec()), // y_tms=3 -> flipped 127-3=124
            ]
        );
    }

    #[test]
    fn enumerate_spans_multiple_bundles_at_zoom8() {
        let conn = Connection::open_in_memory().unwrap();
        // Zoom 8 is 256x256 -- four bundles. Place one tile in each corner.
        build_fixture(
            &conn,
            &[
                (8, 0, 0, b"sw"),
                (8, 255, 0, b"se"),
                (8, 0, 255, b"nw"),
                (8, 255, 255, b"ne"),
            ],
        );
        let mut keys = enumerate_bundle_keys(&conn, 8, true).unwrap();
        keys.sort_by_key(|k| (k.bundle_row, k.bundle_col));
        assert_eq!(
            keys,
            vec![
                BundleKey {
                    zoom: 8,
                    bundle_row: 0,
                    bundle_col: 0
                },
                BundleKey {
                    zoom: 8,
                    bundle_row: 0,
                    bundle_col: 1
                },
                BundleKey {
                    zoom: 8,
                    bundle_row: 1,
                    bundle_col: 0
                },
                BundleKey {
                    zoom: 8,
                    bundle_row: 1,
                    bundle_col: 1
                },
            ]
        );
        for key in &keys {
            let tiles = fetch_bundle_tiles(&conn, key).unwrap();
            assert_eq!(
                tiles.len(),
                1,
                "each corner bundle should contain exactly its one tile"
            );
        }
    }

    #[test]
    fn max_zoom_filters_higher_levels() {
        let conn = Connection::open_in_memory().unwrap();
        build_fixture(
            &conn,
            &[(5, 0, 0, b"a"), (10, 0, 0, b"b"), (13, 0, 0, b"c")],
        );
        assert_eq!(list_zoom_levels(&conn, 10, true).unwrap(), vec![5, 10]);
        assert_eq!(list_zoom_levels(&conn, 4, true).unwrap(), Vec::<i64>::new());
    }

    #[test]
    fn metadata_present_and_absent() {
        let conn = Connection::open_in_memory().unwrap();
        build_fixture(&conn, &[]);
        assert_eq!(read_metadata_json(&conn).unwrap(), None);
        conn.execute(
            "INSERT INTO metadata (name, value) VALUES ('json', ?1)",
            params!["{\"a\":1}"],
        )
        .unwrap();
        assert_eq!(
            read_metadata_json(&conn).unwrap(),
            Some("{\"a\":1}".to_string())
        );
    }

    /// Confirms the per-bundle fetch query is answered without a temp
    /// b-tree sort -- the whole point of restructuring around bundles
    /// instead of the original's `ORDER BY tile_row DESC, tile_column ASC`
    /// per zoom level, which forced SQLite to materialize and sort every
    /// zoom level's rows (blobs included).
    #[test]
    fn fetch_query_plan_has_no_temp_btree_sort() {
        let conn = Connection::open_in_memory().unwrap();
        let tiles: Vec<(i64, i64, i64, &[u8])> =
            (0..50).map(|i| (10, i, i, b"x" as &[u8])).collect();
        build_fixture(&conn, &tiles);

        let plan_lines: Vec<String> = conn
            .prepare(
                "EXPLAIN QUERY PLAN SELECT tile_column, tile_row, tile_data FROM tiles \
                 WHERE zoom_level = 10 AND tile_column BETWEEN 0 AND 127 AND tile_row BETWEEN 0 AND 127",
            )
            .unwrap()
            .query_map([], |row| row.get::<_, String>(3))
            .unwrap()
            .collect::<rusqlite::Result<Vec<_>>>()
            .unwrap();
        let plan = plan_lines.join(" | ");
        assert!(
            !plan.to_uppercase().contains("TEMP B-TREE"),
            "expected no temp b-tree sort in plan, got: {plan}"
        );
    }
}
