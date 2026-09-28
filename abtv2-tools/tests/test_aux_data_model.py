"""Tests for abt.aux_data_model: AuxDataLayer's url/local_path XOR
validation, and other pure logic (ogr_options splitting, dl_cls/
download_filename dispatch)."""

import pytest
from pydantic import ValidationError

from abt.aux_data_model import AuxDataLayer, AuxLayer, FormatType
from abt.download.downloader import DownloadFile, DownloadOverture


def test_validate_source_rejects_neither_url_nor_local_path():
    with pytest.raises(ValidationError, match="Either 'url' or 'local_path'"):
        AuxDataLayer(folder_name="test", type=FormatType.SHAPEFILE, zipped=False)


def test_validate_source_rejects_both_url_and_local_path():
    with pytest.raises(ValidationError, match="Only one of 'url' or 'local_path'"):
        AuxDataLayer(
            folder_name="test",
            url="https://example.com/data.zip",
            local_path="/data/local.zip",
            type=FormatType.SHAPEFILE,
            zipped=False,
        )


def test_validate_source_accepts_url_only():
    layer = AuxDataLayer(
        folder_name="test", url="https://example.com/data.zip",
        type=FormatType.SHAPEFILE, zipped=True,
    )
    assert layer.is_local is False


def test_validate_source_accepts_local_path_only():
    layer = AuxDataLayer(
        folder_name="test", local_path="/data/local.gpkg",
        type=FormatType.GEOPACKAGE, zipped=False,
    )
    assert layer.is_local is True


def test_dl_cls_raises_for_local_layers():
    layer = AuxDataLayer(
        folder_name="test", local_path="/data/local.gpkg",
        type=FormatType.GEOPACKAGE, zipped=False,
    )
    with pytest.raises(ValueError, match="download is not applicable"):
        _ = layer.dl_cls


def test_dl_cls_returns_download_file_for_non_overture_types():
    layer = AuxDataLayer(
        folder_name="test", url="https://example.com/data.zip",
        type=FormatType.SHAPEFILE, zipped=True,
    )
    assert isinstance(layer.dl_cls, DownloadFile)


def test_dl_cls_returns_download_overture_with_theme_and_type():
    layer = AuxDataLayer(
        folder_name="admins", url="https://example.com/overture",
        type=FormatType.OVERTURE, zipped=False,
        overture_params={"theme": "admins", "type": "locality"},
    )
    dl = layer.dl_cls
    assert isinstance(dl, DownloadOverture)
    assert dl.theme == "admins"
    assert dl.type == "locality"


def test_download_filename_uses_url_basename_for_non_overture(tmp_path):
    layer = AuxDataLayer(
        folder_name="test", url="https://example.com/path/to/data.zip",
        type=FormatType.SHAPEFILE, zipped=True,
    )
    assert layer.download_filename == "data.zip"


def test_download_filename_uses_folder_name_for_overture():
    layer = AuxDataLayer(
        folder_name="admins", url="https://example.com/overture",
        type=FormatType.OVERTURE, zipped=False,
        overture_params={"theme": "admins", "type": "locality"},
    )
    assert layer.download_filename == "admins"


def test_ogr_options_splits_on_spaces():
    layer = AuxLayer(file_name="x", layer_name="x", load_options="-nlt PROMOTE_TO_MULTI -skipfailures")
    assert layer.ogr_options == ["-nlt", "PROMOTE_TO_MULTI", "-skipfailures"]


def test_ogr_options_empty_when_unset():
    layer = AuxLayer(file_name="x", layer_name="x")
    assert layer.ogr_options == []


def test_aux_data_layer_from_dict_builds_aux_load_layers():
    data = {
        "folder_name": "test",
        "url": "https://example.com/data.zip",
        "type": "shp",
        "zipped": True,
        "aux_load": [
            {"aux_file_name": "a.shp", "aux_layer_name": "layer_a"},
            {"aux_folder_name": "b"},
        ],
    }
    layer = AuxDataLayer.from_dict(data)
    assert layer.aux_load[0].file_name == "a.shp"
    assert layer.aux_load[0].layer_name == "layer_a"
    assert layer.aux_load[1].file_name == "b"
    assert layer.aux_load[1].layer_name == "b"


def test_verify_tls_defaults_on_and_reaches_the_downloader():
    layer = AuxDataLayer.from_dict({
        "folder_name": "test", "url": "https://example.com/data.zip", "type": "shp", "zipped": True,
    })
    assert layer.verify_tls is True
    assert layer.dl_cls.verify_tls is True


def test_verify_tls_false_is_scoped_to_its_own_source():
    layer = AuxDataLayer.from_dict({
        "folder_name": "test", "url": "https://example.com/data.zip", "type": "shp", "zipped": True,
        "verify_tls": False,
    })
    assert layer.dl_cls.verify_tls is False


# --- init_importer: prep never runs a tool, and a bad source fails alone -------

def test_filegdb_import_defers_its_conversion_to_the_import_task(tmp_path, monkeypatch):
    # Regression test: the FileGDB -> FlatGeobuf conversion used to run via
    # subprocess.run(check=True) while the job list was built -- serially,
    # unlogged, and aborting every aux import if it failed.
    import abt.aux_data_model as aux_module

    def no_tools(*args, **kwargs):
        raise AssertionError("prep must not run any tool")

    monkeypatch.setattr(aux_module.subprocess, "run", no_tools)
    layer = AuxDataLayer.from_dict({
        "folder_name": "disdi", "url": "https://example.com/x.zip", "type": "gdb", "zipped": True,
        "aux_load": [{"aux_folder_name": "disdi", "aux_source_name": "MirtaLocations",
                      "aux_layer_name": "MirtaLocations", "aux_load_options": "-nlt MULTIPOINT"}],
    })
    (importer,) = layer.init_importer(output_directory=tmp_path, log_dir=tmp_path, pg_string="postgresql://u:p@h:5432/d")
    ogr = importer.importer
    assert ogr.prep_error is None
    assert ogr.pre_output == tmp_path / "MirtaLocations.fgb"
    assert ogr.pre_cmd[:3] == ["ogr2ogr", "-f", "FlatGeobuf"]
    assert ogr.pre_cmd[-1] == "MirtaLocations"
    assert ogr.cmd[-1] == str(tmp_path / "MirtaLocations.fgb")


def test_a_source_that_cannot_be_resolved_fails_only_its_own_layer(tmp_path, monkeypatch):
    import subprocess

    import abt.aux_data_model as aux_module

    def ogrinfo_fails(*args, **kwargs):
        raise subprocess.CalledProcessError(1, args[0])

    monkeypatch.setattr(aux_module.subprocess, "run", ogrinfo_fails)
    layer = AuxDataLayer.from_dict({
        "folder_name": "lsib", "url": "https://example.com/LSIB.gpkg", "type": "gpkg", "zipped": False,
        "aux_load": [
            {"aux_file_name": "LSIB.gpkg", "aux_source_name": "LSIB*", "aux_layer_name": "lsib"},
            {"aux_file_name": "LSIB.gpkg", "aux_source_name": "plain", "aux_layer_name": "plain"},
        ],
    })
    bad, good = layer.init_importer(output_directory=tmp_path, log_dir=tmp_path, pg_string="postgresql://u:p@h:5432/d")
    assert "aux_data.lsib" in bad.importer.prep_error
    assert good.importer.prep_error is None
    assert good.importer.cmd[-1] == "plain"
