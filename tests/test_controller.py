"""VDL-7 acceptance suite.

`test_R_*`   the requirements tabulated in Section 6.2 of VD-DSL-SPEC-001
             RevA, one test per row (R-MESH-1/2 split in two).
`test_EXT_*` requirements stated elsewhere in the spec (Sections 2-6) that
             the 6.2 table does not list, plus the safety fixes this
             implementation makes to the spec's own formulas.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta

import pytest

from vdl7 import spectral
from vdl7.bench import Bench
from vdl7.clock import (DC_LAT, DC_LON, UTC, Photocell, RtcHoldover, is_dst, local_to_utc,
                        night_bounds, solar_elevation_exact, sun_times, to_local)
from vdl7.cms import Cms, geofence
from vdl7.controller import Flash, Mode
from vdl7.driver import LuminaireDriver
from vdl7.events import EventKind, Priority, make_targets
from vdl7.mesh import MeshNetwork
from vdl7.profiles import (DEFAULT_PROFILES, Phase, RoadClass, clo_factor, default_bundle,
                           phase_for_hour)
from vdl7.security import SignedMessage


def hm(dt: datetime) -> float:
    return dt.hour * 60 + dt.minute + dt.second / 60


# ============================================================ 6.2: CLOCK
def test_R_CLK_1_dst_rule_matches_iana_2024_2030():
    """Firmware POSIX rule matches the IANA database at every 6-hour step."""
    zoneinfo = pytest.importorskip("zoneinfo")
    ny = zoneinfo.ZoneInfo("America/New_York")
    t, end, n = datetime(2024, 1, 1, tzinfo=UTC), datetime(2031, 1, 1, tzinfo=UTC), 0
    while t < end:
        assert is_dst(t) == (t.astimezone(ny).dst() != timedelta(0)), t
        t += timedelta(hours=6)
        n += 1
    assert n > 10_000


@pytest.mark.parametrize("d, rise, sset", [
    (date(2026, 10, 13), "07:15", "18:32"),
    (date(2026, 12, 21), "07:23", "16:49"),
    (date(2026, 6, 21), "05:43", "20:37"),
])
def test_R_CLK_2_astronomical_night_at_dc(d, rise, sset):
    """Known sunrise/sunset for DC within 3 min; dusk and dawn are the -3 deg
    crossings; and the controller switches on at that crossing with the
    photocell blind, not a minute either side."""
    r, s = sun_times(DC_LAT, DC_LON, d)
    def mins(x): h, m = x.split(":"); return int(h) * 60 + int(m)
    assert abs(hm(r) - mins(rise)) <= 3 and abs(hm(s) - mins(sset)) <= 3
    dusk, dawn = night_bounds(DC_LAT, DC_LON, d)
    assert solar_elevation_exact(DC_LAT, DC_LON, dusk) == pytest.approx(-3.0, abs=0.01)
    assert solar_elevation_exact(DC_LAT, DC_LON, dawn) == pytest.approx(-3.0, abs=0.01)
    start = to_local(dusk - timedelta(minutes=30))
    b = Bench(RoadClass.LOCAL, start=start.isoformat(sep=" "))
    b.lx_override = 500.0                                     # photocell reads day all night
    assert not b.run_until(to_local(dusk - timedelta(seconds=60)).isoformat(sep=" ")).lit
    out = b.run_until(to_local(dusk + timedelta(seconds=60)).isoformat(sep=" "))
    assert out.lit and "PHOTOCELL_VETOED" in out.reasons


def test_R_CLK_3_rtc_holdover_trust():
    """Trusted at 1 year, not at 4; never before the first sync; a 7-day
    supercap keeps time, a longer cut resets the clock and its counter."""
    rtc = RtcHoldover(drift_ppm=3.0, trust_budget_s=300.0)
    assert not rtc.trusted(0.0)
    rtc.sync(0.0, datetime(2026, 10, 13, 22, 0, tzinfo=UTC))
    assert rtc.trusted(365 * 86400.0) and rtc.error_bound_s(365 * 86400.0) < 100
    assert not rtc.trusted(4 * 365 * 86400.0)
    rtc.power_cycle(1000.0, 3 * 86400.0)
    assert rtc.trusted(0.0) and rtc.raw(0.0) == pytest.approx(1000.0 + 3 * 86400.0)
    epoch = rtc.epoch
    rtc.power_cycle(0.0, 10 * 86400.0)
    assert not rtc.trusted(0.0) and rtc.epoch == epoch + 1 and rtc.raw(0.0) == 0.0


# ========================================================== 6.2: DIMMING
def test_R_DIM_1_curfew_profile_arterial_60_at_2330():
    out = Bench(RoadClass.ARTERIAL).run_until("2026-10-13 23:30", dt=5)
    assert out.mode == Mode.ONLINE and out.phase == Phase.CURFEW and out.level == 60


# ======================================================== 6.2: FAIL-SAFE
def test_R_FS_1_total_outage_autonomous_local_30_at_0100():
    """5 h with no backhaul or mesh: AUTONOMOUS, local street at 30 % at 01:00."""
    b = Bench(RoadClass.LOCAL)
    b.run_until("2026-10-13 20:00", dt=5)
    b.go_offline()
    assert b.run_until("2026-10-13 20:20", dt=5).mode == Mode.AUTONOMOUS
    out = b.run_until("2026-10-14 01:01", dt=5)          # 10 s fade past the 01:00 step
    assert out.mode == Mode.AUTONOMOUS and out.phase == Phase.DEEP and out.level == 30


def test_R_FS_2_backhaul_only_loss_mesh_applies_emergency():
    b = Bench(RoadClass.ALLEY)
    b.run_until("2026-10-14 01:00", dt=5)
    b.go_offline()
    b.mesh_gateway = True
    out = b.run_until("2026-10-14 01:20", dt=5)
    assert out.mode == Mode.MESH and out.level == 20
    b.send(EventKind.EMERGENCY, ttl_s=3600, payload={"incident": "F-2201"}, via="mesh")
    out = b.advance(10)
    assert out.mode == Mode.MESH and out.level == 100
    assert b.advance(3600 + 120, dt=5).level == 20       # TTL elapsed, 80-point fade at 1 %/s


def test_R_FS_3_clock_lost_reboot_safe_lands_curfew():
    """A clockless node (RTC counter running, absolute time untrusted) loses
    power at 21:00. The monotonic clock restarts at zero; the RTC counter
    rides through on the supercap. From the photocell and the flash
    checkpoint alone it resumes the evening level and lands the 23:00
    curfew within 10 min."""
    learner = Bench(RoadClass.LOCAL, start="2026-10-12 17:00")
    learner.run_until("2026-10-13 08:00", dt=10)          # one clocked night in flash
    rtc = learner.rtc
    rtc.reset()                                           # supercap drained: time and counter lost
    b = Bench(RoadClass.LOCAL, start="2026-10-13 15:00", flash=learner.flash, rtc=rtc,
              online=False, cms=learner.cms)
    out = b.run_until("2026-10-13 21:00", dt=10)
    assert out.mode == Mode.SAFE and out.level == 80 and "SAFE_CLOCK" in out.reasons
    b.power_cut(outage_s=20 * 60, supercap_ok=True)
    assert b.mono == 0.0
    reboot_utc = b.utc
    b.keep_history = True
    out = b.run_until("2026-10-13 21:25", dt=10)
    assert out.mode == Mode.SAFE and out.lit and out.level == 80 and "SAFE_CLOCK" in out.reasons
    b.run_until("2026-10-13 23:30", dt=10)
    first = next(o for o in b.outputs if o.phase == Phase.CURFEW)
    landed = to_local(reboot_utc + timedelta(seconds=first.mono))
    assert abs(hm(landed) - 23 * 60) <= 10, landed
    assert b.node.output.level == 40


# ========================================================= 6.2: ADAPTIVE
def test_R_ADP_1_presence_boost_under_2s_then_hold_and_fade():
    b = Bench(RoadClass.LOCAL)
    assert b.run_until("2026-10-14 01:30", dt=5).level == 30
    b.node.radar_detect(b.mono)
    assert b.advance(2).level >= 69                      # 25 %/s: 40 points in 1.6 s
    assert b.advance(1).level == 70
    assert b.advance(85).level == 70                     # inside the 90 s hold
    assert 30 < b.advance(10).level < 70                 # fading at 1 %/s
    assert b.advance(45).level == 30


def test_R_ADP_2_loop_volume_arterial_75():
    """Arterial at 50 % + 50 % x (150/300) in the deep phase."""
    b = Bench(RoadClass.ARTERIAL)
    assert b.run_until("2026-10-14 02:00", dt=5).level == 50
    b.loop_volume(150)
    out = b.advance(5)
    assert out.activity == 0.5 and out.level == 75
    b.loop_volume(300)
    assert b.advance(5).level == 100
    b.loop_volume(0)
    assert b.advance(60).level == 50


def test_R_ADP_3_loop_volume_cache_one_slot_after_backhaul_loss():
    """Backhaul lost, mesh still up: the last volume holds for one 15-min
    slot, then the loop term drops (Section 5.3 step 1)."""
    b = Bench(RoadClass.ARTERIAL)
    b.run_until("2026-10-14 02:00", dt=5)
    b.node.backhaul_hello(b.mono, b.utc)
    b.loop_volume(300)
    b.go_offline()
    b.mesh_gateway = True
    assert b.advance(5).level == 100
    out = b.advance(14 * 60, dt=5)
    assert out.level == 100 and "LOOP" in out.reasons
    out = b.advance(2 * 60, dt=5)
    assert out.mode == Mode.MESH and "LOOP" not in out.reasons
    assert b.advance(60, dt=5).level == 50


# =========================================================== 6.2: SAFETY
def test_R_SAF_1_hin_floor_wins_over_rain_boost():
    b = Bench(RoadClass.PARK, hin=True)
    out = b.run_until("2026-10-14 02:00", dt=5)
    assert out.level == 60 and "FLOOR_HIN" in out.reasons
    b.send(EventKind.RAIN, ttl_s=1800)
    out = b.advance(5)
    assert out.level == 60 and "RAIN" in out.reasons and "FLOOR_HIN" in out.reasons
    plain = Bench(RoadClass.PARK)
    plain.run_until("2026-10-14 02:00", dt=5)
    plain.send(EventKind.RAIN, ttl_s=1800)
    assert plain.advance(5).level == 25                  # 10 + 15, no HIN floor


def test_R_SAF_2_fog_and_snow_no_boost():
    b = Bench(RoadClass.LOCAL)
    assert b.run_until("2026-10-14 02:00", dt=5).level == 30
    b.send(EventKind.FOG, ttl_s=1800)
    b.send(EventKind.SNOW, ttl_s=1800)
    out = b.advance(5)
    assert out.level == 30 and "FOG_NO_BOOST" in out.reasons and "SNOW_NO_BOOST" in out.reasons


def test_R_SAF_3_blocked_photocell_cannot_keep_lights_off_at_night():
    b = Bench(RoadClass.LOCAL)
    b.run_until("2026-10-13 23:30", dt=5)
    b.lx_override = 500.0
    out = b.advance(180, dt=5)
    assert not b.node.photocell.dark
    assert out.lit and out.level == 40 and "PHOTOCELL_VETOED" in out.reasons


def test_R_SAF_4_storm_darkness_lights_at_evening_level():
    b = Bench(RoadClass.LOCAL, start="2026-10-13 13:00")
    out = b.run_until("2026-10-13 14:00", dt=5)
    assert not out.lit and out.level == 0
    b.lx_override = 3.0
    out = b.advance(90, dt=5)                            # 60 s debounce + ramp
    assert out.lit and out.level == 80 and out.phase == Phase.EVENING and "PHOTOCELL_EARLY" in out.reasons
    b.lx_override = None
    assert not b.advance(600, dt=5).lit


# ======================================================== 6.2: EMERGENCY
def test_R_EM_1_emergency_in_safe_expires_on_monotonic_ttl():
    """Never synced, photocell dark. The event still lands at 100 and
    expires on monotonic seconds."""
    b = Bench(RoadClass.LOCAL, online=False, start="2026-10-13 22:00")
    out = b.advance(120, dt=5)
    assert out.mode == Mode.SAFE and out.lit
    b.send(EventKind.EMERGENCY, ttl_s=600, via="mesh")
    assert b.advance(10).level == 100
    assert b.advance(580).level == 100
    out = b.advance(20 + 60, dt=5)
    assert out.level < 100 and "EMERGENCY" not in " ".join(out.reasons)


def test_R_EM_2_override_vs_emergency_priority():
    b = Bench(RoadClass.LOCAL)
    b.run_until("2026-10-14 02:00", dt=5)
    b.send(EventKind.EMERGENCY, ttl_s=3600, event_id="cad-1")
    assert b.advance(10).level == 100
    b.send(EventKind.OVERRIDE, ttl_s=3600, payload={"level": 50}, priority=Priority.PLANNED, event_id="plan-1")
    out = b.advance(10)
    assert out.level == 100 and any(r.startswith("OVERRIDE_BLOCKED") for r in out.reasons)
    b.send(EventKind.OVERRIDE, ttl_s=3600, payload={"level": 50}, priority=Priority.INCIDENT_COMMAND, event_id="ic-1")
    assert b.advance(60, dt=5).level == 50
    assert b.deliver(b.cms.cancel("ic-1", segments=[b.cfg.segment_id], issued=b.utc))
    assert b.advance(5).level == 100


# ============================================================== 6.2: CLO
def test_R_CLO_1_constant_light_output():
    assert clo_factor(0) == pytest.approx(0.86)
    assert clo_factor(50_000) == pytest.approx(0.93)
    assert clo_factor(100_000) == pytest.approx(1.0)
    assert clo_factor(150_000) == pytest.approx(1.0)
    new = Bench(RoadClass.ARTERIAL, burn_hours=0).run_until("2026-10-13 21:00", dt=5)
    old = Bench(RoadClass.ARTERIAL, burn_hours=100_000).run_until("2026-10-13 21:00", dt=5)
    assert new.level == old.level == 100
    assert new.drive == pytest.approx(86.0, abs=0.01) and old.drive == pytest.approx(100.0, abs=0.01)


# ============================================================= 6.2: MESH
def test_R_MESH_1_twelve_hop_budget():
    m = MeshNetwork(hop_budget=12)
    m.chain([f"p{i}" for i in range(15)])
    gw = lambda n: n == "p0"
    assert m.hops_to_gateway("p12", gw) == 12
    assert m.gateway_reachable("p12", gw) and not m.gateway_reachable("p13", gw)
    assert m.reachable_from(["p0"]) == {f"p{i}" for i in range(13)}


def test_R_MESH_2_broken_path_isolation_and_3_hop_carpet():
    m = MeshNetwork()
    ids = [f"p{i}" for i in range(20)]
    m.chain(ids)
    gw = lambda n: n == "p0"
    m.remove_link("p7", "p8")
    assert m.gateway_reachable("p7", gw) and not m.gateway_reachable("p8", gw)
    targets = dict(m.carpet_targets("p12"))
    assert set(targets) == {"p9", "p10", "p11", "p13", "p14", "p15"}
    assert targets["p9"] == 3 and targets["p13"] == 1
    seen = []
    m.flood("p3", SignedMessage(b"x", b"y"), lambda n, msg, h: seen.append(n))
    assert "p7" in seen and "p8" not in seen


# ===================================================== EXT: DIMMING
def test_EXT_DIM_0_phase_table_boundaries():
    for h, ph in [(21.99, Phase.EVENING), (22.0, Phase.STEP), (23.0, Phase.CURFEW), (0.5, Phase.CURFEW),
                  (1.0, Phase.DEEP), (4.99, Phase.DEEP), (5.0, Phase.DAWN), (14.0, Phase.EVENING)]:
        assert phase_for_hour(h) == ph


@pytest.mark.parametrize("road", list(RoadClass))
def test_EXT_DIM_2_every_class_follows_its_table(road):
    """Section 2.2 table, phase by phase, no activity."""
    b, prof = Bench(road), DEFAULT_PROFILES[road]
    for local_t, phase in [("2026-10-13 21:00", Phase.EVENING), ("2026-10-13 22:30", Phase.STEP),
                           ("2026-10-13 23:30", Phase.CURFEW), ("2026-10-14 03:00", Phase.DEEP),
                           ("2026-10-14 06:00", Phase.DAWN)]:
        out = b.run_until(local_t, dt=5)
        assert out.phase == phase and out.level == prof.base(phase), (road, phase, out)
    out = b.run_until("2026-10-14 07:30", dt=5)
    assert not out.lit and out.level == 0


def test_EXT_DIM_3_curfew_follows_dst():
    for start, before, after in [("2026-01-10 18:00", "2026-01-10 22:59", "2026-01-10 23:01"),
                                 ("2026-07-10 21:30", "2026-07-10 22:59", "2026-07-10 23:01")]:
        b = Bench(RoadClass.COLLECTOR, start=start)
        assert b.run_until(before, dt=5).phase == Phase.STEP
        assert b.run_until(after, dt=5).phase == Phase.CURFEW
    assert local_to_utc(datetime(2026, 1, 10, 23)).hour == 4
    assert local_to_utc(datetime(2026, 7, 10, 23)).hour == 3


def test_EXT_DIM_4_activity_and_rain_never_dim_a_street():
    """Spec erratum: the 2.4 formula lowers classes whose evening level is
    above the boost cap. A pedestrian on a local street at 21:00 must not
    take it from 80 to 70; rain must not take a park edge from 60 to 50."""
    local = Bench(RoadClass.LOCAL)
    assert local.run_until("2026-10-13 21:00", dt=5).level == 80
    local.node.radar_detect(local.mono)
    out = local.advance(5)
    assert out.level == 80 and out.activity == 1.0
    coll = Bench(RoadClass.COLLECTOR)
    coll.run_until("2026-10-13 21:00", dt=5)
    coll.loop_volume(120)
    assert coll.advance(30).level == 100
    park = Bench(RoadClass.PARK)
    park.run_until("2026-10-13 21:00", dt=5)
    park.send(EventKind.RAIN, ttl_s=1800)
    assert park.advance(30).level == 60


# =================================================== EXT: FAIL-SAFE
def test_EXT_FS_4_cold_clockless_boot_anchors_on_photocell_dusk():
    """No clock, no backhaul, boots in daylight: waits for the photocell
    dusk, counts from the dark midpoint learned from the photocell on the
    previous clocked night, and lands the curfew within 10 min."""
    learner = Bench(RoadClass.LOCAL, start="2026-10-12 17:00")
    learner.run_until("2026-10-13 08:00", dt=10)
    cp = learner.flash.checkpoint
    assert cp.learned and 0.5 < cp.learned_midpoint_h < 1.5 and 11 < cp.prev_night_len_h < 13
    rtc = learner.rtc
    rtc.reset()
    b = Bench(RoadClass.LOCAL, start="2026-10-13 15:00", flash=learner.flash, rtc=rtc, online=False,
              cms=learner.cms)
    out = b.run_until("2026-10-13 18:00", dt=10)
    assert out.mode == Mode.SAFE and not out.lit
    start_utc = b.utc - timedelta(seconds=b.mono)
    b.keep_history = True
    assert b.run_until("2026-10-13 19:30", dt=10).level == 80
    b.run_until("2026-10-13 23:30", dt=10)
    first = next(o for o in b.outputs if o.phase == Phase.CURFEW)
    assert abs(hm(to_local(start_utc + timedelta(seconds=first.mono))) - 23 * 60) <= 10
    assert b.node.output.level == 40


def test_EXT_FS_5_rtc_reset_holds_2200_level_until_next_dusk():
    """After a cut longer than the supercap, the checkpoint cannot be dated,
    so the node holds the 22:00 level rather than guess, and re-anchors on
    the next photocell dusk."""
    b = Bench(RoadClass.LOCAL)
    b.run_until("2026-10-13 21:00", dt=5)
    b.go_offline()
    b.power_cut(outage_s=10 * 86400)                     # 10 days: RTC reset
    out = b.advance(300, dt=5)
    assert out.mode == Mode.SAFE and out.level == 60 and "SAFE_NO_ANCHOR" in out.reasons
    assert b.run_until("2026-10-24 02:00", dt=10).level == 60    # no guessed curfew
    assert not b.run_until("2026-10-24 12:00", dt=10).lit
    out = b.run_until("2026-10-24 23:45", dt=10)
    assert out.phase == Phase.CURFEW and out.level == 40 and "SAFE_CLOCK" in out.reasons


@pytest.mark.parametrize("road", list(RoadClass))
def test_EXT_FS_6_dead_controller_falls_to_failure_level(road):
    """Section 5.2: the driver falls to the class's 22:00 level (60 % on the
    High-Injury Network if higher) when the controller stops writing."""
    for hin in (False, True):
        b = Bench(road, hin=hin)
        b.run_until("2026-10-14 02:00", dt=5)
        drv = b.driver
        assert not drv.watchdog(drv.last_write_mono + 3)  # one slow pass is fine
        assert drv.watchdog(drv.last_write_mono + 10)     # node hung: bus silent
        expected = max(DEFAULT_PROFILES[road].base(Phase.STEP), 60 if hin else 0)
        assert drv.relay_closed and drv.output_pct == expected
    d = LuminaireDriver.commissioned_for(DEFAULT_PROFILES[RoadClass.LOCAL])
    d.set(0.0, 0.0, relay_on=False)
    d.control_power_lost()
    assert d.relay_closed and d.output_pct == 60


def test_EXT_FS_7_one_hello_leaves_safe():
    b = Bench(RoadClass.LOCAL, online=False, start="2026-10-13 23:30")
    assert b.advance(60, dt=5).mode == Mode.SAFE
    b.go_online()
    out = b.advance(1)
    assert out.mode == Mode.ONLINE and out.phase == Phase.CURFEW


def test_EXT_FS_8_no_loop_boost_in_autonomous_only_relayed_in_mesh():
    b = Bench(RoadClass.ARTERIAL)
    b.run_until("2026-10-14 02:00", dt=5)
    b.go_offline()
    assert b.run_until("2026-10-14 02:20", dt=5).mode == Mode.AUTONOMOUS
    assert b.deliver(b.cms.loop_volume(b.cfg.segment_id, 300, issued=b.utc), via="mesh")
    out = b.advance(5)
    assert out.mode == Mode.AUTONOMOUS and "LOOP" not in out.reasons and out.level == 50
    b.mesh_gateway = True
    out = b.advance(5)
    assert out.mode == Mode.MESH and "LOOP" in out.reasons and out.level == 100


# ================================================== EXT: ADAPTIVE
def test_EXT_ADP_4_presence_on_arterial_is_half_activity():
    b = Bench(RoadClass.ARTERIAL)
    assert b.run_until("2026-10-14 02:00", dt=5).level == 50
    b.node.radar_detect(b.mono)
    out = b.advance(3)
    assert out.activity == 0.5 and out.level == 75


def test_EXT_MESH_3_carpet_lights_neighbours_without_their_own_detection():
    b = Bench(RoadClass.ALLEY)
    assert b.run_until("2026-10-14 02:00", dt=5).level == 20
    b.node.carpet_event(b.mono)
    out = b.advance(3)
    assert out.level == 70 and "CARPET" in out.reasons
    assert b.advance(60 + 60).level == 20


# ================================================== EXT: SECURITY
def test_EXT_SEC_1_forged_or_tampered_messages_rejected():
    b = Bench(RoadClass.LOCAL)
    b.run_until("2026-10-14 02:00", dt=5)
    stranger = Cms()
    seg = make_targets(segments=[b.cfg.segment_id])
    assert not b.deliver(stranger.event(EventKind.EMERGENCY, 3600, seg, issued=b.utc))
    good = b.cms.event(EventKind.EMERGENCY, 3600, seg, issued=b.utc)
    assert not b.deliver(SignedMessage(good.payload.replace(b"3600", b"9999"), good.signature))
    assert b.advance(5).level == 30
    assert any("REJECT unsigned" in line for line in b.node.log)


def test_EXT_SEC_2_bundle_version_monotonic_and_reverified_at_boot():
    b = Bench(RoadClass.LOCAL, bundle_version=5)
    assert not b.deliver(b.cms.bundle(default_bundle(version=4)))
    newer = default_bundle(version=6)
    newer.hin_floor = 70
    assert b.deliver(b.cms.bundle(newer))
    b.power_cut(outage_s=30)                             # boot re-reads and re-verifies the bank
    assert b.flash.version == 6 and b.flash.bundle.hin_floor == 70
    assert "BOOT v6 from bank" in " ".join(b.flash.install_log)
    payload, sig = b.flash.banks[b.flash.active]         # bit-rot in the active bank
    b.flash.banks[b.flash.active] = (payload.replace(b'"hin_floor":70', b'"hin_floor":99'), sig)
    b.power_cut(outage_s=30)
    assert b.flash.version == 5                          # fell back to the other bank
    assert any("signature bad" in s for s in b.flash.install_log)


@pytest.mark.parametrize("mutate, why", [
    (lambda bd: bd.profiles.__setitem__(RoadClass.LOCAL, replace(bd.profiles[RoadClass.LOCAL], levels=(0, 0, 0, 0, 0), floor=0)), "floor"),
    (lambda bd: bd.profiles.pop(RoadClass.ALLEY), "missing"),
    (lambda bd: setattr(bd, "hin_floor", 40), "hin_floor"),
    (lambda bd: bd.mix.__setitem__(Phase.CURFEW, (50, 40)), "mix"),
    (lambda bd: bd.profiles.__setitem__(RoadClass.ARTERIAL, replace(bd.profiles[RoadClass.ARTERIAL], boost_cap=120)), "boost cap"),
    (lambda bd: setattr(bd, "rain_boost", 80), "rain_boost"),
])
def test_EXT_SEC_3_signed_but_unsafe_bundles_are_refused(mutate, why):
    """A valid signature is not enough: a bundle that would put a street
    below its firmware-minimum floor, or is incomplete, is refused and the
    active bank keeps running."""
    b = Bench(RoadClass.LOCAL)
    bad = default_bundle(version=2)
    mutate(bad)
    assert not b.deliver(b.cms.bundle(bad))
    assert b.flash.version == 1 and why in b.flash.install_log[-1]
    assert b.run_until("2026-10-14 02:00", dt=10).level == 30


def test_EXT_SEC_4_bundle_validity_400_days():
    cms = Cms()
    b = Bench(RoadClass.LOCAL, cms=cms)
    b.advance(5)                                         # clock synced
    stale = default_bundle(version=2, issued="2025-01-01")
    assert not b.deliver(cms.bundle(stale))
    assert "expired" in b.flash.install_log[-1]
    f = Flash()                                          # installed at the factory, no clock
    assert f.install(cms.bundle(default_bundle(version=3, issued="2025-01-01")), cms.verifier)
    old = Bench(RoadClass.LOCAL, cms=cms, flash=f)
    out = old.run_until("2026-10-14 02:00", dt=10)
    assert "BUNDLE_EXPIRED" in out.reasons and "BUNDLE_EXPIRED" in out.alarms
    assert out.level == 30                               # keeps running its last good profile


def test_EXT_SEC_5_events_apply_only_inside_their_geofence():
    cms = Cms()
    positions = {f"local-{i:02d}": (30.0 * i, 0.0) for i in range(30)}
    fence = geofence(positions, center=(300.0, 0.0), radius_m=400.0)
    assert fence == [f"local-{i:02d}" for i in range(0, 24)]
    inside = Bench(RoadClass.LOCAL, cms=cms, node_id="local-05", segment_id="seg-k")
    outside = Bench(RoadClass.LOCAL, cms=cms, node_id="local-27", segment_id="seg-k")
    for b in (inside, outside):
        b.run_until("2026-10-14 02:00", dt=10)
    msg = cms.emergency(fence, ttl_s=3600, incident="F26-1183", issued=inside.utc)
    assert inside.deliver(msg) and not outside.deliver(msg)
    assert inside.advance(5).level == 100 and outside.advance(5).level == 30
    other = cms.event(EventKind.EMERGENCY, 3600, make_targets(segments=["seg-elsewhere"]), issued=inside.utc)
    assert not outside.deliver(other) and outside.advance(5).level == 30


def test_EXT_SEC_6_replay_window():
    b = Bench(RoadClass.LOCAL)
    b.run_until("2026-10-14 02:00", dt=5)
    captured = b.send(EventKind.EMERGENCY, ttl_s=600, event_id="cad-9")
    assert b.advance(600 + 120, dt=5).level == 30
    assert not b.deliver(captured)                       # played back after expiry
    assert b.advance(5).level == 30
    rain = b.send(EventKind.RAIN, ttl_s=1800)
    assert not b.deliver(rain, via="mesh")               # same message by mesh: applied once
    seg = make_targets(segments=[b.cfg.segment_id])
    fog = b.cms.event(EventKind.FOG, 600, seg, issued=b.utc)
    snow = b.cms.event(EventKind.SNOW, 600, seg, issued=b.utc)
    assert b.deliver(snow) and b.deliver(fog)            # out of order inside the window
    for i in range(70):
        b.send(EventKind.FOG, ttl_s=600, event_id=f"fog-{i}")
    assert not b.deliver(captured)
    assert any("REJECT replayed" in line for line in b.node.log)
    b.power_cut(outage_s=30)                             # window top survives the reboot
    b.advance(5)
    assert not b.deliver(fog)
    assert b.deliver(b.cms.event(EventKind.FOG, 600, seg, issued=b.utc))


def test_EXT_SEC_7_expired_on_arrival_or_from_the_future():
    b = Bench(RoadClass.LOCAL)
    b.run_until("2026-10-14 02:00", dt=5)
    seg = make_targets(segments=[b.cfg.segment_id])
    assert not b.deliver(b.cms.event(EventKind.RAIN, 1800, seg, issued=b.utc - timedelta(hours=2)))
    assert "expired" in b.node.log[-1]
    assert not b.deliver(b.cms.event(EventKind.RAIN, 1800, seg, issued=b.utc + timedelta(hours=1)))
    assert "future" in b.node.log[-1]


def test_EXT_SEC_8_event_store_keeps_emergencies_and_ignores_unknown_kinds():
    b = Bench(RoadClass.LOCAL)
    b.run_until("2026-10-14 02:00", dt=5)
    b.send(EventKind.EMERGENCY, ttl_s=3600, event_id="cad-1")
    for i in range(80):
        b.send(EventKind.FOG, ttl_s=3600, event_id=f"fog-{i}")
    assert len(b.node.events) == 64
    assert b.node.events.latest(EventKind.EMERGENCY, b.mono) is not None
    assert b.advance(5).level == 100
    b.cms.seq += 1
    odd = b.cms.signer.sign_obj({"kind": "teleport", "id": "x", "ttl_s": 10, "seq": b.cms.seq,
                                 "targets": make_targets(everyone=True), "issued": b.utc.isoformat()})
    assert not b.deliver(odd)
    assert "REJECT unknown or malformed" in b.node.log[-1]


def test_EXT_SEC_9_override_audit_who_when_why():
    b = Bench(RoadClass.LOCAL)
    b.run_until("2026-10-14 02:00", dt=5)
    seg = [b.cfg.segment_id]
    assert not b.deliver(b.cms.override(55, 3600, Priority.OPERATOR, by="", reason="x", segments=seg, issued=b.utc))
    assert b.deliver(b.cms.override(55, 3600, Priority.OPERATOR, by="J. Rivera, DDOT", reason="water main break",
                                    segments=seg, event_id="ov-1", issued=b.utc))
    assert b.advance(30).level == 55
    rec = b.node.audit[-1]
    assert (rec.by, rec.reason, rec.priority, rec.action) == ("J. Rivera, DDOT", "water main break", 2, "applied")
    assert rec.utc is not None
    assert b.deliver(b.cms.cancel("ov-1", segments=seg, issued=b.utc))
    assert b.node.audit[-1].action == "cancelled"
    assert b.advance(60, dt=5).level == 30


# ============================================= EXT: TUNABLE WHITE
def test_EXT_TW_1_channel_mix_follows_phase_presence_and_emergency():
    b = Bench(RoadClass.LOCAL, tunable=True)
    for t, mix in [("2026-10-13 21:00", (1.0, 0.0)), ("2026-10-13 22:30", (0.6, 0.4)),
                   ("2026-10-13 23:30", (0.0, 1.0)), ("2026-10-14 02:00", (0.0, 1.0))]:
        out = b.run_until(t, dt=5)
        assert out.white == pytest.approx(out.drive * mix[0]) and out.amber == pytest.approx(out.drive * mix[1]), t
    b.node.radar_detect(b.mono)
    out = b.advance(3)
    assert out.level == 70 and out.amber == 0.0 and out.white == pytest.approx(out.drive)
    out = b.run_until("2026-10-14 06:00", dt=5)
    assert out.white == pytest.approx(out.drive * 0.6) and out.amber == pytest.approx(out.drive * 0.4)
    b.send(EventKind.EMERGENCY, ttl_s=600)
    out = b.advance(3)
    assert out.level == 100 and out.amber == 0.0


# ================================================== EXT: HARDWARE
def test_EXT_HW_1_photocell_15_on_40_off_60s_debounce():
    pc = Photocell()
    assert pc.sample(100, 0) is None and pc.dark is False   # power-on read, no debounce
    assert pc.sample(20, 1) is None and not pc.dark          # above 15 lx: stays light
    for t in range(2, 62):
        assert pc.sample(10, t) is None
    assert pc.sample(10, 62) is True                          # 60 s after the first dark read
    assert pc.sample(30, 100) is None and pc.dark             # 30 lx < 40: hysteresis holds
    assert pc.sample(45, 101) is None
    assert pc.sample(45, 160) is None and pc.sample(45, 161) is False
    pc2 = Photocell()
    pc2.sample(100, 0)
    pc2.sample(10, 10)
    pc2.sample(50, 40)                                        # bounce resets the debounce
    assert pc2.sample(10, 69) is None and pc2.sample(10, 75) is None and not pc2.dark


def test_EXT_HW_2_legacy_0_10v_single_channel():
    b = Bench(RoadClass.LOCAL, tunable=True, interface="0-10v")
    out = b.run_until("2026-10-13 22:30", dt=5)
    assert b.driver.white == pytest.approx(out.white + out.amber) and b.driver.amber == 0.0


def test_EXT_HW_3_tilt_alarm_above_2_degrees():
    b = Bench(RoadClass.LOCAL)
    b.node.commission_tilt(0.4)
    b.run_until("2026-10-13 20:00", dt=10)
    b.node.tilt_sample(1.9, b.mono)
    assert "TILT" not in b.advance(2).alarms
    b.node.tilt_sample(2.6, b.mono)
    assert "TILT" in b.advance(2).alarms
    assert any("TILT" in u["alarms"] for u in b.uplinks)      # sent immediately while ONLINE


def test_EXT_HW_4_driver_fault_and_day_burner_alarms():
    b = Bench(RoadClass.LOCAL)
    b.run_until("2026-10-13 21:00", dt=5)
    b.driver.fault = "open_circuit"
    assert "DRIVER_FAULT" not in b.advance(30).alarms
    assert "DRIVER_FAULT" in b.advance(40).alarms
    day = Bench(RoadClass.LOCAL, start="2026-10-14 09:00")
    assert not day.run_until("2026-10-14 09:10", dt=5).lit
    day.driver.fault = "stuck_on"
    assert "DAY_BURNER" not in day.advance(200, dt=5).alarms
    assert "DAY_BURNER" in day.advance(120, dt=5).alarms


def test_EXT_HW_5_metering_buffers_offline_and_replays_on_recovery():
    b = Bench(RoadClass.LOCAL)
    b.run_until("2026-10-13 21:00", dt=5)
    evening = [r for u in b.uplinks for r in u["metering"]]
    # an evening slot: 15 min x (0.5 W standby + 40 W x 80 % x 0.86 CLO)
    assert evening[-1]["wh"] == pytest.approx(0.25 * (0.5 + 40 * 0.80 * 0.86), rel=0.01)
    b.go_offline()
    b.run_until("2026-10-13 23:00", dt=5)
    buffered = list(b.node.outbox)
    assert len(buffered) >= 7 and any(r["mode"] == "AUTONOMOUS" for r in buffered)
    sent_before = len(b.uplinks)
    b.go_online()
    b.advance(2)
    up = b.uplinks[sent_before]
    assert up["metering"][:len(buffered)] == buffered and up["bundle_version"] == 1
    assert len(b.node.outbox) == 0


def test_EXT_HW_6_cycling_alarm():
    b = Bench(RoadClass.LOCAL, start="2026-10-14 12:00")
    for i in range(8):
        b.lx_override = 3.0 if i % 2 == 0 else 500.0
        b.advance(75, dt=5)
    assert "CYCLING" in b.node.output.alarms


# ================================================== EXT: SPECTRAL
def test_EXT_SPEC_1_spectral_metrics_order_and_limits():
    by = {r["spectrum"]: r for r in spectral.relative_table()}
    for name, target in [("4000K", 4000), ("3000K", 3000), ("2700K", 2700), ("2200K", 2200)]:
        assert abs(by[name]["cct_K"] - target) / target < 0.02
        assert abs(by[name]["duv"]) < 0.003                         # Section 4.2 limit
    order = ["4000K", "3000K", "2700K", "2200K", "PC-Amber", "Narrow-band amber"]
    for key in ("skyglow_scotopic_rel", "mel_der"):
        vals = [by[n][key] for n in order]
        assert vals == sorted(vals, reverse=True)
    assert by["2200K"]["blue_fraction"] <= 0.07                     # <= 7 % below 500 nm
    assert by["PC-Amber"]["blue_fraction"] < 0.01                   # < 1 % below 500 nm
    assert spectral.window_melanopic_edi(0.5, "2200K") < 1.0        # Brown et al. 2022 sleep limit


def test_EXT_SPEC_2_measured_spd_round_trip(tmp_path):
    """A measured SPD (LM-79 CSV) can replace the parametric model."""
    spd = spectral.spectrum("2700K")
    p = tmp_path / "engine.csv"
    p.write_text("nm,W\n" + "\n".join(f"{l},{v:.6g}" for l, v in zip(spectral.LAMBDA[::5], spd[::5])))
    m = spectral.metrics("measured", spectral.load_spd_csv(str(p)))
    ref = spectral.table()["2700K"]
    assert m.cct == pytest.approx(ref.cct, rel=0.01)
    assert m.mel_der == pytest.approx(ref.mel_der, rel=0.02)
