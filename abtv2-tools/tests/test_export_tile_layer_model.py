"""Tests for abt.export.tile_layer_model: TippecanoeOptions/OGRExportOptions
flag builders, TileLayer.from_dict, and the tippecanoe_cmd/ogr_cmd/ogr_sql
command builders. No live Postgres -- does_table_exist/count_features/
layer_summary (which need a real connection) are out of scope."""

from pathlib import Path

import pytest

from abt.export.tile_layer_model import (
    AttributeTypes,
    GeometryTypes,
    OGRExportOptions,
    TileLayer,
    TileLayerAttributes,
    TippecanoeOptions,
)
from abt.utils.pg_config import PGConfig


def make_pg_config(tmp_path: Path) -> PGConfig:
    return PGConfig(
        host="localhost", port=5432, user="u", password="p", database="d",
        log_path=tmp_path,
    )


def make_layer(tmp_path: Path, **overrides) -> TileLayer:
    defaults = dict(
        layer_id="roads",
        geometry_type=GeometryTypes.LINESTRING,
        pg_config=make_pg_config(tmp_path),
        flatgeobuf_dir=tmp_path / "fgb",
        mbtiles_dir=tmp_path / "mbtiles",
        tmp_dir=tmp_path / "tmp",
        log_dir=tmp_path / "logs",
        tippecanoe_options=TippecanoeOptions(minimum_zoom=0, maximum_zoom=13, max_detail_const=15),
        ogr_export_options=OGRExportOptions(),
    )
    defaults.update(overrides)
    return TileLayer(**defaults)


def from_dict_layer(tmp_path: Path, data: dict, max_detail_const: int = 13) -> TileLayer:
    return TileLayer.from_dict(
        data, max_detail_const=max_detail_const, pg_config=make_pg_config(tmp_path),
        flatgeobuf_dir=tmp_path / "fgb", mbtiles_dir=tmp_path / "mbtiles",
        tmp_dir=tmp_path / "tmp", log_dir=tmp_path / "logs",
    )


# --- TippecanoeOptions ---------------------------------------------------

def test_zoom_flags_caps_max_zoom_at_max_detail_const():
    opts = TippecanoeOptions(minimum_zoom=0, maximum_zoom=20, max_detail_const=13)
    assert opts.zoom_flags == ["-Z0", "-z13"]


def test_zoom_flags_clamps_min_zoom_to_the_capped_max_zoom():
    # minimum_zoom (15) configured higher than the capped max_zoom (13).
    opts = TippecanoeOptions(minimum_zoom=15, maximum_zoom=20, max_detail_const=13)
    assert opts.zoom_flags == ["-Z13", "-z13"]


def test_detail_flag_uses_max_detail_const_plus_one_past_the_cap():
    opts = TippecanoeOptions(minimum_zoom=0, maximum_zoom=20, max_detail_const=13)
    assert opts.detail_flag == "--extra-detail=14"


def test_detail_flag_uses_maximum_zoom_plus_one_within_the_cap():
    opts = TippecanoeOptions(minimum_zoom=0, maximum_zoom=8, max_detail_const=13)
    assert opts.detail_flag == "--extra-detail=9"


def test_tippecanoe_flags_splits_on_spaces():
    opts = TippecanoeOptions(
        minimum_zoom=0, maximum_zoom=13, max_detail_const=13,
        additional_flags="--drop-densest-as-needed --hilbert",
    )
    assert opts.tippecanoe_flags == ["--drop-densest-as-needed", "--hilbert"]


def test_tippecanoe_flags_empty_when_unset():
    opts = TippecanoeOptions(minimum_zoom=0, maximum_zoom=13, max_detail_const=13)
    assert opts.tippecanoe_flags == []


def test_tippecanoe_filter_argument_present_only_when_filter_set():
    opts = TippecanoeOptions(minimum_zoom=0, maximum_zoom=13, max_detail_const=13)
    assert opts.tippecanoe_filter_argument == []

    opts_with_filter = TippecanoeOptions(
        minimum_zoom=0, maximum_zoom=13, max_detail_const=13,
        filter={"highway": "primary"},
    )
    assert opts_with_filter.tippecanoe_filter_argument == ["-j", '{"highway": "primary"}']


@pytest.mark.parametrize("bad_zoom", [-1, 25])
def test_minimum_zoom_out_of_range_is_rejected(bad_zoom):
    with pytest.raises(Exception):
        TippecanoeOptions(minimum_zoom=bad_zoom, maximum_zoom=13, max_detail_const=13)


