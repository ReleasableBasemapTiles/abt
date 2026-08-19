"""Tests for abt.vundler.convert: builds the abt-vundler subprocess argv
correctly and omits --num-workers when unset. run_subprocess itself is
mocked here -- actually running the binary end-to-end is covered by
vundler-rs/tests/test_golden.py and vundler-rs/tests/cli.rs."""

from pathlib import Path
from unittest.mock import MagicMock

import abt.vundler as vundler_module
from abt.vundler import convert
from abt.vundler_model import VundlerConverter


def make_converter(tmp_path: Path) -> VundlerConverter:
    return VundlerConverter(
        mbtiles_path=tmp_path / "in.mbtiles",
        output_dir=tmp_path / "out",
        max_zoom=13,
    )


def test_convert_builds_expected_argv_without_num_workers(tmp_path, monkeypatch):
    mock_run = MagicMock()
    monkeypatch.setattr(vundler_module, "run_subprocess", mock_run)

    converter = make_converter(tmp_path)
    convert(converter, max_workers=None)

    mock_run.assert_called_once()
    kwargs = mock_run.call_args.kwargs
    cmd = kwargs["cmd"]
    assert cmd[0] == "abt-vundler"
    assert "--mbtiles-path" in cmd and str(converter.mbtiles_path) in cmd
    assert "--output-dir" in cmd and str(converter.output_dir) in cmd
    assert "--max-zoom" in cmd and "13" in cmd
    assert "--num-workers" not in cmd
    assert kwargs["layer"] == "vundler"
    assert kwargs["process_stage"] == "vundler"
    assert kwargs["tool_name"] == "abt-vundler"


def test_convert_includes_num_workers_when_given(tmp_path, monkeypatch):
    mock_run = MagicMock()
    monkeypatch.setattr(vundler_module, "run_subprocess", mock_run)

    convert(make_converter(tmp_path), max_workers=8)

    cmd = mock_run.call_args.kwargs["cmd"]
    assert "--num-workers" in cmd
    assert cmd[cmd.index("--num-workers") + 1] == "8"


def test_convert_creates_the_logs_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(vundler_module, "run_subprocess", MagicMock())

    converter = make_converter(tmp_path)
    convert(converter, max_workers=None)

    assert (converter.output_dir / "logs").is_dir()
