"""
schema.py

Defines Pydantic models that represent and validate the directory structures
for the entire data processing pipeline. This includes the layout of the main
working directory where all output is stored, and the structure of the input
data schema directory which contains all user-defined configurations.
"""

import datetime
from pydantic import BaseModel, model_validator
from typing import List
from typing_extensions import Self
from pathlib import Path

from .utils.messages import DataSchemaErrorMessage


class ProcessingDirectorySchema(BaseModel):
    """
    Defines and manages the directory structure for all processing outputs.

    This model centralizes the paths for all temporary files, logs, and final
    outputs, ensuring a consistent and organized working directory. It should be
    initialized using the `init_working_directories` class method.

    Attributes:
        working_dir: The root directory for all outputs.
        osm_dir: Directory for OSM processing files (PBF, imposm mapping/cache).
        aux_download_dir: Directory for downloaded auxiliary data.
        flatgeobuf_dir: Directory for intermediate FlatGeobuf files.
        mbtiles_dir: Directory for individual MBTiles files.
        bundled_dir: Directory for the final joined MBTiles package.
        tmp_dir: Root directory for temporary files.
        run_id: Unique identifier for this invocation, used to scope its log folder.
        log_dir: Root directory for this run's log files (working_dir/logs/<run_id>).
        summary_file: Path to this run's consolidated JSON summary.
        # ... and other specific log/temp directories.
    """
    working_dir: Path
    osm_dir: Path
    aux_download_dir: Path
    flatgeobuf_dir: Path
    mbtiles_dir: Path
    bundled_dir: Path
    tmp_dir: Path
    ogr_tmp: Path
    tippecanoe_tmp: Path
    run_id: str
    log_dir: Path
    summary_file: Path
    download_log_dir: Path
    import_log_dir: Path
    carto_log_dir: Path
    fgb_log_dir: Path
    mbtiles_log_dir: Path

    @classmethod
    def init_working_directories(cls, working_dir: Path) -> "ProcessingDirectorySchema":
        """
        Creates the entire directory tree required for processing and returns an instance.

        This method takes a base working directory path, creates all necessary
        subdirectories for data, logs, and temporary files, and then instantiates
        the class with all the correct paths. Each call gets its own timestamped
        run_id, so logs from separate invocations never overwrite each other,
        even if they run the same day or overlap in time.

        Args:
            working_dir: The root path for all processing outputs.

        Returns:
            A fully configured ProcessingDirectorySchema instance.
        """
        run_id = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")

        # Create main output directories
        dirs = {
            "working_dir": working_dir,
            "aux_download_dir": working_dir / "aux_downloads",
            "osm_dir": working_dir / "osm",
            "flatgeobuf_dir": working_dir / "flatgeobuf",
            "mbtiles_dir": working_dir / "mbtiles",
            "bundled_dir": working_dir / "bundled",
            "tmp_dir": working_dir / "tmp",
            "log_dir": working_dir / "logs" / run_id,
        }

        # Create temporary subdirectories
        dirs["ogr_tmp"] = dirs["tmp_dir"] / "ogr_tmp"
        dirs["tippecanoe_tmp"] = dirs["tmp_dir"] / "tippecanoe_tmp"

        # Create log subdirectories
        dirs["download_log_dir"] = dirs["log_dir"] / "download"
        dirs["import_log_dir"] = dirs["log_dir"] / "import"
        dirs["carto_log_dir"] = dirs["log_dir"] / "carto"
        dirs["fgb_log_dir"] = dirs["log_dir"] / "fgb"
        dirs["mbtiles_log_dir"] = dirs["log_dir"] / "mbtiles"

        # Create all directories on the filesystem
        for path in dirs.values():
            path.mkdir(parents=True, exist_ok=True)

        dirs["run_id"] = run_id
        dirs["summary_file"] = dirs["log_dir"] / "summary.json"

        return cls(**dirs)


class DataSchema(BaseModel):
    """
    Validates and provides access to the user-defined data schema directory.

    This model ensures that the specified schema directory contains the required
    subdirectories for import, export, and SQL configurations. It provides
    properties to easily access the lists of configuration files within them.

    Attributes:
        base_schema_dir: The root path to the user's schema definition folder.
    """
    base_schema_dir: Path

    @model_validator(mode='after')
    def validate_data_schema_directories(self) -> Self:
        """
        Ensures that all required subdirectories exist within the base schema directory.
        """
        required_subdirectories = [
            self.base_schema_dir / "import",
            self.base_schema_dir / "import" / "osm",
            self.base_schema_dir / "import" / "aux_data",
            self.base_schema_dir / "export",
            self.base_schema_dir / "carto_sql"
        ]
        missing = [str(d) for d in required_subdirectories if not d.exists()]
        if missing:
            error_string = f"The following directories are missing: {', '.join(missing)}"
            raise ValueError(f"Data schema directories are invalid.\n{error_string}\n{DataSchemaErrorMessage}")
        return self
    
    @property
    def aux_import_dir(self) -> Path:
        """Returns the directory where auxiliary data files are located."""
        return self.base_schema_dir / "import" / "aux_data"

    @property
    def imposm_mapping_files(self) -> List[Path]:
        """Returns a list of all 'imposm' mapping files (.yaml or .yml)."""
        imposm_dir = self.base_schema_dir / "import" / "osm"
        mapping_files = list(imposm_dir.glob('*.yaml')) + list(imposm_dir.glob('*.yml'))
        if not mapping_files:
            raise FileNotFoundError(f"No mapping files found in {imposm_dir}")
        return mapping_files

    @property
    def aux_files(self) -> List[Path]:
        """Returns a list of all auxiliary data JSON configuration files."""
        aux_data_dir = self.base_schema_dir / "import" / "aux_data"
        aux_files = list(aux_data_dir.glob('*.json'))
        if not aux_files:
            # This might not be an error if a run doesn't use aux data.
            # Consider changing to a warning or handling it upstream.
            pass
        return aux_files

    @property
    def carto_sql_layers(self) -> List[Path]:
        """Returns a sorted list of all SQL scripts for data transformation."""
        carto_sql_dir = self.base_schema_dir / "carto_sql"
        sql_files = sorted(list(carto_sql_dir.glob('*.sql')))
        if not sql_files:
            raise FileNotFoundError(f"No SQL files found in {carto_sql_dir}")
        return sql_files

    @property
    def carto_execution_plan_path(self) -> Path:
        """Path to the optional carto_sql/execution_plan.yml.

        Declares which carto_sql scripts may run concurrently -- see
        CartoProcessingModel. This is just the conventional path; it may not
        exist (older/other --schema-dir directories won't have one), in
        which case carto falls back to fully sequential execution.
        """
        return self.base_schema_dir / "carto_sql" / "execution_plan.yml"

    @property
    def export_layers(self) -> List[Path]:
        """Returns a list of all tile layer export JSON configuration files."""
        export_layers_dir = self.base_schema_dir / "export"
        export_layers = list(export_layers_dir.glob('*.json'))
        if not export_layers:
            raise FileNotFoundError(f"No export layer JSON files found in {export_layers_dir}")
        return export_layers
