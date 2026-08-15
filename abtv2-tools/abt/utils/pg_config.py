"""
pg_config.py

This module provides a Pydantic-based configuration model, `PGConfig`, for
managing PostgreSQL database connections. It offers methods to create connection
configurations from environment variables or direct input, and includes utilities
for testing the connection, resetting schemas, and executing SQL scripts.
"""

import os
from typing import List, Tuple
from pydantic import BaseModel
import psycopg2
from pathlib import Path
import logging


class PGConfig(BaseModel):
    """
    Manages PostgreSQL database connection parameters and provides interaction methods.

    This model stores connection details and offers convenient properties to generate
    various connection string formats (psycopg2, standard URI, PostGIS URI). It also
    includes methods to execute SQL commands and manage database schemas.

    Attributes:
        host: The database host address.
        port: The database port.
        user: The username for the database connection.
        password: The password for the database user.
        database: The name of the database to connect to.
        log_path: The directory where logs for this connection will be stored.
    """
    host: str
    port: int
    user: str
    password: str
    database: str
    log_path: Path
    extra_options: str = ""

    @classmethod
    def from_env(cls, log_path: Path) -> "PGConfig":
        """
        Creates a PGConfig instance from standard PostgreSQL environment variables.

        Reads PGHOST, PGPORT, PGUSER, PGPASSWORD, and PGDATABASE from the environment.

        Args:
            log_path: The path to the directory for storing logs.

        Returns:
            A configured PGConfig instance.

        Raises:
            ValueError: If any of the required environment variables are not set.
        """
        env_vars = {
            "host": os.getenv("PGHOST"),
            "port": os.getenv("PGPORT"),
            "user": os.getenv("PGUSER"),
            "password": os.getenv("PGPASSWORD"),
            "database": os.getenv("PGDATABASE"),
        }
        if not all(env_vars.values()):
            missing = [k.upper() for k, v in env_vars.items() if not v]
            raise ValueError(
                f"Missing required environment variables: {', '.join(missing)}."
            )
        return cls(**env_vars, log_path=log_path)

    @classmethod
    def from_input(cls, host: str, port: str, user: str, password: str, database: str, log_path: Path) -> "PGConfig":
        """
        Creates a PGConfig instance from direct string inputs.

        Args:
            host: The database host.
            port: The database port.
            user: The database username.
            password: The database password.
            database: The database name.
            log_path: The path to the directory for storing logs.

        Returns:
            A configured PGConfig instance.
        """
        return cls(
            host=host, port=port, user=user, password=password, database=database, log_path=log_path
        )

    @property
    def conn_str(self) -> str:
        """Returns the connection string in the format required by psycopg2."""
        base = f"host={self.host} port={self.port} user='{self.user}' password='{self.password}' dbname='{self.database}'"
        if not self.extra_options:
            return base
        # Same 'options=<libpq -c key=value ...>' shape carto_sql's own dblink
        # connstrs use, so a session opened this way starts with those GUCs
        # already set -- no separate SET statement needed after connecting.
        escaped = self.extra_options.replace("'", "''")
        return f"{base} options='{escaped}'"

    def with_options(self, extra_options: str) -> "PGConfig":
        """Returns a copy of this config that opens connections with extra
        libpq '-c key=value' startup options (e.g. to scale down a carto
        group's GUCs for concurrent execution -- see CartoProcessingModel).
        Leaves this instance untouched.
        """
        return self.model_copy(update={"extra_options": extra_options})

    @property
    def uri(self) -> str:
        """Returns a standard PostgreSQL connection URI."""
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"

    @property
    def pguri(self) -> str:
        """Returns a PostGIS-style connection URI, often used by external tools."""
        return f"postgis://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"

    @property
    def conn(self) -> psycopg2.extensions.connection:
        """Establishes and returns a new psycopg2 database connection."""
        return psycopg2.connect(self.conn_str)

    # --- Schema Properties ---
    @property
    def osm_schema(self) -> str:
        """The name of the schema for OSM data (defaults to 'osm')."""
        return "osm"
    
    @property
    def osm_populated(self) -> bool:
        """Indicates whether the OSM schema is expected to be populated with data."""
        with self.conn as conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = '{self.osm_schema}' AND table_name NOT IN ('spatial_ref_sys', 'geography_columns','geometry_columns'))")
                return cur.fetchone()[0]
    @property
    def aux_schema(self) -> str:
        """The name of the schema for auxiliary data."""
        return "aux_data"

    @property
    def export_schema(self) -> str:
        """The name of the schema for final data to be exported."""
        return "export"

    def get_logger(self) -> logging.Logger:
        """Initializes and returns a logger specific to this database configuration."""
        logger = logging.getLogger(f"pg_config_{self.database}")
        if not logger.handlers:
            logger.setLevel("INFO")
            formatter = logging.Formatter("[%(asctime)s | %(levelname)s] %(message)s")
            handler = logging.FileHandler(self.log_path / f"{self.database}_pgconfig.log")
            handler.setFormatter(formatter)
            handler.setLevel("INFO")
            logger.addHandler(handler)
        return logger

    def reset_aux_schema(self):
        """Drops the auxiliary schema if it exists and recreates it."""
        logger = self.get_logger()
        logger.info(f"Resetting auxiliary schema '{self.aux_schema}'...")
        with self.conn as conn:
            with conn.cursor() as cur:
                cur.execute(f"DROP SCHEMA IF EXISTS {self.aux_schema} CASCADE;")
                cur.execute(f"CREATE SCHEMA {self.aux_schema};")
                conn.commit()
        logger.info(f"Schema '{self.aux_schema}' has been reset.")

    def test_sql(self):
        """Runs a simple 'SELECT 1' query to test the database connection."""
        logger = self.get_logger()
        try:
            with self.conn as conn, conn.cursor() as cur:
                cur.execute("SELECT 1;")
                result = cur.fetchone()
                logger.info(f"Test query successful, result: {result}")
        except Exception as e:
            logger.error(f"Error testing PostgreSQL connection: {e}")
            raise

    def execute_sql(self, sql: str, description: str):
        """
        Executes an arbitrary SQL string against the configured database, in
        its own connection/transaction. Used both by runSQLScript (for a
        whole file's contents) and directly for short statements like
        `CREATE SCHEMA IF NOT EXISTS` (see CartoProcessingModel).

        Args:
            sql: The SQL text to execute.
            description: Short label for logging (e.g. a filename).
        """
        logger = self.get_logger()
        logger.info(f"Running SQL: {description}")
        try:
            with self.conn as conn, conn.cursor() as cur:
                cur.execute(sql)
                conn.commit()
            logger.info(f"SQL '{description}' executed successfully.")
        except Exception as e:
            logger.error(f"SQL failed: {description} - {e}")
            raise

    def runSQLScript(self, sql_script: Path):
        """
        Executes a SQL script file against the configured database.

        Args:
            sql_script: The path to the .sql file to be executed.
        """
        self.execute_sql(sql_script.read_text(), description=sql_script.name)
