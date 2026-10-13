"""VDL-7 acceptance suite. Each test is a requirement from Section 6.2 of
VD-DSL-SPEC-001 RevA; the requirement ID is in the test name."""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from vdl7.bench import Bench
from vdl7.clock import (DC_LAT, DC_LON, UTC, RtcHoldover, is_dst, local_to_utc, night_bounds,
                        sun_times, to_local)
from vdl7.controller import Flash, Mode, NodeConfig, VDL7Controller
from vdl7.driver import LuminaireDriver
from vdl7.events import Event, EventKind, Priority
from vdl7.mesh import MeshNetwork
from vdl7.profiles import (DEFAULT_PROFILES, Phase, RoadClass, clo_factor, default_bundle,
                           phase_for_hour)
from vdl7.security import SignedMessage, make_signer
from vdl7 import spectral


# ===================================================================== CLOCK
def test_R_CLK_1_dst_rule_matches_iana_2024_2030():
    """Firmware POSIX rule matches the IANA database at every 6-hour step."""
    zoneinfo = pytest.importorskip("zoneinfo")
    ny = zoneinfo.ZoneInfo("America/New_York")
    t = datetime(2024, 1, 1, tzinfo=UTC)
    end = datetime(2031, 1, 1, tzinfo=UTC)
    n = 0
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
    """Known sunrise/sunset instants for DC within 3 minutes, and -3 deg
    dusk/dawn fall on the right side of them."""
    r, s = sun_times(DC_LAT, DC_LON, d)
    def mins(hhmm): h, m = hhmm.split(":"); return int(h) * 60 + int(m)
    assert abs(r.hour * 60 + r.minute - mins(rise)) <= 3
    assert abs(s.hour * 60 + s.minute - mins(sset)) <= 3
    dusk, dawn = night_bounds(DC_LAT, DC_LON, d)
    assert to_local(dusk) > s and to_local(dusk) - s < timedelta(minutes=25)
    assert to_local(dawn) < r + timedelta(days=1) and (r + timedelta(days=1)) - to_local(dawn) < timedelta(minutes=25)


def test_R_CLK_3_rtc_holdover_trust():
    """Trusted at 1 year, not at 4; never trusted before the first sync."""
    rtc = RtcHoldover(drift_ppm=3.0, trust_budget_s=300.0)
    assert not rtc.trusted(0.0)
    rtc.sync(0.0, datetime(2026, 10, 13, 22, 0, tzinfo=UTC))
    assert rtc.trusted(365 * 86400.0)
    assert rtc.error_bound_s(365 * 86400.0) < 100
    assert not rtc.trusted(4 * 365 * 86400.0)
    # a 7-day supercap holdover keeps time; a longer cut resets the clock
    rtc.power_cycle(1000.0, 3 * 86400.0)
    assert rtc.trusted(0.0)
    rtc.power_cycle(0.0, 10 * 86400.0)
    assert not rtc.trusted(0.0)


# =================================================================== DIMMING
def test_R_DIM_1_curfew_profile_arterial_60_at_2330():
    b = Bench(RoadClass.ARTERIAL)
    out = b.run_until("2026-10-13 23:30", dt=5)
    assert out.mode == Mode.ONLINE
    assert out.phase == Phase.CURFEW
    assert out.level == 60


@pytest.mark.parametrize("road", list(RoadClass))
def test_R_DIM_2_every_class_follows_its_table(road):
    """Section 2.2 table, phase by phase, no activity."""
    b = Bench(road)
    prof = DEFAULT_PROFILES[road]
    for local_t, phase in [("2026-10-13 21:00", Phase.EVENING), ("2026-10-13 22:30", Phase.STEP),
                           ("2026-10-13 23:30", Phase.CURFEW), ("2026-10-14 03:00", Phase.DEEP),
                           ("2026-10-14 06:00", Phase.DAWN)]:
        out = b.run_until(local_t, dt=5)
        assert out.phase == phase
        assert out.level == prof.base(phase), (road, phase, out)
    out = b.run_until("2026-10-14 07:30", dt=5)
    assert not out.lit and out.level == 0                       # dawn past, off


