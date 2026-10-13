"""CMS side of the node protocol: what the central system signs and sends.

The node never asks the CMS what level to run; the CMS only publishes signed
bundles and signed, addressed, sequenced events (Sections 2.1, 2.3, 5.4).
This module is the reference for those messages, used by the bench, the
simulation and the tests.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Tuple

from .events import Event, EventKind, Priority, make_targets
from .profiles import ProfileBundle
from .security import SignedMessage, Signer, make_signer

GEOFENCE_RADIUS_M = 400.0   # Section 2.3: incident point to 400 m geofence


def geofence(positions: Dict[str, Tuple[float, float]], center: Tuple[float, float],
             radius_m: float = GEOFENCE_RADIUS_M) -> List[str]:
    """Node ids whose commissioned position (metres, local grid) lies within
    `radius_m` of the incident point."""
    cx, cy = center
    return sorted(n for n, (x, y) in positions.items() if math.hypot(x - cx, y - cy) <= radius_m)


class Cms:
    def __init__(self, signer: Optional[Signer] = None):
        self.signer = signer or make_signer()
        self.seq = 0
        self.sent: List[dict] = []          # CMS-side audit of everything signed

    @property
    def verifier(self):
        return self.signer.public()

    def _sign(self, ev: Event, issued: Optional[datetime]) -> SignedMessage:
        self.seq += 1
        ev.seq = self.seq
        ev.issued = (issued or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
        d = ev.to_dict()
        self.sent.append(d)
        return self.signer.sign_obj(d)

    # ------------------------------------------------------------- events
    def event(self, kind: EventKind, ttl_s: float, targets: dict, payload: Optional[dict] = None,
              priority: int = Priority.NONE, event_id: Optional[str] = None,
              issued: Optional[datetime] = None) -> SignedMessage:
        ev = Event(kind=kind, ttl_s=ttl_s, payload=dict(payload or {}), priority=int(priority), targets=targets)
        if event_id:
            ev.id = event_id
        return self._sign(ev, issued)

    def emergency(self, nodes: Iterable[str], ttl_s: float = 3600, incident: str = "",
                  event_id: Optional[str] = None, issued: Optional[datetime] = None) -> SignedMessage:
        return self.event(EventKind.EMERGENCY, ttl_s, make_targets(nodes=nodes), {"incident": incident},
                          event_id=event_id, issued=issued)

    def override(self, level: float, ttl_s: float, priority: int, by: str, reason: str,
                 nodes: Iterable[str] = (), segments: Iterable[str] = (), everyone: bool = False,
                 event_id: Optional[str] = None, issued: Optional[datetime] = None) -> SignedMessage:
        return self.event(EventKind.OVERRIDE, ttl_s, make_targets(nodes, segments, everyone),
                          {"level": float(level), "by": by, "reason": reason}, priority=priority,
                          event_id=event_id, issued=issued)

    def weather(self, kind: EventKind, ttl_s: float = 1800, segments: Iterable[str] = (),
                everyone: bool = True, event_id: str = "wx", issued: Optional[datetime] = None) -> SignedMessage:
        return self.event(kind, ttl_s, make_targets(segments=segments, everyone=everyone and not segments),
                          {}, event_id=event_id, issued=issued)

    def loop_volume(self, segment: str, veh15: float, ttl_s: float = 900,
                    issued: Optional[datetime] = None) -> SignedMessage:
        return self.event(EventKind.LOOP_VOLUME, ttl_s, make_targets(segments=[segment]),
                          {"veh15": round(float(veh15), 1)}, event_id=f"loop-{segment}", issued=issued)

    def cancel(self, target_id: str, nodes: Iterable[str] = (), segments: Iterable[str] = (),
               everyone: bool = False, issued: Optional[datetime] = None) -> SignedMessage:
        ev = Event(kind=EventKind.CANCEL, ttl_s=60, payload={"target": target_id},
                   targets=make_targets(nodes, segments, everyone))
        return self._sign(ev, issued)

    # ------------------------------------------------------------ bundles
    def bundle(self, bundle: ProfileBundle) -> SignedMessage:
        return self.signer.sign_obj(bundle.to_dict())
