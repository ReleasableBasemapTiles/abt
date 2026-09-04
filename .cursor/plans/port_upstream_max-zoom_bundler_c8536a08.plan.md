---
name: Port upstream max-zoom bundler
overview: Port the only upstream-only change in ReleasableBasemapTiles/abtv2-tools — the `--max-zoom` bundler flag for RBT Small packages (5 commits, 3 files) — into `abtv2-tools/`, merging it with local divergence in `bundler_model.py`, hardening the SQLite trim helper, and adding test and doc coverage.
todos:
  - id: fields
    content: Add optional_max_zoom_field to abt/utils/fields.py reusing max_zoom_aliases
    status: completed
  - id: model
    content: "In bundler_model.py: add max_zoom field, hand-merge _has_tiles (local try/finally + upstream LIMIT 1), extract build_tile_join_cmd(files)"
    status: completed
  - id: trim
    content: "In export/bundler.py: add hardened _trim_mbtiles (bound ATTACH path, guarded metadata copy, DETACH on all paths) and wire the pre-trim path into export_bundled with unique temp names and finally-cleanup"
    status: completed
  - id: cli
    content: Thread max_zoom through init_bundler and cli_bundler in abt/cli_funcs/bundler.py
    status: completed
  - id: tests
    content: Extend tests/test_export_bundler_model.py and add tests/test_export_bundler_trim.py covering the hardening cases
    status: completed
  - id: docs
    content: Document -z/--max-zoom in abtv2-tools/README.md and the root README.md bundler sections
    status: completed
  - id: verify
    content: Run the full pytest suite from abtv2-tools/ and confirm it passes
    status: completed
isProject: false
---

# Port the upstream `--max-zoom` bundler feature

## What the comparison found

The local `abtv2-tools/` tree already contains upstream history through `e6cce3f` (2026-08-13, "Strip tippecanoe build metadata and honor declared bundle center"). Upstream `main` has exactly five commits past that point, and they are all one feature:

- `a4f04ef` Add `--max-zoom` flag to bundler for RBT Small output
- `3196c19` Replace tile-join zoom cap with SQLite pre-trim for `--max-zoom`
- `82318d9` Speed up trim: ATTACH+INSERT SELECT, fix `_has_tiles` count
- `22cdb1f` Log trim progress to file instead of stdout
- `495cfbd` Merge commit for the above

Total surface is `+88 / -16` across `abt/cli_funcs/bundler.py`, `abt/export/bundler_model.py`, and `abt/export/bundler.py`. The upstream branches `rbt-small` and `docs/readme-setup-ubuntu` are already ancestors of `main`, so there is nothing extra to pull from them.

Everything else that differs between the two repos is local work upstream does not have (`tests/`, `vundler-rs/`, `planet_mirrors.py`, concurrent carto, aria2 downloads, `pyproject.toml`, `requirements-dev.txt`, the relocated root `setup_ubuntu.sh`). Nothing else needs to come inbound.

## Merge risk

Locally, [abtv2-tools/abt/cli_funcs/bundler.py](abtv2-tools/abt/cli_funcs/bundler.py) and [abtv2-tools/abt/export/bundler.py](abtv2-tools/abt/export/bundler.py) are byte-identical to the upstream base, so the upstream hunks apply cleanly.

Only [abtv2-tools/abt/export/bundler_model.py](abtv2-tools/abt/export/bundler_model.py) diverged, via `cd770f2`, and it collides with upstream in `_has_tiles`. Local rewrote it to close the connection in a `finally`; upstream changed the population check from a full `COUNT(*)` to `SELECT 1 ... LIMIT 1`. Both changes are wanted, so this one function needs a hand merge rather than a straight apply. Local also added `parents=True` to `bundled_mbtiles_tmp`, which now matters more because upstream writes trimmed files into that directory.

## Changes

### 1. `abt/utils/fields.py`

`max_zoom_field` is a required option (`...`), so `bundler` needs its own optional variant. Add one next to it, reusing the existing `max_zoom_aliases = ['-z', '--max-zoom']` (line 44):

```python
optional_max_zoom_field = typer.Option(
    None,
    *max_zoom_aliases,
    help="Cap the bundled output at this zoom level. Omit for no cap (full resolution).",
)
```

Upstream inlined this `typer.Option` in the command signature; putting it in `fields.py` matches how every other option in this repo is declared. No alias collision — `bundler` currently only uses `-w`, `-s`, `-p`, `-q`, `-o`.

