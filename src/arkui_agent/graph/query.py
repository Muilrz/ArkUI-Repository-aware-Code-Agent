"""Storage-independent read-only graph query boundary."""

from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable

from arkui_agent.graph.model import GraphEdge, GraphNode, NodeIdentity, RelationType


class Direction(str, Enum):
    OUTGOING = "outgoing"
    INCOMING = "incoming"
    BOTH = "both"


class TraversalStop(str, Enum):
    NODE_LIMIT = "node_limit"
    EDGE_LIMIT = "edge_limit"


@dataclass(frozen=True, slots=True)
class TraversalBounds:
    max_depth: int
    max_nodes: int = 100
    max_edges: int = 1000

    def __post_init__(self) -> None:
        for name, minimum in (("max_depth", 0), ("max_nodes", 1), ("max_edges", 0)):
            value = getattr(self, name)
            if type(value) is not int:
                raise TypeError(f"{name} must be an integer.")
            if value < minimum:
                raise ValueError(f"{name} must be at least {minimum}.")


@dataclass(frozen=True, slots=True)
class NodeVisit:
    node: GraphNode
    depth: int


@dataclass(frozen=True, slots=True)
class TraversalResult:
    visits: tuple[NodeVisit, ...]
    edges: tuple[GraphEdge, ...]
    stopped_by: TraversalStop | None = None


class GraphQueryError(RuntimeError):
    """Operational backend failure; must not be disguised as an empty result."""


@runtime_checkable
class GraphQuery(Protocol):
    """Query one consistent repository graph snapshot.

    Missing nodes return None/empty tuples/empty traversal. Edges are unique by
    EdgeIdentity and sorted by its sort_key; neighbors are unique by NodeIdentity
    and sorted by (namespace, key). None filters match all, empty filters none.
    BOTH combines incoming/outgoing without reversing or duplicating edges.

    Traversal is FIFO breadth-first, visiting each node once, seed at depth 0.
    For each expanded node, inspect matching edges in EdgeIdentity.sort_key order.
    Nodes at max_depth are returned but not expanded. Return all inspected unique
    edges, including cycles/cross edges, not an induced graph or a path trace.
    Visits retain discovery order; returned edges use the global edge order.
    Seed counts toward max_nodes. Before admitting a new edge, check max_edges,
    then max_nodes for an unseen endpoint; stop at the first exceeded budget.
    An edge and its newly discovered node are admitted together. stopped_by is
    set only when a budget prevents admission, not merely when a cap is reached.
    Reaching max_depth is normal query completion. Operational errors raise
    GraphQueryError; invalid query arguments raise TypeError/ValueError.
    """

    def node(self, identity: NodeIdentity) -> GraphNode | None: ...

    def incoming_edges(
        self, identity: NodeIdentity, *, relations: frozenset[RelationType] | None = None
    ) -> tuple[GraphEdge, ...]: ...

    def outgoing_edges(
        self, identity: NodeIdentity, *, relations: frozenset[RelationType] | None = None
    ) -> tuple[GraphEdge, ...]: ...

    def neighbors(
        self, identity: NodeIdentity, *, direction: Direction = Direction.OUTGOING,
        relations: frozenset[RelationType] | None = None,
    ) -> tuple[GraphNode, ...]: ...

    def traverse(
        self, identity: NodeIdentity, *, bounds: TraversalBounds,
        direction: Direction = Direction.OUTGOING,
        relations: frozenset[RelationType] | None = None,
    ) -> TraversalResult: ...
