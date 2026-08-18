"""
osm_data_model.py

Defines Pydantic models and helper functions for managing the download and
import of OpenStreetMap (OSM) data. This includes fetching data sources from
GeoFabrik, managing 'imposm' mapping configurations, and orchestrating the
download and import processes.
"""

from pydantic import BaseModel, HttpUrl, field_validator, model_validator
from typing import List, Optional, Dict, Tuple
from typing_extensions import Self
import requests
import json
from pathlib import Path
import yaml

from .download.downloader import Downloader, DownloadFile, DownloadAria2
from .download.planet_mirrors import discover_planet_sources
from .importer.importer import Importer, ImportImposm
from .schema import DataSchema, ProcessingDirectorySchema

PLANET_IDENTIFIER = "planet"


def _geometry_bbox(geometry: Dict) -> Tuple[float, float, float, float]:
    """Computes a (xmin, ymin, xmax, ymax) envelope from GeoJSON coordinates."""
    def flatten(coords):
        if isinstance(coords[0], (int, float)):
            yield coords
        else:
            for c in coords:
                yield from flatten(c)

    xs, ys = zip(*((x, y) for x, y, *_ in flatten(geometry["coordinates"])))
    return (min(xs), min(ys), max(xs), max(ys))


def getGeoFabrikIndex() -> Dict[str, "OSMData"]:
    """Fetches the official GeoFabrik index of available OSM extracts.

    This function retrieves a JSON index from GeoFabrik, which lists all
    available country and regional OSM data extracts in PBF format. It also
    manually adds an entry for the full planet file.

    Returns:
        A dictionary where keys are region identifiers (e.g., 'thailand') and
        values are configured OSMData objects.
    """
    url = "https://download.geofabrik.de/index-v1.json"
    r = requests.get(url)
    raw = r.json()
    features = raw["features"]

    return_dict = {}
    for f in features:
        properties = f['properties']
        identifier = properties.get('id')
        if identifier and 'urls' in properties and 'pbf' in properties['urls']:
            return_dict[identifier] = OSMData(
                identifier=identifier,
                pbf_location=properties["urls"]["pbf"],
                diff_location=properties["urls"].get("updates"),
                bbox=_geometry_bbox(f["geometry"]) if f.get("geometry") else None
            )

    return_dict[PLANET_IDENTIFIER] = OSMData(
        identifier=PLANET_IDENTIFIER,
        pbf_location="https://planet.openstreetmap.org/pbf/planet-latest.osm.pbf",
        diff_location="https://planet.openstreetmap.org/replication/changesets/"
    )

    return return_dict


def resolve_osm_data(osm_index: str) -> "OSMData":
    """Looks up a GeoFabrik/planet key in the index, raising a clear error if unknown."""
    osm_data = getGeoFabrikIndex().get(osm_index)
    if osm_data is None:
        raise ValueError(
            f"Unknown OSM key '{osm_index}'. Expected a GeoFabrik extract id "
            "(e.g. 'liechtenstein') or 'planet'."
        )
    return osm_data


def get_osm_bbox(osm_index: str) -> Optional[Tuple[float, float, float, float]]:
    """Looks up the (xmin, ymin, xmax, ymax) WGS84 extent for a GeoFabrik key.

    Returns None for 'planet' or any extract with no usable geometry, since
    there's no meaningful bounding box to clip aux data against.
    """
    return resolve_osm_data(osm_index).bbox


class ImposmMappingFile(BaseModel):
    """Represents a single 'imposm' mapping configuration loaded from a YAML file.

    This model validates that the mapping file contains the essential 'imposm' keys.

    Attributes:
        table: The name of the target database table, derived from the YAML filename.
        data: The raw dictionary content of the mapping configuration for the table.
    """
    table: str
    data: Dict

    @model_validator(mode='after')
    def validate_mapping_data(self) -> Self:
        """Ensures the mapping data contains required 'imposm' fields."""
        if not all(k in self.data for k in ['columns', 'mapping', 'type']):
            raise ValueError(
                f"The imposm file for {self.table} is missing required elements "
                "(columns, mapping, type) or has typos."
            )
        return self

    @classmethod
    def from_yaml(cls, yaml_path: Path) -> "ImposmMappingFile":
        """Loads and parses an 'imposm' mapping from a YAML file.

        Args:
            yaml_path: The path to the .yml mapping file.

        Returns:
            An instance of ImposmMappingFile.
        """
        with yaml_path.open(mode='r') as file:
            mapping = yaml.safe_load(file)
            # Assumes the YAML file is structured with the table name as the top-level key
            return cls(table=yaml_path.stem, data=mapping[yaml_path.stem])

    @property
    def load_data(self) -> Dict:
        """Returns the model's data as a dictionary."""
        return self.model_dump()


class ImposmManagement(BaseModel):
    """Manages a collection of 'imposm' mapping files.

    Attributes:
        mapping_files: A list of ImposmMappingFile objects.
    """
    mapping_files: List[ImposmMappingFile]

    @property
    def combined_mapping(self) -> Dict:
        """Combines multiple mapping files into a single dictionary for 'imposm'.

        This property aggregates individual table mappings into the final structure
        required by 'imposm' in its main mapping file.
        """
        return {"tables": {m.table: m.data for m in self.mapping_files}}


