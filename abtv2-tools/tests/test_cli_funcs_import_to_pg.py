"""Tests for abt.cli_funcs.import_to_pg.init_importer: under -d all the OSM
import runs alongside the aux imports, the aux schema is reset before either
starts, and a populated osm schema still stops the run first unless
--force. Postgres, OSM prep and the imports themselves are replaced."""

import threading
from types import SimpleNamespace

import pytest

from abt.cli_funcs import import_to_pg as import_module
from abt.cli_funcs.import_to_pg import OSMAlreadyPopulatedError, init_importer
from abt.importer.importer import Importer, ImportOGR
from abt.utils.fields import CliDataType
from abt.utils.pg_config import PGConfig


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Stubs out Postgres and the aux import list. `db.events` lists what
    ran, in order; set `db.osm_populated` to simulate an earlier import."""
    db = SimpleNamespace(events=[], osm_populated=False)
    monkeypatch.setattr(import_module, "get_pg_config", lambda cli_input, log_dir: PGConfig(
        host="localhost", port=5432, user="u", password="p", database="d", log_path=log_dir,
    ))
    monkeypatch.setattr(PGConfig, "osm_populated", property(lambda self: db.osm_populated))
    monkeypatch.setattr(PGConfig, "reset_aux_schema", lambda self: db.events.append("reset_aux_schema"))
    aux = [Importer(importer=ImportOGR(cmd=["ogr2ogr"]), layer=name, log_dir=tmp_path) for name in ("lsib", "dams")]
    monkeypatch.setattr(import_module, "prep_aux", lambda **kwargs: (aux, []))
    return db


def fake_osm(import_to_pg):
    """Stands in for prep_osm: an extract whose import runs `import_to_pg`."""
    return lambda **kwargs: SimpleNamespace(
        osm_data=SimpleNamespace(filename="norway-latest.osm.pbf"),
        init_import=lambda **kwargs: SimpleNamespace(import_to_pg=import_to_pg),
    )


def make_schema_dir(tmp_path):
    schema_dir = tmp_path / "schema"
    for sub in ("import/osm", "import/aux_data", "export", "carto_sql"):
        (schema_dir / sub).mkdir(parents=True)
    return schema_dir


def run_import(tmp_path, **kwargs):
    return init_importer(
        working_dir=tmp_path / "work", schema_dir=make_schema_dir(tmp_path), data_type=CliDataType.ALL,
        num_workers=2, pg_config_type="env", osm_key="norway", **kwargs,
    )


def test_all_imports_osm_alongside_the_aux_sources(tmp_path, monkeypatch, db):
    aux_started = threading.Event()
    osm_saw_aux_start = []

    def osm_import():
        # Run one after the other, this would wait out the timeout.
        osm_saw_aux_start.append(aux_started.wait(10))
        db.events.append("osm import")

    def aux_import(self):
        db.events.append(f"aux import {self.layer}")
        aux_started.set()

    monkeypatch.setattr(import_module, "prep_osm", fake_osm(osm_import))
    monkeypatch.setattr(Importer, "import_to_pg", aux_import)
    reporter = run_import(tmp_path)
    assert osm_saw_aux_start == [True]
    assert db.events[0] == "reset_aux_schema"
    assert sorted(db.events[1:]) == ["aux import dams", "aux import lsib", "osm import"]
    assert reporter.overall_status == "SUCCESS"
    summary = reporter.write_summary(tmp_path / "summary.json")
    (stage,) = summary["stages"]
    assert {task["task"] for task in stage["tasks"]} == {"norway-latest.osm.pbf", "lsib", "dams"}


def test_a_failed_osm_import_is_recorded_and_the_aux_imports_still_run(tmp_path, monkeypatch, db):
    def fail():
        raise RuntimeError("imposm exit 1")

    monkeypatch.setattr(import_module, "prep_osm", fake_osm(fail))
    monkeypatch.setattr(Importer, "import_to_pg", lambda self: db.events.append(f"aux import {self.layer}"))
    reporter = run_import(tmp_path)
    assert sorted(db.events) == ["aux import dams", "aux import lsib", "reset_aux_schema"]
    assert reporter.overall_status == "PARTIAL_FAILURE"


def test_a_populated_osm_schema_stops_the_run_before_anything_starts(tmp_path, monkeypatch, db):
    db.osm_populated = True
    monkeypatch.setattr(import_module, "prep_osm", fake_osm(lambda: db.events.append("osm import")))
    monkeypatch.setattr(Importer, "import_to_pg", lambda self: db.events.append("aux import"))
    with pytest.raises(OSMAlreadyPopulatedError):
        run_import(tmp_path)
    assert db.events == []
