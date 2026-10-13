"""Signed events with monotonic time-to-live (Sections 2.3, 5.1, 5.3).

Nothing in the store depends on wall time. An event is stamped with the
node's monotonic clock when it arrives and expires `ttl_s` later, so a stale
emergency cannot hold a street at 100 % after its TTL even when the node has
no idea what time it is.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import Dict, List, Optional


class EventKind(str, Enum):
    EMERGENCY = "emergency"        # CAD incident geofence -> 100 %
    RAIN = "rain"                  # +15 points up to the boost cap
    FOG = "fog"                    # logged, no boost
    SNOW = "snow"                  # logged, no boost
    LOOP_VOLUME = "loop_volume"    # ATSPM 15-min volume for the segment
    OVERRIDE = "override"          # operator or planned-event level
    CARPET = "carpet"              # neighbour presence relayed over the mesh
    CANCEL = "cancel"              # cancels an event by id


class Priority(IntEnum):
    NONE = 0
    PLANNED = 1            # special-event permit
    OPERATOR = 2           # CMS console, MPD/FEMS request
    INCIDENT_COMMAND = 3   # the only priority that may pull an emergency below 100 %


@dataclass
class Event:
    kind: EventKind
    ttl_s: float
    payload: dict = field(default_factory=dict)
    priority: int = Priority.NONE
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    issued: str = ""               # CMS wall-clock stamp, informational
    received_mono: float = 0.0
    via: str = "backhaul"
    cancelled: bool = False

    def active(self, mono: float) -> bool:
        return (not self.cancelled) and (mono - self.received_mono) < self.ttl_s

    def remaining_s(self, mono: float) -> float:
        return max(0.0, self.ttl_s - (mono - self.received_mono))

    def to_dict(self) -> dict:
        return {
            "kind": self.kind.value, "id": self.id, "ttl_s": self.ttl_s,
            "payload": self.payload, "priority": int(self.priority), "issued": self.issued,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Event":
        return cls(kind=EventKind(d["kind"]), ttl_s=float(d["ttl_s"]), payload=dict(d.get("payload", {})),
                   priority=int(d.get("priority", 0)), id=str(d["id"]), issued=str(d.get("issued", "")))


class EventStore:
    """Bounded in-RAM store. A reboot empties it; the CMS re-pushes anything
    that still matters."""

    def __init__(self, capacity: int = 64):
        self.capacity = capacity
        self._events: Dict[str, Event] = {}

    def put(self, ev: Event, mono: float) -> None:
        ev.received_mono = mono
        self._events[ev.id] = ev                   # same id refreshes the TTL
        self.purge(mono)
        if len(self._events) > self.capacity:      # drop the oldest
            oldest = min(self._events.values(), key=lambda e: e.received_mono)
            del self._events[oldest.id]

    def cancel(self, event_id: str) -> bool:
        ev = self._events.get(event_id)
        if ev is None:
            return False
        ev.cancelled = True
        return True

    def purge(self, mono: float) -> None:
        dead = [k for k, e in self._events.items() if not e.active(mono)]
        for k in dead:
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
