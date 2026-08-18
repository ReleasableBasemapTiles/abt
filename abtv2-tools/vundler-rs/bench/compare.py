"""
compare.py

CLI wrapper around oracle.compare_trees: verifies two vundler output
packages (e.g. one from the Python implementation, one from the Rust
binary) are semantically identical -- every (zoom, row, col) tile's bytes
match and metadata.json matches -- regardless of on-disk write order/offsets.

Exits non-zero with a diagnostic on any mismatch.
"""

import argparse
import sys
from pathlib import Path

from oracle import compare_trees

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("a", type=Path)
    ap.add_argument("b", type=Path)
    ap.add_argument("--a-label", default="A")
    ap.add_argument("--b-label", default="B")
    args = ap.parse_args()

    try:
        summary = compare_trees(args.a, args.b, args.a_label, args.b_label)
    except AssertionError as e:
        print(f"MISMATCH between {args.a} and {args.b}:\n{e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"ERROR comparing {args.a} and {args.b}: {e}", file=sys.stderr)
        sys.exit(2)

    print(summary)
