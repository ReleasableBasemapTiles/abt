"""Tests for abt.cli_funcs.vundler.resolve_input: explicit-path vs
default-location resolution."""

import pytest

from abt.cli_funcs.vundler import resolve_input


def test_resolve_input_returns_explicit_path_without_touching_disk(tmp_path):
    explicit = tmp_path / "somewhere" / "custom.mbtiles"  # deliberately does not exist
    assert resolve_input(tmp_path, explicit) == explicit


def test_resolve_input_finds_joined_mbtiles_in_default_location(tmp_path):
    bundled_dir = tmp_path / "bundled"
    bundled_dir.mkdir()
    joined = bundled_dir / "joined.mbtiles"
    joined.write_bytes(b"")
    assert resolve_input(tmp_path, None) == joined


def test_resolve_input_falls_back_to_joined_btis(tmp_path):
    bundled_dir = tmp_path / "bundled"
    bundled_dir.mkdir()
    joined_btis = bundled_dir / "joined.btis"
    joined_btis.write_bytes(b"")
    assert resolve_input(tmp_path, None) == joined_btis


def test_resolve_input_prefers_mbtiles_over_btis_when_both_exist(tmp_path):
    bundled_dir = tmp_path / "bundled"
    bundled_dir.mkdir()
    (bundled_dir / "joined.mbtiles").write_bytes(b"")
    (bundled_dir / "joined.btis").write_bytes(b"")
    assert resolve_input(tmp_path, None) == bundled_dir / "joined.mbtiles"


def test_resolve_input_raises_when_neither_file_exists(tmp_path):
    with pytest.raises(FileNotFoundError, match="No joined.mbtiles or joined.btis"):
        resolve_input(tmp_path, None)
