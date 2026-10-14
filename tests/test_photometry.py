"""Section 3 verification: LM-63 parsing, TM-15 BUG ratings, light trespass.

`EXT-OPT-*` check the integration against closed-form answers, the file
parser against the format's corners, and the trespass arithmetic against
the inverse-square and cosine laws.
"""
from __future__ import annotations

import math

import pytest

from vdl7.photometry import (B_TABLE, CIE150_WINDOW_LX, Photometry, _rating, load_ies, parse_ies, synthetic,
                             trespass_report, window_exposure, write_ies)

I0 = 1000.0


def band(v0, v1):
    """Integral of sin V over [v0, v1] degrees."""
    return math.cos(math.radians(v0)) - math.cos(math.radians(v1))


def iso(v_max=180, h=(0.0,)):
    v = [float(x) for x in range(0, v_max + 1, 5)]
    return Photometry(v, list(h), [[I0] * len(v) for _ in h])


def test_EXT_OPT_1_zonal_lumens_match_closed_form_for_an_isotropic_source():
    z = iso().zonal_lumens()
    exact = {"BL": math.pi * I0 * band(0, 30), "BM": math.pi * I0 * band(30, 60), "BH": math.pi * I0 * band(60, 80),
             "BVH": math.pi * I0 * band(80, 90), "UL": 2 * math.pi * I0 * band(90, 100),
             "UH": 2 * math.pi * I0 * band(100, 180), "total": 4 * math.pi * I0}
    for k, v in exact.items():
        assert z[k] == pytest.approx(v, rel=1e-4), k
        if k.startswith("B"):
            assert z["F" + k[1:]] == pytest.approx(v, rel=1e-4)
    bug = iso().bug()                      # BH 1025 -> B3; UL 1091 > 1000 -> U5; FVH 545 -> G4
    assert (bug.B, bug.U, bug.G) == (3, 5, 4) and bug.symmetric_table
    assert str(bug) == "B3-U5-G4" and bug.limiting["U"] == "UH" and bug.limiting["G"] in ("FVH", "BVH")


def test_EXT_OPT_2_lower_hemisphere_only_photometry_is_u0():
    p = iso(v_max=90)
    assert p.zonal_lumens()["up"] == 0.0 and p.ulr == 0.0 and p.bug().U == 0


def test_EXT_OPT_3_declared_symmetry_expands_to_the_same_light():
    """A full 0-360 table and the same light declared quadrant-symmetric
    (0-90) or bilateral about 90-270 give identical zonal lumens."""
    v = [float(x) for x in range(0, 181, 5)]

    def cd(vv, hh):                       # symmetric about both the 0-180 and 90-270 planes
        return 500 + 300 * abs(math.cos(math.radians(hh))) * math.sin(math.radians(min(vv, 89)))
    full_h = [float(x) for x in range(0, 361, 5)]
    full = Photometry(v, full_h, [[cd(a, b) for a in v] for b in full_h])
    quad_h = [float(x) for x in range(0, 91, 5)]
    quad = Photometry(v, quad_h, [[cd(a, b) for a in v] for b in quad_h])
    bil_h = [float(x) for x in range(90, 271, 5)]
    bil = Photometry(v, bil_h, [[cd(a, b) for a in v] for b in bil_h])
    assert quad.symmetry == "quadrant" and bil.symmetry == "bilateral-90-270"
    zf = full.zonal_lumens()
    for other in (quad, bil):
        zo = other.zonal_lumens()
        for k in zf:
            assert zo[k] == pytest.approx(zf[k], rel=1e-6, abs=1e-6), k


def test_EXT_OPT_4_front_and_back_split_on_the_street_side():
    """I = 1000 (1 + 0.5 sin H): the street half (H 0-180) carries
    (pi + 1) / (pi - 1) times the house half."""
    v = [float(x) for x in range(0, 91, 5)]
    h = [float(x) for x in range(0, 361, 5)]
    p = Photometry(v, h, [[I0 * (1 + 0.5 * math.sin(math.radians(b)))] * len(v) for b in h])
    z = p.zonal_lumens()
    assert z["front"] == pytest.approx(I0 * (math.pi + 1), rel=2e-3)
    assert z["back"] == pytest.approx(I0 * (math.pi - 1), rel=2e-3)
    assert z["FL"] / z["BL"] == pytest.approx((math.pi + 1) / (math.pi - 1), rel=3e-3)
    turned = Photometry(v, h, p.candela, street_side_h=270.0)          # a file with the house at 90
    assert turned.zonal_lumens()["front"] == pytest.approx(z["back"], rel=1e-9)


