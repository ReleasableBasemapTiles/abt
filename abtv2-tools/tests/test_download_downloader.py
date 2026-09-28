"""Tests for abt.download.downloader: get_retry_session's retry config,
get_file's atomic/verified download, Extractor's atomic extraction,
build_aria2c_cmd, and overture_folder_release_by_date. No real network
calls or S3 access -- the HTTP session is faked."""

import datetime
import logging
from zipfile import ZipFile

import pytest
import requests

from abt.download import downloader as downloader_module
from abt.download.downloader import (
    DownloadAria2,
    Extractor,
    build_aria2c_cmd,
    get_file,
    get_retry_session,
    overture_folder_release_by_date,
)

LOGGER = logging.getLogger("test_downloader")


class FakeResponse:
    def __init__(self, status_code=200, chunks=(b"abc", b"def"), fail_after=None):
        self.status_code = status_code
        self._chunks = chunks
        self._fail_after = fail_after

    def iter_content(self, chunk_size):
        for i, chunk in enumerate(self._chunks):
            if self._fail_after is not None and i >= self._fail_after:
                raise requests.exceptions.ChunkedEncodingError("connection dropped")
            yield chunk

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class RecordedCalls(list):
    """A list of recorded calls that can also carry the fake's state."""


@pytest.fixture
def fake_session(monkeypatch):
    """Replaces the retry session; returns the list of recorded get() calls."""
    calls = RecordedCalls()
    state = {"response": FakeResponse()}

    class FakeSession:
        def get(self, url, **kwargs):
            calls.append({"url": url, **kwargs})
            return state["response"]

    monkeypatch.setattr(downloader_module, "get_retry_session", lambda: FakeSession())
    monkeypatch.delenv(downloader_module.INSECURE_DOWNLOADS_ENV, raising=False)
    calls.state = state
    return calls


def test_get_retry_session_configures_retry_strategy_on_both_schemes():
    session = get_retry_session()
    for scheme in ("http://example.com", "https://example.com"):
        retry = session.get_adapter(scheme).max_retries
        assert retry.total == 3
        assert set(retry.status_forcelist) == {429, 500, 502, 503, 504}
        assert set(retry.allowed_methods) == {"HEAD", "GET", "OPTIONS"}
        assert retry.backoff_factor == 2


def test_get_retry_session_bakes_in_a_default_timeout():
    session = get_retry_session()
    for method in ("get", "options", "head", "post", "put", "patch", "delete"):
        assert getattr(session, method).keywords.get("timeout") == 10


def test_overture_folder_release_by_date_parses_the_date_segment():
    result = overture_folder_release_by_date("release/2024-06-13.0/")
    assert result == datetime.datetime(2024, 6, 13)


def test_build_aria2c_cmd_includes_checksum_and_split_count():
    downloader = DownloadAria2(
        urls=["https://mirror-a.example.com/planet.osm.pbf", "https://mirror-b.example.com/planet.osm.pbf"],
        md5="d41d8cd98f00b204e9800998ecf8427e",
    )
    cmd = build_aria2c_cmd(downloader, output_dir="/data/osm", filename="planet-latest.osm.pbf")
    assert cmd[0] == "aria2c"
    assert "--checksum=md5=d41d8cd98f00b204e9800998ecf8427e" in cmd
    assert "--split=2" in cmd
    assert "--check-integrity=true" in cmd
    assert "--dir=/data/osm" in cmd
    assert "--out=planet-latest.osm.pbf" in cmd
    assert "https://mirror-a.example.com/planet.osm.pbf" in cmd
    assert "https://mirror-b.example.com/planet.osm.pbf" in cmd


def test_build_aria2c_cmd_split_count_matches_number_of_urls():
    downloader = DownloadAria2(
        urls=[f"https://mirror-{i}.example.com/planet.osm.pbf" for i in range(5)],
        md5="d41d8cd98f00b204e9800998ecf8427e",
    )
    cmd = build_aria2c_cmd(downloader, output_dir="/data/osm", filename="planet-latest.osm.pbf")
    assert "--split=5" in cmd


# --- get_file ----------------------------------------------------------------

def test_get_file_writes_the_whole_body_and_leaves_no_partial(tmp_path, fake_session):
    target = tmp_path / "data.zip"
    assert get_file("https://example.com/data.zip", target, LOGGER) == target
    assert target.read_bytes() == b"abcdef"
    assert not (tmp_path / "data.zip.part").exists()


