"""MkDocs hook: regenerate docs/schema/database.md from rbt-schema/carto_sql/*.sql
header comments and rbt-schema/export/*.json.

Every layer-building script in rbt-schema/carto_sql/ carries a structured
header (see docs/schema/carto-sql.md):

    -- LAYER: Water — Polygons
    -- Schema:        export
    -- Intermediates: water.water_surface
    --                water.valid_ocean
    -- Sources:       osm.osm_water_polygon
    --                aux_data.osm_ocean

This hook parses that header (30 of the 33 scripts have one; the exceptions
are the sequential prefix/suffix scripts 000_/001_/099_, which build no
layer of their own) plus each script's own `CREATE MATERIALIZED VIEW
export.*` statements, cross-references them against rbt-schema/export/*.json
(for geometry type, zoom range, and whether a view is actually tiled), and
renders one Mermaid flowchart + table per theme -- mirroring
https://mjj203.github.io/rbt-data-generator/database-schema/, but generated
instead of hand-written, since this schema's header comments are
structured enough to make that possible.

The file is only rewritten when its content changes, which keeps `mkdocs
serve` from rebuild-looping.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CARTO_SQL_DIR = REPO_ROOT / "rbt-schema" / "carto_sql"
EXPORT_DIR = REPO_ROOT / "rbt-schema" / "export"
EXECUTION_PLAN_PATH = CARTO_SQL_DIR / "execution_plan.yml"

# Scripts with no LAYER header: the sequential prefix/suffix, not a layer.
NON_LAYER_SCRIPTS = {"000_update_aux_geom", "001_set_schema", "099_update_geometry"}

# Every layer-building script, grouped into the same nine themes the
# reference page uses. Deliberately exhaustive -- on_pre_build() raises if
# any script on disk is missing here, or if this lists one that no longer
# exists, rather than silently under- or over-covering the schema.
THEMES: list[tuple[str, list[str]]] = [
    ("Water & hydrography", [
        "005a_water_polygon", "005b_water_line", "006_geonames_hydrographic", "033_culvert",
    ]),
    ("Terrain, landcover & parks", [
        "008_glacier", "009_land_cover", "010_park", "029_physical_labels",
    ]),
    ("Boundaries & places", [
        "026_places", "027_admin",
    ]),
    ("Transportation", [
        "003_road", "004_railway", "028_ferry", "011_lock", "030_pier",
    ]),
    ("Aviation & ports", [
        "021_aeroway", "012_port",
    ]),
    ("Built-up areas & land use", [
        "007_builtup_area", "024_cemetery", "025_sports",
    ]),
    ("Infrastructure & utilities", [
        "013_pipeline", "014_energy", "015_grain_storage", "017_utility_point",
        "018_powerline", "019_power_station", "020_pumping_station", "022_dam",
    ]),
    ("Military & security", [
        "023_military",
    ]),
    ("Points of interest", [
        "032_poi",
    ]),
]

# -- Header parsing -----------------------------------------------------
#
# A header field is any "-- Label: value" line; its value continues on
# subsequent "--"-prefixed lines until the next such line, a divider
# ("-- ===...==="), or the first non-comment line. This is deliberately
# permissive about the *label* (LAYER/Schema/Intermediates/Sources, but
# also one-off fields like "Depends on:"/"Outputs:"/"Source layer:" that a
# few scripts add) -- in every script as of this writing, prose that would
# otherwise run on past the real Sources:/Intermediates: content happens to
# start a new "-- Something:"-shaped line first (e.g. 022_dam.sql's "Build
# order matters:", 033_culvert.sql's "Captures culvert nodes via two OSM
# tagging patterns:"), which naturally closes off the field before the
# prose. Token extraction below is additionally constrained to a schema
# allow-list specifically so free-form prose elsewhere in a field's text
# (e.g. "GeoNames." in 026_places.sql's methodology block) can never be
# mistaken for a real source/intermediate reference.
FIELD_LABEL_RE = re.compile(r"^--\s*([A-Za-z][A-Za-z ]*?):\s*(.*)$")
DIVIDER_RE = re.compile(r"^--\s*=+\s*$")

# Sources are always osm.* (imposm3) or aux_data.* (ogr2ogr) -- the two
# schemas `import` populates directly. See docs/schema/index.md.
SOURCE_TOKEN_RE = re.compile(r"\b(osm|aux_data)\.([a-z_][a-z_0-9]*)\b")

# CREATE MATERIALIZED VIEW <schema>.<name> -- this is executable SQL, not
# prose, so no allow-list constraint is needed here.
CMV_RE = re.compile(
    r"CREATE MATERIALIZED VIEW\s+(?:IF NOT EXISTS\s+)?([a-z_]+)\.([a-z_0-9]+)",
    re.IGNORECASE,
)

# A "(...)" immediately after a source token, on the same line, is kept as
# an edge annotation (e.g. "osm.osm_highway_linestring (surface
# enrichment)" in 022_dam.sql) -- only applied to Sources, since
# Intermediates: lines are messier (ranges, "/"-separated siblings; see
# 009_land_cover.sql) and aren't rendered with edge labels anyway.
ANNOTATION_RE = re.compile(r"\(([^)]+)\)")
ANNOTATION_MAX_DISTANCE = 40

HEADER = """\
<!-- THIS FILE IS GENERATED by docs/_hooks/gen_db_schema.py at docs build
     time from rbt-schema/carto_sql/*.sql header comments and
     rbt-schema/export/*.json. Edit those files, not this one -- `mkdocs
     build` regenerates it, and a committed copy is kept so the page is
     browsable on GitHub without running a build. -->

# Database Schema

This page documents the PostgreSQL schemas `carto` builds and traces every
`export.*` materialized view back to the `osm.*`/`aux_data.*` source tables
and carto-owned intermediate schemas it's built from. It's generated from
each [`carto_sql/*.sql`](carto-sql.md) script's own header comment (`LAYER`/
`Sources`/`Intermediates`) plus its `CREATE MATERIALIZED VIEW` statements,
cross-referenced against [`export/*.json`](layers.md) for geometry type,
zoom range, and whether a view is actually tiled -- so it can't drift from
the SQL. See [Adding a Layer](adding-a-layer.md) for the workflow this
schema supports.

"""


def _build_intermediate_token_re(custom_schemas: list[str]) -> re.Pattern:
    alternation = "|".join(re.escape(s) for s in custom_schemas)
    return re.compile(rf"\b({alternation})\.([a-z_][a-z_0-9]*)\b")


def _extract_tokens(field_text: str, token_re: re.Pattern, *, with_annotations: bool) -> list[tuple[str, str | None]]:
    results: list[tuple[str, str | None]] = []
    seen: set[str] = set()
    for line in field_text.splitlines():
        for m in token_re.finditer(line):
            token = f"{m.group(1)}.{m.group(2)}"
            if token in seen:
                continue
            seen.add(token)
            annotation = None
            if with_annotations:
                ann_m = ANNOTATION_RE.search(line[m.end():])
                if ann_m and ann_m.start() < ANNOTATION_MAX_DISTANCE:
                    annotation = ann_m.group(1).strip()
            results.append((token, annotation))
    return results


def _parse_script(path: Path, intermediate_token_re: re.Pattern) -> dict | None:
    lines = path.read_text(encoding="utf-8").splitlines()

    start = None
    for i, line in enumerate(lines):
        m = FIELD_LABEL_RE.match(line)
        if m and m.group(1).strip().upper() == "LAYER":
            start = i
            break
    if start is None:
        return None

    end = len(lines)
    for i in range(start, len(lines)):
        if i > start and DIVIDER_RE.match(lines[i]):
            end = i
            break
        if not (lines[i].startswith("--") or lines[i].strip() == ""):
            end = i
            break

    fields: dict[str, list[str]] = {}
    current: str | None = None
    for line in lines[start:end]:
        m = FIELD_LABEL_RE.match(line)
        if m:
            current = m.group(1).strip()
            fields.setdefault(current, []).append(m.group(2))
        elif current is not None:
            fields[current].append(line[2:] if line.startswith("--") else line)

    sources = _extract_tokens("\n".join(fields.get("Sources", [])), SOURCE_TOKEN_RE, with_annotations=True)
    intermediates = _extract_tokens(
        "\n".join(fields.get("Intermediates", [])), intermediate_token_re, with_annotations=False
    )

    text = path.read_text(encoding="utf-8")
    export_views = [name for schema, name in CMV_RE.findall(text) if schema == "export"]

    return {
        "stem": path.stem,
        "layer": (fields.get("LAYER") or [""])[0].strip(),
        "sources": sources,
        "intermediates": intermediates,
        "export_views": export_views,
    }


def _parse_all_scripts(intermediate_token_re: re.Pattern) -> dict[str, dict]:
    scripts: dict[str, dict] = {}
    for path in sorted(CARTO_SQL_DIR.glob("*.sql")):
        if path.stem in NON_LAYER_SCRIPTS:
            continue
        parsed = _parse_script(path, intermediate_token_re)
        if parsed is None:
            raise ValueError(
                f"{path.name} has no '-- LAYER:' header and isn't in "
                f"gen_db_schema.py's NON_LAYER_SCRIPTS -- add a header, or "
                f"add it to NON_LAYER_SCRIPTS if it genuinely builds no layer."
            )
        scripts[parsed["stem"]] = parsed
    return scripts


def _validate_theme_coverage(scripts: dict[str, dict]) -> None:
    themed = [stem for _, stems in THEMES for stem in stems]
    themed_set = set(themed)
    if len(themed) != len(themed_set):
        dupes = sorted({s for s in themed if themed.count(s) > 1})
        raise ValueError(f"gen_db_schema.py's THEMES lists these scripts more than once: {dupes}")
    all_stems = set(scripts)
    missing = all_stems - themed_set
    if missing:
        raise ValueError(
            f"gen_db_schema.py's THEMES doesn't cover these carto_sql scripts: "
            f"{sorted(missing)} -- add each to a theme."
        )
    stale = themed_set - all_stems
    if stale:
        raise ValueError(
            f"gen_db_schema.py's THEMES lists scripts that no longer exist "
            f"under carto_sql/: {sorted(stale)} -- remove them."
        )


def _load_export_layers() -> tuple[dict[str, dict], set[str]]:
    """Returns (layer_id -> export/*.json config, set of skipped layer_ids)."""
    layers: dict[str, dict] = {}
    for path in sorted(EXPORT_DIR.glob("*.json")):
        config = json.loads(path.read_text(encoding="utf-8"))
        layers[config["layer_id"]] = config
    skipped: set[str] = set()
    for path in sorted(EXPORT_DIR.glob("*.json.skip")):
        config = json.loads(path.read_text(encoding="utf-8"))
        skipped.add(config.get("layer_id", Path(path.stem).stem))
    return layers, skipped


def _mermaid_id(token: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", token)


def _quote_label(text: str) -> str:
    return text.replace('"', "'")


def _render_theme_diagram(stems: list[str], scripts: dict[str, dict]) -> str:
    osm_nodes: dict[str, str] = {}
    aux_nodes: dict[str, str] = {}
    lines = ["```mermaid", "flowchart LR"]

    for stem in stems:
        script = scripts[stem]
        script_id = f"script_{_mermaid_id(stem)}"
        for token, _ in script["sources"]:
            node_id = _mermaid_id(token)
            bucket = osm_nodes if token.startswith("osm.") else aux_nodes
            bucket[node_id] = token

    if osm_nodes:
        lines.append('    subgraph src_osm ["osm"]')
        for node_id, token in osm_nodes.items():
            lines.append(f'        {node_id}["{_quote_label(token)}"]')
        lines.append("    end")
    if aux_nodes:
        lines.append('    subgraph src_aux ["aux_data"]')
        for node_id, token in aux_nodes.items():
            lines.append(f'        {node_id}["{_quote_label(token)}"]')
        lines.append("    end")

    for stem in stems:
        script = scripts[stem]
        script_id = f"script_{_mermaid_id(stem)}"
        script_label = _quote_label(f"{script['layer']}<br/>({stem}.sql)")
        lines.append(f'    {script_id}["{script_label}"]')
        for token, annotation in script["sources"]:
            source_id = _mermaid_id(token)
            if annotation:
                lines.append(f'    {source_id} -->|"{_quote_label(annotation)}"| {script_id}')
            else:
                lines.append(f"    {source_id} --> {script_id}")
        for token, _ in script["intermediates"]:
            inter_id = f"inter_{_mermaid_id(token)}"
            lines.append(f'    {inter_id}["{_quote_label(token)}"]')
            lines.append(f"    {script_id} --> {inter_id}")
        for view in script["export_views"]:
            view_id = f"export_{_mermaid_id(view)}"
            lines.append(f'    {view_id}["export.{view}"]')
            lines.append(f"    {script_id} --> {view_id}")

    lines.append("```")
    return "\n".join(lines) + "\n"


def _render_theme_table(stems: list[str], scripts: dict[str, dict], layers: dict[str, dict], skipped: set[str]) -> str:
    lines = [
        "| Export view | Built by | Sources | Intermediates | Geometry | Zoom | Tiled |",
        "|---|---|---|---|---|---|---|",
    ]
    for stem in stems:
        script = scripts[stem]
        sources_cell = "<br/>".join(
            f"`{token}` ({_quote_label(ann)})" if ann else f"`{token}`" for token, ann in script["sources"]
        ) or "—"
        intermediates_cell = "<br/>".join(f"`{token}`" for token, _ in script["intermediates"]) or "—"
        for view in script["export_views"]:
            layer_config = layers.get(view)
            if layer_config is not None:
                geometry = layer_config.get("geometry_type", "—")
                tippecanoe = layer_config.get("tippecanoe_options") or {}
                zoom = f"{tippecanoe.get('minimum_zoom', '?')}–{tippecanoe.get('maximum_zoom', '?')}"
                tiled = "Yes"
            elif view in skipped:
                geometry = "—"
                zoom = "—"
                tiled = "No (`.skip`'d)"
            else:
                geometry = "—"
                zoom = "—"
                tiled = "No — see [Carto SQL](carto-sql.md)"
            lines.append(
                f"| `export.{view}` | `{stem}.sql` | {sources_cell} | {intermediates_cell} "
                f"| {geometry} | {zoom} | {tiled} |"
            )
    return "\n".join(lines) + "\n"


def _render_overview(scripts: dict[str, dict], custom_schemas: list[str], layers: dict[str, dict]) -> str:
    all_sources: set[str] = set()
    for script in scripts.values():
        all_sources.update(token for token, _ in script["sources"])
    osm_count = sum(1 for t in all_sources if t.startswith("osm."))
    aux_count = sum(1 for t in all_sources if t.startswith("aux_data."))
    export_count = sum(len(s["export_views"]) for s in scripts.values())

    lines = [
        "## Overview",
        "",
        "| Schema | Loaded by | Contents |",
        "|---|---|---|",
        f"| `osm` | `import` (imposm3) | {osm_count} distinct OSM source tables referenced below |",
        f"| `aux_data` | `import` (ogr2ogr) | {aux_count} distinct auxiliary source tables referenced below "
        "(Natural Earth, NGA GeoNames, OurAirports, FieldMaps, USGS, DoS LSIB, DISDI/MIRTA, OSM coastline/ocean "
        "extracts, and any bundled `static_data/` file) — see [Auxiliary Data](aux-data.md) |",
    ]
    for schema in custom_schemas:
        lines.append(f"| `{schema}` | `carto` (SQL transforms) | Intermediate staging tables/views for the "
                      f"`{schema}`-owned layer(s) below |")
    lines.append(
        f"| `export` | `carto` (SQL transforms) | {export_count} materialized views, "
        f"{len(layers)} of which are tiled — see [Layer Registry](layers.md) |"
    )
    lines.append("")
    lines.append("```mermaid")
    lines.append("flowchart LR")
    lines.append('    osmSchema[("osm")]')
    lines.append('    auxSchema[("aux_data")]')
    lines.append('    subgraph carto ["carto-owned intermediate schemas"]')
    for schema in custom_schemas:
        lines.append(f'        {_mermaid_id(schema)}Schema[("{schema}")]')
    lines.append("    end")
    lines.append('    exportSchema[("export")]')
    lines.append('    fgb["FlatGeobuf<br/>(export stage)"]')
    lines.append('    mbtiles["MBTiles<br/>(tippecanoe)"]')
    lines.append("    osmSchema --> carto")
    lines.append("    auxSchema --> carto")
    lines.append("    osmSchema --> exportSchema")
    lines.append("    auxSchema --> exportSchema")
    lines.append("    carto --> exportSchema")
    lines.append("    exportSchema --> fgb --> mbtiles")
    lines.append("```")
    lines.append("")
    lines.append(
        "Every `export.*` view is a `CREATE MATERIALIZED VIEW` — see "
        "[Carto SQL](carto-sql.md) for the prefix/concurrent-groups/suffix "
        "execution model that builds them, and the sections below for the "
        "full source-to-view trace, by theme."
    )
    return "\n".join(lines) + "\n"


def _generate_page() -> str:
    plan = yaml.safe_load(EXECUTION_PLAN_PATH.read_text(encoding="utf-8"))
    custom_schemas = plan["custom_schemas"]
    intermediate_token_re = _build_intermediate_token_re(custom_schemas)

    scripts = _parse_all_scripts(intermediate_token_re)
    _validate_theme_coverage(scripts)
    layers, skipped = _load_export_layers()

    parts = [HEADER, _render_overview(scripts, custom_schemas, layers)]
    for title, stems in THEMES:
        parts.append(f"\n## {title}\n\n")
        parts.append(_render_theme_diagram(stems, scripts))
        parts.append("\n")
        parts.append(_render_theme_table(stems, scripts, layers, skipped))
    return "".join(parts)


def on_pre_build(config) -> None:  # noqa: ANN001 - mkdocs hook signature
    content = _generate_page()
    target = Path(config["docs_dir"]) / "schema" / "database.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists() or target.read_text(encoding="utf-8") != content:
        target.write_text(content, encoding="utf-8")
