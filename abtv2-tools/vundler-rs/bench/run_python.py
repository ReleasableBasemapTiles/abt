"""
run_python.py

Runs the current (pre-Rust-port) Python vundler implementation in-process
against a given mbtiles file, reporting wall time and peak child RSS. Used
both as the golden-output generator and as the "before" side of the
before/after benchmark.

Requires `pydantic` on the interpreter running this script (only dependency
abt/vundler.py's import chain needs) -- see bench/README.md for the isolated
venv this was developed against, so this doesn't disturb any project env.
"""

import argparse
import resource
import sys
import time
from pathlib import Path

ABTV2_TOOLS_DIR = Path(__file__).resolve().parents[2]  # .../abtv2-tools
sys.path.insert(0, str(ABTV2_TOOLS_DIR))

from abt.vundler import convert  # noqa: E402
from abt.vundler_model import VundlerConverter  # noqa: E402


def run(mbtiles_path: Path, output_dir: Path, max_zoom: int, num_workers=None) -> float:
    converter = VundlerConverter(mbtiles_path=mbtiles_path, output_dir=output_dir, max_zoom=max_zoom)
    t0 = time.perf_counter()
    convert(converter, max_workers=num_workers)
    return time.perf_counter() - t0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mbtiles-path", required=True, type=Path)
    ap.add_argument("--output-dir", required=True, type=Path)
    ap.add_argument("--max-zoom", required=True, type=int)
    ap.add_argument("--num-workers", type=int, default=None)
    args = ap.parse_args()

    elapsed = run(args.mbtiles_path, args.output_dir, args.max_zoom, args.num_workers)
    # ru_maxrss unit is platform-dependent: KB on Linux, bytes on macOS.
    # ProcessPoolExecutor spawns real child processes, so their peak RSS
    # accumulates into RUSAGE_CHILDREN on the parent once they exit.
    peak_children = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    unit = "bytes" if sys.platform == "darwin" else "KB"
    print(f"python vundler: {elapsed:.3f}s wall, peak child RSS (RUSAGE_CHILDREN)={peak_children} {unit}")
