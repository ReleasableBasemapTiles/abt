"""
run_rust.py

Runs the compiled abt-vundler Rust binary as a subprocess against a given
mbtiles file, reporting wall time and peak RSS -- the "after" side of the
before/after benchmark, in the same units/methodology as run_python.py.
"""

import argparse
import resource
import subprocess
import sys
import time
from pathlib import Path

DEFAULT_BINARY = Path(__file__).resolve().parent.parent / "target" / "release" / "abt-vundler"


def run(binary: Path, mbtiles_path: Path, output_dir: Path, max_zoom: int, num_workers=None) -> float:
    cmd = [
        str(binary),
        "--mbtiles-path", str(mbtiles_path),
        "--output-dir", str(output_dir),
        "--max-zoom", str(max_zoom),
    ]
    if num_workers is not None:
        cmd += ["--num-workers", str(num_workers)]

    t0 = time.perf_counter()
    subprocess.run(cmd, check=True)
    return time.perf_counter() - t0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--binary", type=Path, default=DEFAULT_BINARY)
    ap.add_argument("--mbtiles-path", required=True, type=Path)
    ap.add_argument("--output-dir", required=True, type=Path)
    ap.add_argument("--max-zoom", required=True, type=int)
    ap.add_argument("--num-workers", type=int, default=None)
    args = ap.parse_args()

    if not args.binary.exists():
        sys.exit(f"binary not found at {args.binary} -- build it first with `cargo build --release`")

    elapsed = run(args.binary, args.mbtiles_path, args.output_dir, args.max_zoom, args.num_workers)
    peak_children = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    unit = "bytes" if sys.platform == "darwin" else "KB"
    print(f"rust vundler: {elapsed:.3f}s wall, peak child RSS (RUSAGE_CHILDREN)={peak_children} {unit}")
