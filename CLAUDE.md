# CLAUDE.md

Instructions for coding agents in this repo. For background (domain terms, architecture, design
rationale, history, known issues), read [CONTEXT.md](CONTEXT.md) before you change a pipeline
stage or the schema. The human docs are in `docs/` and published at
<https://ReleasableBasemapTiles.github.io/abt/>.

## What this is

ABT builds the RBT (Releasable Basemap Tiles) vector tileset. It takes OpenStreetMap and a set of
auxiliary open datasets, loads them into PostGIS, exports one `.mbtiles` per layer, and joins
those into a single `.mbtiles`. An optional last stage converts that file to an Esri Compact Cache
V2 bundle. The pipeline is a fixed sequence of CLI stages, `download` → `import` → `carto` →
`export` → `bundler` → `vundler`. Each stage reads `-s/--schema-dir` and writes under
`-w/--working-dir`.

- `abtv2-tools/` is the engine: `abt-tools.py` (a Typer CLI), the `abt/` package, and `tests/`.
  `vundler-rs/` is the Rust `abt-vundler` binary that the `vundler` stage shells out to.
- `rbt-schema/` is the content passed as `--schema-dir`. It holds imposm mappings
  (`import/osm/`), aux-data configs (`import/aux_data/`), SQL transforms (`carto_sql/` plus
  `execution_plan.yml`), per-layer tile configs (`export/`), and bundle metadata
  (`tile-metadata/metadata.py`). It has no pipeline code except the standalone
  `scripts/overture/`.
- `docs/` is the MkDocs site. The scripts in `docs/_hooks/` regenerate several pages from code and
  schema at build time.
