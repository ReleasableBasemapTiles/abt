"""
importer.py

Defines the Pydantic models that manage the data import process into PostgreSQL.
This module provides a structured way to handle different import tools, specifically
'ogr2ogr' for general vector data and 'imposm' for specialized OpenStreetMap (OSM)
data imports. The main `Importer` class acts as a generic wrapper that dispatches
the import task to the correct underlying tool.
"""

from pydantic import BaseModel
from typing import Union, List, Optional
from pathlib import Path

from ..utils.subprocess_tools import run_subprocess


class ImportOGR(BaseModel):
    """
    A simple model to hold a pre-constructed command for an 'ogr2ogr' import.

    Attributes:
        cmd: A list of strings representing the full 'ogr2ogr' command to be executed.
        pre_cmd: An optional command run first, inside the same import task
            (e.g. converting a FileGDB layer to an intermediate FlatGeobuf).
        pre_output: The file pre_cmd writes, deleted before it runs (the
            FlatGeobuf driver can't overwrite an existing file).
        prep_error: Set instead of a usable cmd when preparing this import
            failed (e.g. no source layer matched its glob). The task then
            fails with this message when it runs, so one bad source is
            reported against its own layer instead of aborting every import.
    """
    cmd: List[str] = []
    pre_cmd: Optional[List[str]] = None
    pre_output: Optional[Path] = None
    prep_error: Optional[str] = None


class ImportImposm(BaseModel):
    """
    Constructs and manages the command for an 'imposm' import process.

    This model takes all the necessary configuration for an 'imposm' run,
    including file paths, database URI, and cache settings, and builds the
    appropriate command-line arguments.

    Attributes:
        mapping: Path to the 'imposm' mapping YAML file.
        pbf: Path to the source OpenStreetMap PBF file.
        pg_uri: The PostgreSQL connection URI.
        pg_schema: The target PostgreSQL schema for the imported OSM data.
        cache_directory: Path to the directory for 'imposm's cache.
        diff_directory: Optional path to a directory for differential updates.
    """
    mapping: Path
    pbf: Path
    pg_uri: str
    pg_schema: str
    cache_directory: Path
    diff_directory: Optional[Path] = None

    @property
    def if_diff(self) -> List[str]:
        """
        Returns the appropriate command-line flags if a differential import is specified.
        """
        if self.diff_directory:
            return ["-diff", "-diffdir", str(self.diff_directory)]
        else:
            return []

    @property
    def cmd(self) -> List[str]:
        """
        Builds the complete 'imposm import' command as a list of strings.
        """
        return [
            "imposm", "import",
            "-mapping", str(self.mapping),
            "-read", str(self.pbf),
            "-write",
            "--overwritecache",
            "-connection", self.pg_uri,
            "-cachedir", str(self.cache_directory),
            *self.if_diff,
            "-srid", "4326",
            "-dbschema-production", self.pg_schema,
            "-deployproduction"
        ]


class Importer(BaseModel):
    """
    An orchestrator model that handles different types of database import tasks.

    This class acts as a generic wrapper, determining whether to use 'ogr2ogr' or
    'imposm' based on the type of the `importer` attribute and then executing the
    appropriate command via a subprocess helper.

    Attributes:
        importer: The specific importer model (ImportOGR or ImportImposm).
        layer: A descriptive name for the data layer being imported, used for logging.
        log_dir: The directory for storing logs related to the import process.
    """
    importer: Union[ImportOGR, ImportImposm]
    layer: str
    log_dir: Path

    @property
    def name(self) -> str:
        """Alias for layer, used by ParallelExecutor for per-task reporting."""
        return self.layer

    def import_to_pg(self) -> None:
        """Runs the import via ogr2ogr or imposm, depending on the configured importer type."""
        if isinstance(self.importer, ImportOGR):
            tool_name = "ogr2ogr"
            if self.importer.prep_error:
                raise RuntimeError(self.importer.prep_error)
            if self.importer.pre_cmd:
                if self.importer.pre_output is not None:
                    self.importer.pre_output.unlink(missing_ok=True)
                run_subprocess(
                    cmd=self.importer.pre_cmd,
                    layer=self.layer,
                    process_stage=f"{self.layer}_import",
                    log_dir=self.log_dir,
                    tool_name="ogr2ogr (pre-conversion)",
                )
        elif isinstance(self.importer, ImportImposm):
            tool_name = "imposm"
        else:
            raise TypeError(f"Unsupported importer type: {type(self.importer)}")

        run_subprocess(
            cmd=self.importer.cmd,
            layer=self.layer,
            process_stage=f"{self.layer}_import",
            log_dir=self.log_dir,
            tool_name=tool_name,
        )
