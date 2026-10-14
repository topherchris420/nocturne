"""The randomised rollout and its safety brake.

`EXT-PIL-*` check that DC's real segments randomise reproducibly and in
balance, that the exact rate test has the right size and sees a real harm,
that the brake compares within periods so the season cannot hide a harm,
and that the power arithmetic is the textbook one.
"""
from __future__ import annotations

import math
import random
from datetime import date, timedelta

import pytest

from vdl7.pilot import (Segment, brake, exposure_needed, load_segments, public_seed, rate_ratio_test,
                        stepped_wedge, stratified_rate_test, tally)

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
    assert brake([(30, 1000.0, 15, 1000.0)], looks=4)[0] == "continue"
    assert brake([(30, 1000.0, 15, 1000.0)], looks=1)[0] == "pause"
    assert brake([(40, 1000.0, 15, 1000.0)], looks=4)[0] == "pause"
    assert brake([(20, 1000.0, 18, 1000.0)])[0] == "continue"
    even = rate_ratio_test(10, 500.0, 20, 1000.0)                  # unequal exposure, equal rates
    assert even.rate_ratio == pytest.approx(1.0) and even.p_harm > 0.3
    assert brake([(0, 0.0, 5, 1000.0)]) == ("continue", rate_ratio_test(0, 0.0, 5, 1000.0))   # nothing to compare
    with pytest.raises(ValueError):
        rate_ratio_test(-1, 10.0, 3, 10.0)


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


def _wedge(rates, share_on, harm, nights_exposure=12106 * 56.0):
    """Expected counts per period: crash risk falls from winter to June
    (it tracks hours of darkness), while the switched share grows."""
    return [(round(r * harm * f * nights_exposure), f * nights_exposure,
             round(r * (1 - f) * nights_exposure), (1 - f) * nights_exposure) for r, f in zip(rates, share_on)]


def test_EXT_PIL_7_the_season_cannot_hide_a_harm():
    """The reviewer's case: night-crash risk tracks hours below -3 deg
    (13.3, 11.1, 9.1 h in the three periods) while each wave raises the
    switched share. Pooling all nights so far mixes the season into the
    comparison and a real 15 % harm reads as RR 1.01, 'continue'. Within
    periods, it is RR 1.15 and the brake pulls."""
    rates = [0.0018 * h / 11.1 for h in (13.3, 11.1, 9.1)]
    harm = _wedge(rates, (0.25, 0.5, 0.75), 1.15)
    pooled = rate_ratio_test(*(sum(p[i] for p in harm) for i in range(4)))
    assert pooled.rate_ratio < 1.05 and pooled.p_harm > 0.2
    decision, t = brake(harm, looks=3)
    assert decision == "pause" and t.rate_ratio == pytest.approx(1.15, abs=0.01) and t.lo > 1.0
    null = _wedge(rates, (0.25, 0.5, 0.75), 1.0)
    assert rate_ratio_test(*(sum(p[i] for p in null) for i in range(4))).rate_ratio < 0.9   # pooling flatters too
    assert brake(null, looks=3)[0] == "continue" and stratified_rate_test(null).rate_ratio == pytest.approx(1.0, abs=0.01)


def test_EXT_PIL_8_stratified_test_is_exact():
    """The p-value is the convolution of the periods' binomials, checked
    by enumeration; the interval inverts the same distribution; one period
    is the plain test; periods with no comparison drop out."""
    st = [(4, 30.0, 2, 90.0), (3, 50.0, 5, 50.0), (2, 40.0, 0, 0.0)]
    pmf = lambda n, p, k: math.comb(n, k) * p ** k * (1 - p) ** (n - k)
    brute = sum(pmf(6, 0.25, a) * pmf(8, 0.5, b) for a in range(7) for b in range(9) if a + b >= 7)
    t = stratified_rate_test(st)
    assert t.p_harm == pytest.approx(brute, rel=1e-12) and t.lo < t.rate_ratio < t.hi
    num, den = 4 * 90 / 120 + 3 * 50 / 100, 2 * 30 / 120 + 5 * 50 / 100
    assert t.rate_ratio == pytest.approx(num / den)                  # Mantel-Haenszel
    one = stratified_rate_test([(30, 1000.0, 15, 1000.0)])
    assert (one.p_harm, one.lo, one.hi) == pytest.approx(tuple(getattr(rate_ratio_test(30, 1000.0, 15, 1000.0), k)
                                                               for k in ("p_harm", "lo", "hi")))


def test_EXT_PIL_9_size_with_a_season():
    rng = random.Random(11)

    def poisson(lam):
        L, k, p = math.exp(-lam), 0, 1.0
        while True:
            p *= rng.random()
            if p <= L:
                return k
            k += 1
    fired = 0
    for _ in range(300):
        st = []
        for r, f in zip((0.0009, 0.0006, 0.0004), (0.25, 0.5, 0.75)):
            st.append((poisson(r * f * 40000), f * 40000, poisson(r * (1 - f) * 40000), (1 - f) * 40000))
        fired += stratified_rate_test(st).p_harm < 0.05
    assert fired / 300 <= 0.06


def test_EXT_PIL_10_tally_from_the_plan_and_a_crash_list():
    segs = [Segment(f"s{i}", str(i % 2), "local") for i in range(8)]
    plan = stepped_wedge(segs, "seed", waves=4, start=date(2027, 1, 4), wave_days=7)
    switch_on = {s.id: plan.wave_start(plan.assignment[s.id]) for s in segs}
    w1 = next(s for s, d in switch_on.items() if d == date(2027, 1, 4))
    w4 = next(s for s, d in switch_on.items() if d == date(2027, 1, 25))
    events = [(w1, date(2027, 1, 5)), (w4, date(2027, 1, 5)), (w4, date(2027, 1, 26)),
              ("nope", date(2027, 1, 5)), (w1, date(2027, 1, 1)), (w1, date(2027, 2, 9))]
    periods, skipped = tally(switch_on, events, through=date(2027, 1, 31))
    assert skipped == 3 and [p.nights for p in periods] == [7, 7, 7, 7]
    assert (periods[0].events_on, periods[0].exposure_on, periods[0].events_off, periods[0].exposure_off) == (1, 14, 1, 42)
    assert periods[3].events_on == 1 and periods[3].exposure_off == 0               # all switched: no comparison
    assert tally(switch_on, [], through=date(2027, 1, 7))[0][0].nights == 4
    with pytest.raises(ValueError):
        stepped_wedge(segs + segs[:1], "seed")                                       # a segment listed twice
