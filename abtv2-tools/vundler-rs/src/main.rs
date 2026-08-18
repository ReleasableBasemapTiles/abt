//! abt-vundler: converts an mbtiles database into Esri's Compact Cache V2
//! tile bundle format (one .bundle file per 128x128 tile block, per zoom
//! level). Rust port of abt/vundler.py, restructured around per-bundle work
//! units instead of per-zoom-level tasks -- see bundle.rs and db.rs module
//! docs for why. Produces the raw tile-bundle folder structure and a bare
//! metadata.json -- not a complete, packaged .vtpk (no conf.xml/root.json).

mod bundle;
mod db;

use std::cell::RefCell;
use std::fs;
use std::io::IsTerminal;
use std::path::{Path, PathBuf};

use anyhow::{Context, Result};
use clap::Parser;
use indicatif::{ProgressBar, ProgressDrawTarget, ProgressStyle};
use rayon::prelude::*;
use rusqlite::Connection;
use serde::Serialize;

use bundle::BundleTile;
use db::BundleKey;

#[derive(Parser, Debug)]
#[command(
    name = "abt-vundler",
    version,
    about = "Converts an mbtiles file into Esri Compact Cache V2 tile bundles"
)]
struct Args {
    /// Source .mbtiles/.btis file.
    #[arg(short = 'i', long = "mbtiles-path")]
    mbtiles_path: PathBuf,

    /// Output package directory. Tiles go in <output-dir>/tile/L##/,
    /// metadata.json sits alongside tile/.
    #[arg(short = 'o', long = "output-dir")]
    output_dir: PathBuf,

    /// Highest zoom level to convert.
    #[arg(short = 'z', long = "max-zoom")]
    max_zoom: i64,

    /// Number of worker threads to convert bundles concurrently. Defaults
    /// to rayon's own default (one per available core).
    #[arg(short = 'n', long = "num-workers")]
    num_workers: Option<usize>,
}

fn main() -> Result<()> {
    let args = Args::parse();
    run(&args)
}

fn run(args: &Args) -> Result<()> {
    let discover_conn = db::open_readonly(&args.mbtiles_path)
        .with_context(|| format!("opening {}", args.mbtiles_path.display()))?;
    let has_map = db::has_table(&discover_conn, "map")?;

    let zoom_levels = db::list_zoom_levels(&discover_conn, args.max_zoom, has_map)?;

    // Flatten every zoom's bundle keys into one work list up front, rather
    // than treating each zoom level as its own task -- a single zoom level
    // can dominate the tile count (in a real 223 MB sample, z13 alone was
    // 48% of all tiles), which would otherwise cap parallelism far below
    // the number of available cores regardless of --num-workers.
    let mut work: Vec<BundleKey> = Vec::new();
    for &zoom in &zoom_levels {
        work.extend(db::enumerate_bundle_keys(&discover_conn, zoom, has_map)?);
    }

    if !work.is_empty() {
        // Create the shared parent dir and every zoom's subdirectory up
        // front so concurrent workers don't race to create them.
        fs::create_dir_all(args.output_dir.join("tile"))?;
        for &zoom in &zoom_levels {
            fs::create_dir_all(level_dir(&args.output_dir, zoom))?;
        }

        let pool = build_thread_pool(args.num_workers)?;
        let progress = make_progress_bar(work.len() as u64);

        pool.install(|| -> Result<()> {
            work.par_iter().try_for_each(|key| -> Result<()> {
                convert_one_bundle(&args.mbtiles_path, &args.output_dir, key)?;
                progress.inc(1);
                Ok(())
            })
        })?;
        progress.finish_and_clear();
    }

    write_metadata(&discover_conn, &args.output_dir)?;
    Ok(())
}

fn level_dir(output_dir: &Path, zoom: i64) -> PathBuf {
    output_dir.join("tile").join(format!("L{zoom:02}"))
}

fn bundle_path(output_dir: &Path, key: &BundleKey) -> PathBuf {
    let start_row = key.bundle_row * 128;
    let start_col = key.bundle_col * 128;
    level_dir(output_dir, key.zoom).join(format!("R{start_row:04x}C{start_col:04x}.bundle"))
}

// Each rayon worker thread keeps exactly one connection open, reused across
// every bundle task it picks up -- opening a fresh connection per bundle
// (there can be tens of thousands across all zoom levels) would add
// needless per-task overhead, and SQLite has no issue with many concurrent
// read-only connections to the same file. Bounded by the thread pool size,
// same as the Python original's "one connection per zoom-level worker
// process".
thread_local! {
    static TLS_CONN: RefCell<Option<Connection>> = const { RefCell::new(None) };
}

fn with_thread_connection<T>(
    mbtiles_path: &Path,
    f: impl FnOnce(&Connection) -> Result<T>,
) -> Result<T> {
    TLS_CONN.with(|cell| {
        let mut slot = cell.borrow_mut();
        if slot.is_none() {
            *slot = Some(db::open_readonly(mbtiles_path)?);
        }
        f(slot.as_ref().unwrap())
    })
}

fn convert_one_bundle(mbtiles_path: &Path, output_dir: &Path, key: &BundleKey) -> Result<()> {
    let tiles: Vec<BundleTile> =
        with_thread_connection(mbtiles_path, |conn| db::fetch_bundle_tiles(conn, key))?;
    let path = bundle_path(output_dir, key);
    bundle::write_bundle(&path, &tiles).with_context(|| format!("writing {}", path.display()))
}

