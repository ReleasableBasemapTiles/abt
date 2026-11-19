"""setup_ubuntu.sh builds the SQL that creates its Postgres role from PG_USER
and PG_PASSWORD and runs it as the postgres superuser. Both are the
operator's values, and a generated password often holds a quote or a dollar
sign, so whatever is in them has to reach Postgres as data.

pg_role_sql is the function in setup_ubuntu.sh that prints that SQL. It is
lifted out of the script and called on its own here, since the script itself
reconfigures the host it runs on. These tests check the text it prints;
nothing here connects to Postgres.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

SETUP_SH = Path(__file__).resolve().parents[1] / "setup_ubuntu.sh"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")


def _role_sql(role: str, password: str, cwd: Path) -> str:
    script = 'eval "$(sed -n \'/^pg_role_sql() {$/,/^}$/p\' "$1")"; pg_role_sql "$2" "$3"'
    result = subprocess.run(
        ["bash", "-c", script, "_", str(SETUP_SH), role, password],
        capture_output=True, text=True, timeout=30, cwd=cwd,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_a_plain_role_and_password_are_quoted(tmp_path):
    sql = _role_sql("rbt", "s3cret", tmp_path)

    assert "WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'rbt')" in sql
    assert """ALTER ROLE "rbt" WITH LOGIN SUPERUSER PASSWORD 's3cret';""" in sql


def test_a_quote_in_the_password_stays_inside_the_literal(tmp_path):
    sql = _role_sql("rbt", "pa'ss; DROP ROLE postgres; --", tmp_path)

    assert "PASSWORD 'pa''ss; DROP ROLE postgres; --';" in sql


def test_a_dollar_quote_in_the_password_has_no_block_to_close(tmp_path):
    # The role used to be created inside a DO $$ ... $$ block, which a
    # password containing $$ ended early.
    sql = _role_sql("rbt", "a$$b", tmp_path)

    assert "PASSWORD 'a$$b';" in sql
    assert sql.count("$$") == 1


def test_the_shell_expands_nothing_in_the_password(tmp_path):
    password = "$(touch expanded)`touch expanded`$HOME\\n"

    sql = _role_sql("rbt", password, tmp_path)

    assert f"PASSWORD '{password}';" in sql
    assert not (tmp_path / "expanded").exists()


def test_the_role_name_is_quoted_as_an_identifier_and_as_a_literal(tmp_path):
    sql = _role_sql('odd"ro\'le', "pw", tmp_path)

    assert """rolname = 'odd"ro''le'""" in sql
    assert """ALTER ROLE "odd""ro'le" WITH""" in sql


def test_backslashes_in_the_password_are_not_escapes(tmp_path):
    # True only with standard_conforming_strings on, so the SQL turns it on
    # rather than trust the cluster's setting.
    sql = _role_sql("rbt", "back\\slash", tmp_path)

    assert sql.startswith("SET standard_conforming_strings = on;")
    assert "PASSWORD 'back\\slash';" in sql
