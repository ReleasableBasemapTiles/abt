"""
aux_data_model.py

Defines Pydantic models for managing auxiliary data sources. These models
structure the entire workflow for an auxiliary data layer, from defining its
source and format to orchestrating its download, extraction, and import into
a PostgreSQL database.
"""

from pydantic import BaseModel, HttpUrl, Field, model_validator
from typing import List, Optional, Any, Union, Tuple
from enum import Enum
import fnmatch
import json
import re
import subprocess
from pathlib import Path
from itertools import chain as iterchain

from .download.downloader import Downloader, DownloadFile, DownloadOverture, Extractor
from .importer.importer import Importer, ImportOGR

class FormatType(Enum):
    """Enumeration for supported auxiliary data formats."""
    GEOPACKAGE = 'gpkg'
    FILEGEODATABASE = 'gdb'
    FLATGEOBUF = 'fgb'
    SHAPEFILE = 'shp'
    OVERTURE = 'overture'
    CSV = 'csv'
    TEXT = 'txt'  # Assumed to be tab/comma separated

class AuxLayer(BaseModel):
    """Represents a single data layer within an auxiliary data source.

    Attributes:
        file_name: The name of the file or layer within the source.
        layer_name: The target table name when imported into the database.
        source_name: The layer name inside the source file. Supports glob patterns
            (e.g. "Department of State LSIB*") to handle versioned layer names.
            Defaults to layer_name when absent.
        load_options: A string of command-line options for OGR.
    """
    file_name: str
    layer_name: str
    source_name: Optional[str] = None
    load_options: Optional[str] = None

    @property
    def ogr_options(self) -> List[str]:
        """Splits the load_options string into a list for OGR commands."""
        return self.load_options.split(' ') if self.load_options else []

    def resolve_source_layer(self, file_path: Path) -> str:
        """Returns the resolved source layer name for ogr2ogr.

        If source_name contains glob wildcards, runs ogrinfo to list layers in
        the file and matches against the pattern. Raises ValueError if zero or
        multiple layers match.
        """
        name = self.source_name if self.source_name is not None else self.layer_name
        if '*' not in name and '?' not in name:
            return name
        result = subprocess.run(
            ['ogrinfo', str(file_path)],
            capture_output=True, text=True, check=True
        )
        layers = []
        for line in result.stdout.splitlines():
            match = re.match(r'^(?:\d+|Layer):\s+(.+?)\s+\(', line.strip())
            if match:
                layers.append(match.group(1))
        matched = fnmatch.filter(layers, name)
        if len(matched) == 1:
            return matched[0]
        elif len(matched) == 0:
            raise ValueError(f"No layers in '{file_path}' matched pattern '{name}'")
        else:
            raise ValueError(f"Pattern '{name}' matched multiple layers in '{file_path}': {matched}")

    def import_filename(self, data_type: FormatType, extraction_folder: Path, zipped: bool) -> Path:
        """Determines the correct path or name for the file to be imported.

        Args:
            data_type: The format of the parent data source.
            extraction_folder: The directory where files have been extracted.
            zipped: Whether the source was a zip archive.

        Returns:
            The path to the specific file or folder needed for import.
        """
        if data_type in (FormatType.FILEGEODATABASE, FormatType.OVERTURE, FormatType.CSV):
            return extraction_folder
        elif data_type == FormatType.TEXT:
            # Rename .txt to .csv for easier processing by OGR.
            original_file_name = extraction_folder / self.file_name
            updated_file_name = original_file_name.with_suffix('.csv')
            if not updated_file_name.exists() and original_file_name.exists():
                original_file_name.rename(updated_file_name)
            return updated_file_name
        else:
            return extraction_folder / self.file_name if zipped else extraction_folder

