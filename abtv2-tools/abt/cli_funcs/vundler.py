import typer
from typing import Annotated, Optional
from pathlib import Path

from ..vundler_model import VundlerConverter
from ..vundler import convert
from ..utils.fields import (
    working_dir_field,
    max_zoom_field,
    vundler_input_field,
    vundler_output_dir_field,
    num_workers_field,
    default_num_workers,
)


def resolve_input(working_dir: Path, input_path: Optional[Path]) -> Path:
    if input_path is not None:
        return input_path
    bundled_dir = working_dir / "bundled"
    for name in ("joined.mbtiles", "joined.btis"):
        candidate = bundled_dir / name
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"No joined.mbtiles or joined.btis found in {bundled_dir}")


def init_vundler(
    working_dir: Path,
    input_path: Optional[Path] = None,
    output_dir: Optional[Path] = None,
    max_zoom: int = 13,
    num_workers: Optional[int] = None
):
    """Converts a bundled mbtiles file into Esri Compact Cache V2 tile bundles.

    Args:
        working_dir: Root directory for all processing and output files.
        input_path: Source .mbtiles/.btis file. Defaults to the bundler output
            under working_dir/bundled.
        output_dir: Output package directory. Defaults to
            working_dir/bundled/vundled/p12.
        max_zoom: Highest zoom level to convert.
        num_workers: Number of worker threads converting bundles concurrently
            (the abt-vundler binary's own --num-workers). Defaults to one per
            available core (see `default_num_workers`).
    """
    mbtiles_path = resolve_input(working_dir, input_path)
    package_dir = output_dir or working_dir / "bundled" / "vundled" / "p12"

    print(f"--- Converting {mbtiles_path} to {package_dir} ---")
    convert(
        VundlerConverter(
            mbtiles_path=mbtiles_path,
            output_dir=package_dir,
            max_zoom=max_zoom
        ),
        max_workers=num_workers
    )
    print("--- Vundler complete ---")


app = typer.Typer()

@app.command("vundler")
def cli_vundler(
    working_dir: Annotated[Path, working_dir_field],
    input_path: Annotated[Path, vundler_input_field] = None,
    output_dir: Annotated[Path, vundler_output_dir_field] = None,
    max_zoom: Annotated[int, max_zoom_field] = 13,
    num_workers: Annotated[int, num_workers_field] = default_num_workers(divisor=1),
):
    """CLI command to convert a bundled mbtiles file into Esri Compact Cache V2 tile bundles.

    Not a complete .vtpk -- produces the raw tile bundle structure and a bare
    metadata.json only, no conf.xml/root.json/styles.
    """
    try:
        init_vundler(
            working_dir=working_dir,
            input_path=input_path,
            output_dir=output_dir,
            max_zoom=max_zoom,
            num_workers=num_workers
        )
    except Exception as e:
        typer.echo(f"Error during vundler process: {e}. Check logs for details.", err=True)
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
