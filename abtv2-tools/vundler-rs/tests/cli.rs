//! End-to-end integration tests for the abt-vundler binary. Complements
//! the inline unit tests in src/bundle.rs and src/db.rs (which exercise
//! internal functions directly) and tests/test_golden.py (which
//! cross-checks output against the frozen Python reference) -- this file
//! only asserts CLI-level, implementation-agnostic behavior: exit codes,
//! which files get created, and metadata.json content.

use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Output};

use rusqlite::{params, Connection};

fn binary() -> &'static str {
    env!("CARGO_BIN_EXE_abt-vundler")
}

fn scratch_dir(label: &str) -> PathBuf {
    let dir = std::env::temp_dir().join(format!(
        "abt_vundler_cli_test_{label}_{}_{:?}",
        std::process::id(),
        std::thread::current().id()
    ));
    let _ = fs::remove_dir_all(&dir);
    fs::create_dir_all(&dir).unwrap();
    dir
}

/// Minimal map/images/tiles-view mbtiles: one tile at zoom 3 (col 2, row
/// 5) and one at zoom 9 (col 100, row 100, deep enough that --max-zoom
/// truncation has something real to cut), plus a metadata 'json' row.
fn write_fixture(path: &Path) {
    let conn = Connection::open(path).unwrap();
    conn.execute_batch(
        "CREATE TABLE metadata (name TEXT, value TEXT);
         CREATE TABLE map (zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_id TEXT);
         CREATE UNIQUE INDEX map_index ON map (zoom_level, tile_column, tile_row);
         CREATE TABLE images (zoom_level INTEGER, tile_data BLOB, tile_id TEXT);
         CREATE UNIQUE INDEX images_id ON images (zoom_level, tile_id);
         CREATE VIEW tiles AS SELECT map.zoom_level AS zoom_level, map.tile_column AS tile_column,
             map.tile_row AS tile_row, images.tile_data AS tile_data FROM map
             JOIN images ON images.tile_id = map.tile_id AND images.zoom_level = map.zoom_level;",
    )
    .unwrap();
    for (zoom, col, row, id, data) in [
        (3i64, 2i64, 5i64, "0", b"low-zoom-tile".to_vec()),
        (9i64, 100i64, 100i64, "1", b"high-zoom-tile".to_vec()),
    ] {
        conn.execute(
            "INSERT INTO images (zoom_level, tile_data, tile_id) VALUES (?1, ?2, ?3)",
            params![zoom, data, id],
        )
        .unwrap();
        conn.execute(
            "INSERT INTO map (zoom_level, tile_column, tile_row, tile_id) VALUES (?1, ?2, ?3, ?4)",
            params![zoom, col, row, id],
        )
        .unwrap();
    }
    conn.execute(
        "INSERT INTO metadata (name, value) VALUES ('json', ?1)",
        params!["{\"name\": \"cli test fixture\", \"nested\": {\"a\": 1}}"],
    )
    .unwrap();
}

/// Same schema, zero tiles, but a metadata row present -- checks that an
/// empty input still writes metadata.json without erroring, but never
/// creates a tile/ directory.
fn write_empty_fixture(path: &Path) {
    let conn = Connection::open(path).unwrap();
    conn.execute_batch(
        "CREATE TABLE metadata (name TEXT, value TEXT);
         CREATE TABLE map (zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_id TEXT);
         CREATE TABLE images (zoom_level INTEGER, tile_data BLOB, tile_id TEXT);
         CREATE VIEW tiles AS SELECT map.zoom_level AS zoom_level, map.tile_column AS tile_column,
             map.tile_row AS tile_row, images.tile_data AS tile_data FROM map
             JOIN images ON images.tile_id = map.tile_id AND images.zoom_level = map.zoom_level;",
    )
    .unwrap();
    conn.execute(
        "INSERT INTO metadata (name, value) VALUES ('json', ?1)",
        params!["{\"name\": \"empty fixture\"}"],
    )
    .unwrap();
}

fn run(mbtiles: &Path, output_dir: &Path, max_zoom: i64) -> Output {
    Command::new(binary())
        .args([
            "--mbtiles-path",
            mbtiles.to_str().unwrap(),
            "--output-dir",
            output_dir.to_str().unwrap(),
            "--max-zoom",
            &max_zoom.to_string(),
        ])
        .output()
        .expect("failed to run abt-vundler")
}

