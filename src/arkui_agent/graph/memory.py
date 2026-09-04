"""Small read-only reference implementation of GraphQuery, with no persistence."""

from collections import deque
from collections.abc import Iterable

from arkui_agent.graph.model import EdgeIdentity, GraphEdge, GraphNode, NodeIdentity, RelationType
from arkui_agent.graph.query import (
    Direction,
    NodeVisit,
    TraversalBounds,
    TraversalResult,
    TraversalStop,
)


class MemoryGraph:
    """Snapshot of supplied graph records, not a repository-fact projector.

    Exact duplicate nodes are accepted; conflicting records fail regardless of
    input order. Duplicate edges union their evidence. Dangling endpoints fail
    explicitly; callers may supply symbol-only anchored nodes when unresolved.
    """

    def __init__(self, nodes: Iterable[GraphNode], edges: Iterable[GraphEdge]) -> None:
        self._nodes: dict[NodeIdentity, GraphNode] = {}
        unique_edges: dict[EdgeIdentity, GraphEdge] = {}
        for node in nodes:
            previous = self._nodes.get(node.identity)
            if previous is not None and previous != node:
                raise ValueError(f"Conflicting graph node: {node.identity.value}")
            self._nodes[node.identity] = node
        for edge in edges:
            if (edge.identity.source not in self._nodes
                    or edge.identity.target not in self._nodes):
                raise ValueError(f"Dangling graph edge: {edge.identity.value}")
            previous_edge = unique_edges.get(edge.identity)
            unique_edges[edge.identity] = (
                edge if previous_edge is None else previous_edge.merge(edge)
            )
        incoming: dict[NodeIdentity, list[GraphEdge]] = {}
        outgoing: dict[NodeIdentity, list[GraphEdge]] = {}
        for identity in sorted(unique_edges, key=lambda item: item.sort_key):
            edge = unique_edges[identity]
            incoming.setdefault(identity.target, []).append(edge)
            outgoing.setdefault(identity.source, []).append(edge)
        self._incoming = {key: tuple(value) for key, value in incoming.items()}
        self._outgoing = {key: tuple(value) for key, value in outgoing.items()}

    def node(self, identity: NodeIdentity) -> GraphNode | None:
        return self._nodes.get(identity)

    def incoming_edges(
        self, identity: NodeIdentity, *, relations: frozenset[RelationType] | None = None
    ) -> tuple[GraphEdge, ...]:
        return self._edges(identity, Direction.INCOMING, relations)

    def outgoing_edges(
        self, identity: NodeIdentity, *, relations: frozenset[RelationType] | None = None
    ) -> tuple[GraphEdge, ...]:
        return self._edges(identity, Direction.OUTGOING, relations)

    def neighbors(
        self, identity: NodeIdentity, *, direction: Direction = Direction.OUTGOING,
        relations: frozenset[RelationType] | None = None,
    ) -> tuple[GraphNode, ...]:
        identities = {
            self._other(edge, identity) for edge in self._edges(identity, direction, relations)
        }
        return tuple(self._nodes[key] for key in sorted(identities))

    def traverse(
        self, identity: NodeIdentity, *, bounds: TraversalBounds,
        direction: Direction = Direction.OUTGOING,
        relations: frozenset[RelationType] | None = None,
    ) -> TraversalResult:
        _validate_query(direction, relations)
        if not isinstance(bounds, TraversalBounds):
            raise TypeError("bounds must be TraversalBounds.")
        seed = self.node(identity)
        if seed is None:
            return TraversalResult((), ())
        visits = [NodeVisit(seed, 0)]
        pending = deque(visits)
        seen = {identity}
        edges: dict[EdgeIdentity, GraphEdge] = {}
        stopped_by = None
        while pending and stopped_by is None:
            visit = pending.popleft()
            if visit.depth == bounds.max_depth:
                continue
            for edge in self._edges(visit.node.identity, direction, relations):
                if edge.identity in edges:
                    continue
                other = self._other(edge, visit.node.identity)
                if len(edges) == bounds.max_edges:
                    stopped_by = TraversalStop.EDGE_LIMIT
                    break
                if other not in seen and len(seen) == bounds.max_nodes:
                    stopped_by = TraversalStop.NODE_LIMIT
                    break
                edges[edge.identity] = edge
                if other not in seen:
                    seen.add(other)
                    discovered = NodeVisit(self._nodes[other], visit.depth + 1)
                    visits.append(discovered)
                    pending.append(discovered)
        return TraversalResult(
            tuple(visits),
            tuple(edges[key] for key in sorted(edges, key=lambda item: item.sort_key)),
            stopped_by,
        )

    def _edges(
        self, identity: NodeIdentity, direction: Direction,
        relations: frozenset[RelationType] | None,
    ) -> tuple[GraphEdge, ...]:
        _validate_query(direction, relations)
        if direction == Direction.INCOMING:
            candidates = self._incoming.get(identity, ())
        elif direction == Direction.OUTGOING:
            candidates = self._outgoing.get(identity, ())
        else:
            unique = {
                edge.identity: edge for edge in (
                    *self._incoming.get(identity, ()), *self._outgoing.get(identity, ())
                )
            }
            candidates = tuple(unique[key] for key in sorted(
                unique, key=lambda item: item.sort_key
            ))
        return tuple(edge for edge in candidates
                     if relations is None or edge.identity.relation in relations)

    @staticmethod
    def _other(edge: GraphEdge, identity: NodeIdentity) -> NodeIdentity:
        return edge.identity.target if edge.identity.source == identity else edge.identity.source


def _validate_query(direction: Direction, relations: frozenset[RelationType] | None) -> None:
    if not isinstance(direction, Direction):
        raise TypeError("direction must be a Direction.")
    if relations is not None and (
        not isinstance(relations, frozenset)
        or any(not isinstance(item, RelationType) for item in relations)
    ):
        raise TypeError("relations must be a frozenset of RelationType or None.")
