"""Tests for abt.schema.DataSchema: required-subdirectory validation and
the file-discovery properties built on top of it. Uses real directories
under tmp_path -- these are pure filesystem checks, not worth mocking."""

import pytest
from pydantic import ValidationError

from abt.schema import DataSchema


def make_valid_schema_dir(base):
    for sub in ("import", "import/osm", "import/aux_data", "export", "carto_sql"):
        (base / sub).mkdir(parents=True, exist_ok=True)
    return base


def test_data_schema_accepts_a_directory_with_all_required_subdirs(tmp_path):
    make_valid_schema_dir(tmp_path)
    schema = DataSchema(base_schema_dir=tmp_path)
    assert schema.base_schema_dir == tmp_path


def test_data_schema_rejects_a_directory_missing_required_subdirs(tmp_path):
    (tmp_path / "import").mkdir()  # only some, not all, required subdirs
    with pytest.raises(ValidationError, match="directories are missing"):
        DataSchema(base_schema_dir=tmp_path)


def test_data_schema_error_lists_every_missing_directory(tmp_path):
    (tmp_path / "export").mkdir()
    with pytest.raises(ValidationError) as exc_info:
        DataSchema(base_schema_dir=tmp_path)
    message = str(exc_info.value)
    assert "import" in message
    assert "carto_sql" in message


def test_aux_import_dir_property(tmp_path):
    make_valid_schema_dir(tmp_path)
    schema = DataSchema(base_schema_dir=tmp_path)
    assert schema.aux_import_dir == tmp_path / "import" / "aux_data"


def test_imposm_mapping_files_raises_when_none_found(tmp_path):
    make_valid_schema_dir(tmp_path)
    schema = DataSchema(base_schema_dir=tmp_path)
    with pytest.raises(FileNotFoundError):
        _ = schema.imposm_mapping_files


def test_imposm_mapping_files_finds_yaml_and_yml(tmp_path):
    make_valid_schema_dir(tmp_path)
    (tmp_path / "import" / "osm" / "roads.yml").write_text("roads: {}")
    (tmp_path / "import" / "osm" / "water.yaml").write_text("water: {}")
    schema = DataSchema(base_schema_dir=tmp_path)
    names = {p.name for p in schema.imposm_mapping_files}
    assert names == {"roads.yml", "water.yaml"}


def test_aux_files_returns_empty_list_without_erroring_when_none_present(tmp_path):
    make_valid_schema_dir(tmp_path)
    schema = DataSchema(base_schema_dir=tmp_path)
    assert schema.aux_files == []


def test_carto_sql_layers_raises_when_none_found(tmp_path):
    make_valid_schema_dir(tmp_path)
    schema = DataSchema(base_schema_dir=tmp_path)
    with pytest.raises(FileNotFoundError):
        _ = schema.carto_sql_layers


def test_carto_sql_layers_are_sorted(tmp_path):
    make_valid_schema_dir(tmp_path)
    (tmp_path / "carto_sql" / "010_park.sql").write_text("-- park")
    (tmp_path / "carto_sql" / "003_road.sql").write_text("-- road")
    schema = DataSchema(base_schema_dir=tmp_path)
    names = [p.name for p in schema.carto_sql_layers]
    assert names == ["003_road.sql", "010_park.sql"]


def test_carto_execution_plan_path_is_conventional_and_need_not_exist(tmp_path):
    make_valid_schema_dir(tmp_path)
    schema = DataSchema(base_schema_dir=tmp_path)
    assert schema.carto_execution_plan_path == tmp_path / "carto_sql" / "execution_plan.yml"
    assert not schema.carto_execution_plan_path.exists()


def test_export_layers_raises_when_none_found(tmp_path):
    make_valid_schema_dir(tmp_path)
    schema = DataSchema(base_schema_dir=tmp_path)
    with pytest.raises(FileNotFoundError):
        _ = schema.export_layers
