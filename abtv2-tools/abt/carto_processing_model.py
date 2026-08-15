"""
carto_processing_model.py

Defines a Pydantic model responsible for executing a sequence of SQL scripts
against a PostgreSQL database. This model is a core part of the data
transformation process, preparing the raw imported data for subsequent steps
like tile exporting.
"""

from pydantic import BaseModel
from typing import List
from pathlib import Path
from tqdm import tqdm

from .utils.pg_config import PGConfig

class CartoProcessingModel(BaseModel):
    """
    A model that encapsulates the logic for running a series of SQL scripts.

    This model takes a list of SQL file paths and a database configuration,
    providing a simple method to execute them in order.

    Attributes:
        sql_files: A list of Path objects, each pointing to a .sql file.
        pg_config: A PGConfig object with the database connection details.
        log_dir: The directory where logs should be stored.
    """
    sql_files: List[Path]
    pg_config: PGConfig
    log_dir: Path

    def process_sql(self):
        """
        Executes each SQL script in the `sql_files` list sequentially.

        This method iterates through the provided SQL files and runs them
        against the configured PostgreSQL database, displaying a progress

        bar to track completion.
        """
        for sql in tqdm(self.sql_files, desc="Processing Carto SQL"):
            self.pg_config.runSQLScript(sql_script=sql)
