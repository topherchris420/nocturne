"""Single-node bench: drives one VDL-7 through simulated time with a modelled
sky, a CMS that sends hellos and signed, addressed events, and optional
mesh/backhaul faults. Used by the acceptance suite and the `trace` CLI."""
from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import List, Optional

from .clock import RtcHoldover, parse_local, solar_elevation_deg, to_local
from .cms import Cms
from .controller import Flash, NodeConfig, Output, VDL7Controller
from .driver import LuminaireDriver
from .events import EventKind, Priority
from .profiles import RoadClass, default_bundle
from .security import SignedMessage
from .sites import DEFAULT_SITE, Site


def sky_lux(elev_deg: float) -> float:
    """Horizontal illuminance from solar elevation, rough but monotonic."""
    if elev_deg > 0:
        return 100.0 + 100_000.0 * math.sin(math.radians(elev_deg))
    if elev_deg > -6:
        return 100.0 * 10 ** (elev_deg / 2.0)        # civil twilight, 100 -> 0.1 lx
    return 0.05


class Bench:
    def __init__(self, road: RoadClass = RoadClass.LOCAL, start: str = "2026-10-13 18:00",
                 hin: bool = False, online: bool = True, tunable: bool = False,
                 cms: Optional[Cms] = None, burn_hours: float = 0.0,
                 hello_every_s: float = 600.0, flash: Optional[Flash] = None,
                 rtc: Optional[RtcHoldover] = None, bundle_version: int = 1,
                 interface: str = "dali2", node_id: Optional[str] = None, segment_id: str = "seg-bench",
                 site: Optional[Site] = None, zone: Optional[str] = None):
        self.site = site or DEFAULT_SITE
        self.cms = cms or Cms()
        self.verifier = self.cms.verifier
        self.flash = flash or Flash()
        if flash is None:
            assert self.flash.install(self.cms.bundle(default_bundle(bundle_version)), self.verifier)
        self.rtc = rtc or RtcHoldover()
        self.cfg = NodeConfig(node_id=node_id or f"bench-{road.value}", road=road, hin=hin,
                              tunable_white=tunable, burn_hours=burn_hours, segment_id=segment_id,
                              lat=self.site.lat, lon=self.site.lon, tz=self.site.tz, zone=zone)
        self.driver = LuminaireDriver.commissioned_for(self.flash.bundle.profiles[road], hin, interface)
        self.node = VDL7Controller(self.cfg, self.flash, self.rtc, self.verifier, self.driver)
        self.mono = 0.0
        self.utc = parse_local(start, self.site.tz)
        self.online = online
        self.mesh_gateway = False
        self.lx_override: Optional[float] = None
        self.hello_every_s = hello_every_s
        self._last_hello = -math.inf
        self.outputs: List[Output] = []
        self.keep_history = False
        self.uplinks: List[dict] = []
        self._last_alarms: tuple = ()
        self.hung = False                       # controller firmware hung: no ticks, bus silent

    @property
    def signer(self):
        return self.cms.signer

    # ------------------------------------------------------------- the world
    @property
    def local(self) -> datetime:
        return to_local(self.utc, self.site.tz)

    def lx_now(self) -> float:
        if self.lx_override is not None:
            return self.lx_override
        return sky_lux(solar_elevation_deg(self.site.lat, self.site.lon, self.utc))

    def step(self, dt: float = 1.0) -> Output:
        if self.online and self.mono - self._last_hello >= self.hello_every_s:
            self.node.backhaul_hello(self.mono, self.utc)
            self._last_hello = self.mono
        if self.hung:                           # the driver's watchdog is all that runs
            self.driver.watchdog(self.mono)
            self.mono += dt
            self.utc += timedelta(seconds=dt)
            return self.node.output
        if self.mesh_gateway:
            self.node.mesh_gateway_seen(self.mono)
        self.node.photocell_sample(self.lx_now(), self.mono)
        out = self.node.tick(self.mono, dt)
        up = self.node.pending_uplink()        # the node transmits whenever it thinks it is ONLINE
        if up and self.online:                  # ...but only a live carrier delivers, and only then the CMS acks
            alarms = tuple(up["alarms"])
            if up["records"] or alarms != self._last_alarms:
                self.uplinks.append(up)
                self._last_alarms = alarms
            self.node.ack_uplink(up["upto"])
        if self.keep_history:
            self.outputs.append(out)
        self.mono += dt
        self.utc += timedelta(seconds=dt)
        return out

    def advance(self, seconds: float, dt: float = 1.0) -> Output:
        out = self.node.output
        end = self.mono + seconds
        while self.mono < end - 1e-9:
            out = self.step(min(dt, end - self.mono))
        return out

    def run_until(self, local_str: str, dt: float = 1.0) -> Output:
        target = parse_local(local_str, self.site.tz)
        out = self.node.output
        while self.utc < target:
            out = self.step(min(dt, (target - self.utc).total_seconds()))
        return out

    # ------------------------------------------------------------------- CMS
    def deliver(self, msg: SignedMessage, via: Optional[str] = None) -> bool:
        return self.node.receive(msg, self.mono, via=via or ("backhaul" if self.online else "mesh"))

    def send(self, kind: EventKind, ttl_s: float, payload: Optional[dict] = None,
             priority: int = Priority.NONE, via: Optional[str] = None, event_id: Optional[str] = None,
             segment: Optional[str] = None, nodes=()) -> SignedMessage:
        """Sign an event addressed to this node's segment and deliver it; the
        delivery must be accepted."""
        payload = dict(payload or {})
        if kind == EventKind.OVERRIDE:
            payload.setdefault("by", "bench-operator")
            payload.setdefault("reason", "acceptance test")
        msg = self.cms.event(kind, ttl_s, segment or self.cfg.segment_id, payload, priority, event_id,
                             nodes=nodes, issued=self.utc)
        assert self.deliver(msg, via), list(self.node.log)[-3:]
        return msg

    def hang(self) -> None:
        """The controller stops running; only the driver's bus watchdog is left."""
        self.hung = True

    def loop_volume(self, veh15: float) -> SignedMessage:
        msg = self.cms.loop_volume(self.cfg.segment_id, veh15, issued=self.utc)
        assert self.deliver(msg)
        return msg

    def go_offline(self) -> None:
        self.online = False

    def go_online(self) -> None:
        self.online = True
        self._last_hello = -math.inf

    # ----------------------------------------------------------------- power
    def power_cut(self, outage_s: float, supercap_ok: bool = True) -> None:
        """Mains lost now. The monotonic clock restarts at zero on reboot."""
        if supercap_ok:
            self.rtc.power_cycle(self.mono, outage_s)
        else:
            self.rtc.reset()
        self.utc += timedelta(seconds=outage_s)
        self.mono = 0.0
        self._last_hello = -math.inf
        self.node = self.node.reboot()
        self.flash = self.node.flash
