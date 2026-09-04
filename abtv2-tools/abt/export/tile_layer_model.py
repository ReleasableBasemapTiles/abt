"""
tile_layer_model.py

Defines the Pydantic data models for the vector tile export process: a
TileLayer's structure and command-string builders for `ogr2ogr`/`tippecanoe`.
Actually running these commands and writing output happens in
export/exporter.py. The Bundler model (`tile-join` stage) lives in
export/bundler_model.py.
"""

import json
from pathlib import Path
from pydantic import BaseModel, Field
from typing import Optional, List, Annotated
from enum import Enum

from ..utils.pg_config import PGConfig


class AttributeTypes(Enum):
    """Enumeration for supported attribute data types in a tile layer."""
    STRING = "string"
    FLOAT = "float"
    INTEGER = "int"
    BOOLEAN = "bool"


class GeometryTypes(Enum):
    """Enumeration for supported geometry types."""
    POLYGON = "polygon"
    LINESTRING = "linestring"
    POINT = "point"


class TippecanoeOptions(BaseModel):
    """Defines and validates options for the 'tippecanoe' tool.

    Attributes:
        minimum_zoom: The minimum zoom level at which to generate tiles.
        maximum_zoom: The maximum zoom level at which to generate tiles.
        max_detail_const: The zoom level at which to preserve all feature detail.
        additional_flags: A string of any other 'tippecanoe' flags to include.
        filter: A JSON filter to apply to features.
    """
    minimum_zoom: Annotated[int, Field(strict=True, ge=0, le=24)]
    maximum_zoom: Annotated[int, Field(strict=True, gt=0, le=24)]
    max_detail_const: Annotated[int, Field(strict=True, gt=0, le=15)]
    additional_flags: Optional[str] = ""
    filter: Optional[dict] = {}

    @property
    def zoom_flags(self) -> List[str]:
        """Generates the zoom level flags (-Z and -z) for 'tippecanoe'."""
        # Cap max zoom at max_detail_const to prevent over-tiling
        max_zoom = min(self.maximum_zoom, self.max_detail_const)
        # Ensure min zoom never exceeds max zoom (e.g. if a layer's minimum_zoom
        # is configured higher than the pipeline's max_detail_const)
        min_zoom = min(self.minimum_zoom, max_zoom)
        return [f"-Z{min_zoom}", f"-z{max_zoom}"]

    @property
    def detail_flag(self) -> str:
        """Generates the detail flag (--extra-detail) for 'tippecanoe'."""
        # Use a higher detail level for zooms beyond the max detail constant
        detail = min(self.maximum_zoom + 1, self.max_detail_const + 1)
        return f"--extra-detail={detail}"

    @property
    def tippecanoe_flags(self) -> List[str]:
        """Splits the additional_flags string into a list for the command."""
        return self.additional_flags.split(" ") if self.additional_flags else []
    
    @property
    def tippecanoe_filter_argument(self) -> List[str]:
        """Constructs the JSON filter argument (-j) for 'tippecanoe'."""
        return ["-j", json.dumps(self.filter)] if self.filter else []


class OGRExportOptions(BaseModel):
    """Defines options for the 'ogr2ogr' tool.

    Attributes:
        additional_flags: A string of any other 'ogr2ogr' flags to include.
    """
    additional_flags: Optional[str] = ""

    @property
    def ogr_flags(self) -> List[str]:
        """Splits the additional_flags string into a list for the command."""
        return self.additional_flags.split(" ") if self.additional_flags else []


class TileLayerAttributes(BaseModel):
    """Defines an attribute within a vector tile layer.

    Attributes:
        name: The name of the attribute field.
        type: The data type of the attribute.
        description: A description of the attribute.
    """
    name: str
    type: AttributeTypes = AttributeTypes.STRING
    description: str = ""