class AuxDataLayer(BaseModel):
    """Defines a complete auxiliary data source to be downloaded and processed.

    This model contains all the necessary information to handle an auxiliary
    dataset, including its source URL, format, and a list of specific layers
    to be loaded from it.

    Attributes:
        folder_name: A descriptive name for the data source.
        url: The URL from which to download the data.
        type: The format of the data, as defined by FormatType.
        zipped: A boolean indicating if the downloaded file is a zip archive.
        overture_params: Specific parameters for downloading Overture Maps data.
        aux_load: A list of AuxLayer models defining the layers to import.
    """
    folder_name: str
    url: Optional[HttpUrl] = None
    local_path: Optional[Path] = None
    type: FormatType
    zipped: bool
    overture_params: Optional[dict] = None
    aux_load: Optional[List[AuxLayer]] = None

    @model_validator(mode='after')
    def validate_source(self) -> "AuxDataLayer":
        """Ensures exactly one of url or local_path is provided."""
        if self.url is None and self.local_path is None:
            raise ValueError("Either 'url' or 'local_path' must be provided.")
        if self.url is not None and self.local_path is not None:
            raise ValueError("Only one of 'url' or 'local_path' may be provided, not both.")
        return self

    @classmethod
    def from_dict(cls, d: dict) -> "AuxDataLayer":
        """Creates an AuxDataLayer instance from a dictionary."""
        return cls(
            folder_name=d.get('folder_name'),
            url=d.get('url'),
            local_path=d.get('local_path'),
            type=FormatType(d.get('type')),
            zipped=d.get('zipped', False),
            overture_params=d.get('overture_params', None),
            aux_load=[
                AuxLayer(
                    file_name=aux.get("aux_file_name") or aux.get("aux_folder_name"),
                    layer_name=aux.get("aux_layer_name") or aux.get("aux_folder_name"),
                    source_name=aux.get("aux_source_name", None),
                    load_options=aux.get("aux_load_options", None)
                )
                for aux in d.get('aux_load', [])
            ]
        )

    @classmethod
    def from_file(cls, f: Path) -> "AuxDataLayer":
        """Creates an AuxDataLayer instance from a JSON file path."""
        d = json.loads(f.read_text())
        if 'local_path' in d:
            # Resolve relative to schema_dir/static_data/
            # f is at schema_dir/import/aux_data/<name>.json
            schema_dir = f.parent.parent.parent
            d['local_path'] = str(schema_dir / d['local_path'])
        return cls.from_dict(d)

    @property
    def is_local(self) -> bool:
        """Returns True if this layer uses a local file rather than a remote URL."""
        return self.local_path is not None

    @property
    def dl_cls(self) -> Union[DownloadFile, DownloadOverture]:
        """Returns the appropriate downloader class based on the data type."""
        if self.is_local:
            raise ValueError(f"Layer '{self.folder_name}' uses a local_path — download is not applicable.")
        if self.type != FormatType.OVERTURE:
            return DownloadFile(url=self.url)
        else:
            return DownloadOverture(theme=self.overture_params.get('theme'), type=self.overture_params.get('type'))

    @property
    def download_filename(self) -> str:
        """Determines the local filename for the downloaded data."""
        if self.is_local:
            raise ValueError(f"Layer '{self.folder_name}' uses a local_path — download_filename is not applicable.")
        if self.type != FormatType.OVERTURE:
            return self.url.path.split("/")[-1]
        else:
            return self.folder_name

    def init_download(self, output_directory: Path, log_dir: Path) -> Downloader:
        """Initializes a Downloader instance for this data layer.

        Args:
            output_directory: The directory where the file will be saved.
            log_dir: The directory for storing download logs.

        Returns:
            A configured Downloader instance.
        """
        return Downloader(
            downloader=self.dl_cls,
            output_dir=output_directory,
            filename=self.download_filename,
            log_dir=log_dir,
        )

    def extraction_folder(self, output_directory: Path) -> Path:
        """Determines and creates the folder for extracted files.

        For local_path layers, returns the resolved local file path directly —
        no download directory is involved.

        Args:
            output_directory: The base directory where downloads are stored.

        Returns:
            The path to the folder where files will be or have been extracted.
        """
        if self.is_local and not self.zipped:
            return self.local_path
        if self.zipped:
            if self.type == FormatType.FILEGEODATABASE:
                extraction_folder = output_directory / f"{self.folder_name}_extracted.gdb"
            else:
                extraction_folder = output_directory / f"{self.folder_name}_extracted"
            extraction_folder.mkdir(parents=True, exist_ok=True)
        else:
            # If not zipped, the "extraction folder" is just the file itself.
            extraction_folder = output_directory / self.download_filename
        return extraction_folder

    def init_extraction(self, output_directory: Path) -> Optional[Extractor]:
        """Initializes an Extractor if the data source is zipped.

        Args:
            output_directory: The directory containing the downloaded file.

        Returns:
            A configured Extractor instance, or None if not applicable.
        """
        if self.zipped:
            source = self.local_path if self.is_local else output_directory / self.download_filename
            return Extractor(
                filename=source,
                output_dir=self.extraction_folder(output_directory),
            )
        return None

    @staticmethod
    def importer_cmd_prefix(pg_string: str) -> List[str]:
        """Builds the base command for an ogr2ogr import.

        Args:
            pg_string: The PostgreSQL connection string.

        Returns:
            A list of strings representing the start of an ogr2ogr command.
        """
        return [
            'ogr2ogr',
            '-f', 'PostgreSQL',
            f'PG:{pg_string}',
            "-nln"  # Assign new layer name
        ]

    def init_importer(
        self,
        output_directory: Path,
        log_dir: Path,
        pg_string: str,
        bbox: Optional[Tuple[float, float, float, float]] = None
    ) -> List[Importer]:
        """Initializes Importer instances for each specified sub-layer.

        Constructs the full ogr2ogr command for each layer defined in `aux_load`.

        Args:
            output_directory: The directory containing the extracted data.
            log_dir: The directory for storing import logs.
            pg_string: The PostgreSQL connection string.
            bbox: Optional WGS84 (xmin, ymin, xmax, ymax) filter, reprojected
                from EPSG:4326 as needed. When given, each layer's import is
                both pre-filtered (`-spat`, skips features entirely outside
                the box) and actually clipped to it (`-clipsrc spat_extent`,
                reuses the -spat box as a clip geometry) -- the clip matters
                for layers like a global dissolved ocean polygon, where a
                single feature's own bbox always intersects any query box, so
                `-spat` alone wouldn't shrink anything.

        Returns:
            A list of configured Importer instances.
        """
        spat_flags = (
            ['-spat_srs', 'EPSG:4326', '-spat', *map(str, bbox), '-clipsrc', 'spat_extent']
            if bbox else []
        )
        importers = []
        for aux in self.aux_load:
            aux_filename = aux.import_filename(
                data_type=self.type,
                extraction_folder=self.extraction_folder(output_directory=output_directory),
                zipped=self.zipped
            )

            if self.type == FormatType.FILEGEODATABASE:
                # GDAL's OpenFileGDB driver has a spatial-index bug (confirmed via
                # ogrinfo/ogr2ogr, not bypassable via GDAL config options) that
                # hard-fails a -spat-filtered read of some .gdb layers. Convert to
                # an intermediate FlatGeobuf unfiltered first (which works), and
                # import from that instead of the raw .gdb -- always, not just
                # under a clip, since there's no way to know ahead of time which
                # layers' indexes are affected.
                source_layer = aux.resolve_source_layer(aux_filename)
                intermediate = output_directory / f"{aux.layer_name}.fgb"
                # FlatGeobuf doesn't support DeleteLayer(), so -overwrite can't replace
                # an existing output file -- delete it ourselves first instead.
                intermediate.unlink(missing_ok=True)
                subprocess.run(
                    ['ogr2ogr', '-f', 'FlatGeobuf', *aux.ogr_options,
                     str(intermediate), str(aux_filename), source_layer],
                    check=True
                )
                cmd_aux_chain = iterchain(
                    [f"aux_data.{aux.layer_name}"],
                    spat_flags,
                    aux.ogr_options,
                    [str(intermediate)]
                )
            elif self.type == FormatType.GEOPACKAGE:
                source_layer = aux.resolve_source_layer(aux_filename)
                cmd_aux_chain = iterchain(
                    [f"aux_data.{aux.layer_name}"],  # Target table name
                    spat_flags,
                    aux.ogr_options,
                    [str(aux_filename), source_layer]  # Source file and source layer
                )
            else:
                cmd_aux_chain = iterchain(
                    [f"aux_data.{aux.layer_name}"],
                    spat_flags,
                    aux.ogr_options,
                    [str(aux_filename)]
                )
            
            cmd = self.importer_cmd_prefix(pg_string=pg_string) + list(cmd_aux_chain)
            
            importers.append(
                Importer(
                    importer=ImportOGR(cmd=cmd),
                    layer=aux.layer_name,
                    log_dir=log_dir
                )
            )
        return importers