def test_R_DIM_3_curfew_follows_dst():
    """23:00 local is the boundary in January (EST) and July (EDT)."""
    for start, before, after in [("2026-01-10 18:00", "2026-01-10 22:59", "2026-01-10 23:01"),
                                 ("2026-07-10 21:30", "2026-07-10 22:59", "2026-07-10 23:01")]:
        b = Bench(RoadClass.COLLECTOR, start=start)
        assert b.run_until(before, dt=5).phase == Phase.STEP
        assert b.run_until(after, dt=5).phase == Phase.CURFEW
    assert local_to_utc(datetime(2026, 1, 10, 23)).hour == 4    # EST: 23:00 -> 04:00Z
    assert local_to_utc(datetime(2026, 7, 10, 23)).hour == 3    # EDT: 23:00 -> 03:00Z


# ================================================================= FAIL-SAFE
def test_R_FS_1_total_outage_autonomous_local_30_at_0100():
    """5 h with no backhaul or mesh: AUTONOMOUS, local street at 30 % at 01:00."""
    b = Bench(RoadClass.LOCAL)
    b.run_until("2026-10-13 20:00", dt=5)
    b.go_offline()
    out = b.run_until("2026-10-13 20:20", dt=5)
    assert out.mode == Mode.AUTONOMOUS
    out = b.run_until("2026-10-14 01:01", dt=5)          # 10 s fade past the 01:00 step
    assert out.mode == Mode.AUTONOMOUS
    assert out.level == 30
    assert out.phase == Phase.DEEP


def test_R_FS_2_backhaul_only_loss_mesh_applies_emergency():
    """MESH mode still applies an emergency event at 100 %."""
    b = Bench(RoadClass.ALLEY)
    b.run_until("2026-10-14 01:00", dt=5)
    b.go_offline()
    b.mesh_gateway = True
    out = b.run_until("2026-10-14 01:20", dt=5)
    assert out.mode == Mode.MESH
    assert out.level == 20
    b.send(EventKind.EMERGENCY, ttl_s=3600, payload={"incident": "F-2201"}, via="mesh")
    out = b.advance(10)
    assert out.mode == Mode.MESH
    assert out.level == 100
    out = b.advance(3600 + 120, dt=5)                 # TTL elapsed, 80 pt fade at 1 %/s
    assert out.level == 20


def test_R_FS_3_clock_lost_reboot_safe_lands_curfew():
    """Power cut at 21:00 zeroes the monotonic clock and loses the RTC; SAFE
    mode lands the 23:00 curfew within 10 min from the photocell and the
    flash checkpoint alone."""
    b = Bench(RoadClass.LOCAL)
    b.run_until("2026-10-13 21:00", dt=5)
    assert b.node.flash.checkpoint.night_hour is not None
    b.power_cut(outage_s=120, supercap_ok=False)      # supercap failed: RTC reset
    b.go_offline()
    assert b.mono == 0.0
    out = b.run_until("2026-10-13 21:05", dt=5)
    assert out.mode == Mode.SAFE and out.lit
    assert out.level == 80                              # evening level resumed
    assert b.run_until("2026-10-13 22:50", dt=5).level == 60
    out = b.run_until("2026-10-13 23:10", dt=5)
    assert out.phase == Phase.CURFEW
    assert out.level == 40


def test_R_FS_4_safe_mode_reanchors_on_observed_dusk():
    """A node that boots clockless in daylight waits for the photocell dusk,
    then counts from the learned dark midpoint; the curfew lands within 15 min."""
    learner = Bench(RoadClass.LOCAL, start="2026-10-12 17:00")
    learner.run_until("2026-10-13 08:00", dt=10)       # one clocked night in flash
    cp = learner.flash.checkpoint
    assert cp.learned and 0.5 < cp.learned_midpoint_h < 1.5 and 12 < cp.prev_night_len_h < 13
    # same flash, fresh node, no clock, no backhaul, booting at 15:00
    b = Bench(RoadClass.LOCAL, start="2026-10-13 15:00", flash=learner.flash, rtc=RtcHoldover(),
              online=False)
    out = b.run_until("2026-10-13 18:00", dt=10)
    assert out.mode == Mode.SAFE and not out.lit and out.level == 0
    out = b.run_until("2026-10-13 19:30", dt=10)
    assert out.lit and out.level == 80
    assert b.run_until("2026-10-13 22:45", dt=10).level == 60
    out = b.run_until("2026-10-13 23:15", dt=10)
    assert out.level == 40 and out.phase == Phase.CURFEW