class OSMData(BaseModel):
    """Represents a specific OpenStreetMap data extract (e.g., a country or planet).

    Attributes:
        identifier: The unique ID of the extract (e.g., 'thailand', 'planet').
        pbf_location: The URL to the PBF file for a full import.
        diff_location: The URL to the replication service for updates.
        bbox: WGS84 (xmin, ymin, xmax, ymax) envelope of the extract, or None
            for 'planet' (no meaningful bounding box to clip against).
    """
    identifier: str
    pbf_location: HttpUrl
    diff_location: HttpUrl
    bbox: Optional[Tuple[float, float, float, float]] = None

    @property
    def filename(self) -> str:
        """Extracts the filename from the PBF file's URL."""
        return self.pbf_location.path.split('/')[-1]


class OSMProcessingModel(BaseModel):
    """Orchestrates the download and import process for a given OSM dataset.

    This is the central model that holds the configuration for an OSM task,
    manages working directories, and initializes downloader and importer objects.

    Attributes:
        working_directory: The root directory for all OSM-related files (imposm cache,
            downloaded PBF, generated mapping) -- distinct from the run's log directory.
        osm_data: The OSMData object specifying which extract to process.
        imposm_mapping: The combined 'imposm' mapping dictionary.
        download_log_dir: The directory for this run's download-stage logs.
        import_log_dir: The directory for this run's import-stage logs.
    """
    working_directory: Path
    osm_data: OSMData
    imposm_mapping: Dict
    download_log_dir: Path
    import_log_dir: Path

    # --- Directory Properties ---
    @property
    def pbf_directory(self) -> Path:
        """Returns the path to the PBF download directory, creating it if needed."""
        pbf_dir = self.working_directory / "pbf"
        pbf_dir.mkdir(exist_ok=True, parents=True)
        return pbf_dir

    # --- Path and File Properties ---
    @property
    def pbf_out_path(self) -> Path:
        """Returns the full path for the downloaded PBF file."""
        return self.pbf_directory / self.osm_data.filename

    @property
    def imposm_mapping_path(self) -> Path:
        """Returns the path for the generated combined 'imposm' mapping file."""
        return self.working_directory / 'combined_mapping.yaml'

    @property
    def export_imposm_mapping_file(self) -> Path:
        """Writes the combined mapping to a YAML file and returns its path."""
        with self.imposm_mapping_path.open(mode='w') as file:
            yaml.safe_dump(self.imposm_mapping, file, default_flow_style=False)
        return self.imposm_mapping_path

    # --- Initialization Methods ---
    def init_download(self) -> Downloader:
        """Initializes a Downloader instance for the PBF file.

        For the full planet file, this discovers every current mirror via
        `discover_planet_sources` and downloads from all of them at once
        via aria2c (see download/planet_mirrors.py and DownloadAria2) --
        aggregating their bandwidth instead of being capped by a single
        mirror, and mandatorily checksum-verifying the result. Every other
        (Geofabrik) key keeps using the single-URL requests-based
        DownloadFile path, since Geofabrik only ever publishes one URL per
        extract -- there is nothing to mirror-race there.

        Returns:
            A configured Downloader object ready to start the download.
        """
        if self.osm_data.identifier == PLANET_IDENTIFIER:
            urls, md5 = discover_planet_sources(log_dir=self.download_log_dir)
            downloader = DownloadAria2(urls=urls, md5=md5)
        else:
            downloader = DownloadFile(url=self.osm_data.pbf_location)

        return Downloader(
            downloader=downloader,
            output_dir=self.pbf_directory,
            filename=self.osm_data.filename,
            log_dir=self.download_log_dir
        )

    def init_import(self, pg_uri: str, pg_schema: str, diff: bool) -> Importer:
        """Initializes an Importer instance for the OSM data.

        This method configures an 'imposm' importer with the correct paths,
        database URI, and options for either a full or differential import.

        Args:
            pg_uri: The PostgreSQL connection URI.
            pg_schema: The target PostgreSQL schema for imported OSM data.
            diff: A boolean indicating whether to perform a differential update.

        Returns:
            A configured Importer object ready to start the import process.
        """
        importer = Importer(
            importer=ImportImposm(
                mapping=self.export_imposm_mapping_file,
                pbf=self.pbf_out_path,
                pg_uri=pg_uri,
                pg_schema=pg_schema,
                cache_directory=self.working_directory / "imposm_cache",
                diff_directory=self.working_directory / "imposm_diff" if diff else None
            ),
            layer=self.osm_data.filename,
            log_dir=self.import_log_dir
        )
        return importer


def prep_osm(
    data_schema: DataSchema,
    processing_directory: ProcessingDirectorySchema,
    osm_index: str
) -> OSMProcessingModel:
    """Builds an OSMProcessingModel for the given GeoFabrik/planet index.

    Fetches the specified OSM data from the GeoFabrik index, loads the imposm
    mapping files defined in the data schema, and assembles an
    OSMProcessingModel configured for either downloading or importing that data.

    Args:
        data_schema: The data schema configuration containing paths to imposm mapping files.
        processing_directory: The schema for processing directories, specifying where
                              imposm-related files and logs should be stored.
        osm_index: The identifier for the GeoFabrik OSM extract to be used (e.g., 'thailand').

    Returns:
        An OSMProcessingModel instance configured for the specified OSM data.
    """
    osm_data = resolve_osm_data(osm_index)

    imposm_management = ImposmManagement(
        mapping_files=list(
            map(
                lambda y: ImposmMappingFile.from_yaml(yaml_path=y).load_data,
                data_schema.imposm_mapping_files
            )
        )
    )

    return OSMProcessingModel(
        working_directory=processing_directory.osm_dir,
        osm_data=osm_data,
        imposm_mapping=imposm_management.combined_mapping,
        download_log_dir=processing_directory.download_log_dir,
        import_log_dir=processing_directory.import_log_dir
    )

