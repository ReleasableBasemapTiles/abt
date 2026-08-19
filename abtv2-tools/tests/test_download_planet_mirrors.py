"""Tests for abt.download.planet_mirrors: the pure _attr_to_hash
reconciliation helper, and discover_planet_sources' winner-selection
heuristic (prefer a more widely-mirrored older file over an
under-propagated newest one). _load_mirror_sources is monkeypatched to a
pure function of each mirror's fixed position in PLANET_MIRRORS, so this
never makes a real network call and is safe under discover_planet_sources'
real ThreadPoolExecutor concurrency (no shared mutable state between
worker threads)."""

import datetime

import pytest

from abt.download import planet_mirrors as pm
from abt.download.planet_mirrors import PLANET_MIRRORS, PlanetSource, _attr_to_hash, discover_planet_sources


def make_source(hash_, mirror_country, timestamp=None, file_len=None):
    return PlanetSource(
        name="planet-latest.osm.pbf",
        url=f"https://{mirror_country.lower()}.example.com/planet-latest.osm.pbf",
        mirror_country=mirror_country,
        hash=hash_,
        timestamp=timestamp,
        file_len=file_len,
    )


# --- _attr_to_hash ---------------------------------------------------------

def test_attr_to_hash_returns_none_on_disagreement():
    ts = datetime.datetime(2024, 1, 1)
    sources_by_hash = {
        "hashA": [make_source("hashA", "US", timestamp=ts)],
        "hashB": [make_source("hashB", "DE", timestamp=ts)],
    }
    assert _attr_to_hash(sources_by_hash, "timestamp") is None


def test_attr_to_hash_maps_agreeing_values():
    ts = datetime.datetime(2024, 1, 1)
    sources_by_hash = {
        "hashA": [make_source("hashA", "US", timestamp=ts), make_source("hashA", "DE", timestamp=ts)],
    }
    assert _attr_to_hash(sources_by_hash, "timestamp") == {ts: "hashA"}


def test_attr_to_hash_ignores_none_values():
    sources_by_hash = {"hashA": [make_source("hashA", "US", timestamp=None)]}
    assert _attr_to_hash(sources_by_hash, "timestamp") == {}


# --- discover_planet_sources winner-selection heuristic --------------------

def _patch_loader_by_mirror_index(monkeypatch, assignments):
    """assignments: list of (lo, hi, factory) -- mirrors at PLANET_MIRRORS
    index [lo, hi) get [factory()] as their sources; everything else gets
    []. Deterministic per-mirror-identity, so it's safe under real
    ThreadPoolExecutor concurrency (no shared mutable state)."""
    def fake_loader(mirror, session, logger):
        idx = PLANET_MIRRORS.index(mirror)
        for lo, hi, factory in assignments:
            if lo <= idx < hi:
                return [factory()]
        return []

    monkeypatch.setattr(pm, "_load_mirror_sources", fake_loader)


def test_discover_planet_sources_prefers_wider_mirrored_previous_file(tmp_path, monkeypatch):
    """When the newest file is mirrored by meaningfully fewer sources than
    the second-newest (< ~2/3 as many), prefer the more widely-available
    previous file -- it likely hasn't propagated everywhere yet."""
    newest_ts = datetime.datetime(2024, 6, 1)
    older_ts = datetime.datetime(2024, 5, 1)
    assert len(PLANET_MIRRORS) >= 7, "test assumes at least 7 known mirrors"

    _patch_loader_by_mirror_index(monkeypatch, [
        (0, 2, lambda: make_source("new_hash", "US", timestamp=newest_ts)),  # 2 mirrors
        (2, 7, lambda: make_source("old_hash", "DE", timestamp=older_ts)),  # 5 mirrors
    ])

    _, winning_hash = discover_planet_sources(log_dir=tmp_path)
    assert winning_hash == "old_hash"


def test_discover_planet_sources_force_latest_skips_the_propagation_heuristic(tmp_path, monkeypatch):
    newest_ts = datetime.datetime(2024, 6, 1)
    older_ts = datetime.datetime(2024, 5, 1)

    _patch_loader_by_mirror_index(monkeypatch, [
        (0, 2, lambda: make_source("new_hash", "US", timestamp=newest_ts)),
        (2, 7, lambda: make_source("old_hash", "DE", timestamp=older_ts)),
    ])

    _, winning_hash = discover_planet_sources(log_dir=tmp_path, force_latest=True)
    assert winning_hash == "new_hash"


def test_discover_planet_sources_keeps_newest_when_mirror_counts_are_close(tmp_path, monkeypatch):
    # 3 mirrors on the newest file vs 4 on the previous one: 3*1.5=4.5 is
    # NOT < 4, so the newest file should still win (not under-propagated
    # enough to fall back).
    newest_ts = datetime.datetime(2024, 6, 1)
    older_ts = datetime.datetime(2024, 5, 1)

    _patch_loader_by_mirror_index(monkeypatch, [
        (0, 3, lambda: make_source("new_hash", "US", timestamp=newest_ts)),
        (3, 7, lambda: make_source("old_hash", "DE", timestamp=older_ts)),
    ])

    _, winning_hash = discover_planet_sources(log_dir=tmp_path)
    assert winning_hash == "new_hash"


def test_discover_planet_sources_raises_when_no_mirror_has_a_hash(tmp_path, monkeypatch):
    monkeypatch.setattr(pm, "_load_mirror_sources", lambda mirror, session, logger: [])
    with pytest.raises(RuntimeError, match="Unable to determine"):
        discover_planet_sources(log_dir=tmp_path)


def test_discover_planet_sources_raises_when_mirrors_disagree_on_timestamp(tmp_path, monkeypatch):
    # Same timestamp, two different hashes -- mirrors actively disagree,
    # not just "some are stale".
    ts = datetime.datetime(2024, 6, 1)
    _patch_loader_by_mirror_index(monkeypatch, [
        (0, 1, lambda: make_source("hash_a", "US", timestamp=ts)),
        (1, 2, lambda: make_source("hash_b", "DE", timestamp=ts)),
    ])
    with pytest.raises(RuntimeError, match="disagree"):
        discover_planet_sources(log_dir=tmp_path)


def test_discover_planet_sources_excludes_primary_mirror_when_enough_others_agree(tmp_path, monkeypatch):
    ts = datetime.datetime(2024, 6, 1)
    # PLANET_MIRRORS[0] is the primary (GB) mirror -- see module docstring.
    assert PLANET_MIRRORS[0].is_primary

    def fake_loader(mirror, session, logger):
        idx = PLANET_MIRRORS.index(mirror)
        if idx >= 4:
            return []
        # Distinct, recognizable URL per mirror (not the real mirror.url)
        # so inclusion/exclusion of a specific source can be checked
        # precisely, and is_primary is forwarded from the real mirror
        # rather than defaulted -- both matter for this test.
        return [PlanetSource(
            name="planet-latest.osm.pbf",
            url=f"https://fake-mirror-{idx}.example.com/planet-latest.osm.pbf",
            mirror_country=mirror.country,
            is_primary=mirror.is_primary,
            hash="only_hash",
            timestamp=ts,
        )]

    monkeypatch.setattr(pm, "_load_mirror_sources", fake_loader)

    urls, winning_hash = discover_planet_sources(log_dir=tmp_path)
    assert winning_hash == "only_hash"
    assert len(urls) == 3
    assert "https://fake-mirror-0.example.com/planet-latest.osm.pbf" not in urls, (
        "primary mirror (index 0) should be excluded once >2 other sources agree"
    )
