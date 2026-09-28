"""Tests for abt.osm_data_model: ImposmMappingFile's required-keys
validator, ImposmManagement's combined mapping (with the optional base
settings), OSMData's optional diff_location, and the pure _geometry_bbox
envelope calculation."""

import pytest
from pydantic import ValidationError

from abt import osm_data_model
from abt.osm_data_model import (
    PLANET_IDENTIFIER,
    ImposmManagement,
    ImposmMappingFile,
    OSMData,
    _geometry_bbox,
    getGeoFabrikIndex,
    load_imposm_base,
    resolve_osm_data,
)

ROADS = {"columns": [], "mapping": {"highway": ["__any__"]}, "type": "linestring"}


# --- ImposmMappingFile.validate_mapping_data -----------------------------

def test_validate_mapping_data_accepts_all_required_keys():
    mapping = ImposmMappingFile(
        table="roads",
        data={"columns": [], "mapping": {}, "type": "linestring"},
    )
    assert mapping.table == "roads"


@pytest.mark.parametrize("missing_key", ["columns", "mapping", "type"])
def test_validate_mapping_data_rejects_missing_required_key(missing_key):
    data = {"columns": [], "mapping": {}, "type": "linestring"}
    del data[missing_key]
    with pytest.raises(ValidationError, match="missing required elements"):
        ImposmMappingFile(table="roads", data=data)


def test_validate_mapping_data_rejects_completely_empty_dict():
    with pytest.raises(ValidationError, match="missing required elements"):
        ImposmMappingFile(table="roads", data={})


# --- ImposmManagement.combined_mapping --------------------------------------

def test_combined_mapping_without_a_base_is_just_the_tables():
    management = ImposmManagement(mapping_files=[ImposmMappingFile(table="roads", data=ROADS)])
    assert management.combined_mapping == {"tables": {"roads": ROADS}}


def test_combined_mapping_merges_base_settings_beside_the_tables():
    management = ImposmManagement(
        mapping_files=[ImposmMappingFile(table="roads", data=ROADS)],
        base={"tags": {"include": ["covered", "razed:highway"]}},
    )
    assert management.combined_mapping == {
        "tags": {"include": ["covered", "razed:highway"]},
        "tables": {"roads": ROADS},
    }


def test_base_that_defines_tables_is_rejected():
    with pytest.raises(ValidationError, match="must not define 'tables'"):
        ImposmManagement(
            mapping_files=[ImposmMappingFile(table="roads", data=ROADS)],
            base={"tables": {"other": ROADS}},
        )


def test_load_imposm_base_returns_empty_without_a_file():
    assert load_imposm_base(None) == {}


def test_load_imposm_base_reads_yaml_and_tolerates_an_empty_file(tmp_path):
    base = tmp_path / "imposm_base.yml"
    base.write_text("tags:\n  include:\n    - covered\n")
    assert load_imposm_base(base) == {"tags": {"include": ["covered"]}}
    base.write_text("# only comments\n")
    assert load_imposm_base(base) == {}


# --- OSMData.diff_location -------------------------------------------------

def test_osm_data_accepts_a_missing_diff_location():
    # Regression test for a fixed bug (see docs/code-review-findings.md,
    # F2): diff_location used to be a non-Optional HttpUrl, but
    # getGeoFabrikIndex() feeds it `properties["urls"].get("updates")`,
    # which is None for any extract with no updates feed.
    data = OSMData(identifier="no-updates-extract", pbf_location="https://example.com/x.osm.pbf")
    assert data.diff_location is None


def test_osm_data_accepts_a_present_diff_location():
    data = OSMData(
        identifier="thailand",
        pbf_location="https://example.com/thailand.osm.pbf",
        diff_location="https://example.com/replication/",
    )
    assert str(data.diff_location) == "https://example.com/replication/"


# --- _geometry_bbox -------------------------------------------------------

def test_geometry_bbox_for_a_simple_polygon():
    geometry = {
        "type": "Polygon",
        "coordinates": [[[0.0, 0.0], [10.0, 0.0], [10.0, 5.0], [0.0, 5.0], [0.0, 0.0]]],
    }
    assert _geometry_bbox(geometry) == (0.0, 0.0, 10.0, 5.0)


def test_geometry_bbox_for_a_point():
    geometry = {"type": "Point", "coordinates": [12.5, -7.5]}
    assert _geometry_bbox(geometry) == (12.5, -7.5, 12.5, -7.5)


def test_geometry_bbox_for_a_multipolygon_spans_all_parts():
    geometry = {
        "type": "MultiPolygon",
        "coordinates": [
            [[[-10.0, -10.0], [-5.0, -10.0], [-5.0, -5.0], [-10.0, -5.0]]],
            [[[20.0, 20.0], [30.0, 20.0], [30.0, 25.0], [20.0, 25.0]]],
        ],
    }
    assert _geometry_bbox(geometry) == (-10.0, -10.0, 30.0, 25.0)


def test_geometry_bbox_ignores_extra_z_or_m_coordinates():
    # flatten()'s `x, y, *_` unpacking should tolerate a 3rd/4th ordinate.
    geometry = {"type": "Point", "coordinates": [1.0, 2.0, 100.0]}
    assert _geometry_bbox(geometry) == (1.0, 2.0, 1.0, 2.0)


# --- GeoFabrik index lookup ---------------------------------------------------

GEOFABRIK_INDEX = {
    "features": [
        {
            "properties": {"id": "liechtenstein",
                           "urls": {"pbf": "https://example.com/liechtenstein-latest.osm.pbf"}},
            "geometry": {"type": "Point", "coordinates": [9.5, 47.1]},
        }
    ]
}


class FakeIndexResponse:
    def __init__(self, status_error=None):
        self._status_error = status_error

    def raise_for_status(self):
        if self._status_error:
            raise self._status_error

    def json(self):
        return GEOFABRIK_INDEX


class RecordedCalls(list):
    """A list of recorded calls that can also carry the fake's response."""


@pytest.fixture
def index_requests(monkeypatch):
    """Fakes requests.get for the index; returns the recorded calls."""
    calls = RecordedCalls()
    getGeoFabrikIndex.cache_clear()

    def fake_get(url, **kwargs):
        calls.append({"url": url, **kwargs})
        return calls.response

    calls.response = FakeIndexResponse()
    monkeypatch.setattr(osm_data_model.requests, "get", fake_get)
    yield calls
    getGeoFabrikIndex.cache_clear()


def test_planet_resolves_without_fetching_the_index(index_requests):
    data = resolve_osm_data(PLANET_IDENTIFIER)
    assert data.filename == "planet-latest.osm.pbf"
    assert data.bbox is None
    assert index_requests == []


def test_index_is_fetched_once_with_a_timeout(index_requests):
    assert resolve_osm_data("liechtenstein").bbox == (9.5, 47.1, 9.5, 47.1)
    resolve_osm_data("liechtenstein")
    assert len(index_requests) == 1
    assert index_requests[0]["timeout"] > 0


def test_index_http_error_is_raised_not_parsed(index_requests):
    import requests

    index_requests.response = FakeIndexResponse(status_error=requests.HTTPError("503"))
    with pytest.raises(requests.HTTPError):
        resolve_osm_data("liechtenstein")


def test_unknown_key_is_a_clear_error(index_requests):
    with pytest.raises(ValueError, match="Unknown OSM key 'atlantis'"):
        resolve_osm_data("atlantis")
