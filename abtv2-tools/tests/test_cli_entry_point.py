"""Tests for abt-tools.py's root callback, which raises the open-file limit
for every command rather than only the ones that need it most.

The entry point is loaded by path rather than imported: "abt-tools.py" isn't
a valid module name, and the callback's registration on the root Typer app
is the whole guarantee under test, so there's nothing else to assert
against.
"""

import importlib.util
from pathlib import Path

import pytest
from typer.testing import CliRunner

from abt.cli_funcs import export_tiles

ENTRY_POINT = Path(__file__).resolve().parent.parent / "abt-tools.py"


@pytest.fixture
def entry_point():
    spec = importlib.util.spec_from_file_location("abt_tools_entry", ENTRY_POINT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def recorded_raises(entry_point, monkeypatch):
    """Stubs out the real setrlimit call, recording that it was made."""
    calls = []

    def fake_raise():
        calls.append(True)
        return 1024, 1048576

    monkeypatch.setattr(entry_point, "raise_open_file_limit", fake_raise)
    return calls


class FakeReporter:
    overall_status = "SUCCESS"


@pytest.fixture
def stubbed_export(monkeypatch):
    """Keeps `export` from doing any real work when invoked."""
    monkeypatch.setattr(export_tiles, "init_exporter", lambda **kwargs: FakeReporter())


def test_callback_is_registered_on_the_root_app(entry_point):
    # Click runs a group's callback ahead of whichever subcommand was
    # named, so registering it here is what makes the limit apply to every
    # command uniformly.
    assert entry_point.app.registered_callback.callback is entry_point.cli_root


def test_limit_is_raised_before_a_command_runs(
    tmp_path, entry_point, recorded_raises, stubbed_export
):
    result = CliRunner().invoke(
        entry_point.app,
        ["export", "-w", str(tmp_path), "-s", str(tmp_path), "-p", "env"],
    )
    assert result.exit_code == 0, result.output
    assert recorded_raises == [True]


def test_limit_is_reported_on_stderr_not_stdout(entry_point, recorded_raises, capsys):
    entry_point.cli_root()
    captured = capsys.readouterr()
    assert "Open file limit: 1048576 (was 1024)" in captured.err
    assert captured.out == ""