- `init.sh` is the production orchestrator and `setup_ubuntu.sh` is the host bootstrap. See
  [Don't run casually](#dont-run-casually).

## Commands

The target is Python 3.13. `abtv2-tools/env.yaml` is the source of truth; it was pinned back from
3.14 because pyclipper has no 3.14 build. None of these commands need Postgres, GDAL, tippecanoe,
or network access.

```bash
# Python unit tests, from abtv2-tools/. The package isn't installed: pyproject.toml's
# pythonpath=["."] is what makes `abt` importable, so run pytest from this directory.
cd abtv2-tools
pip install -r requirements-dev.txt     # or: conda env create -f env.yaml && conda activate abtv2
pytest                                  # a few seconds; one skip unless duckdb is on PATH
pytest tests/test_carto_processing_model.py -k plan

# Rust, from the repo root
cargo test --manifest-path abtv2-tools/vundler-rs/Cargo.toml  # also builds target/debug/abt-vundler
pytest abtv2-tools/vundler-rs/tests/test_golden.py            # Rust vs frozen Python oracle; skips if unbuilt

# Docs, as CI builds them, from the repo root
pip install -r requirements-docs.txt -r abtv2-tools/requirements-dev.txt
mkdocs build --strict

# What this branch would publish to each mirror (needs a full, non-shallow clone)
bash .github/scripts/subtree-sync.sh check abtv2-tools origin/main
bash .github/scripts/subtree-sync.sh check rbt-schema origin/main

git config core.hooksPath .githooks     # optional: reject non-conventional commit subjects locally
```

## CI: what it checks and what it doesn't

- **Lint PR** checks that the PR title and every commit are Conventional Commits.
- **Subtree sync** reports what merging would publish to each mirror, and fails if a mirror has
  diverged from abt.
- **Docs** runs `mkdocs build --strict` on every push to `main`, then publishes the site. On a PR
  it runs only if the PR touches one of these:
  - `docs/`, `mkdocs.yml`, `requirements-docs.txt`, or the workflow file itself
  - `abtv2-tools/`
  - one of `rbt-schema/{export,import/aux_data,tile-metadata,carto_sql}/`

  It is the only job that imports the Python code. On a PR it uploads the built site as the
  `docs-site` artifact.
- **No job runs pytest, cargo test, or a linter.** Run the suites above yourself before you push.

## Commits and PRs

- Use Conventional Commits: `type(scope): description`. The types are `feat fix docs style
  refactor perf test build ci chore revert`. Scope is optional; examples are `init`, `overture`,
  `schema`, `bundler`, `vundler`, `sync`, `docs`, and `ci`. Mark a breaking change with `feat!:`
  or a `BREAKING CHANGE:` footer.
- commitlint (`config-conventional`) also rejects:
  - a capitalized subject (`fix: Correct …`)
  - a subject that ends with a period
  - a header over 100 characters
  - any body or footer line over 100 characters
- **Every commit subject on your branch becomes a changelog line.** `CONTRIBUTING.md` asks for
  squash merges, but so far every PR has landed as a merge commit. git-cliff skips the merge
  commit and lists each branch commit instead. Write each subject as a user-facing entry, and
  don't leave fixup commits on the branch.
- Fill in the PR template's `## Summary` and `## Test plan` sections.
- Don't edit `CHANGELOG.md`. The Changelog workflow regenerates it from the commits on `main`.

## Mirrors: `abtv2-tools/` and `rbt-schema/`

Both directories are git subtrees. Every merge to `main` publishes each one, with its history, to
`ReleasableBasemapTiles/abtv2-tools` and `ReleasableBasemapTiles/rbt-schema`. Inside them:

- **Don't rename, move, or delete either directory.** Publishing stops, and someone has to
  re-bootstrap the mirror by hand.
- Markdown links must not climb out of the directory with `../`, because those links 404 in the
  mirror. Link to `https://github.com/ReleasableBasemapTiles/abt/blob/main/...` or
  `https://ReleasableBasemapTiles.github.io/abt/...` instead.
- Each directory's `LICENSE` must stay a byte-identical copy of the root `LICENSE`. Each `NOTICE`
  carries the part of the root `NOTICE` that applies to that directory.
- Everything committed in these directories is published along with its history. Don't add large
  files, credentials, or editor or agent scratch files. That's why this file lives at the root.
- Don't push to the mirror repos or open PRs against them. A PR that brings mirror history in
  (`git subtree pull`, `git merge -s ours`) must be merged with a merge commit, not squashed. See
  `docs/project/mirrors.md`.

## Changing `rbt-schema/`

Schema files refer to each other only by name, and nothing checks those references until a real
run. Keep them consistent yourself:

- **Export configs name views.** The `layer_id` field in each `export/*.json` file must name an
  `export.<layer_id>` materialized view that some `carto_sql/*.sql` script creates. The field is
  what counts, not the filename: `adm0_labels.json` has `layer_id` `adm0_label`.
- **The execution plan lists every script.** Each `carto_sql/*.sql` must appear exactly once in
  `carto_sql/execution_plan.yml`, and `carto` refuses to start otherwise.
  - A new script normally gets a group of its own.
  - If it reads a table or function that another script creates, put it after that script in the
    same group.
  - A new custom schema goes in `custom_schemas`.
  - The comments in `execution_plan.yml` explain these rules in detail.
- **Layer scripts need a header and a theme.** Each script that builds a layer needs a header
  with `-- LAYER:`, `-- Schema:`, `-- Intermediates:`, and `-- Sources:` lines. It also needs an
  entry in `THEMES` in `docs/_hooks/gen_db_schema.py`. A script that builds no layer goes in
  `NON_LAYER_SCRIPTS` in the same file instead. If any of this is missing,
  `mkdocs build --strict` fails.
- **Scripts must be re-runnable.** `carto` rebuilds everything from scratch on every run. Each
  block follows this pattern: `BEGIN; DROP … IF EXISTS … CASCADE; CREATE MATERIALIZED VIEW
  export.…; CREATE INDEX … USING gist (geometry); COMMIT;`.
- **Disable a layer instead of deleting it.** Append `.skip` to the `.sql` or `.json` filename,
  then remove the script from both `execution_plan.yml` and `THEMES`.
- **Tiling-only changes stay in one file.** Changing zooms, attributes, or the tippecanoe filter
  only touches that layer's `export/*.json` file.

This offline check covers all three naming rules and doesn't need Postgres. Run it from
`abtv2-tools/`:

```bash
python - <<'EOF'
import importlib.util, json, re
from pathlib import Path
from abt.carto_processing_model import CartoExecutionPlan, CartoProcessingModel
from abt.schema import DataSchema
from abt.utils.pg_config import PGConfig
s = DataSchema(base_schema_dir=Path("../rbt-schema"))
pg = PGConfig(host="-", port=0, user="-", password="-", database="-", log_path=Path("."))  # never connects
# 1. every carto_sql/*.sql is in execution_plan.yml exactly once (what `carto` enforces at run time)
CartoProcessingModel(sql_files=s.carto_sql_layers, pg_config=pg, log_dir=Path("."))._validate_plan_covers_all_files(
    CartoExecutionPlan.load(s.carto_execution_plan_path))
# 2. every export/*.json layer_id has a matching `CREATE MATERIALIZED VIEW export.<layer_id>`
views = {v.lower() for f in s.carto_sql_layers for v in re.findall(
    r"CREATE MATERIALIZED VIEW\s+(?:IF NOT EXISTS\s+)?export\.(\w+)", f.read_text(), re.I)}
bad = sorted(i for i in (json.loads(p.read_text())["layer_id"] for p in s.export_layers) if i not in views)
assert not bad, f"export/*.json layer_id with no export.<layer_id> view: {bad}"
# 3. -- LAYER: headers + THEMES coverage (what `mkdocs build --strict` enforces)
spec = importlib.util.spec_from_file_location("gen_db_schema", "../docs/_hooks/gen_db_schema.py")
hook = importlib.util.module_from_spec(spec); spec.loader.exec_module(hook); hook._generate_page()
print("schema OK")
EOF
```

## Python conventions (`abtv2-tools/abt/`)

- **Every stage has the same shape.**
  - `abt/cli_funcs/<stage>.py` holds the Typer command. Its `init_*()` function does the work.
  - The `cli_*` wrapper exits with code 1 if `init_*()` raises, or if the run summary isn't
    `SUCCESS`.
  - Below that, an engine module runs the external tools through
    `utils/subprocess_tools.run_subprocess`. That function streams tool output to a per-task log
    and raises `CalledProcessError` on failure.
  - A new sub-app must also be registered with `app.add_typer(...)` in `abt-tools.py`.
- **Reuse the shared flags.** Use the `typer.Option` fields in `abt/utils/fields.py` instead of
  defining flags again. `-n` means `--num-workers` in every command except `carto`, where it
  means `--carto-concurrency`.
- **Worker defaults depend on the host.** Each default is
  `default_num_workers()` = `max(floor, os.cpu_count() // divisor)`, evaluated at import time.
- **Paths and run records have fixed sources.**
  - Get paths from `ProcessingDirectorySchema.init_working_directories()`. It gives each
    invocation its own `logs/<run_id>/` directory.
  - Fan out work with `ParallelExecutor`. It's a thread pool; the heavy work runs in subprocesses.
  - Record task outcomes in a `RunReporter`, which writes `logs/<run_id>/summary.json`.
- **Config uses Pydantic v2 models.** CLI parameters use `Annotated[...]`.
- **Comments explain why.** Docstrings and comments give the failure, measurement, or constraint
  behind the code; match that density. The repo has no formatter or linter config, so match the
  surrounding style.
- **Tests stop at the mockable boundary.** They never touch a live Postgres, the network, or S3;
  mock with `monkeypatch` and use real files under `tmp_path`.
  - Pin a known bug with `xfail` rather than asserting the wrong behavior.
  - `abt-tools.py` can't be imported by name, so tests load it with
    `importlib.util.spec_from_file_location`.
- **Some known issues are unfixed on purpose.** They're waiting on a product decision; see R1–R10
  in `docs/project/code-review-findings.md`. Two examples are the hard-coded `verify=False` on
  downloads and the connection that every DB-touching `PGConfig` method leaks on each call.
  Raise these issues rather than fixing them in passing.

## Rust (`abtv2-tools/vundler-rs/`)

- The crate is `abt-vundler`, edition 2024. `abt/vundler.py` runs it as `abt-vundler` from `PATH`.
- `tests/reference/vundler_reference.py` is a frozen transcription of the Python implementation
  from before the port, and the golden tests use it as the oracle. **Never edit it to match new
  output.** The golden tests compare semantically: per-tile payloads plus `metadata.json`, not
  byte-identical bundle files.

## Docs gotchas

- **Generated pages: edit the source, not the page.** Then commit the regenerated page together
  with its source.

  | Generated page (under `docs/`) | Source |
  |---|---|
  | `reference/cli.md` | CLI help text in `abt/cli_funcs/*.py` and `abt/utils/fields.py` |
  | `schema/layers.md` | `export/*.json` |
  | `overview/data-sources.md` | `import/aux_data/*.json` and `tile-metadata/metadata.py` |
  | `schema/database.md` | the header comments in `carto_sql` |
  | the marked block in `schema/carto-sql.md` | `execution_plan.yml` |

- **A local build rewrites the CLI reference.** It fills the `[default: N]` values in
  `docs/reference/cli.md` from *your* CPU count; the committed copy came from a 16-core host.
  Don't commit that churn. If you changed help text, stage only those hunks.
- **The strict build needs `unpkg.com`.** The mermaid2 plugin checks its script URL there. In a
  network-restricted sandbox, `mkdocs build --strict` aborts on that single warning, and the
  failure isn't caused by your change.
- **Some prose has drifted from the code.** Trust code and config over prose. Fix any prose you
  find stale in the files you touch. CONTEXT.md lists the drift that's already known.

## Don't run casually

- **`init.sh`** is the production run. It hard-codes `/rbt/...` paths, requires AWS STS
  credentials before it starts, runs for hours, and uploads to S3.
- **`setup_ubuntu.sh`** rewrites sysctl and ulimit settings, installs a systemd unit, and can run
  `initdb` on a cluster. It's only for bootstrapping a dedicated host.
- **`download` or `import` without `-k <geofabrik-key>`** fetches the whole planet, because `-k`
  defaults to `planet` (a PBF of more than 80 GB). To test end to end, use a small extract; see
  `docs/walkthroughs/norway.md`. `import` won't overwrite a populated `osm` schema without `-f`.
