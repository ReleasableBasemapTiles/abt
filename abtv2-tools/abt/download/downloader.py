"""
downloader.py

Provides a robust framework for downloading files from various sources, including
standard HTTP(S) endpoints and the Overture Maps S3 bucket. It features
automatic retries for network requests, progress tracking, and a filtered
extraction of one Overture Maps theme/type via DuckDB. The module also
includes a simple utility for extracting zip archives.

Downloads and extractions are atomic: a file only appears at its final path
once it has been fully written, so an interrupted run never leaves a
truncated file or half-extracted folder that a rerun would mistake for done.
"""
from pydantic import BaseModel, HttpUrl
from typing import Union, List, Optional, Tuple
from pathlib import Path
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import functools
import datetime
import os
import shutil

from ..utils.logger import get_logger
from ..utils.subprocess_tools import run_subprocess
from ..utils.zip_tools import extract_zip
from .boto_configuration import s3

# TLS certificates are verified by default. Setting this to 1/true/yes turns
# verification off for HTTP(S) downloads (with a warning), as an escape hatch
# for a source host whose certificate chain is temporarily broken.
INSECURE_DOWNLOADS_ENV = "ABT_INSECURE_DOWNLOADS"

# Identifies this pipeline to aria2c's remote servers, mirroring the
# politeness convention openmaptiles-tools' download-osm follows for its own
# planet-mirror requests (see download/planet_mirrors.py's USER_AGENT).
ARIA2_USER_AGENT = "abt-planet-downloader/1.0 (+https://github.com/ReleasableBasemapTiles/abt)"


