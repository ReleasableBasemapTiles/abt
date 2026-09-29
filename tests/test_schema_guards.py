"""Cross-checks between rbt-schema and abtv2-tools that nothing enforces at
run time until hours into a build, or ever:

- export/<file>.json's layer_id must name an export.* table or view that
  carto_sql creates. The binding is by name alone, so a typo on either side
  makes the layer fail at export, after every earlier stage has run.
- A script that reads abt.dissolve_shards must never shard by a literal
  count. Its fan-out loops run 0 .. abt.dissolve_shards - 1, so a shard
  column computed `% 16` leaves every shard past the setting unprocessed,
  and those rows are silently missing from the output.
- execution_plan.yml must cover every carto_sql script exactly once, with
  weights only for scripts in its groups. `carto` runs this check itself
  only before it runs the groups (a plan and -n above 1); at -n 1, the
  default below 12 vCPUs, it runs every script in filename order and never
  checks. Running it here on the real schema makes a drift fail in CI
  whatever -n a build would use.
- A group script may only create a schema or extension that the plan
  creates up front, so concurrent groups never race to create it first.
"""

import json
import re
import sys
from pathlib import Path

import pytest

REPO_DIR = Path(__file__).resolve().parents[1]
SCHEMA_DIR = REPO_DIR / "rbt-schema"
CARTO_SQL_DIR = SCHEMA_DIR / "carto_sql"

sys.path.insert(0, str(REPO_DIR / "abtv2-tools"))

from abt.carto_processing_model import CartoExecutionPlan, CartoProcessingModel  # noqa: E402
from abt.schema import DataSchema  # noqa: E402
from abt.utils.pg_config import PGConfig  # noqa: E402

CREATES_EXPORT_RELATION = re.compile(
    r"\bCREATE\s+(?:MATERIALIZED\s+VIEW|(?:UNLOGGED\s+)?TABLE|VIEW)\s+(?:IF\s+NOT\s+EXISTS\s+)?export\.(\w+)",
    re.IGNORECASE,
)
# `x % 16`, `x %% 16` (a modulus inside format()) or mod(x, 16), but not a
# positional format() placeholder such as %1$s.
LITERAL_MODULUS = re.compile(
    r"%{1,2}\s*(\d+)(?![\d$])|\bmod\s*\((?:[^,()]|\([^()]*\))+,\s*(\d+)\s*\)", re.IGNORECASE
)
CREATES_SCHEMA = re.compile(r"\bCREATE\s+SCHEMA\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)", re.IGNORECASE)
CREATES_EXTENSION = re.compile(r"\bCREATE\s+EXTENSION\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)", re.IGNORECASE)


def strip_comments_and_literals(text: str) -> str:
    """SQL without its -- comments and single-quoted literals, which mention
    table names and shard counts without acting on them."""
    text = re.sub(r"--[^\n]*", "", text)
    return re.sub(r"'(?:[^']|'')*'", "''", text)


def sql_code(path: Path) -> str:
    return strip_comments_and_literals(path.read_text())


def carto_sql_scripts():
    return sorted(CARTO_SQL_DIR.glob("*.sql"))


def literal_moduli(code: str):
    return [a or b for a, b in LITERAL_MODULUS.findall(code)]


@pytest.fixture(scope="module")
def plan():
    return CartoExecutionPlan.load(CARTO_SQL_DIR / "execution_plan.yml")


def test_every_export_layer_has_a_carto_sql_relation():
    created = {name for sql in carto_sql_scripts() for name in CREATES_EXPORT_RELATION.findall(sql_code(sql))}
    layer_ids = {
        path.name: json.loads(path.read_text())["layer_id"] for path in sorted((SCHEMA_DIR / "export").glob("*.json"))
    }
    assert layer_ids, "no export/*.json found"
    missing = {name: layer_id for name, layer_id in layer_ids.items() if layer_id not in created}
    assert not missing, f"layer_ids with no CREATE ... export.<layer_id> in carto_sql: {missing}"


@pytest.mark.parametrize(
    "code, moduli",
    [
        ("(row_number() OVER (ORDER BY n DESC) - 1) % 16 AS shard", ["16"]),
        ("WHERE abs(osm_id) %% 16 = %s", ["16"]),
        ("WHERE mod(abs(osm_id), 16) = 0", ["16"]),
        ("abs(osm_id) % COALESCE(current_setting('abt.dissolve_shards', true)::int, 16)", []),
        ("WHERE abs(osm_id) %% %s = %s", []),
        ("SELECT %1$s, %2$s FROM t", []),
    ],
)
def test_literal_modulus_detection(code, moduli):
    assert literal_moduli(strip_comments_and_literals(code)) == moduli


def test_dissolve_shard_readers_never_shard_by_a_literal_count():
    readers = [sql for sql in carto_sql_scripts() if "abt.dissolve_shards" in sql.read_text()]
    assert readers, "no carto_sql script reads abt.dissolve_shards any more; retire this test"
    offenders = {sql.name: literal_moduli(sql_code(sql)) for sql in readers}
    offenders = {name: moduli for name, moduli in offenders.items() if moduli}
    assert not offenders, (
        "modulus by a literal in a script that reads abt.dissolve_shards; use "
        f"COALESCE(current_setting('abt.dissolve_shards', true)::int, 16) instead: {offenders}"
    )


def test_execution_plan_covers_every_carto_sql_script(plan, tmp_path):
    assert plan is not None, "carto_sql/execution_plan.yml is missing"
    data_schema = DataSchema(base_schema_dir=SCHEMA_DIR)
    carto = CartoProcessingModel(
        sql_files=data_schema.carto_sql_layers,
        pg_config=PGConfig(host="localhost", port=5432, user="u", password="p", database="d", log_path=tmp_path),
        log_dir=tmp_path,
        execution_plan_path=data_schema.carto_execution_plan_path,
    )
    carto._validate_plan_covers_all_files(plan)


def test_group_scripts_only_create_schemas_and_extensions_the_plan_creates(plan):
    group_scripts = {name for group in plan.groups for name in group}
    unplanned = {}
    for sql in carto_sql_scripts():
        if sql.name not in group_scripts:
            continue
        code = sql_code(sql)
        schemas = set(CREATES_SCHEMA.findall(code)) - set(plan.custom_schemas)
        extensions = set(CREATES_EXTENSION.findall(code)) - set(plan.extensions)
        if schemas or extensions:
            unplanned[sql.name] = sorted(schemas | extensions)
    assert not unplanned, (
        "group scripts create schemas/extensions missing from execution_plan.yml's "
        f"custom_schemas/extensions: {unplanned}"
    )
