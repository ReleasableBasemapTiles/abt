"""Tests for abt.cli_funcs.download: each aux source is one task that
downloads and then extracts it (prep_aux, AuxDownloadTask), and under -d all
the OSM download runs alongside the aux downloads. Downloads, extractions
and OSM prep are replaced, so nothing touches the network."""

import json
import threading
from types import SimpleNamespace

import pytest

from abt.cli_funcs import download as download_module
from abt.cli_funcs.download import init_downloader, prep_aux
from abt.download.downloader import Downloader, Extractor
from abt.schema import DataSchema, ProcessingDirectorySchema
from abt.utils.fields import CliDataType

AUX_CONFIGS = {
    "lsib": {"folder_name": "lsib", "url": "https://example.com/d/LSIB.zip", "type": "shp", "zipped": True},
    "dams": {"folder_name": "dams", "url": "https://example.com/d/dams.gpkg", "type": "gpkg", "zipped": False},
    "regions": {"folder_name": "regions", "local_path": "static_data/regions.zip", "type": "shp", "zipped": True},
    "points": {"folder_name": "points", "local_path": "static_data/points.gpkg", "type": "gpkg", "zipped": False},
}


def make_schema_dir(tmp_path, aux_configs=AUX_CONFIGS):
    schema_dir = tmp_path / "schema"
    for sub in ("import/osm", "import/aux_data", "export", "carto_sql"):
        (schema_dir / sub).mkdir(parents=True)
    for name, config in aux_configs.items():
        (schema_dir / "import" / "aux_data" / f"{name}.json").write_text(json.dumps(config))
    return schema_dir


@pytest.fixture
def steps(monkeypatch):
    """Replaces Downloader.download and Extractor.extract with a recorder of
    (step, file) pairs. Downloading a file whose name starts with "bad" fails."""
    ran = []

    def download(self):
        ran.append(("download", self.filename))
        if self.filename.startswith("bad"):
            raise RuntimeError("HTTP 404")

    def extract(self):
        ran.append(("extract", self.filename.name))

    monkeypatch.setattr(Downloader, "download", download)
    monkeypatch.setattr(Extractor, "extract", extract)
    return ran


def summary_tasks(reporter, tmp_path):
    summary = reporter.write_summary(tmp_path / "summary.json")
    return {stage["stage"]: {task["task"]: task for task in stage["tasks"]} for stage in summary["stages"]}


def test_prep_aux_builds_one_task_per_source_with_anything_to_do(tmp_path):
    schema = DataSchema(base_schema_dir=make_schema_dir(tmp_path))
    dirs = ProcessingDirectorySchema.init_working_directories(working_dir=tmp_path / "work")
    tasks = {task.name: task for task in prep_aux(schema, dirs)}
    # points.gpkg is local and unzipped: nothing to fetch or unpack.
    assert set(tasks) == {"LSIB.zip", "dams.gpkg", "regions.zip"}
    assert tasks["LSIB.zip"].downloader is not None and tasks["LSIB.zip"].extractor is not None
    assert tasks["dams.gpkg"].extractor is None
    assert tasks["regions.zip"].downloader is None
    assert tasks["regions.zip"].extractor.filename == tmp_path / "schema" / "static_data" / "regions.zip"


def test_each_zip_is_extracted_as_soon_as_it_downloads(tmp_path, steps):
    reporter = init_downloader(
        working_dir=tmp_path / "work", schema_dir=make_schema_dir(tmp_path),
        data_type=CliDataType.AUX, num_workers=1, osm_key="planet",
    )
    assert sorted(steps) == sorted([
        ("download", "LSIB.zip"), ("extract", "LSIB.zip"), ("download", "dams.gpkg"), ("extract", "regions.zip"),
    ])
    lsib_download = steps.index(("download", "LSIB.zip"))
    assert steps[lsib_download + 1] == ("extract", "LSIB.zip")
    tasks = summary_tasks(reporter, tmp_path)
    assert set(tasks["download"]) == {"LSIB.zip", "dams.gpkg"}
    assert set(tasks["aux_extraction"]) == {"LSIB.zip", "regions.zip"}
    assert all("duration_s" in task for stage in tasks.values() for task in stage.values())


def test_a_failed_download_is_not_extracted(tmp_path, steps):
    schema_dir = make_schema_dir(tmp_path, {
        "bad": {"folder_name": "bad", "url": "https://example.com/d/bad.zip", "type": "shp", "zipped": True},
    })
    reporter = init_downloader(
        working_dir=tmp_path / "work", schema_dir=schema_dir, data_type=CliDataType.AUX, num_workers=1,
        osm_key="planet",
    )
    assert steps == [("download", "bad.zip")]
    assert reporter.overall_status == "FAILED"
    tasks = summary_tasks(reporter, tmp_path)
    assert tasks["download"]["bad.zip"]["error"] == "HTTP 404"
    assert tasks["aux_extraction"]["bad.zip"]["error"] == "not attempted (download failed)"


def fake_osm(download):
    """Stands in for prep_osm: an extract whose download runs `download`."""
    return lambda **kwargs: SimpleNamespace(
        osm_data=SimpleNamespace(filename="norway-latest.osm.pbf"),
        init_download=lambda: SimpleNamespace(download=download),
    )


def test_all_downloads_osm_alongside_the_aux_sources(tmp_path, monkeypatch):
    aux_started = threading.Event()
    osm_saw_aux_start = []
    # Run one after the other, the OSM download would wait out the timeout.
    monkeypatch.setattr(download_module, "prep_osm", fake_osm(lambda: osm_saw_aux_start.append(aux_started.wait(10))))
    monkeypatch.setattr(Downloader, "download", lambda self: aux_started.set())
    monkeypatch.setattr(Extractor, "extract", lambda self: None)
    reporter = init_downloader(
        working_dir=tmp_path / "work", schema_dir=make_schema_dir(tmp_path),
        data_type=CliDataType.ALL, num_workers=2, osm_key="norway",
    )
    assert osm_saw_aux_start == [True]
    assert reporter.overall_status == "SUCCESS"
    assert "norway-latest.osm.pbf" in summary_tasks(reporter, tmp_path)["download"]


def test_a_failed_osm_download_is_recorded_and_the_aux_downloads_still_run(tmp_path, monkeypatch, steps):
    def fail():
        raise RuntimeError("Geofabrik unreachable")

    monkeypatch.setattr(download_module, "prep_osm", fake_osm(fail))
    reporter = init_downloader(
        working_dir=tmp_path / "work", schema_dir=make_schema_dir(tmp_path),
        data_type=CliDataType.ALL, num_workers=2, osm_key="norway",
    )
    assert ("download", "LSIB.zip") in steps
    assert reporter.overall_status == "PARTIAL_FAILURE"
    assert summary_tasks(reporter, tmp_path)["download"]["norway-latest.osm.pbf"]["error"] == "Geofabrik unreachable"