def test_R_FS_5_driver_fails_to_class_2200_level_never_dark():
    """Below the controller: a dead node leaves the relay closed and the
    driver at the class's 22:00 level."""
    for road in RoadClass:
        d = LuminaireDriver.commissioned_for(DEFAULT_PROFILES[road])
        d.set(10.0, 0.0, relay_on=True)
        d.controller_lost()
        assert d.relay_closed
        assert d.output_pct == DEFAULT_PROFILES[road].base(Phase.STEP)
    d = LuminaireDriver.commissioned_for(DEFAULT_PROFILES[RoadClass.LOCAL])
    d.set(0.0, 0.0, relay_on=False)                     # daytime, relay open
    d.control_power_lost()
    assert d.relay_closed and d.output_pct == 60


# ================================================================== ADAPTIVE
def test_R_ADP_1_presence_boost_under_2s_then_hold_and_fade():
    b = Bench(RoadClass.LOCAL)
    out = b.run_until("2026-10-14 01:30", dt=5)
    assert out.level == 30
    b.node.radar_detect(b.mono)
    out = b.advance(2)
    assert out.level >= 69                              # 25 %/s: 40 points in 1.6 s
    out = b.advance(1)
    assert out.level == 70
    assert b.advance(85).level == 70                    # inside the 90 s hold
    out = b.advance(10)
    assert 30 < out.level < 70                          # fading at 1 %/s
    assert b.advance(45).level == 30                    # hold + 40 s fade done


def test_R_ADP_2_loop_volume_arterial_75():
    """Arterial at 50 % + 50 % x (150/300) in the deep phase."""
    b = Bench(RoadClass.ARTERIAL)
    assert b.run_until("2026-10-14 02:00", dt=5).level == 50
    b.loop_volume(150)
    out = b.advance(5)
    assert out.activity == 0.5
    assert out.level == 75
    b.loop_volume(300)
    assert b.advance(5).level == 100
    b.loop_volume(0)
    assert b.advance(60).level == 50


def test_R_ADP_3_loop_volume_cache_one_slot_after_backhaul_loss():
    b = Bench(RoadClass.ARTERIAL)
    b.run_until("2026-10-14 02:00", dt=5)
    b.loop_volume(300)
    assert b.advance(5).level == 100
    b.go_offline()                                      # loop value age 0 at loss
    out = b.advance(14 * 60, dt=5)
    assert out.level == 100 and "LOOP" in out.reasons   # kept for one 15-min slot
    out = b.advance(2 * 60, dt=5)
    assert "LOOP" not in out.reasons                    # dropped after 15 min
    assert out.mode == Mode.AUTONOMOUS
    assert b.advance(60, dt=5).level == 50


def test_R_ADP_4_presence_on_arterial_is_half_activity():
    b = Bench(RoadClass.ARTERIAL)
    assert b.run_until("2026-10-14 02:00", dt=5).level == 50
    b.node.radar_detect(b.mono)
    out = b.advance(3)
    assert out.activity == 0.5 and out.level == 75


# ==================================================================== SAFETY
def test_R_SAF_1_hin_floor_wins_over_rain_boost():
    b = Bench(RoadClass.PARK, hin=True)
    out = b.run_until("2026-10-14 02:00", dt=5)
    assert out.level == 60 and "FLOOR_HIN" in out.reasons
    b.send(EventKind.RAIN, ttl_s=1800)
    out = b.advance(5)
    assert out.level == 60                              # 10 + 15 = 25 < floor 60
    assert "RAIN" in out.reasons and "FLOOR_HIN" in out.reasons
    plain = Bench(RoadClass.PARK)
    plain.run_until("2026-10-14 02:00", dt=5)
    plain.send(EventKind.RAIN, ttl_s=1800)
    assert plain.advance(5).level == 25                 # same rain, no HIN floor


def test_R_SAF_2_fog_and_snow_no_boost():
    b = Bench(RoadClass.LOCAL)
    assert b.run_until("2026-10-14 02:00", dt=5).level == 30
    b.send(EventKind.FOG, ttl_s=1800)
    b.send(EventKind.SNOW, ttl_s=1800)
    out = b.advance(5)
    assert out.level == 30
    assert "FOG_NO_BOOST" in out.reasons and "SNOW_NO_BOOST" in out.reasons


