"""MkDocs hook: regenerate the execution-graph section of
docs/schema/carto-sql.md from rbt-schema/carto_sql/execution_plan.yml.

Unlike the other generated pages, this hook only replaces the fenced region
between the `<!-- CARTO_DAG_START -->`/`<!-- CARTO_DAG_END -->` markers in an
otherwise hand-written page -- see docs/schema/carto-sql.md's own
"Execution graph" section. If execution_plan.yml is missing, or the target
page or its markers aren't found, the hook leaves things untouched --
`carto` itself falls back to sequential filename order in the
missing-execution-plan case too (see abt/carto_processing_model.py).

The file is only rewritten when its content changes, which keeps `mkdocs
serve` from rebuild-looping.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
EXECUTION_PLAN_PATH = REPO_ROOT / "rbt-schema" / "carto_sql" / "execution_plan.yml"
CARTO_SQL_PAGE = Path("schema") / "carto-sql.md"

START_MARKER = "<!-- CARTO_DAG_START -->"
END_MARKER = "<!-- CARTO_DAG_END -->"

_MARKER_PATTERN = re.compile(
    re.escape(START_MARKER) + r".*?" + re.escape(END_MARKER), re.DOTALL
)


def _script_label(script_filename: str) -> str:
    return Path(script_filename).stem


def _build_diagram(plan: dict) -> str:
    prefix = plan.get("prefix") or []
    groups = plan.get("groups") or []
    suffix = plan.get("suffix") or []
    custom_schemas = plan.get("custom_schemas") or []
    extensions = plan.get("extensions") or []

    lines = ["```mermaid", "flowchart TD"]
    prev_id: str | None = None

    for i, script in enumerate(prefix, start=1):
        node = f"prefix{i:02d}"
        lines.append(f'    {node}["{_script_label(script)}"]')
        if prev_id:
            lines.append(f"    {prev_id} --> {node}")
        prev_id = node

    if custom_schemas or extensions:
        schema_label = ", ".join(custom_schemas + extensions)
        lines.append(f'    setupSchemas["create schemas/extensions up front:<br/>{schema_label}"]')
        if prev_id:
            lines.append(f"    {prev_id} --> setupSchemas")
        prev_id = "setupSchemas"

    if groups:
        box_label = f"{len(groups)} independent groups -- concurrent, up to --carto-concurrency at a time"
        lines.append(f'    subgraph groupsBox ["{box_label}"]')
        for i, group in enumerate(groups, start=1):
            node = f"group{i:02d}"
            label = " then ".join(_script_label(s) for s in group)
            lines.append(f'        {node}["{label}"]')
        lines.append("    end")
        if prev_id:
            lines.append(f"    {prev_id} --> groupsBox")
        prev_id = "groupsBox"

    for i, script in enumerate(suffix, start=1):
        node = f"suffix{i:02d}"
        lines.append(f'    {node}["{_script_label(script)}"]')
        if prev_id:
            lines.append(f"    {prev_id} --> {node}")
        prev_id = node

    lines.append("```")
    lines.append("")

    schema_bits = ", ".join(f"`{s}`" for s in custom_schemas + extensions)
    lines.append(
        f"{len(groups)} independent groups (from `execution_plan.yml`) run "
        "concurrently, up to `-n/--carto-concurrency` at a time, between a "
        f"{len(prefix)}-script sequential prefix and a {len(suffix)}-script "
        "sequential suffix. Custom schemas/extensions are created once up "
        f"front, before any group starts: {schema_bits}."
    )
    return "\n".join(lines) + "\n"


def on_pre_build(config) -> None:  # noqa: ANN001 - mkdocs hook signature
    if not EXECUTION_PLAN_PATH.exists():
        return

    target = Path(config["docs_dir"]) / CARTO_SQL_PAGE
    if not target.exists():
        return

    page = target.read_text(encoding="utf-8")
    if START_MARKER not in page or END_MARKER not in page:
        return

    plan = yaml.safe_load(EXECUTION_PLAN_PATH.read_text(encoding="utf-8"))
    diagram = _build_diagram(plan)
    new_page = _MARKER_PATTERN.sub(f"{START_MARKER}\n{diagram}{END_MARKER}", page, count=1)
    if new_page != page:
        target.write_text(new_page, encoding="utf-8")