def test_EXT_OPT_5_rating_thresholds_are_inclusive():
    lims = B_TABLE["BM"]
    assert _rating(220, lims) == 0 and _rating(220.01, lims) == 1
    assert _rating(8500, lims) == 4 and _rating(8500.1, lims) == 5
    up = (0, 10, 50, 500, 1000)
    assert _rating(0, up) == 0 and _rating(0.01, up) == 1 and _rating(1000.5, up) == 5


IES_TEXT = """IESNA:LM-63-2002\r
[TEST] parser corners\r
[MANUFAC] nobody\r
TILT=INCLUDE\r
1\r
3\r
0 45 90\r
1 1 1\r
1, -1, 2, 3, 2, 1, 2, 0, 0, 0\r
0.9 1 52\r
0 45 90\r
0 180\r
100 80 10\r
100,80,10\r
"""


def test_EXT_OPT_6_lm63_corners():
    """Keywords, TILT=INCLUDE skipped, commas, CRLF, candela multiplier and
    ballast factor applied, absolute photometry, round trip."""
    p = parse_ies(IES_TEXT)
    assert p.keywords["TEST"] == "parser corners" and p.tilt_ignored
    assert p.candela[0] == pytest.approx([180.0, 144.0, 18.0])           # x 2 multiplier x 0.9 ballast
    assert p.lumens_rated is None and p.input_watts == 52 and p.symmetry == "bilateral-0-180"
    q = parse_ies(write_ies(p))
    assert all(a == pytest.approx(b) for a, b in zip(q.candela, p.candela)) and q.v_angles == p.v_angles
    with pytest.raises(ValueError, match="Type C"):
        parse_ies(IES_TEXT.replace("3, 2, 1, 2", "3, 2, 2, 2"))
    with pytest.raises(ValueError, match="truncated"):
        parse_ies(IES_TEXT.rsplit("100,80,10", 1)[0])
    with pytest.raises(ValueError, match="TILT"):
        parse_ies("IESNA:LM-63-2002\n[TEST] x\n")


def test_EXT_OPT_7_point_illuminance_obeys_inverse_square_and_cosine():
    p = iso()
    assert p.illuminance(9.0, (0, 0, 0), (0, 0, 1)) == pytest.approx(I0 / 81)          # nadir
    e = p.illuminance(9.0, (0, -10, 5), (0, 1, 0))                                      # window facing the street
    r2 = 10 ** 2 + 4 ** 2
    assert e == pytest.approx(I0 * (10 / math.sqrt(r2)) / r2)
    assert p.illuminance(9.0, (0, -10, 5), (0, -1, 0)) == 0.0                           # facing away


def test_EXT_OPT_8_window_trespass_scales_with_dimming_and_spectrum():
    road = synthetic("roadway", 6000)
    full = window_exposure(road, 9, 10, 5)
    assert full.zone == "BH" and 0 < full.ev_lux < 10
    half = window_exposure(road, 9, 10, 5, level_pct=50)
    assert half.ev_lux == pytest.approx(full.ev_lux / 2)
    amber = window_exposure(road, 9, 10, 5, spectrum="PC-Amber")
    assert amber.ev_lux == pytest.approx(full.ev_lux) and amber.mel_edi_lux < 0.2 * full.mel_edi_lux
    rows = trespass_report(road, 9, 10, 5, {"evening": 80, "curfew": 40, "deep": 30},
                           {"evening": "2700K", "curfew": "PC-Amber", "deep": "PC-Amber"}, env_zone="E3")
    by = {r["phase"]: r for r in rows}
    assert by["evening"]["cie150_limit_lux"] == CIE150_WINDOW_LX["E3"][0]
    assert by["curfew"]["cie150_limit_lux"] == CIE150_WINDOW_LX["E3"][1]
    assert by["deep"]["ev_lux"] < by["evening"]["ev_lux"] and by["deep"]["below_sleep_guide"]


def test_EXT_OPT_9_globe_uplight_and_the_reflector_retrofit(tmp_path):
    """DC's ~16,600 post-top globes and teardrops are where its streetlight
    uplight lives. The examples: a clear globe is U4, the same globe with an
    internal top reflector is U0, a modern roadway optic is U0."""
    legacy = synthetic("globe", 4000, ulr=0.15)
    retro = synthetic("globe", 4000, ulr=0.0)
    assert legacy.bug().U == 4 and legacy.ulr == pytest.approx(0.15, abs=1e-3)
    assert retro.bug().U == 0 and retro.ulr == 0.0
    f = tmp_path / "x.ies"
    f.write_text(write_ies(legacy, {"TEST": "t"}, watts=40))
    loaded = load_ies(str(f))
    assert str(loaded.bug()) == str(legacy.bug()) and loaded.input_watts == 40
