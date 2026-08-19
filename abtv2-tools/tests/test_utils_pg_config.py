"""Tests for abt.utils.pg_config.PGConfig -- string-building logic only
(conn_str/uri/pguri/with_options/schema names). The DB-touching methods
(conn, osm_populated, reset_aux_schema, test_sql, execute_sql,
runSQLScript) need a live Postgres and are out of scope here.
"""

from pathlib import Path

from abt.utils.pg_config import PGConfig


def make_config(**overrides) -> PGConfig:
    defaults = dict(
        host="localhost", port=5432, user="u", password="p", database="d",
        log_path=Path("/tmp"),
    )
    defaults.update(overrides)
    return PGConfig(**defaults)


def test_conn_str_without_extra_options():
    cfg = make_config()
    assert cfg.conn_str == "host=localhost port=5432 user='u' password='p' dbname='d'"


def test_conn_str_with_extra_options_appended():
    cfg = make_config().with_options("statement_timeout=5000")
    assert cfg.conn_str == (
        "host=localhost port=5432 user='u' password='p' dbname='d' "
        "options='statement_timeout=5000'"
    )


def test_conn_str_escapes_single_quotes_in_extra_options():
    raw = "app_name='o''brien'"
    cfg = make_config().with_options(raw)
    escaped = raw.replace("'", "''")
    assert cfg.conn_str.endswith(f"options='{escaped}'")


def test_with_options_returns_a_new_instance_and_leaves_original_untouched():
    base = make_config()
    derived = base.with_options("foo=bar")
    assert base.extra_options == ""
    assert derived.extra_options == "foo=bar"
    assert base is not derived


def test_uri_and_pguri_format():
    cfg = make_config()
    assert cfg.uri == "postgresql://u:p@localhost:5432/d"
    assert cfg.pguri == "postgis://u:p@localhost:5432/d"


def test_schema_name_constants():
    cfg = make_config()
    assert cfg.osm_schema == "osm"
    assert cfg.aux_schema == "aux_data"
    assert cfg.export_schema == "export"


def test_from_input_builds_expected_config_and_coerces_numeric_port():
    cfg = PGConfig.from_input(
        host="h", port="1234", user="u", password="p", database="d",
        log_path=Path("/tmp"),
    )
    assert cfg.host == "h"
    assert cfg.port == 1234
    assert isinstance(cfg.port, int)
    assert cfg.database == "d"
