"""
vundler_model.py

Defines the VundlerConverter data model: source mbtiles, output directory, and
max zoom for an Esri Compact Cache V2 conversion. Actually running the
conversion happens in vundler.py.
"""

from pathlib import Path

from pydantic import BaseModel


class VundlerConverter(BaseModel):
    """Converts an mbtiles file into an Esri Compact Cache V2 tile package.

    Attributes:
        mbtiles_path: Source .mbtiles/.btis file.
        output_dir: Package root (e.g. .../vundled/p12). Tiles go in
            output_dir/tile/L##/, metadata.json sits alongside tile/.
        max_zoom: Highest zoom level to convert.
    """
    mbtiles_path: Path
    output_dir: Path
    max_zoom: int
