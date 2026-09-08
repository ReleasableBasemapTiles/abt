# vundler-rs

`abt-vundler` is a Rust binary at `abtv2-tools/vundler-rs/` that converts an mbtiles database into Esri's Compact Cache V2 tile bundle format (one `.bundle` file per 128x128 tile block, per zoom level). The Python [Vundler stage](../pipeline/vundler.md) (`abt/vundler.py`) delegates to this binary for the actual conversion rather than doing it in pure Python.

!!! note "Package output, not a full .vtpk"
    `abt-vundler` produces the raw tile-bundle folder structure and a bare `metadata.json` — it does not produce a complete, packaged `.vtpk` (there's no `conf.xml`/`root.json` written).

## Why a Rust port

The pre-port pure-Python implementation had two measured problems on real data:

- **~40x redundant bundle-index rewrites.** Its row-major tile iteration reopens the same bundle file once per tile row it contains, rewriting that bundle's index far more than necessary.
- **A parallelism ceiling around 2x**, because the original unit of parallel work was a whole zoom level — and zoom levels are not evenly sized. In a real 223 MB sample, zoom 13 alone accounted for 48% of all tiles, which caps per-zoom-level task parallelism well below the number of available cores no matter how many workers are requested.

`abt-vundler` restructures the work around per-*bundle* units instead of per-zoom-level tasks, which removes both problems — see [Implementation highlights](#implementation-highlights) below.

## CLI

```bash
abt-vundler --mbtiles-path <PATH> --output-dir <PATH> --max-zoom <N> [--num-workers <N>]
```

| Flag | Required | Notes |
|---|---|---|
| `-i, --mbtiles-path <PATH>` | yes | Source `.mbtiles`/`.btis` file. |
| `-o, --output-dir <PATH>` | yes | Output package directory; tiles are written to `<output-dir>/tile/L##/`, with `metadata.json` alongside `tile/`. |
| `-z, --max-zoom <N>` | yes | Highest zoom level to convert. |
| `-n, --num-workers <N>` | no | Worker threads used to convert bundles concurrently. Defaults to rayon's own default (one thread per available core). |

## Crate layout

`abt-vundler` (`Cargo.toml`, edition 2024) has five dependencies: `anyhow`, `clap` (derive), `indicatif` (progress bars), `rayon` (parallelism), `rusqlite` (bundled SQLite), and `serde`/`serde_json`.

| File | Lines (approx.) | Contents |
|---|---|---|
| `src/main.rs` | ~324 | CLI parsing (`clap::Parser`) and orchestration: builds the flattened work list, sets up the thread pool and progress bar, and writes `metadata.json`. |
| `src/bundle.rs` | ~281 | The `.bundle` file writer — header, tile index, and payloads. |
| `src/db.rs` | ~397 | All SQLite access: zoom-level/bundle-key enumeration, per-bundle tile fetches, and metadata lookup. |

All three files carry detailed module- and function-level doc comments; read them directly at `abtv2-tools/vundler-rs/src/` for more implementation detail than is summarized here.

## Implementation highlights

**One flat work list, not one task per zoom level.** `main.rs` enumerates every zoom level's bundle keys up front and flattens them into a single `Vec<BundleKey>` before handing the whole thing to `rayon`'s `par_iter`. This is the direct fix for the parallelism ceiling described above — with a single flat list, no individual zoom level (e.g. the z13 that was 48% of all tiles in the reference sample) can cap how many bundles are converted concurrently, regardless of core count or `--num-workers`.

**One pass per bundle file.** `bundle.rs`'s `write_bundle` takes an entire bundle's tiles up front and writes the file in a single pass: header, then each tile payload (building the index in memory as it goes), then one seek-back to patch `max_size` and total size and write the index. This is the direct fix for the redundant-rewrite problem — the file is opened and written exactly once, instead of being reopened per tile row.

**Bundle-key enumeration avoids touching tile blobs.** `db.rs` discovers which bundles exist by querying the `map` table's `(tile_column, tile_row)` columns directly (falling back to a plain `tiles` table when there's no `map`/`images` split), rather than reading through the `tiles` view's join to `images`. Per-bundle tile fetches are also unsorted — unlike the pre-port Python's `ORDER BY tile_row DESC, tile_column ASC` per zoom level, which forced SQLite to materialize and sort every zoom level's rows (blobs included) into a temp b-tree. `abt-vundler` builds each bundle's index in memory keyed by tile position, so fetch order doesn't matter.

**Per-thread SQLite connections.** Each rayon worker thread opens exactly one read-only SQLite connection and reuses it across every bundle task it picks up, rather than opening a fresh connection per bundle (there can be tens of thousands across all zoom levels).

!!! note "Known edge cases"
    Three confirmed, harmless divergences between `abt-vundler` and the pre-port Python reference — not bugs, just documented behavior. Full detail and severity ratings are in [Code Review Findings](../project/code-review-findings.md).

    - **Orphaned `map` rows produce a phantom empty bundle in Rust only.** Because Rust enumerates bundle keys from the `map` table directly (to avoid touching tile blobs), a bundle whose only tile is an orphaned `map` row (no matching `images` row — not something real tippecanoe/tile-join output produces) still gets an empty, all-zero-index `.bundle` file written to disk. The Python reference never visits that key at all. This does not cause a tile-content mismatch in the golden test (an all-zero-index bundle contributes zero tiles either way), but it is a real difference in what ends up on disk.
    - **Bundle filenames can exceed 10 characters at zoom 17+.** `R{:04x}C{:04x}` is a *minimum*-width hex format in both implementations, not a Rust regression — it grows past the conventional `R####C####` shape once a bundle's start row/col reaches `0x10000`. Out of scope for real data today (`--max-zoom` is 13 in practice), but worth knowing before this tool is ever pointed at z17+.
    - **Neither implementation handles a missing `metadata` table.** Both implementations already handle a present-but-empty `metadata` table; if the table is absent outright, both fail loudly and symmetrically. This is a pre-existing, shared limitation, not a port regression.

## Testing and verification

There is no shared CI suite in this repo (see [Testing](../project/testing.md) and [Contributing](../project/contributing.md)) — the harness below is what backs the Rust port's correctness claims, and is run locally.

- **`abtv2-tools/vundler-rs/tests/`** — a golden-oracle regression suite:
    - `tests/reference/vundler_reference.py` — a frozen, dependency-free transcription of the pre-port Python `BundleWriter`/`_convert_level`, taken from a specific pinned git commit and never edited to match new output.
    - `tests/fixtures.py` — generates tiny, deterministic mbtiles fixtures at test time (dozens of tiles), covering edge cases: zooms narrower than one 128x128 bundle, exact 128/256-tile bundle-boundary zooms, sparse coverage, no metadata row, and zero tiles.
    - `tests/test_golden.py` — a pytest suite (9 tests) comparing the frozen Python reference against the compiled Rust binary per fixture, via a semantic (per-tile, not byte-diff) comparison.
    - `tests/cli.rs` — 6 Rust integration tests against the compiled binary: end-to-end conversion, `metadata.json` shape, empty input, `--max-zoom` truncation, `--num-workers` determinism, and missing-input failure.

  Run the Rust side with:

    ```bash
    cargo test --manifest-path abtv2-tools/vundler-rs/Cargo.toml
    ```

  The Python golden tests need `pydantic` (the only third-party import in `abt/vundler_model.py`'s import chain) available in whichever interpreter runs `pytest` against `test_golden.py`.

- **`abtv2-tools/vundler-rs/bench/`** — a separate wall-clock/RSS benchmark and semantic-diff harness, *not* a correctness test suite:
    - `oracle.py` — an independent reader for the Esri Compact Cache V2 format, built from the documented byte layout rather than either implementation's own writer code. Its `compare_trees()` walks every `(zoom, row, col)` tile plus `metadata.json` and reports mismatches; bundle files aren't expected to be byte-identical since tile write order differs between implementations, so the comparison is semantic per-tile-payload equality.
    - `make_fixtures.py` — generates synthetic fixtures into a gitignored `fixtures/` directory.
    - `run_python.py` / `run_rust.py` — measure wall time and peak child RSS for each implementation.
    - `compare.py` — a CLI wrapper around `oracle.compare_trees`.

  Usage:

    ```bash
    python3 -m venv /tmp/vundler_bench_venv
    /tmp/vundler_bench_venv/bin/pip install pydantic
    /tmp/vundler_bench_venv/bin/python3 make_fixtures.py
    cargo build --release --manifest-path ../Cargo.toml
    /tmp/vundler_bench_venv/bin/python3 run_python.py --mbtiles-path fixtures/boundary_zoom7_8.mbtiles --output-dir /tmp/py_out --max-zoom 13
    ../target/release/abt-vundler --mbtiles-path fixtures/boundary_zoom7_8.mbtiles --output-dir /tmp/rust_out --max-zoom 13
    ```

## See also

- [Vundler stage](../pipeline/vundler.md) — how the Python CLI invokes this binary day to day.
- [Code Review Findings](../project/code-review-findings.md) — the full review that produced this test harness and the known edge cases above.
- [Testing](../project/testing.md) — how this test suite fits alongside the Python `abtv2-tools/tests/` suite.
