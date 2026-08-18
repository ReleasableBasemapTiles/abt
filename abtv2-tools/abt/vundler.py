"""
vundler.py

Converts an mbtiles database into Esri's Compact Cache V2 tile bundle format
(one .bundle file per 128x128 tile block, per zoom level). Delegates to the
abt-vundler Rust binary (../vundler-rs/) for the actual conversion, which is
restructured there around per-bundle work units instead of per-zoom-level
tasks -- the original pure-Python implementation measured ~40x redundant
bundle-index rewrites (row-major iteration reopens the same bundle file
once per tile row it contains) and a parallelism ceiling around 2x on real
data (one zoom level alone was measured at 48% of all tiles, capping
per-zoom-level task parallelism regardless of core count). See
vundler-rs/bench/ for the benchmark and golden-output comparison harness
this was verified against. Produces the raw tile-bundle folder structure
and a bare metadata.json -- not a complete, packaged .vtpk (no
conf.xml/root.json).
"""

from typing import Optional

from .vundler_model import VundlerConverter
from .utils.subprocess_tools import run_subprocess


def convert(
    converter: VundlerConverter, max_workers: Optional[int] = None
) -> None:
    """Converts every zoom level up to `converter.max_zoom` via the
    abt-vundler binary, which also writes metadata.json. `max_workers` maps
    directly to the binary's --num-workers; omitted entirely when None, so
    it defaults to one worker thread per available core.
    """
    log_dir = converter.output_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        "abt-vundler",
        "--mbtiles-path", str(converter.mbtiles_path),
        "--output-dir", str(converter.output_dir),
        "--max-zoom", str(converter.max_zoom),
    ]
    if max_workers is not None:
        cmd += ["--num-workers", str(max_workers)]

    run_subprocess(
        cmd=cmd,
        layer="vundler",
        process_stage="vundler",
        log_dir=log_dir,
        tool_name="abt-vundler",
    )
