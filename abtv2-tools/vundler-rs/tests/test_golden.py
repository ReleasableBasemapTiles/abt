"""
test_golden.py

Golden cross-check: for each tiny fixture in fixtures.py, runs both the
frozen Python reference (reference/vundler_reference.py) and the compiled
abt-vundler Rust binary, then compares their output trees per-tile via
oracle.compare_trees (see ../bench/oracle.py's module docstring for why
this is a semantic, not byte-diff, comparison -- reordering tiles within
a bundle shifts offsets even when the content is identical).

Requires the binary to already be built:
    cargo build --manifest-path abtv2-tools/vundler-rs/Cargo.toml
    (or add --release)
Skips with a clear reason if no binary is found in target/release or
target/debug.

Run from anywhere with:
    pytest abtv2-tools/vundler-rs/tests/test_golden.py
"""

import subprocess
import sys
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
CRATE_DIR = TESTS_DIR.parent
BENCH_DIR = CRATE_DIR / "bench"

for _p in (TESTS_DIR, TESTS_DIR / "reference", BENCH_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import fixtures  # noqa: E402
import vundler_reference  # noqa: E402
from oracle import compare_trees, read_tree  # noqa: E402

_binary_cache: dict = {}


def _find_binary() -> Path:
    if "path" in _binary_cache:
        return _binary_cache["path"]
    for profile in ("release", "debug"):
        candidate = CRATE_DIR / "target" / profile / "abt-vundler"
        if candidate.exists():
            _binary_cache["path"] = candidate
            return candidate
    pytest.skip(
        "abt-vundler binary not built -- run `cargo build "
        "--manifest-path abtv2-tools/vundler-rs/Cargo.toml` (or --release) first"
    )


def run_rust(mbtiles_path: Path, output_dir: Path, max_zoom: int) -> None:
    binary = _find_binary()
    subprocess.run(
        [
            str(binary),
            "--mbtiles-path", str(mbtiles_path),
            "--output-dir", str(output_dir),
            "--max-zoom", str(max_zoom),
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def run_reference(mbtiles_path: Path, output_dir: Path, max_zoom: int) -> None:
    vundler_reference.convert(mbtiles_path, output_dir, max_zoom)


# Fixtures expected to produce a successful, directly-comparable
# conversion in both implementations. "orphan_map_row" and
# "no_metadata_table" are handled by their own dedicated tests below
# instead, since they exercise known divergences/shared limitations
# rather than a clean match.
SUCCESSFUL_FIXTURES = [
    "single_tile_z0",
    "sub_bundle_zoom",
    "bundle_seam",
    "sparse_high_zoom",
    "no_metadata_row",
    "empty",
]


@pytest.mark.parametrize("fixture_name", SUCCESSFUL_FIXTURES)
def test_golden_match(tmp_path: Path, fixture_name: str) -> None:
    mbtiles_path = fixtures.build(fixture_name, tmp_path)
    py_out = tmp_path / "py_out"
    rust_out = tmp_path / "rust_out"

    run_reference(mbtiles_path, py_out, max_zoom=13)
    run_rust(mbtiles_path, rust_out, max_zoom=13)

    summary = compare_trees(py_out, rust_out, "python", "rust")
    assert "0 mismatched" in summary


def test_golden_match_with_max_zoom_truncation(tmp_path: Path) -> None:
    mbtiles_path = fixtures.build("multi_zoom_for_truncation", tmp_path)
    py_out = tmp_path / "py_out"
    rust_out = tmp_path / "rust_out"

    # Fixture spans zoom 5..9; truncate below its top zoom so this
    # actually exercises --max-zoom rather than converting everything.
    run_reference(mbtiles_path, py_out, max_zoom=7)
    run_rust(mbtiles_path, rust_out, max_zoom=7)

    summary = compare_trees(py_out, rust_out, "python", "rust")
    assert "0 mismatched" in summary

    # Confirm truncation actually happened, i.e. this isn't vacuously
    # passing because max_zoom=7 already covered the whole fixture.
    tiles, _ = read_tree(rust_out)
    assert tiles, "expected at least one tile after truncation"
    assert all(zoom <= 7 for zoom, _, _ in tiles)
    assert any(zoom == 7 for zoom, _, _ in tiles)


def test_orphan_map_row_creates_an_extra_empty_bundle_in_rust_only(tmp_path: Path) -> None:
    """Known, narrow divergence: the Rust binary enumerates bundle keys
    from `map` directly, so a bundle whose only tile is an orphaned `map`
    row (no matching `images` row) still gets an empty .bundle file
    written to disk. The Python reference only ever iterates the `tiles`
    view's inner join, so it never visits that bundle key at all and
    never creates the file.

    This does NOT show up as a tile-content mismatch under
    oracle.compare_trees -- confirmed below. An empty bundle's index is
    all-zero, so oracle.read_bundle() contributes zero tiles for it
    either way, and compare_trees only compares tile dictionaries, not
    the raw file listing. It's still a real (if narrow) divergence in
    what ends up on disk -- e.g. any downstream tool that assumes "a
    .bundle file on disk has at least one tile" would be surprised -- so
    it's asserted directly against the filesystem here. See
    docs/code-review-findings.md.
    """
    mbtiles_path = fixtures.build("orphan_map_row", tmp_path)
    py_out = tmp_path / "py_out"
    rust_out = tmp_path / "rust_out"

    run_reference(mbtiles_path, py_out, max_zoom=13)
    run_rust(mbtiles_path, rust_out, max_zoom=13)

    # Orphan map row is (zoom=9, tile_column=200, tile_row=200): m=511,
    # bundle_col=200//128=1, bundle_row=(511-200)//128=2 ->
    # start_col=128=0x80, start_row=256=0x100.
    orphan_bundle = Path("tile") / "L09" / "R0100C0080.bundle"
    assert not (py_out / orphan_bundle).exists(), (
        "Python reference should never create a bundle for a key it never visits"
    )
    assert (rust_out / orphan_bundle).exists(), (
        "expected the known divergence: Rust creates an empty bundle for "
        "the orphaned map row's bundle key"
    )

    # Despite the extra file, tile-level comparison still reports a clean
    # match -- the empty bundle contributes zero tiles either way.
    summary = compare_trees(py_out, rust_out, "python", "rust")
    assert "0 mismatched" in summary


def test_missing_metadata_table_fails_in_both_implementations(tmp_path: Path) -> None:
    """Pre-existing, shared limitation (not a Rust-port regression):
    neither implementation guards against the `metadata` table being
    entirely absent (as opposed to present-but-empty, which both handle
    fine -- see test_golden_match[no_metadata_row]). Documented in
    docs/code-review-findings.md as report-only."""
    mbtiles_path = fixtures.build("no_metadata_table", tmp_path)

    with pytest.raises(Exception):
        run_reference(mbtiles_path, tmp_path / "py_out", max_zoom=13)

    binary = _find_binary()
    result = subprocess.run(
        [
            str(binary),
            "--mbtiles-path", str(mbtiles_path),
            "--output-dir", str(tmp_path / "rust_out"),
            "--max-zoom", "13",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
