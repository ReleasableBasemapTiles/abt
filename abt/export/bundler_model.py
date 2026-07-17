"""
bundler_model.py

Defines the Bundler data model: which TileLayer mbtiles to join and how, plus
the command-string builder for `tile-join`. Actually running the join and
writing output happens in export/bundler.py.
"""

import datetime
import sqlite3
from functools import cached_property
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from .tile_layer_model import TileLayer
from ..utils.messages import MbtilesNotFound


class Bundler(BaseModel):
    """A model to join multiple MBTiles files into a single package.

    Attributes:
        bundled_dir: The directory where the final bundled MBTiles file will be saved.
        package_name: The filename for the final output (e.g., "joined.mbtiles").
        package_name_explicit: True if package_name was chosen by the caller
            rather than defaulted -- skips the automatic .btis rename under
            --projection-override, since an explicit name is assumed to
            already include the extension the caller wants.
        tile_layers: A list of TileLayer objects to be included in the bundle.
        additional_mbtiles: Paths to externally-produced mbtiles files to fold into the
            bundle alongside the tile_layers (e.g. contours). Zero, one, or many.
        metadata: Descriptive metadata (name, description, attribution, tags, license,
            etc., typically loaded from the schema repo's abt_metadata.py) to write into
            the joined mbtiles. `tile-join` only accepts a `-n` name flag on the command
            line, so everything else is written directly into the metadata table after
            the join completes. Keys tile-join computes itself from actual tile content
            (bounds, center, format) are never overwritten -- see
            mbtiles_metadata.TOOL_COMPUTED_METADATA_KEYS, used by bundler.py.
    """
    bundled_dir: Path
    package_name: str = "joined.mbtiles"
    package_name_explicit: bool = False
    tile_layers: List[TileLayer]
    additional_mbtiles: List[Path] = []
    metadata: Optional[Dict[str, Any]] = None

    @staticmethod
    def _has_tiles(path: Path) -> bool:
        """
        Returns True if an MBTiles file has a `tiles` table AND it's actually
        populated. A layer with zero exported features still gets a file on
        disk (tippecanoe creates the schema before it errors out on empty
        input, e.g. exit code 110), so checking table existence alone isn't
        enough to exclude genuinely empty layers.
        """
        try:
            con = sqlite3.connect(path)
            cur = con.cursor()
            cur.execute("SELECT count(*) FROM sqlite_master WHERE name='tiles' AND type IN ('table', 'view')")
            has_table = cur.fetchone()[0] == 1
            if not has_table:
                con.close()
                return False
            cur.execute("SELECT count(*) FROM tiles")
            has_rows = cur.fetchone()[0] > 0
            con.close()
            return has_rows
        except Exception:
            return False

    @cached_property
    def tile_list(self) -> List[Path]:
        """Generates a list of all MBTiles file paths to be joined.

        Excludes files that have no tiles table (empty layers with 0 features),
        which would cause tile-join to fail.

        Looks for either a `.mbtiles` or `.btis` file per layer -- the Bundler
        doesn't know whether `export` was run with --projection-override, so
        it discovers the actual extension on disk rather than assuming
        `.mbtiles`. See mbtiles_metadata.resolve_crs_from_files (used by
        bundler.py), which reads the truth back out of whichever
        file it finds.
        """
        additional = [p for p in self.additional_mbtiles if p.exists()]
        layer_files = []
        for t in self.tile_layers:
            for extension in ("mbtiles", "btis"):
                candidate = t.mbtiles_dir / f"{t.layer_id}.{extension}"
                if candidate.exists():
                    layer_files.append(candidate)
                    break
        candidates = layer_files + additional
        valid = [p for p in candidates if self._has_tiles(p)]
        skipped = [p.name for p in candidates if not self._has_tiles(p)]
        if skipped:
            print(f"NOTE: skipping {len(skipped)} empty mbtiles (no tiles table): {', '.join(skipped)}")
        return valid

    def pre_validate_tiles_exists(self) -> bool:
        """Checks if all required MBTiles files exist before attempting to join."""
        missing_files = [str(p) for p in self.tile_list if not p.exists()]
        if missing_files:
            raise MbtilesNotFound(f"Missing Files for Join: {', '.join(missing_files)}")
        return True

    @property
    def bundled_mbtiles_path(self) -> Path:
        """Returns the full path to the final bundled MBTiles file."""
        return self.bundled_dir / self.package_name

    @property
    def bundled_mbtiles_tmp(self) -> Path:
        """Returns the full path to the temporary bundled MBTiles file."""
        tmp_dir = self.bundled_dir / "_tmp"
        tmp_dir.mkdir(exist_ok=True)
        return tmp_dir

    @property
    def tile_join_cmd(self) -> List[str]:
        """Constructs the full 'tile-join' command."""
        default_name = f"Army Basemap Tiles (Build: {datetime.datetime.now().strftime('%Y-%m-%d')})"
        name = self.metadata.get("name", default_name) if self.metadata else default_name
        return [
            "tile-join",
            "-pk",  # Don't skip tiles larger than 500K.
            "-n", name,
            "--output", str(self.bundled_dir / self.package_name),
            *[str(p) for p in self.tile_list]
        ]
