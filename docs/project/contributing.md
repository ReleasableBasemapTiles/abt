# Contributing

Commit and pull-request titles must be [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/) so [git-cliff](https://git-cliff.org/) can keep `CHANGELOG.md` up to date. The repository-root `CONTRIBUTING.md` is the source of truth for commit format, squash-merge guidance, and changelog automation.

This page covers tests and local workflow. As of this writing, this repository has no `LICENSE` and no Python linter/formatter config (no `ruff.toml`, `.flake8`, `mypy.ini`, or `.pre-commit-config.yaml`).

!!! warning "License note"
    This repository does not currently include a `LICENSE` file. Contributors and reusers should confirm licensing terms with the maintainers before assuming any particular license applies — don't guess a license or state one on the project's behalf.

## Conventional Commits

Use `type(scope): short description`. Allowed types: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`, `revert`. `scope` is optional (`init`, `overture`, `schema`, `bundler`, `vundler`, `docs`, `ci`, …).

```text
feat(init): add --from export flag for existing mbtiles
fix(overture): raise open-file limit before invoking tippecanoe
docs: add MkDocs documentation site
chore(ci): add git-cliff changelog workflow
```

The **Lint PR** workflow rejects pull requests whose title or commits do not match. Prefer squash-merge so the PR title becomes the `main` commit that git-cliff publishes. Do not hand-edit `CHANGELOG.md`; the Changelog workflow regenerates it on pushes to `main` and on `v*` tags.

## Running tests before submitting a change

`abtv2-tools/` has a pytest suite (21 test files under `tests/`; config in `pyproject.toml`: `pythonpath = ["."]`, `testpaths = ["tests"]`). From inside `abtv2-tools/`:

```bash
pip install -r requirements-dev.txt   # or: conda env create -f env.yaml && conda activate abtv2
pytest
```

See [Configuration](../install/configuration.md) for more on `env.yaml` vs. `requirements-dev.txt`, and [Testing](testing.md) for the full breakdown of what's covered.

`vundler-rs/` (the Rust component) has its own, separate test workflow — see [vundler-rs](../reference/vundler-rs.md) and [Testing](testing.md).

## CI that exists today

Pull requests are checked for Conventional Commit titles and commit messages (`Lint PR`). Pushes to `main` also rebuild `CHANGELOG.md` and `--strict`-validate this documentation site. There is still no automated lint/test CI for `abtv2-tools` or `vundler-rs` — run those suites locally before opening a PR. Since there's no Python formatter or linter config yet, match the existing code style by eye.

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