class TileLayer(BaseModel):
    """
    The central model for defining and processing a single vector tile layer.

    This class orchestrates the entire export process for one layer, from
    defining its source SQL to generating the final `ogr2ogr` and `tippecanoe`
    commands.

    Attributes:
        layer_id: The unique identifier for the layer.
        geometry_type: The type of geometry in the layer.
        attributes: A list of attributes to include in the tiles.
        pg_config: The PostgreSQL database connection configuration.
        flatgeobuf_dir: The directory to save intermediate FlatGeobuf files.
        mbtiles_dir: The directory to save final MBTiles files.
        tmp_dir: A directory for temporary processing files.
        log_dir: A directory for logs.
    """
    layer_id: str
    description: Optional[str] = ""
    geometry_type: GeometryTypes
    attributes: Optional[List[TileLayerAttributes]] = []
    source_attribution: str = ""
    tippecanoe_options: Optional[TippecanoeOptions] = None
    ogr_export_options: Optional[OGRExportOptions] = None
    pg_config: PGConfig
    flatgeobuf_dir: Path
    mbtiles_dir: Path
    tmp_dir: Path
    log_dir: Path
    projection_override: Optional[str] = None

    @classmethod
    def from_dict(cls, data: dict, max_detail_const: int, pg_config:PGConfig,flatgeobuf_dir:Path,mbtiles_dir:Path,tmp_dir:Path,log_dir:Path, projection_override: Optional[str] = None) -> "TileLayer":
        """Creates a TileLayer instance from a dictionary and runtime arguments.

        A layer JSON that omits "tippecanoe_options"/"ogr_export_options"
        entirely is treated the same as an explicit empty `{}` for that
        key -- both build options from defaults -- rather than leaving the
        field `None`, which `tippecanoe_cmd`/`ogr_cmd` can't handle (they
        unconditionally dereference `self.tippecanoe_options`/
        `self.ogr_export_options`).
        """
        tc = data.get("tippecanoe_options") or {}
        tippecanoe_options = TippecanoeOptions(
            minimum_zoom=tc.get("minimum_zoom", 0),
            maximum_zoom=tc.get("maximum_zoom", max_detail_const),
            additional_flags=tc.get("additional_flags", ""),
            filter=tc.get("filter", {}),
            max_detail_const=max_detail_const,
        )
        ogr_export_options = OGRExportOptions(
            additional_flags=(data.get("ogr_export_options") or {}).get("additional_flags", "")
        )
        return TileLayer(
            layer_id=data.get("layer_id"),
            description=data.get("description", ""),
            geometry_type=data.get("geometry_type"),
            attributes=[
                TileLayerAttributes(
                    name=attr.get("name"),
                    type=attr.get("type", "string"),
                    description=attr.get("description", "")
                )
                for attr in data.get("attributes")
            ] if data.get("attributes") else [],
            source_attribution=data.get("source_attribution", ""),
            tippecanoe_options=tippecanoe_options,
            ogr_export_options=ogr_export_options,
            pg_config=pg_config,
            flatgeobuf_dir=flatgeobuf_dir,
            mbtiles_dir=mbtiles_dir,
            tmp_dir=tmp_dir,
            log_dir=log_dir,
            projection_override=projection_override
        )
    @classmethod
    def from_file(cls, path: Path, max_detail_const: int,pg_config:PGConfig, flatgeobuf_dir:Path,mbtiles_dir:Path,tmp_dir:Path,log_dir:Path, projection_override: Optional[str] = None) -> "TileLayer":
        return cls.from_dict(
            data=json.loads(path.read_text()),
            max_detail_const=max_detail_const,
            pg_config=pg_config,
            flatgeobuf_dir=flatgeobuf_dir,
            mbtiles_dir=mbtiles_dir,
            tmp_dir=tmp_dir,
            log_dir=log_dir,
            projection_override=projection_override
        )
    @property
    def name(self) -> str:
        """Alias for layer_id, used by ParallelExecutor for per-task reporting."""
        return self.layer_id

    @property
    def tippecanoe_flags(self) -> List[str]:
        return self.tippecanoe_options.tippecanoe_flags
    @property
    def tippecanoe_filter_argument(self) -> List[str]:
        return self.tippecanoe_options.tippecanoe_filter_argument
    @property
    def tippecanoe_attributes(self) -> List:
        if self.attributes:
            return " ".join([f"-y {i.name}" for i in self.attributes]).split(" ")
        else:
            return ["-X"]
    @property
    def tippecanoe_attribute_types(self) -> List:
        if self.attributes:
            return " ".join([f"-T {i.name}:{i.type.value}" for i in self.attributes]).split(" ")
        else:
            return []
    @property
    def tippecanoe_detail_flag(self) -> List[str]:
        return self.tippecanoe_options.detail_flag
    @property
    def projection_override_epsg_code(self) -> Optional[int]:
        """Numeric EPSG code from `projection_override` (e.g. "EPSG:3395" -> 3395)."""
        if self.projection_override is None:
            return None
        return int(self.projection_override.split(":")[1])

    @property
    def is_projection_override_active(self) -> bool:
        """
        True when a non-default (non-Web-Mercator) projection override is in
        effect. Explicitly requesting EPSG:3857 is treated the same as not
        passing an override at all, since that's already tippecanoe's default
        and produces spec-conformant output.
        """
        return self.projection_override_epsg_code is not None and self.projection_override_epsg_code != 3857

    @property
    def geometry_column_sql(self) -> str:
        """
        The `geometry` column expression for the export SQL. Reprojects to the
        override EPSG code when active, so tippecanoe can be told (falsely)
        that it's receiving EPSG:3857 -- see `is_projection_override_active`.
        """
        if self.is_projection_override_active:
            return f"ST_Transform(geometry, {self.projection_override_epsg_code}) AS geometry"
        return "geometry"

    @property
    def view_columns(self) -> str:
        if self.attributes:
            return ", ".join([f'"{i.name}"' for i in self.attributes] + [self.geometry_column_sql])
        else:
            return self.geometry_column_sql
    # Exporter - Flatgeobuf
    @property
    def ogr_sql(self) -> str:
        return f'SELECT {self.view_columns} FROM {self.pg_config.export_schema}."{self.layer_id}" WHERE geometry IS NOT NULL AND NOT ST_IsEmpty(geometry)'

    @property
    def ogr_tmp_path(self) -> str:
        tmp_ogr_path = self.tmp_dir / f"{self.layer_id}_ogr_tmp"
        tmp_ogr_path.mkdir(parents=True, exist_ok=True)
        return f"TEMPORARY_DIR={str(tmp_ogr_path)}"
    @property
    def ogr_export_filename(self) -> Path:
        return self.flatgeobuf_dir / f"{self.layer_id}.fgb"
    @property
    def ogr_cmd(self) -> List[str]:
        return [
            "ogr2ogr",
            "-f","FlatGeobuf",
            "-sql",self.ogr_sql,
            "-lco",self.ogr_tmp_path,
            *self.ogr_export_options.ogr_flags,
            str(self.ogr_export_filename),
            f"PG:{self.pg_config.uri}",
        ]
        
    # Exporter - Mbtiles
    @property
    def mbtiles_export_filename(self) -> Path:
        return self.mbtiles_dir / f"{self.layer_id}.mbtiles"
    @property
    def mbtiles_tmp_dir(self) -> Path:
        tmp_dir = self.tmp_dir / f"{self.layer_id}"
        return tmp_dir
    @property
    def tippecanoe_cmd(self) -> List[str]:
        cmd = [
            "tippecanoe",
            *self.tippecanoe_options.zoom_flags,
            "--output",
            str(self.mbtiles_export_filename),
            "--temporary-directory",
            str(self.tmp_dir.absolute()),
            "--progress-interval",
            "300",
            "--layer",
            self.layer_id,
            "--no-feature-limit",
            "--no-tile-size-limit",
            self.tippecanoe_detail_flag,
            *self.tippecanoe_flags,
            *self.tippecanoe_attributes,
            *self.tippecanoe_attribute_types,
            *self.tippecanoe_filter_argument,
            *(["-s", "EPSG:3857"] if self.is_projection_override_active else []),
            str(self.ogr_export_filename)
        ]
        # Filter empty strings that can arise from trailing spaces in additional_flags
        return [x for x in cmd if x != ""]

    # Validation Methods

    def does_table_exist(self, pg_config:PGConfig) -> bool:
        sql = f"SELECT to_regclass('{pg_config.export_schema}.{self.layer_id}') IS NOT NULL AS table_exists"
        with pg_config.conn as conn:
            cur = conn.cursor()
            cur.execute(sql)
            return cur.fetchone()[0]
    def count_features(self,pg_config:PGConfig) -> Optional[int]:
        """Returns the feature count, or None if the table doesn't exist.

        None (rather than the previous sentinel of False) is used
        specifically so a genuinely empty table (count 0, falsy) and a
        missing table (None) stay distinguishable by identity rather than
        truthiness -- see layer_summary, which used to report both as
        "does not exist".
        """
        if not self.does_table_exist(pg_config=pg_config):
            return None
        sql = f"WITH tile_layer AS ({self.ogr_sql}) SELECT count(*) FROM tile_layer;"
        with pg_config.conn as conn:
            cur = conn.cursor()
            cur.execute(sql)
            return cur.fetchone()[0]

    def layer_summary(self, pg_config:PGConfig) -> str:
        count=self.count_features(pg_config=pg_config)
        if count is None:
            print(f"Layer: {self.layer_id} does not exist")
        else:
            print(f"Layer: {self.layer_id}")
            print(f"  Export SQL:     {self.ogr_sql}")
            print(f"  Feature Count:  {str(count)}")
        return
