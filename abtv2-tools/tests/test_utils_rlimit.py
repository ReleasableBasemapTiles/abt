"""Tests for abt.utils.rlimit.raise_open_file_limit. get/setrlimit are faked
rather than exercised for real: the genuine call would either be a no-op (on
a host whose limits are already raised) or irreversibly change the test
process's own ceiling, and neither outcome tells us anything about the
fallback behaviour that matters on a host that refuses the first target.
"""

import resource

import pytest

from abt.utils import rlimit


class FakeRlimit:
    """Stands in for resource.get/setrlimit over a single fake limit.

    `ceiling`, when set, is the largest soft value setrlimit will accept --
    standing in for a kernel (macOS) that rejects values its own hard limit
    nominally permits.
    """

    def __init__(self, soft: int, hard: int, ceiling: int = None):
        self.soft = soft
        self.hard = hard
        self.ceiling = ceiling
        self.attempted = []

    def getrlimit(self, which):
        assert which == resource.RLIMIT_NOFILE
        return self.soft, self.hard

    def setrlimit(self, which, limits):
        assert which == resource.RLIMIT_NOFILE
        soft, hard = limits
        self.attempted.append(soft)
        if self.ceiling is not None and soft > self.ceiling:
            raise ValueError("current limit exceeds maximum limit")
        self.soft, self.hard = soft, hard


@pytest.fixture
def fake_limits(monkeypatch):
    def install(soft, hard, ceiling=None) -> FakeRlimit:
        fake = FakeRlimit(soft, hard, ceiling)
        monkeypatch.setattr(rlimit.resource, "getrlimit", fake.getrlimit)
        monkeypatch.setattr(rlimit.resource, "setrlimit", fake.setrlimit)
        return fake

    return install


def test_raises_soft_limit_to_a_finite_hard_limit(fake_limits):
    fake = fake_limits(soft=1024, hard=1048576)
    assert rlimit.raise_open_file_limit() == (1024, 1048576)
    assert fake.soft == 1048576


def test_is_a_noop_when_soft_already_equals_hard(fake_limits):
    fake = fake_limits(soft=1048576, hard=1048576)
    assert rlimit.raise_open_file_limit() == (1048576, 1048576)
    assert fake.attempted == []


def test_is_a_noop_when_both_limits_are_unlimited(fake_limits):
    fake = fake_limits(soft=resource.RLIM_INFINITY, hard=resource.RLIM_INFINITY)
    previous, current = rlimit.raise_open_file_limit()
    assert previous == current == resource.RLIM_INFINITY
    assert fake.attempted == []


def test_walks_down_the_ladder_when_an_unlimited_hard_limit_is_refused(fake_limits):
    # macOS shape: hard limit claims to be unlimited, kernel caps it anyway.
    fake = fake_limits(soft=256, hard=resource.RLIM_INFINITY, ceiling=20000)
    assert rlimit.raise_open_file_limit() == (256, 10240)
    assert fake.soft == 10240
    assert fake.attempted == [1048576, 262144, 65536, 10240]


def test_leaves_the_soft_limit_alone_when_every_target_is_refused(fake_limits):
    fake = fake_limits(soft=64, hard=resource.RLIM_INFINITY, ceiling=100)
    assert rlimit.raise_open_file_limit() == (64, 64)
    assert fake.soft == 64
    assert fake.attempted == list(rlimit.UNLIMITED_FALLBACK_TARGETS)


def test_never_lowers_a_soft_limit_that_already_beats_the_ladder(fake_limits):
    # Only the top target exceeds the current soft limit, and it's refused;
    # every remaining rung would be a downgrade, so none is attempted.
    fake = fake_limits(soft=524288, hard=resource.RLIM_INFINITY, ceiling=524288)
    assert rlimit.raise_open_file_limit() == (524288, 524288)
    assert fake.soft == 524288
    assert fake.attempted == [1048576]
