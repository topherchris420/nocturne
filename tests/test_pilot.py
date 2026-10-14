"""The randomised rollout and its safety brake.

`EXT-PIL-*` check that DC's real segments randomise reproducibly and in
balance, that the exact rate test has the right size and sees a real harm,
and that the power arithmetic is the textbook one.
"""
from __future__ import annotations

import math
import random
from datetime import date

import pytest

from vdl7.pilot import (Segment, brake, exposure_needed, load_segments, public_seed, rate_ratio_test,
                        stepped_wedge)

SEED = "DC Lottery Pick-4 evening draw, 2026-12-01 (published before the draw)"


@pytest.fixture(scope="module")
def segs():
    return load_segments()


def test_EXT_PIL_1_dc_segments_randomise_reproducibly_and_in_balance(segs):
    assert len(segs) > 10_000 and sum(s.lights for s in segs) > 65_000
    a = stepped_wedge(segs, SEED)
    b = stepped_wedge(list(reversed(segs)), SEED)            # input order does not matter
    assert a.assignment == b.assignment
    assert stepped_wedge(segs, SEED + ".").assignment != a.assignment
    sizes = [sum(1 for w in a.assignment.values() if w == k) for k in range(1, 5)]
    assert max(sizes) - min(sizes) <= 1
    for ward, row in a.balance(segs, "ward").items():
        assert max(row) - min(row) <= 6, (ward, row)         # every ward in every wave
    for cls, row in a.balance(segs, "road_class").items():
        assert max(row) - min(row) <= 0.05 * sum(row) + 8, (cls, row)
    assert a.wave_start(1) == date(2027, 1, 4) and a.wave_start(4) == date(2027, 6, 21)   # 8-week waves
    first = next(iter(a.assignment))
    assert a.switched(first, date(2027, 6, 1)) and not a.switched(first, date(2026, 12, 31))


def test_EXT_PIL_2_seed_is_public_arithmetic():
    assert public_seed("abc") == int("ba7816bf8f01cfea", 16)  # SHA-256("abc"), first 8 bytes


def test_EXT_PIL_3_exact_test_size_and_power():
    """Under the null the brake fires at most at its nominal rate; with a
    real 75 % excess on the switched segments it fires most of the time
    (the exact test is conservative, so somewhat less than the normal
    approximation's 88 %)."""
    rng = random.Random(3)

    def poisson(lam):
        # Knuth, fine for the small means here
        L, k, p = math.exp(-lam), 0, 1.0
        while True:
            p *= rng.random()
            if p <= L:
                return k
            k += 1
    trials, fired_null, fired_harm = 400, 0, 0
    for _ in range(trials):
        on, off = poisson(40.0), poisson(40.0)
        fired_null += rate_ratio_test(on, 1.0, off, 1.0).p_harm < 0.05
        on, off = poisson(70.0), poisson(40.0)
        fired_harm += rate_ratio_test(on, 1.0, off, 1.0).p_harm < 0.05
    assert fired_null / trials <= 0.07 and fired_harm / trials > 0.7


def test_EXT_PIL_4_interval_and_brake():
    t = rate_ratio_test(30, 1000.0, 15, 1000.0)
    assert t.rate_ratio == pytest.approx(2.0) and t.lo < 2.0 < t.hi and t.lo > 1.0
    assert 0.0125 < t.p_harm < 0.05                               # significant once, not at a quarter of alpha
    assert brake(30, 1000.0, 15, 1000.0, looks=4)[0] == "continue"
    assert brake(30, 1000.0, 15, 1000.0, looks=1)[0] == "pause"
    assert brake(40, 1000.0, 15, 1000.0, looks=4)[0] == "pause"
    assert brake(20, 1000.0, 18, 1000.0)[0] == "continue"
    even = rate_ratio_test(10, 500.0, 20, 1000.0)                  # unequal exposure, equal rates
    assert even.rate_ratio == pytest.approx(1.0) and even.p_harm > 0.3


def test_EXT_PIL_5_power_arithmetic():
    """(z_.975 + z_.8)^2 (1/r + 1/(r RR)) / ln(RR)^2."""
    n = exposure_needed(0.001, 1.2)
    assert n == pytest.approx((1.959964 + 0.841621) ** 2 * (1000 + 1000 / 1.2) / math.log(1.2) ** 2, rel=1e-5)
    assert exposure_needed(0.001, 1.5) < n < exposure_needed(0.0005, 1.2)


def test_EXT_PIL_6_small_custom_segment_lists_work(tmp_path):
    segs = [Segment(f"s{i}", str(i % 3), "local") for i in range(30)]
    plan = stepped_wedge(segs, "x", waves=3, wave_days=7)
    plan.to_csv(str(tmp_path / "plan.csv"), segs)
    rows = (tmp_path / "plan.csv").read_text().splitlines()
    assert rows[0].startswith("segment,ward") and len(rows) == 31
