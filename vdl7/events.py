"""Signed events with monotonic time-to-live (Sections 2.3, 5.1, 5.3).

Nothing in the store depends on wall time. An event is stamped with the
node's monotonic clock when it arrives and expires `ttl_s` later, so a stale
emergency cannot hold a street at 100 % after its TTL even when the node has
no idea what time it is.

Every event also carries
* `targets`: who it is for. The CMS turns an incident point into a 400 m
  geofence node list and a loop volume into its segment; a node ignores an
  event that is not addressed to it, so a validly signed emergency for one
  street cannot light another.
* `seq`: a CMS-wide sequence number. The node keeps a 64-wide anti-replay
  window whose top is persisted in flash, so a captured message cannot be
  played back later, and a duplicate arriving by both backhaul and mesh is
  applied once.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import Dict, Iterable, List, Optional


class EventKind(str, Enum):
    EMERGENCY = "emergency"        # CAD incident geofence -> 100 %
    RAIN = "rain"                  # +15 points up to the boost cap
    FOG = "fog"                    # logged, no boost
    SNOW = "snow"                  # logged, no boost
    LOOP_VOLUME = "loop_volume"    # ATSPM 15-min volume for the segment
    OVERRIDE = "override"          # operator or planned-event level
    CANCEL = "cancel"              # cancels an event by id


class Priority(IntEnum):
    NONE = 0
    PLANNED = 1            # special-event permit
    OPERATOR = 2           # CMS console, MPD/FEMS request
    INCIDENT_COMMAND = 3   # the only priority that may pull an emergency below 100 %


PROTECTED = (EventKind.EMERGENCY, EventKind.OVERRIDE)   # evicted last


# ------------------------------------------------------------------ targets
def make_targets(nodes: Iterable[str] = (), segments: Iterable[str] = (), everyone: bool = False) -> dict:
    return {"nodes": sorted(set(nodes)), "segments": sorted(set(segments)), "all": bool(everyone)}


def addressed_to(targets: Optional[dict], node_id: str, segment_id: str) -> bool:
    if not isinstance(targets, dict):
        return False
    if targets.get("all"):
        return True
    return node_id in targets.get("nodes", ()) or segment_id in targets.get("segments", ())


# -------------------------------------------------------------------- event
@dataclass
class Event:
    kind: EventKind
    ttl_s: float
    payload: dict = field(default_factory=dict)
    priority: int = Priority.NONE
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    issued: str = ""               # CMS wall-clock stamp (ISO, UTC)
    targets: dict = field(default_factory=lambda: make_targets(everyone=True))
    seq: int = 0
    received_mono: float = 0.0
    via: str = "backhaul"
    cancelled: bool = False

    def active(self, mono: float) -> bool:
        return (not self.cancelled) and (mono - self.received_mono) < self.ttl_s

    def remaining_s(self, mono: float) -> float:
        return max(0.0, self.ttl_s - (mono - self.received_mono))

    def to_dict(self) -> dict:
        return {
            "kind": self.kind.value, "id": self.id, "ttl_s": self.ttl_s, "payload": self.payload,
            "priority": int(self.priority), "issued": self.issued, "targets": self.targets, "seq": self.seq,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Event":
        """Raises ValueError on an unknown kind or a malformed record."""
        return cls(kind=EventKind(d["kind"]), ttl_s=float(d["ttl_s"]), payload=dict(d.get("payload", {})),
                   priority=int(d.get("priority", 0)), id=str(d["id"]), issued=str(d.get("issued", "")),
                   targets=d.get("targets"), seq=int(d.get("seq", 0)))


# ---------------------------------------------------------------- the store
class EventStore:
    """Bounded in-RAM store. A reboot empties it; the CMS re-pushes anything
    that still matters. When full, the oldest unprotected event goes first;
    an emergency or override is dropped only if nothing else is left."""

    def __init__(self, capacity: int = 64):
        self.capacity = capacity
        self._events: Dict[str, Event] = {}

    def put(self, ev: Event, mono: float) -> None:
        ev.received_mono = mono
        self._events[ev.id] = ev                   # same id refreshes the TTL
        self.purge(mono)
        while len(self._events) > self.capacity:
            pool = [e for e in self._events.values() if e.kind not in PROTECTED] or list(self._events.values())
            oldest = min(pool, key=lambda e: e.received_mono)
            del self._events[oldest.id]

    def cancel(self, event_id: str) -> bool:
        ev = self._events.get(event_id)
        if ev is None:
            return False
        ev.cancelled = True
        return True

    def purge(self, mono: float) -> None:
        for k in [k for k, e in self._events.items() if not e.active(mono)]:
            del self._events[k]

    def active(self, kind: EventKind, mono: float) -> List[Event]:
        return [e for e in self._events.values() if e.kind == kind and e.active(mono)]

    def latest(self, kind: EventKind, mono: float) -> Optional[Event]:
        evs = self.active(kind, mono)
        return max(evs, key=lambda e: e.received_mono) if evs else None

    def highest_priority(self, kind: EventKind, mono: float) -> Optional[Event]:
        evs = self.active(kind, mono)
        return max(evs, key=lambda e: (e.priority, e.received_mono)) if evs else None

    def all(self) -> List[Event]:
        return list(self._events.values())

    def __len__(self) -> int:
        return len(self._events)


# ------------------------------------------------------------- anti-replay
class ReplayWindow:
    """IPsec-style sliding window over the CMS sequence number.

    Accepts a sequence number once, out of order within `width` of the
    highest seen. After a reboot the bitmap is unknown, so everything at or
    below the persisted top is treated as already seen."""

    def __init__(self, hi: int = 0, width: int = 64, after_reboot: bool = True):
        self.hi = hi
        self.width = width
        self.bits = (1 << width) - 1 if (after_reboot and hi > 0) else 0

    def check(self, seq: int) -> str:
        """'new', 'duplicate' (seen inside the window) or 'stale' (too old)."""
        if seq <= 0:
            return "stale"
        if seq > self.hi:
            return "new"
        off = self.hi - seq
        if off >= self.width:
            return "stale"
        return "duplicate" if (self.bits >> off) & 1 else "new"

    def accept(self, seq: int) -> None:
        if seq > self.hi:
            shift = seq - self.hi
            self.bits = ((self.bits << shift) | 1) & ((1 << self.width) - 1) if shift < self.width else 1
            self.hi = seq
        else:
            self.bits |= 1 << (self.hi - seq)
