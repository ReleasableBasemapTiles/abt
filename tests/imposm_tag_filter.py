"""A model of imposm3's read-time tag filter, for checking rbt-schema's
mappings against what carto_sql and the mapping filters actually read.

imposm drops every tag it doesn't need while reading the PBF (`-read`),
before anything is cached or written, so an hstore `tags -> 'key'` lookup
in carto_sql, or a require/reject filter key, only ever sees a key that
survived this filter. The rules below mirror imposm3 master:

- mapping/filter.go: NodeTagFilter / WayTagFilter / RelationTagFilter
  decide which table types' mappings and extra tags each element type
  keeps, and tagFilter.Filter keeps a tag if its key is mapped with its
  value (or `__any__`), or if its key is an extra tag.
- mapping/mapping.go: extraTags() collects column `key`/`keys`,
  `filters.exclude_tags` keys, `type` for tables with `relation_types`,
  every `tags.include` key, and always `area`.
- `tags.load_all` switches to "keep everything except `tags.exclude`".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, Optional, Set

import yaml

ANY = "__any__"

# Which table types feed each element type's tag filter (filter.go).
MAPPING_TABLE_TYPES = {
    "node": {"point"},
    "way": {"linestring", "polygon"},
    "relation": {"linestring", "polygon", "relation", "relation_member"},
}
EXTRA_TAG_TABLE_TYPES = {
    "node": {"point", "relation_member"},
    "way": {"linestring", "polygon", "relation_member"},
    "relation": {"linestring", "polygon", "relation", "relation_member"},
}

# Which element types' (filtered) tags a table's filters are evaluated on.
TABLE_ELEMENT_TYPES = {
    "point": {"node"},
    "linestring": {"way"},
    "polygon": {"way", "relation"},
    "relation": {"relation"},
    "relation_member": {"relation"},
    "geometry": {"node", "way", "relation"},
}


@dataclass
class ElementFilter:
    """The keys (and values) one element type's tag filter keeps."""

    mappings: Dict[str, Set[str]] = field(default_factory=dict)
    extra_keys: Set[str] = field(default_factory=set)
    load_all: bool = False
    exclude: Set[str] = field(default_factory=set)

    def keeps(self, key: str, value: Optional[str] = None) -> bool:
        """Whether a tag survives. value=None asks "for every value"."""
        if self.load_all:
            return key not in self.exclude
        if key in self.extra_keys:
            return True
        values = self.mappings.get(key)
        if values is None:
            return False
        if ANY in values:
            return True
        return value is not None and value in values


def _table_type(table: dict) -> str:
    return table.get("type", "")


def _is_type(table: dict, table_types: Set[str]) -> bool:
    # imposm feeds "geometry" tables from every element type.
    return _table_type(table) in table_types or _table_type(table) == "geometry"


def _mapping_pairs(table: dict, element: str) -> Iterable[tuple]:
    sources = [table.get("mapping") or {}]
    sources += [sub.get("mapping") or {} for sub in (table.get("mappings") or {}).values()]
    type_mappings = table.get("type_mappings") or {}
    sources.append(
        {"node": type_mappings.get("points"),
         "way": type_mappings.get("linestrings") or type_mappings.get("polygons")}.get(element) or {}
    )
    for mapping in sources:
        for key, values in mapping.items():
            for value in values or []:
                yield str(key), str(value)


def _extra_keys(table: dict) -> Set[str]:
    keys = set()
    for column in table.get("columns") or []:
        if column.get("key"):
            keys.add(str(column["key"]))
        keys.update(str(k) for k in column.get("keys") or [])
    filters = table.get("filters") or {}
    for pair in filters.get("exclude_tags") or []:
        keys.add(str(pair[0]))
    if _table_type(table) in {"polygon", "relation", "relation_member"} and table.get("relation_types"):
        keys.add("type")
    return keys


def build_filters(tables: Dict[str, dict], base: Optional[dict] = None) -> Dict[str, ElementFilter]:
    """Builds the node/way/relation tag filters imposm would use."""
    tags_conf = (base or {}).get("tags") or {}
    include = {str(k) for k in tags_conf.get("include") or []}
    filters = {}
    for element in ("node", "way", "relation"):
        f = ElementFilter(load_all=bool(tags_conf.get("load_all")),
                          exclude={str(k) for k in tags_conf.get("exclude") or []})
        if element == "relation":
            f.mappings["type"] = {"multipolygon", "boundary", "land_area"}
        for table in tables.values():
            if _is_type(table, MAPPING_TABLE_TYPES[element]):
                for key, value in _mapping_pairs(table, element):
                    f.mappings.setdefault(key, set()).add(value)
            if _is_type(table, EXTRA_TAG_TABLE_TYPES[element]):
                f.extra_keys |= _extra_keys(table)
        f.extra_keys |= include | {"area"}
        filters[element] = f
    return filters


def load_tables(schema_dir: Path) -> Dict[str, dict]:
    """Loads import/osm/*.yml the way abt's ImposmMappingFile does."""
    tables = {}
    osm_dir = schema_dir / "import" / "osm"
    for path in sorted([*osm_dir.glob("*.yml"), *osm_dir.glob("*.yaml")]):
        tables[path.stem] = yaml.safe_load(path.read_text())[path.stem]
    return tables


def load_base(schema_dir: Path) -> dict:
    """Loads the optional top-level mapping settings (import/imposm_base.yml)."""
    for name in ("imposm_base.yml", "imposm_base.yaml"):
        path = schema_dir / "import" / name
        if path.exists():
            return yaml.safe_load(path.read_text()) or {}
    return {}
