import typer
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Annotated, List, Optional
from pathlib import Path

from pydantic import BaseModel

from ..schema import DataSchema, ProcessingDirectorySchema
from ..aux_data_model import AuxDataLayer
from ..osm_data_model import OSMProcessingModel, prep_osm
from ..parallel import ParallelExecutor
from ..utils.run_reporter import RunReporter, run_stages
from ..download.downloader import Downloader, Extractor
from ..utils.fields import (
    working_dir_field,
    schema_dir_field,
    data_type_field,
    CliDataType,
    num_workers_field,
    osm_key_field,
    default_num_workers,
)

class AuxDownloadTask(BaseModel):
    """One auxiliary source's download, then its extraction if it's zipped,
    as a single task, so each source is extracted as soon as its own
    download finishes. A local source has no download step and an unzipped
    one no extraction step.

    Attributes:
        name: The task's name in logs and the run summary: the downloaded
            file's name, or a local source's zip name.
        downloader: Fetches the source, or None for a local source.
        extractor: Unpacks the zip, or None if the source isn't zipped.
    """
    name: str
    downloader: Optional[Downloader] = None
    extractor: Optional[Extractor] = None

    def run(self, reporter: RunReporter) -> None:
        """Runs the steps, recording them as the download and
        aux_extraction stages -- see run_stages. An extraction whose
        download failed is recorded as not attempted."""
        steps = []
        if self.downloader is not None:
            steps.append(("download", self.downloader.download))
        if self.extractor is not None:
            steps.append(("aux_extraction", self.extractor.extract))
        run_stages(task=self.name, stages=steps, reporter=reporter)


def prep_aux(
    data_schema: DataSchema,
    processing_directory: ProcessingDirectorySchema,
) -> List[AuxDownloadTask]:
    """Prepares the auxiliary data sources for downloading.

    Reads every import/aux_data/*.json config and builds one AuxDownloadTask
    per source that has anything to fetch or unpack: every remote source,
    plus local ones that are zipped.

    Args:
        data_schema: The data schema configuration containing paths to auxiliary data files.
        processing_directory: The schema for processing directories where auxiliary
                              data will be downloaded.

    Returns:
        The tasks, in config order.
    """
    tasks = []
    for layer in map(AuxDataLayer.from_file, data_schema.aux_files):
        if layer.is_local and not layer.zipped:
            continue
        downloader = None if layer.is_local else layer.init_download(
            output_directory=processing_directory.aux_download_dir,
            log_dir=processing_directory.download_log_dir
        )
        extractor = layer.init_extraction(processing_directory.aux_download_dir)
        name = downloader.name if downloader is not None else extractor.name
        tasks.append(AuxDownloadTask(name=name, downloader=downloader, extractor=extractor))
    return tasks


def download_osm(osm_processing: OSMProcessingModel, reporter: RunReporter) -> None:
    """Downloads the OSM extract, recording the outcome in the download
    stage. A failure is recorded and printed, not raised, so the aux
    downloads running alongside it carry on."""
    print("--- Downloading OSM data ---")
    try:
        run_stages(
            task=osm_processing.osm_data.filename,
            stages=[("download", lambda: osm_processing.init_download().download())],
            reporter=reporter,
        )
        print("--- OSM download complete ---")
    except Exception as e:
        print(f"--- OSM download failed: {e} ---")

def init_downloader(working_dir: Path, schema_dir: Path, data_type: CliDataType, num_workers: int, osm_key: str):
    """Initializes and runs the data download process.

    Orchestrates the download of OpenStreetMap (OSM) data, auxiliary data, or both,
    based on the specified data_type. The OSM extract downloads on a thread
    of its own, so with ALL it downloads alongside the auxiliary sources,
    which run num_workers at a time, each extracted as soon as it's
    downloaded.

    Args:
        working_dir: The root directory for all data processing and storage.
        schema_dir: The directory containing the data schema definitions.
        data_type: The type of data to download (OSM, AUX, or ALL).
        num_workers: The number of parallel workers for downloading auxiliary data.

    Raises:
        ValueError: If an unsupported data_type is provided.
    """
    if data_type not in [CliDataType.OSM, CliDataType.AUX, CliDataType.ALL]:
        raise ValueError(f"Invalid data_type specified: {data_type}")

    data_schema = DataSchema(base_schema_dir=schema_dir)
    processing_directory = ProcessingDirectorySchema.init_working_directories(working_dir=working_dir)
    reporter = RunReporter(run_id=processing_directory.run_id, command="abt download")

    osm_processing = None
    if data_type in [CliDataType.OSM, CliDataType.ALL]:
        print("--- Preparing OSM data ---")
        osm_processing = prep_osm(
            data_schema=data_schema,
            processing_directory=processing_directory,
            osm_index=osm_key
        )
    aux_tasks = []
    if data_type in [CliDataType.AUX, CliDataType.ALL]:
        print("--- Preparing auxiliary data ---")
        aux_tasks = prep_aux(
            data_schema=data_schema,
            processing_directory=processing_directory
        )

    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="osm_download") as osm_thread:
        osm_download = None
        if osm_processing is not None:
            osm_download = osm_thread.submit(download_osm, osm_processing, reporter)
        if data_type in [CliDataType.AUX, CliDataType.ALL]:
            print("--- Downloading and extracting auxiliary data ---")
            ParallelExecutor(
                log_dir=processing_directory.download_log_dir,
                max_workers=num_workers,
                instance='download'
            ).run(objects=aux_tasks, action=partial(AuxDownloadTask.run, reporter=reporter))
            print("--- Auxiliary data download complete ---")
    if osm_download is not None:
        osm_download.result()

    reporter.write_summary(processing_directory.summary_file)
    print(f"Run summary: {processing_directory.summary_file}")
    return reporter

app = typer.Typer()

@app.command("download")
def cli_download(
    working_dir: Annotated[Path, working_dir_field],
    schema_dir: Annotated[Path, schema_dir_field],
    data_type: Annotated[CliDataType, data_type_field],
    num_workers: Annotated[int, num_workers_field] = default_num_workers(divisor=4),
    osm_key: Annotated[str, osm_key_field]="planet"
):
    """Download the OSM extract and/or the auxiliary data sources.

    Files land in <working-dir>/osm and <working-dir>/aux_downloads, and
    finished files from an earlier run are skipped. Each zipped aux source
    is extracted as soon as it downloads.
    \f
    Args:
        working_dir: The root directory for all processing tasks.
        schema_dir: The directory where schema definitions are located.
        data_type: The type of data to download (OSM, AUX, or ALL).
        num_workers: The number of concurrent aux downloads.
        osm_key: 'planet' or a Geofabrik extract id.
    """
    try:
        reporter = init_downloader(
            working_dir=working_dir,
            schema_dir=schema_dir,
            data_type=data_type,
            num_workers=num_workers,
            osm_key=osm_key
        )
    except Exception as e:
        typer.echo(f"Error during download process: {e}. Check logs for details.", err=True)
        raise typer.Exit(code=1)
    if reporter.overall_status != "SUCCESS":
        typer.echo(f"Download finished with status {reporter.overall_status}. See summary for details.", err=True)
        raise typer.Exit(code=1)

if __name__ == "__main__":
    app()
