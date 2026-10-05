"""Tests for rbt-schema/scripts/overture/check_proj_agreement.py: the PROJ
cross-engine agreement guard init.sh runs before any non-3857 build (see
that module's own docstring, and this repo's overture.md, for the PROJ 9.8.0
ellipsoidal-eqc background this guards against).

Lives under abtv2-tools/tests/ so it runs with the rest of the abtv2-tools
suite and its pyproj/psycopg2 dependencies -- see requirements-dev.txt --
rather than needing its own test runner. Loaded by file path via importlib
rather than a normal import: the script lives in rbt-schema/scripts/overture/,
outside abtv2-tools' own package, by design -- see tag_crs.py's "no
abtv2-tools" note in that directory. So in abtv2-tools' standalone mirror,
which has no rbt-schema/ next to it, the whole module is skipped.
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
if not _SCRIPT_PATH.exists():
    pytest.skip(
        f"{_SCRIPT_PATH} not found: these tests need the monorepo's rbt-schema/ next to abtv2-tools/",
        allow_module_level=True,
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


# --- gdal_values / duckdb_values / postgis_values: graceful skips ------------

def test_gdal_values_skips_when_ogr2ogr_missing(monkeypatch):
    monkeypatch.setattr(check_proj_agreement.shutil, "which", lambda name: None)
    points, version, reason = check_proj_agreement.gdal_values(4087)
    assert points is None
    assert version is None
    assert "ogr2ogr" in reason


def test_gdal_values_skips_without_gdaltransform_next_to_ogr2ogr(monkeypatch, tmp_path):
    ogr2ogr = tmp_path / "ogr2ogr"
    ogr2ogr.touch()
    monkeypatch.setattr(check_proj_agreement.shutil, "which", lambda name: str(ogr2ogr))
    points, version, reason = check_proj_agreement.gdal_values(4087)
    assert points is None
    assert "gdaltransform not found" in reason


def test_gdal_values_parses_gdaltransform_output(monkeypatch, tmp_path):
    """Runs the gdaltransform beside ogr2ogr, reads one "x y z" line per
    control point in input order, and takes the PROJ version from --build."""
    (tmp_path / "ogr2ogr").touch()
    (tmp_path / "gdaltransform").touch()
    monkeypatch.setattr(check_proj_agreement.shutil, "which", lambda name: str(tmp_path / "ogr2ogr"))
    calls = []

    def fake_run(args, stdin=""):
        calls.append((args, stdin))
        if "--build" in args:
            return "GDAL_VERSION=3.11.0\nPROJ_BUILD_VERSION=9.8.0\nPROJ_RUNTIME_VERSION=9.8.1\n"
        return "".join(f"0 {i * 1000.5} 0\n" for i in range(len(check_proj_agreement.CONTROL_LATITUDES)))

    monkeypatch.setattr(check_proj_agreement, "_run_gdaltransform", fake_run)
    points, version, reason = check_proj_agreement.gdal_values(4087)

    assert reason is None
    assert version == "9.8.1"
    assert calls[0][0] == [str(tmp_path / "gdaltransform"), "-s_srs", "EPSG:4326", "-t_srs", "EPSG:4087"]
    assert calls[0][1].splitlines()[1] == "0.0 30.0"
    assert points[30.0] == (0.0, 1000.5)


def test_gdal_values_skips_on_short_output(monkeypatch, tmp_path):
    (tmp_path / "ogr2ogr").touch()
    (tmp_path / "gdaltransform").touch()
    monkeypatch.setattr(check_proj_agreement.shutil, "which", lambda name: str(tmp_path / "ogr2ogr"))
    monkeypatch.setattr(check_proj_agreement, "_run_gdaltransform", lambda args, stdin="": "0 0 0\n")
    points, _, reason = check_proj_agreement.gdal_values(4087)
    assert points is None
    assert "returned 1 points" in reason


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

# PROJ >=9.8 ellipsoidal EPSG:4087 values, as in the regression test at the top.
# The check_epsg tests below pin pyproj_reference to these, so they test the
# pass/fail logic alone and don't depend on which PROJ the local pyproj has.
ELLIPSOIDAL_4087 = {
    0.0: (0.0, 0.0),
    30.0: (0.0, 3320113.3979403824),
    45.0: (0.0, 4984944.377977743),
    60.0: (0.0, 6654072.819490511),
    84.0: (0.0, 9331826.561184982),
}

# Pre-9.8 PROJ's spherical-only EPSG:4087 values, i.e. y=a*phi.
OLD_SPHERICAL_4087 = {
    0.0: (0.0, 0.0),
    30.0: (0.0, 3339584.723798207),
    45.0: (0.0, 5009377.085697311),
    60.0: (0.0, 6679169.447596414),
    84.0: (0.0, 9350837.226634981),
}


@pytest.fixture
def pinned_reference(monkeypatch):
    monkeypatch.setattr(check_proj_agreement, "pyproj_reference", lambda epsg: ELLIPSOIDAL_4087)
    return ELLIPSOIDAL_4087


def _skipped(epsg):
    return None, None, "not configured"


def test_check_epsg_passes_when_all_reachable_engines_agree(monkeypatch, capsys, pinned_reference):
    reference = pinned_reference
    for engine in ("gdal_values", "duckdb_values", "postgis_values"):
        monkeypatch.setattr(check_proj_agreement, engine, lambda epsg: (reference, "9.8.1", None))

    assert check_proj_agreement.check_epsg(4087, tolerance=0.001) is True
    assert "MISMATCH" not in capsys.readouterr().out


@pytest.mark.parametrize("engine", ["gdal", "postgis"])
def test_check_epsg_fails_when_a_reprojecting_engine_disagrees(monkeypatch, capsys, engine, pinned_reference):
    for other in ("gdal_values", "duckdb_values", "postgis_values"):
        monkeypatch.setattr(check_proj_agreement, other, _skipped)
    monkeypatch.setattr(check_proj_agreement, f"{engine}_values", lambda epsg: (OLD_SPHERICAL_4087, "9.1.1", None))

    assert check_proj_agreement.check_epsg(4087, tolerance=0.001) is False
    assert f"{engine} (PROJ 9.1.1): MISMATCH" in capsys.readouterr().out


def test_check_epsg_reports_but_passes_a_duckdb_mismatch(monkeypatch, capsys, pinned_reference):
    """DuckDB's bundled PROJ is known-stale and shard.sh never reprojects
    with it, so its mismatch mustn't abort init.sh's preflight."""
    reference = pinned_reference
    monkeypatch.setattr(check_proj_agreement, "gdal_values", lambda epsg: (reference, "9.8.1", None))
    monkeypatch.setattr(check_proj_agreement, "postgis_values", _skipped)
    monkeypatch.setattr(check_proj_agreement, "duckdb_values", lambda epsg: (OLD_SPHERICAL_4087, "9.1.1", None))

    assert check_proj_agreement.check_epsg(4087, tolerance=0.001) is True
    out = capsys.readouterr().out
    assert "duckdb (PROJ 9.1.1): differs" in out
    assert "report only" in out
    assert "MISMATCH" not in out


def test_check_epsg_passes_when_every_engine_is_skipped(monkeypatch, capsys):
    monkeypatch.setattr(check_proj_agreement, "gdal_values", lambda epsg: (None, None, "ogr2ogr not found on PATH"))
    monkeypatch.setattr(check_proj_agreement, "duckdb_values", lambda epsg: (None, None, "duckdb not found on PATH"))
    monkeypatch.setattr(check_proj_agreement, "postgis_values", lambda epsg: (None, None, "PG* environment variables not set"))

    assert check_proj_agreement.check_epsg(4087, tolerance=0.001) is True
    out = capsys.readouterr().out
    assert "gdal: skipped" in out
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
    # No ogr2ogr or duckdb on PATH and no PG* env vars already makes every
    # optional engine skip in a bare test environment -- see the graceful-skip tests
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


# --- real GDAL integration (skipped if ogr2ogr isn't on PATH) --------------

@pytest.mark.skipif(shutil.which("ogr2ogr") is None, reason="ogr2ogr not on PATH")
def test_gdal_values_matches_pyproj_for_epsg_3395():
    """End-to-end check of the real gdaltransform plumbing and axis order.
    EPSG:3395 for the same reason as the DuckDB test above: it doesn't
    depend on which side of PROJ 9.8 the local GDAL links."""
    reference = check_proj_agreement.pyproj_reference(3395)
    points, version, reason = check_proj_agreement.gdal_values(3395)
    assert reason is None, reason
    assert version
    assert check_proj_agreement.compare(reference, points, tolerance=0.001) == []
