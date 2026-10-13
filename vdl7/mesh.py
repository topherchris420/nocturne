"""Wi-SUN FAN 1.1 segment mesh (Sections 5, 5.1, R-MESH-1/2).

The mesh does not own the curfew; it keeps *events* flowing between nodes
when the carrier does not. Three things live here:

* gateway reachability: a node is in MESH mode when it can reach, within the
  12-hop RPL budget, any node whose own backhaul is alive;
* the light carpet: a radar detection is re-broadcast 3 hops along the
  segment so the street lights up ahead of the walker;
* flood relay of signed CMS messages (emergency, weather, bundles). Relays
  forward the original bytes and signature and never re-sign.
"""
from __future__ import annotations

from collections import deque
from typing import Callable, Dict, Iterable, List, Optional, Set, Tuple

from .security import SignedMessage


class MeshNetwork:
    def __init__(self, hop_budget: int = 12, carpet_hops: int = 3):
        self.hop_budget = hop_budget
        self.carpet_hops = carpet_hops
        self.links: Dict[str, Set[str]] = {}

    # -------------------------------------------------------------- topology
    def add_node(self, node_id: str) -> None:
        self.links.setdefault(node_id, set())

    def add_link(self, a: str, b: str) -> None:
        self.add_node(a)
        self.add_node(b)
        self.links[a].add(b)
        self.links[b].add(a)

    def remove_link(self, a: str, b: str) -> None:
        self.links.get(a, set()).discard(b)
        self.links.get(b, set()).discard(a)

    def chain(self, node_ids: List[str]) -> None:
        """Link nodes in street order: pole i <-> pole i+1."""
        for a, b in zip(node_ids, node_ids[1:]):
            self.add_link(a, b)

    # -------------------------------------------------------------- queries
    def _bfs(self, origin: str, max_hops: int) -> Dict[str, int]:
        """node -> hop count for every node within max_hops of origin."""
        seen = {origin: 0}
        q = deque([origin])
        while q:
            n = q.popleft()
            h = seen[n]
            if h >= max_hops:
                continue
            for m in self.links.get(n, ()):
                if m not in seen:
                    seen[m] = h + 1
                    q.append(m)
        return seen

    def reachable_from(self, sources: Iterable[str], max_hops: Optional[int] = None) -> Set[str]:
        """Every node within the hop budget of any source: one multi-source
        BFS, so a whole segment's gateway reachability costs O(nodes)."""
        budget = self.hop_budget if max_hops is None else max_hops
        seen: Dict[str, int] = {s: 0 for s in sources if s in self.links}
        q = deque(seen)
        while q:
            n = q.popleft()
            h = seen[n]
            if h >= budget:
                continue
            for m in self.links.get(n, ()):
                if m not in seen:
                    seen[m] = h + 1
                    q.append(m)
        return set(seen)

    def hops_to_gateway(self, node_id: str, is_gateway: Callable[[str], bool]) -> Optional[int]:
        """Fewest hops to a node with live backhaul, or None beyond the budget."""
        for n, h in sorted(self._bfs(node_id, self.hop_budget).items(), key=lambda kv: kv[1]):
            if is_gateway(n):
                return h
        return None

    def gateway_reachable(self, node_id: str, is_gateway: Callable[[str], bool]) -> bool:
        return self.hops_to_gateway(node_id, is_gateway) is not None

    def carpet_targets(self, node_id: str) -> List[Tuple[str, int]]:
        """Neighbours within the carpet radius, excluding the detecting node."""
        return [(n, h) for n, h in self._bfs(node_id, self.carpet_hops).items() if n != node_id]

    def flood(self, origin: str, msg: SignedMessage,
              deliver: Callable[[str, SignedMessage, int], None]) -> List[str]:
        """Relay a signed message to every node reachable within the hop
        budget. `deliver(node_id, msg, hops)` is the receiving node's inbox."""
        delivered = []
        for n, h in self._bfs(origin, self.hop_budget).items():
            if n != origin:
                deliver(n, msg, h)
                delivered.append(n)
        return delivered