def test_R_SAF_3_blocked_photocell_cannot_keep_lights_off_at_night():
    b = Bench(RoadClass.LOCAL)
    b.run_until("2026-10-13 23:30", dt=5)
    b.lx_override = 500.0                               # photocell reads bright
    out = b.advance(180, dt=5)
    assert not b.node.photocell.dark
    assert out.lit and out.level == 40 and "PHOTOCELL_VETOED" in out.reasons


def test_R_SAF_4_storm_darkness_lights_at_evening_level():
    b = Bench(RoadClass.LOCAL, start="2026-10-13 13:00")
    out = b.run_until("2026-10-13 14:00", dt=5)
    assert not out.lit and out.level == 0
    b.lx_override = 3.0
    out = b.advance(90, dt=5)                           # 60 s debounce + ramp
    assert out.lit and out.level == 80 and out.phase == Phase.EVENING
    assert "PHOTOCELL_EARLY" in out.reasons
    b.lx_override = None
    out = b.advance(600, dt=5)
    assert not out.lit                                  # sky back, lights off


# ================================================================= EMERGENCY
def test_R_EM_1_emergency_in_safe_expires_on_monotonic_ttl():
    """No wall clock at all: never synced, photocell dark. The event still
    lands at 100 and expires on monotonic seconds."""
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
    out = b.advance(60, dt=5)
    assert out.level == 50
    # cancelling the incident-command override puts the emergency back
    cancel = {"kind": "cancel", "target": "ic-1", "id": "c-1"}
    assert b.node.receive(b.signer.sign_obj(cancel), b.mono)
    assert b.advance(5).level == 100


# ======================================================================= CLO
def test_R_CLO_1_constant_light_output():
    assert clo_factor(0) == pytest.approx(0.86)
    assert clo_factor(50_000) == pytest.approx(0.93)
    assert clo_factor(100_000) == pytest.approx(1.0)
    assert clo_factor(150_000) == pytest.approx(1.0)
    new = Bench(RoadClass.ARTERIAL, burn_hours=0).run_until("2026-10-13 21:00", dt=5)
    old = Bench(RoadClass.ARTERIAL, burn_hours=100_000).run_until("2026-10-13 21:00", dt=5)
    assert new.level == old.level == 100
    assert new.drive == pytest.approx(86.0, abs=0.01)    # a few lit hours on the bench
    assert old.drive == pytest.approx(100.0, abs=0.01)


# ====================================================================== MESH
def test_R_MESH_1_twelve_hop_budget():
    m = MeshNetwork(hop_budget=12)
    ids = [f"p{i}" for i in range(15)]
    m.chain(ids)
    gw = lambda n: n == "p0"
    assert m.hops_to_gateway("p12", gw) == 12
    assert m.gateway_reachable("p12", gw)
    assert not m.gateway_reachable("p13", gw)


def test_R_MESH_2_broken_path_isolation_and_3_hop_carpet():
    m = MeshNetwork()
    ids = [f"p{i}" for i in range(20)]
    m.chain(ids)
    gw = lambda n: n == "p0"
    assert m.gateway_reachable("p9", gw)
    m.remove_link("p7", "p8")
    assert m.gateway_reachable("p7", gw)
    assert not m.gateway_reachable("p8", gw)
    targets = dict(m.carpet_targets("p12"))
    assert set(targets) == {"p9", "p10", "p11", "p13", "p14", "p15"}
    assert targets["p9"] == 3 and targets["p13"] == 1
    # a flood reaches every node on the connected side and none beyond the break
    seen = []
    m.flood("p3", SignedMessage(b"x", b"y"), lambda n, msg, h: seen.append(n))
    assert "p7" in seen and "p8" not in seen


def test_R_MESH_3_carpet_lights_neighbours_without_their_own_detection():
    b = Bench(RoadClass.ALLEY)
    assert b.run_until("2026-10-14 02:00", dt=5).level == 20
    b.node.carpet_event(b.mono)
    out = b.advance(3)
    assert out.level == 70 and "CARPET" in out.reasons
    assert b.advance(60 + 60).level == 20                # 60 s hold, 50 s fade