def test_zoom_fields_reject_bool_under_strict_validation():
    # Field(strict=True) -- bool is an int subclass in Python, so this
    # specifically guards against a stray True/False sneaking through.
    with pytest.raises(Exception):
        TippecanoeOptions(minimum_zoom=True, maximum_zoom=13, max_detail_const=13)


# --- OGRExportOptions -----------------------------------------------------

def test_ogr_flags_splits_on_spaces():
    opts = OGRExportOptions(additional_flags="-skipfailures -t_srs EPSG:3857")
    assert opts.ogr_flags == ["-skipfailures", "-t_srs", "EPSG:3857"]


def test_ogr_flags_empty_when_unset():
    assert OGRExportOptions().ogr_flags == []


# --- TileLayer.from_dict ---------------------------------------------------

def test_from_dict_builds_full_layer_with_options(tmp_path):
    data = {
        "layer_id": "roads",
        "geometry_type": "linestring",
        "attributes": [{"name": "class", "type": "string"}],
        "tippecanoe_options": {
            "minimum_zoom": 4, "maximum_zoom": 13, "additional_flags": "--hilbert",
        },
        "ogr_export_options": {"additional_flags": "-skipfailures"},
    }
    layer = from_dict_layer(tmp_path, data)
    assert layer.layer_id == "roads"
    assert layer.tippecanoe_options.minimum_zoom == 4
    assert layer.tippecanoe_options.maximum_zoom == 13
    assert layer.ogr_export_options.additional_flags == "-skipfailures"
    assert layer.attributes[0].name == "class"


def test_from_dict_defaults_attributes_to_empty_list_when_absent(tmp_path):
    layer = from_dict_layer(tmp_path, {"layer_id": "roads", "geometry_type": "linestring"})
    assert layer.attributes == []
    assert layer.tippecanoe_attributes == ["-X"]


def test_from_dict_without_tippecanoe_options_key_does_not_crash_tippecanoe_cmd(tmp_path):
    # Regression test for a fixed bug (see docs/code-review-findings.md,
    # F1): from_dict() used to leave tippecanoe_options as None when the
    # JSON omitted the key entirely, and tippecanoe_cmd unconditionally
    # dereferences self.tippecanoe_options.zoom_flags.
    layer = from_dict_layer(tmp_path, {"layer_id": "roads", "geometry_type": "linestring"})
    cmd = layer.tippecanoe_cmd
    assert "tippecanoe" in cmd
    assert "-Z0" in cmd  # default minimum_zoom
    assert f"-z{layer.tippecanoe_options.max_detail_const}" in cmd  # default maximum_zoom


def test_from_dict_without_ogr_export_options_key_does_not_crash_ogr_cmd(tmp_path):
    # Regression test for a fixed bug (see docs/code-review-findings.md,
    # F1): from_dict() used to leave ogr_export_options as None when the
    # JSON omitted the key entirely, and ogr_cmd unconditionally
    # dereferences self.ogr_export_options.ogr_flags.
    layer = from_dict_layer(tmp_path, {"layer_id": "roads", "geometry_type": "linestring"})
    assert "ogr2ogr" in layer.ogr_cmd


# --- tippecanoe_cmd / ogr_cmd / ogr_sql ------------------------------------

def test_tippecanoe_cmd_includes_zoom_and_output_flags(tmp_path):
    layer = make_layer(tmp_path)
    cmd = layer.tippecanoe_cmd
    assert cmd[0] == "tippecanoe"
    assert "-Z0" in cmd
    assert "-z13" in cmd
    assert "--output" in cmd
    assert str(layer.mbtiles_export_filename) in cmd
    assert "--layer" in cmd
    assert "roads" in cmd


def test_tippecanoe_cmd_uses_no_attributes_flag_when_layer_has_none(tmp_path):
    layer = make_layer(tmp_path, attributes=[])
    assert "-X" in layer.tippecanoe_cmd


def test_tippecanoe_cmd_lists_attribute_names_and_types(tmp_path):
    layer = make_layer(
        tmp_path,
        attributes=[TileLayerAttributes(name="class", type=AttributeTypes.STRING)],
    )
    cmd = layer.tippecanoe_cmd
    assert "-y" in cmd and "class" in cmd
    assert "-T" in cmd and "class:string" in cmd


