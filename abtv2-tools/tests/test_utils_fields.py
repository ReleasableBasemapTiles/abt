"""Tests for abt.utils.fields -- pure helpers only (default_num_workers,
validate_projection_override). The typer.Option field definitions
themselves are declarative and exercised indirectly via cli_funcs tests.
"""

import typer
import pytest

from abt.utils import fields


def test_default_num_workers_uses_floor_on_small_host(monkeypatch):
    monkeypatch.setattr(fields.os, "cpu_count", lambda: 4)
    assert fields.default_num_workers(divisor=3, floor=4) == 4  # 4//3=1, floor wins


def test_default_num_workers_scales_up_on_large_host(monkeypatch):
    monkeypatch.setattr(fields.os, "cpu_count", lambda: 96)
    assert fields.default_num_workers(divisor=3, floor=4) == 32  # 96//3=32


def test_default_num_workers_falls_back_to_floor_when_cpu_count_unknown(monkeypatch):
    monkeypatch.setattr(fields.os, "cpu_count", lambda: None)
    assert fields.default_num_workers(divisor=3, floor=4) == 4


def test_default_num_workers_respects_custom_divisor_and_floor(monkeypatch):
    monkeypatch.setattr(fields.os, "cpu_count", lambda: 100)
    assert fields.default_num_workers(divisor=1, floor=10) == 100
    assert fields.default_num_workers(divisor=1000, floor=10) == 10


def test_validate_projection_override_passes_through_none():
    assert fields.validate_projection_override(None) is None


def test_validate_projection_override_accepts_valid_epsg_code():
    assert fields.validate_projection_override("EPSG:3395") == "EPSG:3395"


@pytest.mark.parametrize(
    "bad_value",
    ["epsg:3395", "EPSG:", "EPSG:12a", "3395", "EPSG: 3395", "", "EPSG:3395 "],
)
def test_validate_projection_override_rejects_invalid_forms(bad_value):
    with pytest.raises(typer.BadParameter):
        fields.validate_projection_override(bad_value)


def test_cli_data_type_enum_values():
    assert fields.CliDataType.OSM.value == "osm"
    assert fields.CliDataType.AUX.value == "aux"
    assert fields.CliDataType.ALL.value == "all"
    # Inherits from str, so it compares equal to its plain string value --
    # relied on wherever CliDataType members are compared against CLI input.
    assert fields.CliDataType.OSM == "osm"
