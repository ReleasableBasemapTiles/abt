"""
abt-tools.py

This script serves as the main entry point for the Army Basemap Tiles (ABT)
command-line interface (CLI) application. It aggregates various sub-commands
for downloading, importing, processing, and exporting geographic data
into a unified CLI tool using the Typer framework.
"""

import typer

# from abt.cli_funcs import *
# Import individual CLI applications/commands from their respective modules
from abt.cli_funcs import (
    download,       # Handles data download operations
    import_to_pg,   # Manages data import into PostgreSQL
    run_carto,      # Executes SQL cartographic processing scripts
    export_tiles,   # Exports processed data into tile formats (e.g., MBTiles)
    bundler,         # Bundles multiple tile sets into a single MBTiles file
    vundler,         # Converts a bundled mbtiles file into Esri Compact Cache V2 tile bundles
    import_aux_single
)
from abt.utils.rlimit import raise_open_file_limit

# Initialize the main Typer application
# add_completion=False is used to prevent Typer from generating shell completion scripts
app = typer.Typer(add_completion=False)


@app.callback()
def cli_root() -> None:
    """Army Basemap Tiles (ABT) data pipeline tools."""
    # Raised here rather than per-command so no command can be left out:
    # every one of them shells out to a tool that inherits this process's
    # limit, and tippecanoe scales its descriptor use to the host's core
    # count -- see raise_open_file_limit. Reported on stderr to keep it out
    # of any command's own output.
    previous_soft, current_soft = raise_open_file_limit()
    typer.echo(f"--- Open file limit: {current_soft} (was {previous_soft}) ---", err=True)


# Add each sub-application (defined in separate modules) to the main Typer app.
# This makes their commands accessible through the main CLI.
# For example, 'abt download ...', 'abt import ...', etc.
app.add_typer(download.app)
app.add_typer(import_to_pg.app)
app.add_typer(run_carto.app)
app.add_typer(export_tiles.app)
app.add_typer(bundler.app)
app.add_typer(vundler.app)
app.add_typer(import_aux_single.app)

if __name__ == "__main__":
    # When the script is run directly, start the Typer application.
    # This parses command-line arguments and dispatches to the appropriate command.
    app()