def test_tippecanoe_cmd_adds_projection_flag_when_override_active(tmp_path):
    layer = make_layer(tmp_path, projection_override="EPSG:3395")
    cmd = layer.tippecanoe_cmd
    assert "-s" in cmd
    assert "EPSG:3857" in cmd


def test_tippecanoe_cmd_omits_projection_flag_for_default_web_mercator(tmp_path):
    layer = make_layer(tmp_path, projection_override=None)
    assert "-s" not in layer.tippecanoe_cmd


def test_ogr_cmd_includes_sql_and_pg_uri(tmp_path):
    layer = make_layer(tmp_path)
    cmd = layer.ogr_cmd
    assert cmd[0] == "ogr2ogr"
    assert layer.ogr_sql in cmd
    assert f"PG:{layer.pg_config.uri}" in cmd


def test_ogr_sql_selects_geometry_and_filters_empty(tmp_path):
    layer = make_layer(tmp_path)
    assert layer.ogr_sql == (
        'SELECT geometry FROM export."roads" WHERE geometry IS NOT NULL '
        'AND NOT ST_IsEmpty(geometry)'
    )


def test_ogr_sql_reprojects_geometry_when_override_active(tmp_path):
    layer = make_layer(tmp_path, projection_override="EPSG:3395")
    assert "ST_Transform(geometry, 3395) AS geometry" in layer.ogr_sql


def test_view_columns_quotes_attribute_names(tmp_path):
    layer = make_layer(
        tmp_path,
        attributes=[TileLayerAttributes(name="class", type=AttributeTypes.STRING)],
    )
    assert layer.view_columns == '"class", geometry'


def test_mbtiles_export_filename_uses_btis_extension_under_override(tmp_path):
    layer = make_layer(tmp_path, projection_override="EPSG:3395")
    assert layer.mbtiles_export_filename.suffix == ".btis"


def test_mbtiles_export_filename_uses_mbtiles_extension_by_default(tmp_path):
    assert make_layer(tmp_path).mbtiles_export_filename.suffix == ".mbtiles"


def test_is_projection_override_active_treats_explicit_3857_as_inactive(tmp_path):
    layer = make_layer(tmp_path, projection_override="EPSG:3857")
    assert layer.is_projection_override_active is False
    assert layer.mbtiles_export_filename.suffix == ".mbtiles"


# --- count_features / layer_summary ---------------------------------------
# Regression tests for a fixed bug (see docs/code-review-findings.md, F3):
# count_features used to return False for a missing table and 0 (falsy)
# for a present-but-empty one, so layer_summary couldn't tell them apart.
# does_table_exist/pg_config.conn are monkeypatched -- no live Postgres.

class _FakeCursor:
    def __init__(self, row):
        self._row = row

    def execute(self, sql):
        pass

    def fetchone(self):
        return self._row


class _FakeConnection:
    def __init__(self, row):
        self._row = row

    def cursor(self):
        return _FakeCursor(self._row)

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


def test_count_features_returns_none_when_table_does_not_exist(tmp_path, monkeypatch):
    layer = make_layer(tmp_path)
    monkeypatch.setattr(TileLayer, "does_table_exist", lambda self, pg_config: False)
    assert layer.count_features(pg_config=layer.pg_config) is None


def test_count_features_returns_zero_for_a_genuinely_empty_table(tmp_path, monkeypatch):
    layer = make_layer(tmp_path)
    monkeypatch.setattr(TileLayer, "does_table_exist", lambda self, pg_config: True)
    monkeypatch.setattr(PGConfig, "conn", property(lambda self: _FakeConnection((0,))))

    count = layer.count_features(pg_config=layer.pg_config)
    assert count == 0
    assert count is not None


def test_layer_summary_distinguishes_missing_table_from_empty_table(tmp_path, monkeypatch, capsys):
    layer = make_layer(tmp_path)

    monkeypatch.setattr(TileLayer, "does_table_exist", lambda self, pg_config: False)
    layer.layer_summary(pg_config=layer.pg_config)
    assert "does not exist" in capsys.readouterr().out

    monkeypatch.setattr(TileLayer, "does_table_exist", lambda self, pg_config: True)
    monkeypatch.setattr(PGConfig, "conn", property(lambda self: _FakeConnection((0,))))
    layer.layer_summary(pg_config=layer.pg_config)
    out = capsys.readouterr().out
    assert "does not exist" not in out
    assert "Feature Count:  0" in out
