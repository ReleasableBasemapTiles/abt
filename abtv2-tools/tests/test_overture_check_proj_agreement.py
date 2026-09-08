"""Tests for rbt-schema/scripts/overture/check_proj_agreement.py: the PROJ
cross-engine agreement guard init.sh runs before any non-3857 build (see
that module's own docstring, and this repo's overture.md, for the PROJ 9.8.0
ellipsoidal-eqc background this guards against).

Lives under abtv2-tools/tests/ so it runs with the rest of the abtv2-tools
suite and its pyproj/psycopg2 dependencies -- see requirements-dev.txt --
rather than needing its own test runner. Loaded by file path via importlib
rather than a normal import: the script lives in rbt-schema/scripts/overture/,
outside abtv2-tools' own package, by design -- see tag_crs.py's "no
abtv2-tools" note in that directory.
"""

import importlib.util
import shutil
import sys
from pathlib import Path

import pytest

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "rbt-schema" / "scripts" / "overture" / "check_proj_agreement.py"
)
_spec = importlib.util.spec_from_file_location("check_proj_agreement", _SCRIPT_PATH)
check_proj_agreement = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = check_proj_agreement
_spec.loader.exec_module(check_proj_agreement)


# --- pyproj_reference: regression values ------------------------------------
# Locks in the EPSG:1028 ellipsoidal values PROJ >=9.8 produces (see
# https://github.com/OSGeo/PROJ/issues/4654). Older, spherical-only PROJ
# instead produces y=a*phi -- e.g. 5009377.09m at lat=45, a 24.4km miss --
# so a regression here (this env's pyproj silently downgrading below PROJ
# 9.8) is caught in CI instead of surfacing as misaligned tiles.

def test_pyproj_reference_epsg_4087_matches_known_ellipsoidal_values():
    points = check_proj_agreement.pyproj_reference(4087)
    expected = {
        0.0: (0.0, 0.0),
        30.0: (0.0, 3320113.3979403824),
        45.0: (0.0, 4984944.377977743),
        60.0: (0.0, 6654072.819490511),
        84.0: (0.0, 9331826.561184982),
    }
    assert points.keys() == expected.keys()
    for lat, (expected_x, expected_y) in expected.items():
        actual_x, actual_y = points[lat]
        assert actual_x == pytest.approx(expected_x, abs=1e-3)
        assert actual_y == pytest.approx(expected_y, abs=1e-3)


def test_pyproj_reference_epsg_3395_is_unaffected():
    """World Mercator has always used ellipsoidal formulas -- contrast to
    the 4087 case above, and the basis for the real-DuckDB integration test
    further down, which needs an EPSG code stable across old and new PROJ."""
    points = check_proj_agreement.pyproj_reference(3395)
    assert points[0.0] == (0.0, 0.0)
    assert points[45.0][1] == pytest.approx(5591295.9185533915, abs=1e-3)


# --- compare -----------------------------------------------------------

def test_compare_returns_empty_when_within_tolerance():
    reference = {0.0: (0.0, 0.0), 45.0: (100.0, 200.0)}
    other = {0.0: (0.0, 0.0), 45.0: (100.0004, 199.9996)}
    assert check_proj_agreement.compare(reference, other, tolerance=0.001) == []


def test_compare_flags_points_exceeding_tolerance():
    reference = {0.0: (0.0, 0.0), 45.0: (0.0, 4984944.377977743)}
    other = {0.0: (0.0, 0.0), 45.0: (0.0, 5009377.085697311)}  # old spherical value
    mismatches = check_proj_agreement.compare(reference, other, tolerance=0.001)
    assert len(mismatches) == 1
    lat, dx, dy = mismatches[0]
    assert lat == 45.0
    assert dx == pytest.approx(0.0, abs=1e-6)
    assert dy == pytest.approx(24432.707719568, abs=1e-3)


def test_compare_respects_custom_tolerance():
    reference = {0.0: (0.0, 0.0)}
    other = {0.0: (0.0, 0.05)}
    assert check_proj_agreement.compare(reference, other, tolerance=0.1) == []
    assert len(check_proj_agreement.compare(reference, other, tolerance=0.01)) == 1


# --- duckdb_values / postgis_values: graceful skips ------------------------

def test_duckdb_values_skips_when_binary_missing(monkeypatch):
    monkeypatch.setattr(check_proj_agreement.shutil, "which", lambda name: None)
    points, version, reason = check_proj_agreement.duckdb_values(4087)
    assert points is None
    assert version is None
    assert "PATH" in reason


