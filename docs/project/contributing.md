# Contributing

This page is a starting point, not a claim that a formal contribution process already exists. As of this writing, this repository has no `CONTRIBUTING.md`, no `LICENSE`, no `CHANGELOG.md`, and no linter/formatter config (no `ruff.toml`, `.flake8`, `mypy.ini`, or `.pre-commit-config.yaml`) anywhere in it. Everything below reflects what's actually here today.

!!! warning "License note"
    This repository does not currently include a `LICENSE` file. Contributors and reusers should confirm licensing terms with the maintainers before assuming any particular license applies — don't guess a license or state one on the project's behalf.

## Running tests before submitting a change

`abtv2-tools/` has a pytest suite (21 test files under `tests/`; config in `pyproject.toml`: `pythonpath = ["."]`, `testpaths = ["tests"]`). From inside `abtv2-tools/`:

```bash
pip install -r requirements-dev.txt   # or: conda env create -f env.yaml && conda activate abtv2
pytest
```

See [Configuration](../install/configuration.md) for more on `env.yaml` vs. `requirements-dev.txt`, and [Testing](testing.md) for the full breakdown of what's covered.

`vundler-rs/` (the Rust component) has its own, separate test workflow — see [vundler-rs](../reference/vundler-rs.md) and [Testing](testing.md).

## No enforced CI for code changes today

There is currently no automated lint/test CI pipeline in this repository — only a docs build (which this very documentation site adds). Running the test suites above locally before opening a PR is the only check that exists today. Since there's no formatter or linter config yet, match the existing code style by eye.

## Style conventions observed in the existing code

These are patterns to follow because they're already used consistently, not a written style guide:

- Extensive module- and function-level docstrings explaining *why* a piece of code exists, not just what it does — see any file under `abtv2-tools/abt/`.
- Pydantic models for config validation (e.g. `osm_data_model.py`, `aux_data_model.py`).
- Typer for CLI commands (`abt-tools.py` and `abt/cli_funcs/`).

## Two-repo history

`abtv2-tools/` and `rbt-schema/` were originally separate git repositories, merged into this single monorepo with commit history preserved. `git log -- abtv2-tools/` and `git log -- rbt-schema/` both still work against their respective pre-merge history.

## Where to go next

- [Testing](testing.md) — full detail on every test suite in the repo and how to run it.
- [Adding a Layer](../schema/adding-a-layer.md) — the schema-specific contribution workflow for adding or changing a tile layer.
