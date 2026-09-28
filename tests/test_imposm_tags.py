"""Every OSM tag key that carto_sql or a mapping filter reads must survive
imposm's read-time tag filter (see imposm_tag_filter.py).

A key that doesn't survive is silently NULL in every hstore `tags` column,
and a require/reject filter on it never matches, with no error anywhere.
When one of these tests fails, add the key to
rbt-schema/import/imposm_base.yml's `tags: include:` list (or map it or use
it for a column), then re-import.
"""

import re
from pathlib import Path

import pytest

from imposm_tag_filter import TABLE_ELEMENT_TYPES, ANY, build_filters, load_base, load_tables

SCHEMA_DIR = Path(__file__).resolve().parents[1] / "rbt-schema"

# `tags -> 'key'` (hstore has no ->>, but accept it), `tags ? 'key'`,
# exist(tags, 'key') and defined(tags, 'key').
HSTORE_KEY_READS = [
    re.compile(r"\btags\s*->>?\s*'([^']+)'"),
    re.compile(r"\btags\s*\?\s*'([^']+)'"),
    re.compile(r"\b(?:exist|defined)\s*\(\s*[\w.]*\btags\s*,\s*'([^']+)'\s*\)"),
]


@pytest.fixture(scope="module")
def tables():
    return load_tables(SCHEMA_DIR)


@pytest.fixture(scope="module")
def filters(tables):
    return build_filters(tables, load_base(SCHEMA_DIR))


def carto_sql_hstore_keys():
    keys = {}
    for sql in sorted((SCHEMA_DIR / "carto_sql").glob("*.sql")):
        text = re.sub(r"--[^\n]*", "", sql.read_text())
        for pattern in HSTORE_KEY_READS:
            for key in pattern.findall(text):
                keys.setdefault(key, set()).add(sql.name)
    return keys


def test_carto_sql_hstore_reads_are_found():
    # Guards the extraction itself: if the SQL's style changes and the
    # patterns stop matching, the real test below would pass vacuously.
    assert len(carto_sql_hstore_keys()) > 50


def test_every_hstore_key_carto_sql_reads_is_loaded(filters):
    missing = {
        key: sorted(scripts)
        for key, scripts in carto_sql_hstore_keys().items()
        if not any(f.keeps(key) for f in filters.values())
    }
    assert not missing, (
        "carto_sql reads these hstore keys, but imposm drops them at -read time "
        f"(add them to import/imposm_base.yml tags.include): {missing}"
    )


def test_every_mapping_filter_key_is_loaded(tables, filters):
    missing = []
    for name, table in tables.items():
        table_filters = table.get("filters") or {}
        for kind in ("require", "reject"):
            for key, values in (table_filters.get(kind) or {}).items():
                for element in TABLE_ELEMENT_TYPES[table["type"]]:
                    for value in values or [ANY]:
                        if not filters[element].keeps(key, None if value == ANY else str(value)):
                            missing.append(f"{name}: {kind} {key}={value} ({element}s)")
    assert not missing, (
        "these filter keys are dropped before the filter runs, so the filter never "
        f"fires (add them to import/imposm_base.yml tags.include): {missing}"
    )


# --- the model itself -------------------------------------------------------

def test_model_keeps_mapped_values_column_keys_and_includes_only():
    tables = {
        "roads": {"type": "linestring", "mapping": {"highway": ["primary"]},
                  "columns": [{"name": "name", "key": "name", "type": "string"}],
                  "filters": {"reject": {"covered": ["yes"]}}},
        "pois": {"type": "point", "mapping": {"amenity": [ANY]}, "columns": []},
    }
    way = build_filters(tables)["way"]
    assert way.keeps("highway", "primary")
    assert not way.keeps("highway", "service")
    assert way.keeps("name")
    assert way.keeps("area")
    # Filter keys are not loaded, and point mappings don't reach ways.
    assert not way.keeps("covered", "yes")
    assert not way.keeps("amenity", "cafe")
    assert build_filters(tables)["node"].keeps("amenity", "cafe")

    with_include = build_filters(tables, {"tags": {"include": ["covered"]}})
    assert all(f.keeps("covered", "yes") for f in with_include.values())


def test_model_relation_filter_keeps_multipolygon_type_and_load_all_keeps_everything():
    relation = build_filters({})["relation"]
    assert relation.keeps("type", "multipolygon")
    assert not relation.keeps("type", "route")

    load_all = build_filters({}, {"tags": {"load_all": True, "exclude": ["created_by"]}})
    assert load_all["way"].keeps("anything", "at_all")
    assert not load_all["way"].keeps("created_by", "JOSM")
