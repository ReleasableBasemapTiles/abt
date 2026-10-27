"""Tests for the bundler command's data version: resolve_data_version (a given
version, the UTC-date default, malformed values), init_bundler stamping it
over anything in tile-metadata/metadata.py, and the --data-version option and
ABT_DATA_VERSION variable. The schema, Postgres and the join itself are
replaced."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
import typer
from typer.testing import CliRunner

from abt.cli_funcs import bundler as bundler_cli
from abt.cli_funcs.bundler import init_bundler, resolve_data_version


# --- resolve_data_version -------------------------------------------------

def test_resolve_keeps_a_given_version():
    assert resolve_data_version("2026-10-08.1") == "2026-10-08.1"


def test_resolve_defaults_to_the_utc_date_with_counter_zero():
    now = datetime(2026, 10, 8, 0, 33, 3, tzinfo=timezone.utc)
    assert resolve_data_version(None, now=now) == "2026-10-08.0"


def test_resolve_uses_the_utc_date_not_the_local_one():
    # 8:33 pm on Oct 7 at UTC-4 is already Oct 8 in UTC.
    local = datetime(2026, 10, 7, 20, 33, 3, tzinfo=timezone(timedelta(hours=-4)))
    assert resolve_data_version(None, now=local) == "2026-10-08.0"


@pytest.mark.parametrize(
    "bad_value",
    ["", "2026-10-08", "2026-10-08.", "2026-10-08.x", "2026-1-8.0", "26-10-08.0",
     "2026-10-08.0 ", "v2.0.0", "2026-13-08.0", "2026-02-30.0"],
)
def test_resolve_rejects_malformed_versions(bad_value):
    with pytest.raises(ValueError):
        resolve_data_version(bad_value)


# --- init_bundler ---------------------------------------------------------

@pytest.fixture
def run(tmp_path, monkeypatch):
    """Runs init_bundler against a one-key schema with the schema, Postgres,
    the tile layers and the join replaced; returns the Bundler it built."""
    schema_dir = tmp_path / "schema"
    (schema_dir / "tile-metadata").mkdir(parents=True)
    (schema_dir / "tile-metadata" / "metadata.py").write_text(
        'metadata = {"name": "Test", "version": "9.9.9", "description": "d"}\n'
    )
    built = []
    monkeypatch.setattr(bundler_cli, "DataSchema", lambda base_schema_dir: SimpleNamespace())
    monkeypatch.setattr(bundler_cli, "get_pg_config", lambda cli_input, log_dir: SimpleNamespace())
    monkeypatch.setattr(bundler_cli, "get_tile_layers_for_bundler", lambda **kwargs: [])
    monkeypatch.setattr(bundler_cli, "export_bundled", built.append)

    def go(**kwargs):
        init_bundler(working_dir=tmp_path / "work", schema_dir=schema_dir, **kwargs)
        return built[-1]

    return go


def test_init_bundler_stamps_the_given_version_over_the_schemas(run):
    bundle = run(data_version="2026-10-08.1")
    assert bundle.metadata["version"] == "2026-10-08.1"
    assert bundle.metadata["name"] == "Test"  # the rest of the schema's metadata is kept


def test_init_bundler_defaults_to_todays_utc_date(run):
    before = datetime.now(timezone.utc).strftime("%Y-%m-%d.0")
    bundle = run()
    after = datetime.now(timezone.utc).strftime("%Y-%m-%d.0")
    assert bundle.metadata["version"] in {before, after}


def test_init_bundler_rejects_a_malformed_version_before_creating_anything(run, tmp_path):
    with pytest.raises(ValueError):
        run(data_version="v2")
    assert not (tmp_path / "work").exists()


# --- the command line -----------------------------------------------------

@pytest.fixture
def invoke(tmp_path, monkeypatch):
    """Runs the bundler command with init_bundler replaced; returns
    (result, the keyword arguments init_bundler was called with)."""
    monkeypatch.delenv("ABT_DATA_VERSION", raising=False)
    calls = []
    monkeypatch.setattr(
        bundler_cli, "init_bundler",
        lambda **kwargs: calls.append(kwargs) or SimpleNamespace(overall_status="SUCCESS"),
    )
    # A second command keeps typer from collapsing a one-command app into
    # the command itself, so the tests can name "bundler" as the CLI does.
    app = typer.Typer()
    app.command("bundler")(bundler_cli.cli_bundler)
    app.command("other")(lambda: None)

    def go(*args, env=None):
        result = CliRunner().invoke(
            app, ["bundler", "-w", str(tmp_path / "w"), "-s", str(tmp_path / "s"), *args], env=env,
        )
        return result, calls

    return go


def test_option_passes_the_version_through(invoke):
    result, calls = invoke("--data-version", "2026-10-08.1")
    assert result.exit_code == 0, result.output
    assert calls[0]["data_version"] == "2026-10-08.1"


def test_environment_variable_supplies_the_version(invoke):
    result, calls = invoke(env={"ABT_DATA_VERSION": "2026-10-08.2"})
    assert result.exit_code == 0, result.output
    assert calls[0]["data_version"] == "2026-10-08.2"


def test_option_wins_over_the_environment_variable(invoke):
    result, calls = invoke("--data-version", "2026-10-08.1", env={"ABT_DATA_VERSION": "2026-10-08.2"})
    assert result.exit_code == 0, result.output
    assert calls[0]["data_version"] == "2026-10-08.1"


def test_no_option_leaves_the_version_to_the_default(invoke):
    result, calls = invoke()
    assert result.exit_code == 0, result.output
    assert calls[0]["data_version"] is None


def test_malformed_option_is_rejected_before_anything_runs(invoke):
    result, calls = invoke("--data-version", "latest")
    assert result.exit_code != 0
    assert calls == []
