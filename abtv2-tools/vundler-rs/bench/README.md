# vundler-rs benchmark and golden-comparison harness

Verifies `abt-vundler` produces output semantically identical to the
original pure-Python `abt/vundler.py` (before it was rewired to shell out
to this binary -- see `../../abt/vundler.py`'s module docstring), and
measures wall-clock/RSS for both.

There are no tests elsewhere in this repo, so this harness -- not a shared
CI suite -- is what backs the port's correctness claims. Re-run it after
any change to `bundle.rs`/`db.rs`/`main.rs`.

## Setup

`run_python.py` needs `pydantic` (the only third-party import in
`abt/vundler_model.py`'s chain) on whichever interpreter runs it. An
isolated venv keeps this out of any project/conda environment:

```bash
python3 -m venv /tmp/vundler_bench_venv
/tmp/vundler_bench_venv/bin/pip install pydantic
```

## Files

- `oracle.py` -- independent reader for the Esri Compact Cache V2 bundle
  format, built from the documented byte layout rather than from either
  implementation's own writer code. `compare_trees()` walks every
  `(zoom, row, col)` tile plus `metadata.json` and reports any mismatch.
  Bundle files are not expected to be byte-identical between
  implementations that write tiles in a different order (offsets shift),
  so comparison is semantic (per-tile payload equality), not a raw diff.
- `make_fixtures.py` -- generates small synthetic `.mbtiles` fixtures into
  `fixtures/` (gitignored) covering edge cases real-world files may not
  always exercise: zooms narrower than one 128x128 bundle, the exact
  128/256-tile bundle-boundary zooms, sparse coverage, no metadata row, and
  zero tiles. Uses the same `map`/`images`/`tiles`-view schema
  tippecanoe/tile-join actually produce (confirmed locally, not assumed --
  see `run tippecanoe -o x.mbtiles ... && sqlite3 x.mbtiles .schema`).
- `run_python.py` -- runs `abt.vundler.convert()` in-process, reporting
  wall time and peak child RSS (`RUSAGE_CHILDREN`, since the pre-port
  implementation used a `ProcessPoolExecutor`).
- `run_rust.py` -- runs the compiled `abt-vundler` binary as a subprocess,
  same metrics.
- `compare.py` -- CLI wrapper around `oracle.compare_trees`.

## Usage

```bash
# One-time: generate fixtures
/tmp/vundler_bench_venv/bin/python3 make_fixtures.py

# Build the release binary
cargo build --release --manifest-path ../Cargo.toml

# Run both implementations against the same input
/tmp/vundler_bench_venv/bin/python3 run_python.py \
    --mbtiles-path fixtures/boundary_zoom7_8.mbtiles \
    --output-dir /tmp/py_out --max-zoom 13
../target/release/abt-vundler \
    --mbtiles-path fixtures/boundary_zoom7_8.mbtiles \
    --output-dir /tmp/rust_out --max-zoom 13

# Compare
/tmp/vundler_bench_venv/bin/python3 compare.py /tmp/py_out /tmp/rust_out \
    --a-label python --b-label rust
```

For a real-world benchmark, point `--mbtiles-path` at an actual
`bundled/joined.mbtiles` (or `.btis`) from a completed `abt bundler` run
instead of a `fixtures/*.mbtiles`.

## Important: this only compares against the *pre-port* Python implementation

Once `abt/vundler.py` is wired to shell out to `abt-vundler` (see its
module docstring), `run_python.py` no longer exercises independent logic --
it just calls the same binary through one more layer of subprocess/logging
overhead. Re-verifying "did the Rust port change behavior" after that point
requires either checking out the pre-port commit's `abt/vundler.py`, or
trusting the fixtures/outputs already captured before the rewiring.
