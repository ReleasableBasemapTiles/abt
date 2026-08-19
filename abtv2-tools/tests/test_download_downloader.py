"""Tests for abt.download.downloader: get_retry_session's retry config,
build_aria2c_cmd, and overture_folder_release_by_date. No real network
calls or S3 access."""

import datetime

from abt.download.downloader import (
    DownloadAria2,
    build_aria2c_cmd,
    get_retry_session,
    overture_folder_release_by_date,
)


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
