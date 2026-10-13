"""Single-node bench: drives one VDL-7 through simulated time with a modelled
sky, a CMS that sends hellos and signed events, and optional mesh/backhaul
faults. Used by the acceptance suite and the `trace` CLI."""
from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import List, Optional

from .clock import DC_LAT, DC_LON, Photocell, RtcHoldover, parse_local, solar_elevation_deg, to_local
from .controller import Flash, Mode, NodeConfig, Output, VDL7Controller
from .driver import LuminaireDriver
from .events import Event, EventKind, Priority
from .profiles import RoadClass, default_bundle
from .security import Signer, make_signer


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
                 signer: Optional[Signer] = None, burn_hours: float = 0.0,
                 hello_every_s: float = 600.0, flash: Optional[Flash] = None,
                 rtc: Optional[RtcHoldover] = None, bundle_version: int = 1):
        self.signer = signer or make_signer()
        self.verifier = self.signer.public()
        self.flash = flash or Flash()
        if flash is None:
            assert self.flash.install(self.signer.sign_obj(default_bundle(bundle_version).to_dict()), self.verifier)
        self.rtc = rtc or RtcHoldover()
        self.cfg = NodeConfig(node_id=f"bench-{road.value}", road=road, hin=hin, tunable_white=tunable,
                              burn_hours=burn_hours)
        self.driver = LuminaireDriver.commissioned_for(self.flash.bundle.profiles[road])
        self.node = VDL7Controller(self.cfg, self.flash, self.rtc, self.verifier, self.driver)
        self.mono = 0.0
        self.utc = parse_local(start)
        self.online = online
        self.mesh_gateway = False
        self.lx_override: Optional[float] = None
        self.hello_every_s = hello_every_s
        self._last_hello = -math.inf
        self.outputs: List[Output] = []
        self.keep_history = False

    # ------------------------------------------------------------- the world
    @property
    def local(self) -> datetime:
        return to_local(self.utc)

    def lx_now(self) -> float:
        if self.lx_override is not None:
            return self.lx_override
        return sky_lux(solar_elevation_deg(DC_LAT, DC_LON, self.utc))

    def step(self, dt: float = 1.0) -> Output:
        if self.online and self.mono - self._last_hello >= self.hello_every_s:
            self.node.backhaul_hello(self.mono, self.utc)
            self._last_hello = self.mono
        if self.mesh_gateway:
            self.node.mesh_gateway_seen(self.mono)
        self.node.photocell_sample(self.lx_now(), self.mono)
        out = self.node.tick(self.mono, dt)
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
        target = parse_local(local_str)
        out = self.node.output
        while self.utc < target:
            out = self.step(min(dt, (target - self.utc).total_seconds()))
        return out

    # ------------------------------------------------------------------- CMS
    def send(self, kind: EventKind, ttl_s: float, payload: Optional[dict] = None,
             priority: int = Priority.NONE, via: str = "backhaul", event_id: Optional[str] = None) -> Event:
        ev = Event(kind=kind, ttl_s=ttl_s, payload=payload or {}, priority=priority,
                   issued=self.utc.isoformat())
        if event_id:
            ev.id = event_id
        assert self.node.receive(self.signer.sign_obj(ev.to_dict()), self.mono, via=via)
        return ev

    def loop_volume(self, veh15: float) -> Event:
        return self.send(EventKind.LOOP_VOLUME, ttl_s=900, payload={"veh15": veh15})

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