def get_retry_session() -> requests.Session:
    """
    Creates and configures a requests.Session with a robust retry strategy.

    This session is configured to automatically retry on common server-side
    errors and throttling responses. It also sets a default timeout for all
    requests to prevent indefinite hanging.

    Returns:
        A configured requests.Session object.
    """
    retry_strategy = Retry(
        total=3,  # Total number of retries
        status_forcelist=[429, 500, 502, 503, 504],  # HTTP status codes to retry on
        allowed_methods=["HEAD", "GET", "OPTIONS"],  # HTTP methods to retry
        backoff_factor=2,  # Exponential backoff factor (e.g., 2s, 4s, 8s)
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    http = requests.Session()
    http.mount("https://", adapter)
    http.mount("http://", adapter)

    # Set a default timeout of 10 seconds for all request methods
    for method in ("get", "options", "head", "post", "put", "patch", "delete"):
        setattr(http, method, functools.partial(getattr(http, method), timeout=10))

    return http


def tls_verification_enabled() -> bool:
    """False only when ABT_INSECURE_DOWNLOADS is set to 1/true/yes."""
    return os.environ.get(INSECURE_DOWNLOADS_ENV, "").strip().lower() not in {"1", "true", "yes"}


def partial_path(final_path: Path) -> Path:
    """The sibling path a download streams into before it's complete."""
    return final_path.with_name(final_path.name + ".part")


def get_file(file_url: str, file_path: Path, logger, verify_tls: bool = True) -> Path:
    """
    Downloads a single file from a URL to a local path.

    It checks if the file already exists to prevent re-downloading. It uses a
    session with retry logic and streams the download in chunks to handle
    large files efficiently. The body is streamed into `<name>.part` and only
    renamed to `file_path` once complete, so an existing `file_path` is
    always a whole file.

    Args:
        file_url: The URL of the file to download.
        file_path: The local path where the file should be saved.
        logger: The logger instance to use for recording progress and errors.
        verify_tls: False to skip certificate verification for this one
            source (see AuxDataLayer.verify_tls). ABT_INSECURE_DOWNLOADS
            turns it off for every source.

    Returns:
        The local file path.

    Raises:
        RuntimeError: If the server answers with anything but HTTP 200.
        requests.RequestException: On connection errors, timeouts, or a body
            shorter than its Content-Length.
    """
    if file_path.exists():
        logger.info(f"File {file_path} already exists. Skipping download.")
        return file_path

    verify = verify_tls and tls_verification_enabled()
    if not verify:
        reason = "the source sets verify_tls: false" if not verify_tls else f"{INSECURE_DOWNLOADS_ENV} is set"
        logger.warning(f"TLS certificate verification is disabled for {file_url} ({reason}).")
    logger.info(f"Attempting download of {file_url} to {file_path}")
    part = partial_path(file_path)
    session = get_retry_session()
    with session.get(file_url, stream=True, verify=verify) as response:
        if response.status_code != 200:
            message = f"Failed to download {file_url}: HTTP {response.status_code}"
            logger.error(message)
            raise RuntimeError(message)
        with open(part, "wb") as file:
            for chunk in response.iter_content(chunk_size=8192 * 1000):
                file.write(chunk)
    os.replace(part, file_path)
    logger.info(f"Successfully downloaded {file_path}")
    return file_path

def overture_folder_release_by_date(datestr: str) -> datetime.datetime:
    """Parses a datetime object from an Overture Maps S3 release folder string."""
    return datetime.datetime.fromisoformat(datestr.split('/')[1][:10])


def overture_release_sort_key(prefix: str) -> Tuple[datetime.datetime, int]:
    """Orders Overture release folders such as `release/2026-09-23.1/`.

    The date alone can't: Overture sometimes publishes two releases on one
    day (2026-09-23.0 and 2026-09-23.1 both exist), so the `.N` suffix
    breaks the tie.
    """
    name = prefix.split('/')[1]
    _, _, minor = name.partition('.')
    return overture_folder_release_by_date(prefix), int(minor) if minor.isdigit() else 0


def _duckdb_connect():
    """Opens an in-memory DuckDB connection. Imported here, not at module
    level, so the other download types keep working without duckdb, and so
    tests can replace this function."""
    import duckdb
    return duckdb.connect()


def _sql_literal(text: str) -> str:
    """Quotes `text` as a SQL string literal."""
    return "'" + text.replace("'", "''") + "'"


class DownloadFile(BaseModel):
    """A Pydantic model for a standard file download via a direct URL."""
    url: HttpUrl
    verify_tls: bool = True


class DownloadAria2(BaseModel):
    """
    A Pydantic model for a multi-source, checksum-verified download executed
    via the aria2c CLI tool instead of a plain HTTP GET.

    `urls` must all be byte-identical copies of the same file (verified by
    `md5`); aria2c fetches segments from all of them at once, aggregating
    their bandwidth instead of being capped by a single mirror's
    per-connection throughput. Currently only used for OSM planet
    downloads -- see osm_data_model.py and download/planet_mirrors.py,
    which discover `urls`/`md5` from the known planet mirrors.
    """
    urls: List[HttpUrl]
    md5: str


def build_aria2c_cmd(downloader: DownloadAria2, output_dir: Path, filename: str) -> List[str]:
    """Builds the aria2c command line for a DownloadAria2 task.

    --checksum makes verification mandatory: combined with
    --check-integrity, aria2c itself re-validates any existing/partial file
    against `md5` before deciding whether to skip, resume, or redownload --
    no separate exists-on-disk check is needed here. --split ensures at
    least one segment per mirror, so aria2c pulls from all of `urls`
    concurrently rather than just the first one.
    """
    return [
        "aria2c",
        f"--checksum=md5={downloader.md5}",
        f"--split={len(downloader.urls)}",
        "--check-integrity=true",
        "--continue=true",
        "--allow-overwrite=true",
        "--auto-file-renaming=false",
        "--http-accept-gzip=true",
        "--summary-interval=60",
        f"--user-agent={ARIA2_USER_AGENT}",
        f"--dir={output_dir}",
        f"--out={filename}",
        *[str(u) for u in downloader.urls],
    ]


class DownloadOverture(BaseModel):
    """
    Extracts one Overture Maps theme/type, filtered, into a single FlatGeobuf.

    A whole type is far more than a layer needs: base/land_cover is 128
    parquet files and 109 GB per release, of which the urban areas are a
    small slice. So instead of downloading the parquet files, DuckDB reads
    the release straight from the public S3 bucket, pulls only the rows
    that match `where` and only the `columns` asked for, and writes them to
    one FlatGeobuf that the normal ogr2ogr aux import can load.

    Attributes:
        theme: The Overture Maps theme (e.g., 'base', 'buildings').
        type: The feature type within the theme (e.g., 'land_cover').
        release: Release to read, e.g. '2026-10-21.0'. None takes the latest
            one, resolved when the download runs.
        where: Optional DuckDB WHERE condition, e.g.
            "subtype = 'urban' AND cartography.min_zoom = 8".
        columns: DuckDB select expressions to keep alongside the geometry,
            e.g. ["id", "cartography.min_zoom AS min_zoom"]. Nested struct
            fields need an alias, since FlatGeobuf has no struct type. The
            geometry is always written last, as `geometry`.
    """
    theme: str
    type: str
    release: Optional[str] = None
    where: Optional[str] = None
    columns: List[str] = []

    @property
    def bucket(self) -> str:
        """The official Overture Maps S3 bucket name."""
        return "overturemaps-us-west-2"

    @property
    def region(self) -> str:
        """The bucket's AWS region, which DuckDB needs to address it."""
        return "us-west-2"

    @property
    def latest_release(self) -> str:
        """Finds and returns the S3 prefix for the most recent data release."""
        response = s3.list_objects(Bucket=self.bucket, Prefix='release/', Delimiter='/')
        prefixes = [p.get('Prefix') for p in response['CommonPrefixes']]
        return max(prefixes, key=overture_release_sort_key)

    def resolved_release(self) -> str:
        """The release name this download reads, e.g. '2026-10-21.0'."""
        if self.release:
            return self.release
        return self.latest_release.split('/')[1]

    def source_glob(self, release: str) -> str:
        """The s3:// glob DuckDB reads for this theme/type in `release`."""
        return f"s3://{self.bucket}/release/{release}/theme={self.theme}/type={self.type}/*"

    def select_sql(self, release: str) -> str:
        """The DuckDB query selecting the rows and columns to keep."""
        select = ", ".join([*self.columns, "geometry"])
        sql = f"SELECT {select}\nFROM read_parquet({_sql_literal(self.source_glob(release))})"
        if self.where:
            sql += f"\nWHERE {self.where}"
        return sql

    def setup_statements(self) -> List[str]:
        """Loads DuckDB's spatial (GDAL writer) and httpfs (S3 reader)
        extensions. The bucket is public, so no credentials are set: DuckDB
        sends unsigned requests when it has no S3 secret."""
        return [
            "INSTALL spatial", "LOAD spatial",
            "INSTALL httpfs", "LOAD httpfs",
            f"SET s3_region = {_sql_literal(self.region)}",
        ]

    @staticmethod
    def optional_statements() -> List[str]:
        """Settings that only some DuckDB versions have. DuckDB 1.5 warns that
        GDAL may write EPSG:4326 in latitude/longitude order unless
        geometry_always_xy is set (and only accepts it once spatial is
        loaded); older versions reject the setting, which is logged and
        skipped rather than failing the download."""
        return ["SET geometry_always_xy = true"]

    def copy_sql(self, release: str, output: Path) -> str:
        """The DuckDB COPY writing the selected rows to `output` (.fgb)."""
        return (
            f"COPY ({self.select_sql(release)})\n"
            f"TO {_sql_literal(str(output))} WITH (FORMAT GDAL, DRIVER 'FlatGeobuf')"
        )

    def extract(self, output_path: Path, logger) -> Path:
        """Writes the filtered rows to `output_path`, unless an earlier run did.

        The release used is recorded in `<output_path>.release`. A rerun with
        the file already present skips the extraction, and fails instead if
        it was pinned to a different release than the one on disk, so a
        pinned run never silently imports another release's data (the same
        rule as scripts/overture/fetch.sh). The FlatGeobuf is written under
        `.partial/` and moved into place only once DuckDB finishes; GDAL's
        FlatGeobuf driver treats a name not ending in .fgb as a directory,
        so the staging file keeps the final name.
        """
        release_file = output_path.with_name(output_path.name + ".release")
        if output_path.exists():
            on_disk = release_file.read_text().strip() if release_file.exists() else "unknown"
            if self.release and on_disk != self.release:
                raise RuntimeError(
                    f"{output_path} was extracted from Overture release {on_disk}, but this "
                    f"source is pinned to {self.release}. Delete it to extract again."
                )
            logger.info(f"{output_path} already exists (release {on_disk}). Skipping extraction.")
            return output_path

        release = self.resolved_release()
        staging = output_path.parent / ".partial" / output_path.name
        staging.parent.mkdir(parents=True, exist_ok=True)
        staging.unlink(missing_ok=True)
        copy = self.copy_sql(release, staging)
        logger.info(f"Extracting Overture {self.theme}/{self.type} release {release} to {output_path}:\n{copy}")
        con = _duckdb_connect()
        try:
            for statement in self.setup_statements():
                con.execute(statement)
            for statement in self.optional_statements():
                try:
                    con.execute(statement)
                except Exception as e:  # duckdb.Error, but duckdb is imported lazily
                    logger.info(f"Skipping '{statement}': {e}")
            con.execute(copy)
        finally:
            con.close()
        os.replace(staging, output_path)
        release_file.write_text(release + "\n")
        logger.info(f"Extracted {output_path} from Overture release {release}")
        return output_path


class Downloader(BaseModel):
    """
    An orchestrator model that handles different types of download tasks.

    This class acts as a wrapper, dispatching the download logic to the
    appropriate method based on whether the source is a direct file URL
    or an Overture Maps S3 location.

    Attributes:
        downloader: The specific downloader model (DownloadFile, DownloadAria2,
            or DownloadOverture).
        output_dir: The directory where the downloaded files will be saved.
        filename: The target filename or folder name for the download.
        log_dir: The directory for storing logs.
    """
    downloader: Union[DownloadOverture, DownloadFile, DownloadAria2]
    output_dir: Path
    filename: str
    log_dir: Path

    @property
    def name(self) -> str:
        """Alias for filename, used by ParallelExecutor for per-task reporting."""
        return self.filename

    def download(self):
        """
        Executes the download based on the type of the `downloader` attribute.
        """
        logger = get_logger(name=Path(self.filename).stem, directory=self.log_dir, process_stage="download")

        if isinstance(self.downloader, DownloadFile):
            download_path = self.output_dir / self.filename
            get_file(
                file_url=str(self.downloader.url),
                file_path=download_path,
                logger=logger,
                verify_tls=self.downloader.verify_tls,
            )

        elif isinstance(self.downloader, DownloadAria2):
            run_subprocess(
                cmd=build_aria2c_cmd(self.downloader, self.output_dir, self.filename),
                layer=Path(self.filename).stem,
                process_stage="download",
                log_dir=self.log_dir,
                tool_name="aria2c",
            )

        elif isinstance(self.downloader, DownloadOverture):
            self.downloader.extract(self.output_dir / self.filename, logger)
        else:
            logger.error("Unknown downloader type provided.")
            raise TypeError("Unsupported downloader type.")


class Extractor(BaseModel):
    """
    A simple model to handle the extraction of a zip file.

    Extraction is atomic: the archive is unpacked into a sibling
    `<output_dir>.partial` folder, which is renamed into place only once
    every member is written, and a hidden `.<output_dir name>.complete`
    marker is then written beside it. A rerun skips extraction only when
    that marker exists, so a folder left half-full by an interrupted run is
    re-extracted rather than imported incomplete. (Folders extracted before
    the marker existed are re-extracted once.)

    Attributes:
        output_dir: The directory where the contents will be extracted.
        filename: The path to the zip file to be extracted.
    """
    output_dir: Path
    filename: Path

    @property
    def name(self) -> str:
        """Used by ParallelExecutor for per-task reporting."""
        return self.filename.name

    @property
    def complete_marker(self) -> Path:
        """Written beside output_dir once extraction has fully finished."""
        return self.output_dir.parent / f".{self.output_dir.name}.complete"

    def extract(self) -> str:
        """
        Extracts the zip file unless a previous extraction completed.
        """
        if self.complete_marker.exists():
            return f"{self.output_dir} already extracted. Skipping extraction."

        staging = self.output_dir.with_name(self.output_dir.name + ".partial")
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True)
        extract_zip(file_path=self.filename, extraction_folder=staging)
        # Replace whatever is at output_dir: an empty folder pre-created by
        # AuxDataLayer.extraction_folder(), or leftovers from an earlier run.
        if self.output_dir.exists():
            shutil.rmtree(self.output_dir)
        staging.rename(self.output_dir)
        self.complete_marker.touch()
        return f"Extracted {self.filename}"