### 2. `abt/export/bundler_model.py`

- Add `max_zoom: Optional[int] = None` to the `Bundler` model fields.
- Hand-merge `_has_tiles`: keep the local `try/finally` connection close, swap the body's `SELECT count(*) FROM tiles` for upstream's `SELECT 1 FROM tiles LIMIT 1` / `fetchone() is not None`.
- Extract `build_tile_join_cmd(self, files: List[Path]) -> List[str]` from the current `tile_join_cmd` property, and keep `tile_join_cmd` as a thin property delegating with `self.tile_list` so existing callers and tests keep working.
- Leave `bundled_mbtiles_tmp` as-is (local `parents=True` is correct).

### 3. `abt/export/bundler.py`

Add the `_trim_mbtiles(src, dst, max_zoom)` helper (ATTACH + `INSERT INTO ... SELECT`, `PRAGMA synchronous=OFF`, `journal_mode=MEMORY`, unique index on the copy), with these fixes over the upstream version:

- Bind the source path instead of f-string interpolation: `con.execute("ATTACH DATABASE ? AS src", (str(src),))`. Upstream's `f"ATTACH DATABASE '{src}'"` breaks on any path containing a quote.
- Guard the metadata copy. Upstream unconditionally runs `INSERT INTO metadata SELECT name, value FROM src.metadata`, which raises if an input has no `metadata` table — reachable through user-supplied `--additional-mbtiles`. Check `src.sqlite_master` first, and write the `maxzoom` row with an upsert rather than an `UPDATE` that silently no-ops when the row is absent.
- `DETACH src` on all paths, not only the success path.

Then in `export_bundled`, after the existing `resolve_crs_from_files` / `package_name` block and before the stale-output unlink, pre-trim each input when `bundle.max_zoom is not None`, logging progress through `get_logger("trim", bundle.bundled_dir, "bundler")` (new import from `..utils.logger`), and pass the trimmed list to `bundle.build_tile_join_cmd(tile_files)` inside a `try/finally` that unlinks the temporaries.

Name the trimmed copies with a positional prefix (for example `f"{i:03d}_{src.name}"`) instead of upstream's bare `src.name`: `tile_list` concatenates per-layer files with `additional_mbtiles`, so two inputs from different directories can share a basename and silently overwrite each other.

### 4. `abt/cli_funcs/bundler.py`

Thread `max_zoom: Optional[int] = None` through `init_bundler` (into the `Bundler(...)` construction) and `cli_bundler` (annotated with the new `optional_max_zoom_field`), with matching docstring entries.

### 5. Tests

Extend [abtv2-tools/tests/test_export_bundler_model.py](abtv2-tools/tests/test_export_bundler_model.py), which already has a `make_bundler(tmp_path)` helper and covers `tile_join_cmd` and `_has_tiles`:

- `build_tile_join_cmd` honors an explicit file list; `tile_join_cmd` still resolves to `tile_list`.
- Confirm the five existing `_has_tiles` cases still pass after the `LIMIT 1` swap (the schema-only-no-rows case is the one to watch).

Add a new `tests/test_export_bundler_trim.py` covering the hardened behavior specifically:

- Tiles above `max_zoom` are dropped, tiles at or below are preserved.
- `metadata.maxzoom` is set, including when the source has no `maxzoom` row.
- A source with no `metadata` table at all trims successfully.
- A source path containing a single quote trims successfully (the ATTACH binding fix).
- `export_bundled` cleans up trimmed temporaries even when `tile-join` raises.

### 6. Docs

- [abtv2-tools/README.md](abtv2-tools/README.md) line ~233: extend the usage line to `bundler -w <dir> -s <dir> [-p pg_config] [-q path ...] [-o output_name] [-z max_zoom]` and describe the RBT Small use case alongside the existing `-o/--output-name` paragraph.
- [README.md](README.md): note the flag in the bundler stage table (line 37) and the example invocations (lines 377, 492).

Per your answer, `init.sh` and `setup_ubuntu.sh` stay untouched.

## Verification

Run `pytest` from `abtv2-tools/` and confirm the full suite passes, not just the new tests.

## Out of scope, worth noting

The local repo is far ahead of upstream in the other direction — the entire `tests/` suite, `vundler-rs/`, `planet_mirrors.py`, the aria2 download path, concurrent carto execution, and the EPSG:3395/4087 work exist only here. If the two repos are meant to stay in sync, that backflow is a separate conversation.