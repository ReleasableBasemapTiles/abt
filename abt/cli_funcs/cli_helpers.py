from typing import List
from pathlib import Path

from ..utils.pg_config import PGConfig
from ..schema import DataSchema, ProcessingDirectorySchema
from ..export.tile_layer_model import TileLayer

def get_pg_config(cli_input: str, log_dir: Path) -> "PGConfig":
    """Retrieves PostgreSQL configuration based on CLI input.

    This function attempts to load PostgreSQL connection details either from
    environment variables or from a comma-separated string provided directly
    via the CLI.

    Args:
        cli_input: A string indicating how to get the PG config ('env' or a
                   comma-separated string of host,port,user,password,dbname).
        log_dir: The directory for logging connection attempts or errors.

    Returns:
        A PGConfig object containing the PostgreSQL connection parameters.

    Raises:
        Exception: If the provided connection parameters are incorrect or
                   the connection cannot be established.
    """
    if cli_input == 'env':
        pg_config = PGConfig.from_env(log_path=log_dir)
    elif len(cli_input.split(',')) == 5:
        host, port, user, password, dbname = cli_input.split(',')
        pg_config = PGConfig.from_input(
            host=host,
            port=port,
            user=user,
            password=password,
            database=dbname,
            log_path=log_dir
        )
        
        try:
            pg_config.test_sql()
        except Exception as e:
            raise Exception("PG Vars not correct or connection failed.") from e
    else:
        raise ValueError("Invalid cli_input format for PostgreSQL configuration.")
    return pg_config

def get_tile_layers_for_bundler(
    data_schema: DataSchema,
    processing_directory: ProcessingDirectorySchema,
    pg_config: PGConfig
) -> List[TileLayer]:
    """Prepares a list of TileLayer objects for the tile bundler.

    This function iterates through the export layers defined in the data schema
    and initializes a TileLayer object for each, configuring them with paths
    to various processing directories and the PostgreSQL connection.

    Args:
        data_schema: The data schema containing definitions for exportable layers.
        processing_directory: The schema for various working directories
                              (MBTiles, FlatGeobuf, temporary, logs).
        pg_config: The PostgreSQL configuration object.

    Returns:
        A list of configured TileLayer instances ready for bundling.
    """
    return list(
        map(
            lambda t: TileLayer.from_file(
                path=t,
                max_detail_const=5, # This parameter is explicitly noted as not necessary for the bundler in your code.
                pg_config=pg_config,
                mbtiles_dir=processing_directory.mbtiles_dir,
                flatgeobuf_dir=processing_directory.flatgeobuf_dir,
                tmp_dir=processing_directory.tmp_dir,
                log_dir=processing_directory.mbtiles_log_dir
            ),
            data_schema.export_layers
        )
    )