def test_postgis_values_skips_when_env_vars_missing(monkeypatch):
    for var in ("PGHOST", "PGPORT", "PGUSER", "PGPASSWORD", "PGDATABASE"):
        monkeypatch.delenv(var, raising=False)
    points, version, reason = check_proj_agreement.postgis_values(4087)
    assert points is None
    assert version is None
    # Bare "HOST", not "PGHOST" -- same k.upper() convention as PGConfig.from_env.
    assert "HOST" in reason


# --- check_epsg: pass/fail/skip aggregation --------------------------------

def test_check_epsg_passes_when_all_reachable_engines_agree(monkeypatch, capsys):
    reference = check_proj_agreement.pyproj_reference(4087)
    monkeypatch.setattr(check_proj_agreement, "duckdb_values", lambda epsg: (reference, "9.8.1", None))
    monkeypatch.setattr(check_proj_agreement, "postgis_values", lambda epsg: (reference, "9.8.1", None))

    assert check_proj_agreement.check_epsg(4087, tolerance=0.001) is True
    assert "MISMATCH" not in capsys.readouterr().out


def test_check_epsg_fails_when_an_engine_disagrees(monkeypatch, capsys):
    old_spherical = {
        0.0: (0.0, 0.0),
        30.0: (0.0, 3339584.723798207),
        45.0: (0.0, 5009377.085697311),
        60.0: (0.0, 6679169.447596414),
        84.0: (0.0, 9350837.226634981),
    }
    monkeypatch.setattr(check_proj_agreement, "duckdb_values", lambda epsg: (old_spherical, "9.1.1", None))
    monkeypatch.setattr(check_proj_agreement, "postgis_values", lambda epsg: (None, None, "not configured"))

    assert check_proj_agreement.check_epsg(4087, tolerance=0.001) is False
    out = capsys.readouterr().out
    assert "duckdb (PROJ 9.1.1): MISMATCH" in out
    assert "postgis: skipped (not configured)" in out


def test_check_epsg_passes_when_every_engine_is_skipped(monkeypatch, capsys):
    monkeypatch.setattr(check_proj_agreement, "duckdb_values", lambda epsg: (None, None, "duckdb not found on PATH"))
    monkeypatch.setattr(check_proj_agreement, "postgis_values", lambda epsg: (None, None, "PG* environment variables not set"))

    assert check_proj_agreement.check_epsg(4087, tolerance=0.001) is True
    out = capsys.readouterr().out
    assert "duckdb: skipped" in out
    assert "postgis: skipped" in out


# --- main(): CLI surface ---------------------------------------------------

def test_main_requires_at_least_one_epsg_argument():
    with pytest.raises(SystemExit) as excinfo:
        check_proj_agreement.main(["check_proj_agreement.py"])
    assert "usage" in str(excinfo.value)


def test_main_rejects_non_numeric_epsg():
    with pytest.raises(SystemExit) as excinfo:
        check_proj_agreement.main(["check_proj_agreement.py", "abc"])
    assert "numeric" in str(excinfo.value)


def test_main_returns_zero_when_every_engine_agrees_or_is_skipped(monkeypatch):
    # No duckdb on PATH and no PG* env vars already makes both optional
    # engines skip in a bare test environment -- see the graceful-skip tests
    # above -- so a plain run against pyproj alone should always succeed.
    for var in ("PGHOST", "PGPORT", "PGUSER", "PGPASSWORD", "PGDATABASE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(check_proj_agreement.shutil, "which", lambda name: None)
    assert check_proj_agreement.main(["check_proj_agreement.py", "4087"]) == 0


# --- real DuckDB integration (skipped if the binary isn't on PATH) --------

@pytest.mark.skipif(shutil.which("duckdb") is None, reason="duckdb not on PATH")
def test_duckdb_values_matches_pyproj_for_epsg_3395():
    """End-to-end check of the real subprocess/CSV/axis-order plumbing.

    Deliberately EPSG:3395 (World Mercator), not 4087: Mercator's ellipsoidal
    formulas predate PROJ 9.8, so this stays a meaningful plumbing check
    regardless of which PROJ version the local duckdb happens to bundle --
    unlike 4087, it can't spuriously start failing (or silently start
    passing) purely because duckdb's bundled PROJ was upgraded.
    """
    reference = check_proj_agreement.pyproj_reference(3395)
    points, version, reason = check_proj_agreement.duckdb_values(3395)
    assert reason is None, reason
    assert version
    assert check_proj_agreement.compare(reference, points, tolerance=0.001) == []