# ================================================================== SECURITY
def test_R_SEC_1_unsigned_or_forged_messages_are_rejected():
    b = Bench(RoadClass.LOCAL)
    b.run_until("2026-10-14 02:00", dt=5)
    stranger = make_signer()
    ev = Event(kind=EventKind.EMERGENCY, ttl_s=3600)
    forged = stranger.sign_obj(ev.to_dict())
    assert not b.node.receive(forged, b.mono)
    tampered = b.signer.sign_obj(ev.to_dict())
    tampered = SignedMessage(tampered.payload.replace(b"3600", b"9999"), tampered.signature)
    assert not b.node.receive(tampered, b.mono)
    assert b.advance(5).level == 30
    assert any("REJECT" in line for line in b.node.log)


def test_R_SEC_2_bundle_version_is_monotonic_and_survives_reboot():
    b = Bench(RoadClass.LOCAL, bundle_version=5)
    assert b.flash.version == 5
    older = default_bundle(version=4)
    assert not b.node.receive(b.signer.sign_obj(older.to_dict()), b.mono)
    newer = default_bundle(version=6)
    newer.hin_floor = 70
    assert b.node.receive(b.signer.sign_obj(newer.to_dict()), b.mono)
    assert b.flash.version == 6 and b.flash.bundle.hin_floor == 70
    assert b.flash.banks[b.flash.active] is not None
    b.power_cut(outage_s=30)
    assert b.node.flash.version == 6
    assert "REJECT version 4 <= 5" in b.flash.install_log


# ============================================================ TUNABLE WHITE
def test_R_TW_1_channel_mix_follows_phase_and_presence():
    b = Bench(RoadClass.LOCAL, tunable=True)
    out = b.run_until("2026-10-13 21:00", dt=5)
    assert (out.white, out.amber) == (pytest.approx(out.drive), 0.0)
    out = b.run_until("2026-10-13 22:30", dt=5)
    assert out.white == pytest.approx(out.drive * 0.6) and out.amber == pytest.approx(out.drive * 0.4)
    out = b.run_until("2026-10-14 02:00", dt=5)
    assert out.white == 0.0 and out.amber == pytest.approx(out.drive)
    b.node.radar_detect(b.mono)
    out = b.advance(3)
    assert out.level == 70 and out.amber == 0.0 and out.white == pytest.approx(out.drive)


# ================================================================== SPECTRAL
def test_R_SPEC_1_spectral_metrics_order_and_limits():
    t = spectral.relative_table()
    by = {r["spectrum"]: r for r in t}
    for name, target in [("4000K", 4000), ("3000K", 3000), ("2700K", 2700), ("2200K", 2200)]:
        assert abs(by[name]["cct_K"] - target) / target < 0.02
        assert abs(by[name]["duv"]) < 0.003                       # Section 4.2 limit
    order = ["4000K", "3000K", "2700K", "2200K", "PC-Amber", "Narrow-band amber"]
    sky = [by[n]["skyglow_scotopic_rel"] for n in order]
    assert sky == sorted(sky, reverse=True)
    mel = [by[n]["mel_der"] for n in order]
    assert mel == sorted(mel, reverse=True)
    assert by["2200K"]["blue_fraction"] <= 0.07                   # <= 7 % below 500 nm
    assert by["PC-Amber"]["blue_fraction"] < 0.01
    assert 0.90 < by["2200K"]["mie_rel"] / by["3000K"]["mie_rel"] < 1.02   # aerosol nearly colour-blind
    # Section 4.1 worked example: 0.5 lx window under 2200K stays far under 1 lx melanopic EDI
    assert spectral.window_melanopic_edi(0.5, "2200K") < 0.2


def test_phase_table_boundaries():
    assert phase_for_hour(21.99) == Phase.EVENING
    assert phase_for_hour(22.0) == Phase.STEP
    assert phase_for_hour(23.0) == Phase.CURFEW
    assert phase_for_hour(0.5) == Phase.CURFEW
    assert phase_for_hour(1.0) == Phase.DEEP
    assert phase_for_hour(4.99) == Phase.DEEP
    assert phase_for_hour(5.0) == Phase.DAWN
    assert phase_for_hour(14.0) == Phase.EVENING
