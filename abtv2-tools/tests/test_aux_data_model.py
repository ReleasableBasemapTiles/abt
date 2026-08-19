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