#[test]
fn end_to_end_conversion_produces_expected_bundle_files() {
    let dir = scratch_dir("e2e");
    let mbtiles = dir.join("in.mbtiles");
    write_fixture(&mbtiles);
    let out = dir.join("out");

    let result = run(&mbtiles, &out, 13);
    assert!(
        result.status.success(),
        "stderr: {}",
        String::from_utf8_lossy(&result.stderr)
    );

    // zoom 3, col=2, row=5: m=7, bundle_col=2/128=0, bundle_row=(7-5)/128=0.
    assert!(out.join("tile/L03/R0000C0000.bundle").exists());
    // zoom 9, col=100, row=100: m=511, bundle_col=100/128=0,
    // bundle_row=(511-100)/128=3 -> start_row=3*128=384=0x180.
    assert!(out.join("tile/L09/R0180C0000.bundle").exists());
    assert!(out.join("metadata.json").exists());
}

#[test]
fn metadata_json_matches_python_dumps_shape() {
    let dir = scratch_dir("metadata");
    let mbtiles = dir.join("in.mbtiles");
    write_fixture(&mbtiles);
    let out = dir.join("out");

    let result = run(&mbtiles, &out, 13);
    assert!(result.status.success());

    let content = fs::read_to_string(out.join("metadata.json")).unwrap();
    assert_eq!(
        content,
        r#"{"name": "cli test fixture", "nested": {"a": 1}}"#
    );
}

#[test]
fn empty_input_writes_metadata_but_no_tile_dir() {
    let dir = scratch_dir("empty");
    let mbtiles = dir.join("in.mbtiles");
    write_empty_fixture(&mbtiles);
    let out = dir.join("out");

    let result = run(&mbtiles, &out, 13);
    assert!(
        result.status.success(),
        "stderr: {}",
        String::from_utf8_lossy(&result.stderr)
    );

    assert!(out.join("metadata.json").exists());
    assert!(!out.join("tile").exists());
}

#[test]
fn max_zoom_truncates_higher_levels() {
    let dir = scratch_dir("truncation");
    let mbtiles = dir.join("in.mbtiles");
    write_fixture(&mbtiles);
    let out = dir.join("out");

    let result = run(&mbtiles, &out, 5);
    assert!(
        result.status.success(),
        "stderr: {}",
        String::from_utf8_lossy(&result.stderr)
    );

    assert!(out.join("tile/L03").exists());
    assert!(
        !out.join("tile/L09").exists(),
        "zoom 9 should be excluded entirely by --max-zoom 5"
    );
}

#[test]
fn num_workers_one_and_default_produce_identical_output() {
    let dir = scratch_dir("workers");
    let mbtiles = dir.join("in.mbtiles");
    write_fixture(&mbtiles);
    let out_default = dir.join("out_default");
    let out_single = dir.join("out_single");

    let default_result = run(&mbtiles, &out_default, 13);
    assert!(default_result.status.success());

    let single_result = Command::new(binary())
        .args([
            "--mbtiles-path",
            mbtiles.to_str().unwrap(),
            "--output-dir",
            out_single.to_str().unwrap(),
            "--max-zoom",
            "13",
            "--num-workers",
            "1",
        ])
        .output()
        .expect("failed to run abt-vundler");
    assert!(single_result.status.success());

    let bundle_default = fs::read(out_default.join("tile/L03/R0000C0000.bundle")).unwrap();
    let bundle_single = fs::read(out_single.join("tile/L03/R0000C0000.bundle")).unwrap();
    assert_eq!(
        bundle_default, bundle_single,
        "a single-tile bundle's bytes must not depend on worker count"
    );

    let meta_default = fs::read(out_default.join("metadata.json")).unwrap();
    let meta_single = fs::read(out_single.join("metadata.json")).unwrap();
    assert_eq!(meta_default, meta_single);
}

#[test]
fn nonexistent_input_fails_with_nonzero_exit() {
    let dir = scratch_dir("missing_input");
    let missing = dir.join("does_not_exist.mbtiles");
    let out = dir.join("out");

    let result = run(&missing, &out, 13);
    assert!(!result.status.success());
    assert!(!result.stderr.is_empty());
}