def test_get_file_verifies_tls_by_default(tmp_path, fake_session):
    get_file("https://example.com/data.zip", tmp_path / "data.zip", LOGGER)
    assert fake_session[0]["verify"] is True
    assert fake_session[0]["stream"] is True


@pytest.mark.parametrize("value", ["1", "true", "YES"])
def test_get_file_insecure_env_var_turns_verification_off(tmp_path, fake_session, monkeypatch, value):
    monkeypatch.setenv(downloader_module.INSECURE_DOWNLOADS_ENV, value)
    get_file("https://example.com/data.zip", tmp_path / "data.zip", LOGGER)
    assert fake_session[0]["verify"] is False


def test_get_file_raises_on_non_200_and_writes_nothing(tmp_path, fake_session):
    fake_session.state["response"] = FakeResponse(status_code=404)
    target = tmp_path / "data.zip"
    with pytest.raises(RuntimeError, match="HTTP 404"):
        get_file("https://example.com/data.zip", target, LOGGER)
    assert not target.exists()


def test_get_file_interrupted_download_never_reaches_the_final_path(tmp_path, fake_session):
    # Regression test: the body used to be streamed straight into the final
    # path, so a dropped connection left a truncated file that every later
    # run skipped as "already exists".
    fake_session.state["response"] = FakeResponse(fail_after=1)
    target = tmp_path / "data.zip"
    with pytest.raises(requests.exceptions.ChunkedEncodingError):
        get_file("https://example.com/data.zip", target, LOGGER)
    assert not target.exists()

    fake_session.state["response"] = FakeResponse()
    get_file("https://example.com/data.zip", target, LOGGER)
    assert target.read_bytes() == b"abcdef"


def test_get_file_skips_an_existing_file(tmp_path, fake_session):
    target = tmp_path / "data.zip"
    target.write_bytes(b"already here")
    get_file("https://example.com/data.zip", target, LOGGER)
    assert fake_session == []
    assert target.read_bytes() == b"already here"


# --- Extractor ---------------------------------------------------------------

def make_zip(path, members):
    with ZipFile(path, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return path


def test_extractor_extracts_and_marks_complete(tmp_path):
    archive = make_zip(tmp_path / "src.zip", {"a/one.txt": "1", "two.txt": "2"})
    out = tmp_path / "layer_extracted"
    out.mkdir()  # AuxDataLayer.extraction_folder() pre-creates it
    extractor = Extractor(output_dir=out, filename=archive)
    assert extractor.extract().startswith("Extracted")
    assert sorted(p.name for p in out.iterdir()) == ["one.txt", "two.txt"]
    assert extractor.complete_marker.exists()
    assert extractor.complete_marker.parent == tmp_path
    assert not (tmp_path / "layer_extracted.partial").exists()


def test_extractor_skips_when_marked_complete(tmp_path):
    archive = make_zip(tmp_path / "src.zip", {"one.txt": "1"})
    out = tmp_path / "layer_extracted"
    extractor = Extractor(output_dir=out, filename=archive)
    extractor.extract()
    (out / "one.txt").write_text("edited")
    assert "Skipping" in extractor.extract()
    assert (out / "one.txt").read_text() == "edited"


def test_extractor_redoes_a_half_finished_extraction(tmp_path):
    # Regression test: a non-empty folder used to count as done, so a run
    # killed mid-extraction left the layer permanently incomplete.
    archive = make_zip(tmp_path / "src.zip", {"one.txt": "1", "two.txt": "2"})
    out = tmp_path / "layer_extracted"
    out.mkdir()
    (out / "one.txt").write_text("truncated")
    (out / "stale.txt").write_text("from an older archive")
    Extractor(output_dir=out, filename=archive).extract()
    assert sorted(p.name for p in out.iterdir()) == ["one.txt", "two.txt"]
    assert (out / "one.txt").read_text() == "1"


def test_extractor_failure_leaves_no_complete_marker(tmp_path):
    bad = tmp_path / "bad.zip"
    bad.write_bytes(b"not a zip")
    out = tmp_path / "layer_extracted"
    extractor = Extractor(output_dir=out, filename=bad)
    with pytest.raises(Exception):
        extractor.extract()
    assert not extractor.complete_marker.exists()


def test_get_file_per_source_opt_out_turns_verification_off(tmp_path, fake_session):
    get_file("https://example.com/data.zip", tmp_path / "data.zip", LOGGER, verify_tls=False)
    assert fake_session[0]["verify"] is False
