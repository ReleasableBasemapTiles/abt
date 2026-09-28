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


def test_conn_str_escapes_quotes_and_backslashes_the_libpq_way():
    # libpq backslash-escapes inside a quoted value; the SQL-style doubling
    # this used to do ('' for ') makes libpq end the value early.
    cfg = make_config(password="it's\\x").with_options("-c application_name='o'")
    assert "password='it\\'s\\\\x'" in cfg.conn_str
    assert cfg.conn_str.endswith("options='-c application_name=\\'o\\''")


def test_conn_str_round_trips_through_libpq():
    from psycopg2.extensions import parse_dsn  # libpq's own PQconninfoParse

    password = "p@ss:w/o'rd\\ #1"
    cfg = make_config(user="u'ser", password=password, database="d b").with_options("-c a='b'")
    parsed = parse_dsn(cfg.conn_str)
    assert parsed["user"] == "u'ser"
    assert parsed["password"] == password
    assert parsed["dbname"] == "d b"
    assert parsed["options"] == "-c a='b'"


def test_uri_percent_encodes_credentials_and_round_trips_through_libpq():
    from psycopg2.extensions import parse_dsn

    password = "p@ss:w/o#rd%"
    cfg = make_config(user="me@corp", password=password, database="d b")
    assert cfg.uri == "postgresql://me%40corp:p%40ss%3Aw%2Fo%23rd%25@localhost:5432/d%20b"
    assert cfg.pguri.startswith("postgis://me%40corp:")
    parsed = parse_dsn(cfg.uri)
    assert (parsed["user"], parsed["password"], parsed["dbname"]) == ("me@corp", password, "d b")


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