fn build_thread_pool(num_workers: Option<usize>) -> Result<rayon::ThreadPool> {
    let mut builder = rayon::ThreadPoolBuilder::new();
    if let Some(n) = num_workers {
        builder = builder.num_threads(n);
    }
    Ok(builder.build()?)
}

fn make_progress_bar(total: u64) -> ProgressBar {
    let bar = ProgressBar::new(total);
    if std::io::stderr().is_terminal() {
        if let Ok(style) = ProgressStyle::with_template(
            "{spinner} [{elapsed_precise}] [{bar:40.cyan/blue}] {pos}/{len} bundles",
        ) {
            bar.set_style(style.progress_chars("=>-"));
        }
    } else {
        // Avoid flooding piped/logged output with carriage-return redraws --
        // abt/utils/subprocess_tools.py tees this process's output line by
        // line into a per-task log file when invoked from the Python CLI.
        bar.set_draw_target(ProgressDrawTarget::hidden());
    }
    bar
}

/// Matches Python's `json.dumps(value, ensure_ascii=False)` default
/// separators (`", "` / `": "`, i.e. WITH a space): serde_json's built-in
/// compact formatter omits the space, and its pretty formatter adds
/// newlines/indentation that Python's non-indent `dumps` doesn't produce.
struct PyCompactFormatter;

impl serde_json::ser::Formatter for PyCompactFormatter {
    fn begin_array_value<W: ?Sized + std::io::Write>(
        &mut self,
        writer: &mut W,
        first: bool,
    ) -> std::io::Result<()> {
        writer.write_all(if first { b"" } else { b", " })
    }

    fn begin_object_key<W: ?Sized + std::io::Write>(
        &mut self,
        writer: &mut W,
        first: bool,
    ) -> std::io::Result<()> {
        writer.write_all(if first { b"" } else { b", " })
    }

    fn begin_object_value<W: ?Sized + std::io::Write>(
        &mut self,
        writer: &mut W,
    ) -> std::io::Result<()> {
        writer.write_all(b": ")
    }
}

/// Parses `raw_json` and re-serializes it in the same shape Python's
/// `json.dumps(json.loads(row[0]), ensure_ascii=False)` would produce.
///
/// The `arbitrary_precision` feature is load-bearing, not cosmetic:
/// tippecanoe's own `tilestats` block can contain 17-significant-digit
/// floats (real sample data, not a contrived case), and serde_json's
/// normal `Value::Number` parsing measurably disagrees with both Python's
/// and Rust's own standard-library float parsers by one ULP on such inputs
/// -- see the regression test below. `arbitrary_precision` sidesteps this
/// entirely by never parsing numbers into `f64` at all, preserving the
/// original digit string byte-for-byte instead (which also means, unlike
/// Python's own parse-then-`repr()` round trip, this never perturbs the
/// value from what tippecanoe originally wrote).
fn format_metadata_json(raw_json: &str) -> Result<Vec<u8>> {
    let value: serde_json::Value =
        serde_json::from_str(raw_json).context("parsing metadata 'json' row as JSON")?;
    let mut buf = Vec::new();
    let mut serializer = serde_json::Serializer::with_formatter(&mut buf, PyCompactFormatter);
    value.serialize(&mut serializer)?;
    Ok(buf)
}

/// Reads the metadata `json` row and writes it to `output_dir/metadata.json`.
/// Writes nothing if there's no such row, matching the Python original's
/// `_write_metadata` early return.
fn write_metadata(conn: &Connection, output_dir: &Path) -> Result<()> {
    let Some(raw_json) = db::read_metadata_json(conn)? else {
        return Ok(());
    };
    let formatted = format_metadata_json(&raw_json)?;
    fs::create_dir_all(output_dir)?;
    fs::write(output_dir.join("metadata.json"), formatted)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn separators_match_python_json_dumps_default() {
        let out = format_metadata_json(r#"{"a":1,"b":[1,2,3],"c":{"d":4}}"#).unwrap();
        assert_eq!(
            String::from_utf8(out).unwrap(),
            r#"{"a": 1, "b": [1, 2, 3], "c": {"d": 4}}"#
        );
    }

    #[test]
    fn key_order_is_preserved_not_sorted() {
        let out = format_metadata_json(r#"{"zebra": 1, "apple": 2, "mango": 3}"#).unwrap();
        assert_eq!(
            String::from_utf8(out).unwrap(),
            r#"{"zebra": 1, "apple": 2, "mango": 3}"#
        );
    }

    #[test]
    fn non_ascii_is_not_escaped() {
        let out = format_metadata_json(r#"{"name": "caf\u00e9 \u65e5\u672c\u8a9e"}"#).unwrap();
        assert_eq!(
            String::from_utf8(out).unwrap(),
            "{\"name\": \"caf\u{e9} \u{65e5}\u{672c}\u{8a9e}\"}"
        );
    }

    /// Regression test for a real discrepancy found against production
    /// data: serde_json's default `Value::Number` float parser rounds
    /// `0.0027596873696893455` (17 significant digits, straight from a
    /// real tippecanoe `tilestats` block) to a bit pattern one ULP away
    /// from what both Python's `float()` and Rust's own `str::parse::<f64>`
    /// agree is the correctly-rounded result. `arbitrary_precision`
    /// preserves the literal input digits instead of reparsing them,
    /// which sidesteps the discrepancy entirely.
    #[test]
    fn high_precision_floats_survive_round_trip_exactly() {
        let input = r#"{"area":[0.0027596873696893455,770186215424]}"#;
        let out = format_metadata_json(input).unwrap();
        assert_eq!(
            String::from_utf8(out).unwrap(),
            r#"{"area": [0.0027596873696893455, 770186215424]}"#
        );
    }
}
