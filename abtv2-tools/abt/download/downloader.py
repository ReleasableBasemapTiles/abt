"""
downloader.py

Provides a robust framework for downloading files from various sources, including
standard HTTP(S) endpoints and the Overture Maps S3 bucket. It features
automatic retries for network requests, progress tracking, and specific logic
for discovering and downloading Overture Maps data releases. The module also
includes a simple utility for extracting zip archives.

Downloads and extractions are atomic: a file only appears at its final path
once it has been fully written, so an interrupted run never leaves a
truncated file or half-extracted folder that a rerun would mistake for done.
"""
from pydantic import BaseModel, HttpUrl
from typing import Union, List
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
from .boto_configuration import s3, multipart_transfer_config

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
    A Pydantic model to manage downloading data from the Overture Maps S3 bucket.

    This model contains the logic to discover the latest data release for a given
    theme and type, and to list all associated Parquet files for download.

    Attributes:
        theme: The Overture Maps theme (e.g., 'admins', 'places').
        type: The feature type within the theme (e.g., 'locality', 'building').
    """
    theme: str
    type: str

    @property
    def bucket(self) -> str:
        """The official Overture Maps S3 bucket name."""
        return "overturemaps-us-west-2"

    @property
    def latest_release(self) -> str:
        """Finds and returns the S3 prefix for the most recent data release."""
        response = s3.list_objects(Bucket=self.bucket, Prefix='release/', Delimiter='/')
        releases = {
            overture_folder_release_by_date(p.get('Prefix')): p.get('Prefix')
            for p in response['CommonPrefixes']
        }
        return releases[max(releases.keys())]

    @property
    def data_prefix(self) -> str:
        """Constructs the full S3 prefix to the specified theme/type data."""
        return f"{self.latest_release}theme={self.theme}/type={self.type}/"

    def parquet_paths(self) -> str:
        """A generator that yields the S3 key for every Parquet file in the data prefix."""
        paginator = s3.get_paginator('list_objects_v2')
        for page in paginator.paginate(Bucket=self.bucket, Prefix=self.data_prefix):
            for obj in page.get('Contents', []):
                yield obj['Key']


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
            output_path = self.output_dir / self.filename
            output_path.mkdir(parents=True, exist_ok=True)
            logger.info(f"Starting Overture download for theme '{self.downloader.theme}'")
            for key in self.downloader.parquet_paths():
                key_path = output_path / key.split('/')[-1]
                if not key_path.exists():
                    logger.info(f"Downloading {key} to {key_path}")
                    s3.download_file(
                        Bucket=self.downloader.bucket,
                        Key=key,
                        Filename=str(key_path),
                        Config=multipart_transfer_config
                    )
                else:
                    logger.info(f"File {key_path} already exists. Skipping.")
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
