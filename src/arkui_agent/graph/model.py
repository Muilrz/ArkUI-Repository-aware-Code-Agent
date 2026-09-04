"""Immutable graph contracts; identities are scoped to one repository snapshot."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum

from arkui_agent.repository.model import RepositoryFile, SourceRange, SymbolIdentity


class NodeKind(str, Enum):
    FILE = "file"
    SYMBOL = "symbol"
    FUNCTION = "function"
    METHOD = "method"
    CLASS = "class"
    COMPONENT = "component"
    ARKTS_API = "arkts_api"
    BRIDGE = "bridge"
    MODEL = "model"
    PATTERN = "pattern"
    LAYOUT_PROPERTY = "layout_property"
    PAINT_PROPERTY = "paint_property"
    LAYOUT_ALGORITHM = "layout_algorithm"
    OVERLAY_MANAGER = "overlay_manager"
    TEST_FIXTURE = "test_fixture"
    TEST_CASE = "test_case"


class RelationType(str, Enum):
    DECLARE = "DECLARE"
    DEFINE = "DEFINE"
    CALL = "CALL"
    REFERENCE = "REFERENCE"
    INHERIT = "INHERIT"
    OVERRIDE = "OVERRIDE"
    CREATE = "CREATE"
    UPDATE_PROPERTY = "UPDATE_PROPERTY"
    MEASURE = "MEASURE"
    LAYOUT = "LAYOUT"
    SHOW = "SHOW"
    CLOSE = "CLOSE"
    TEST = "TEST"
    MOCK = "MOCK"


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


@dataclass(frozen=True, slots=True, order=True)
class NodeIdentity:
    """Namespaced stable key, independent of display name and node kind.

    ``symbol`` and ``file`` namespaces use exact P1 identities. Domain entities
    use producer-defined namespaces and stable keys, never a display-name guess.
    The versioned JSON value is lossless (including delimiters and Unicode).
    """

    namespace: str
    key: str

    def __post_init__(self) -> None:
        if not self.namespace.strip() or not self.key.strip():
            raise ValueError("NodeIdentity namespace and key must not be empty.")

    @classmethod
    def for_symbol(cls, identity: SymbolIdentity) -> NodeIdentity:
        return cls("symbol", identity.value)

    @classmethod
    def for_file(cls, file: RepositoryFile) -> NodeIdentity:
        return cls("file", file.path.as_posix())

    @property
    def value(self) -> str:
        return "graph-node:v1:" + _canonical([self.namespace, self.key])


@dataclass(frozen=True, slots=True)
class SourceAnchor:
    """Reference to existing P1 facts, without copying a Symbol record.

    Symbol-only anchors preserve unresolved endpoints. A range implies its P1
    file; a supplied file must agree. Missing ranges are never manufactured.
    """

    symbol_identity: SymbolIdentity | None = None
    file: RepositoryFile | None = None
    source_range: SourceRange | None = None

    def __post_init__(self) -> None:
        if self.source_range is not None:
            if self.file is not None and self.file != self.source_range.file:
                raise ValueError("SourceAnchor file must match its source range.")
            object.__setattr__(self, "file", self.source_range.file)
        if self.symbol_identity is None and self.file is None:
            raise ValueError("SourceAnchor requires a P1 symbol, file or range.")

    @property
    def sort_key(self) -> str:
        return _canonical([
            None if self.symbol_identity is None else self.symbol_identity.value,
            None if self.file is None else self.file.path.as_posix(),
            None if self.source_range is None else self.source_range.to_dict(),
        ])


@dataclass(frozen=True, slots=True)
class GraphNode:
    identity: NodeIdentity
    kind: NodeKind
    display_name: str
    anchors: tuple[SourceAnchor, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.kind, NodeKind):
            raise TypeError("GraphNode.kind must be a NodeKind.")
        if not self.display_name.strip():
            raise ValueError("GraphNode.display_name must not be empty.")
        if not isinstance(self.anchors, tuple):
            raise TypeError("GraphNode.anchors must be a tuple.")
        if not self.anchors:
            raise ValueError("GraphNode requires P1 source anchors.")
        object.__setattr__(self, "anchors", tuple(sorted(
            set(self.anchors), key=lambda anchor: anchor.sort_key
        )))
        if self.identity.namespace == "symbol" and not any(
            anchor.symbol_identity == SymbolIdentity(self.identity.key)
            for anchor in self.anchors
        ):
            raise ValueError("Symbol node identity must match a P1 anchor.")
        if self.identity.namespace == "file" and not any(
            anchor.file is not None and anchor.file.path.as_posix() == self.identity.key
            for anchor in self.anchors
        ):
            raise ValueError("File node identity must match a P1 anchor.")


@dataclass(frozen=True, slots=True)
class RelationEvidence:
    """Producer/fact or rule identifier plus a precise account of the evidence.

    ``description`` must state what the anchor proves, e.g. caller definition
    rather than call site when that is all P1 supplies. Multiple producers and
    occurrences can support the same relation without changing its identity.
    """

    provenance: str
    anchor: SourceAnchor
    description: str

    def __post_init__(self) -> None:
        if not self.provenance.strip() or not self.description.strip():
            raise ValueError("RelationEvidence requires provenance and description.")

    @property
    def sort_key(self) -> tuple[str, str, str]:
        return self.provenance, self.anchor.sort_key, self.description


@dataclass(frozen=True, slots=True)
class EdgeIdentity:
    """One directed semantic relation, irrespective of occurrence or producer."""

    source: NodeIdentity
    target: NodeIdentity
    relation: RelationType

    def __post_init__(self) -> None:
        if not isinstance(self.relation, RelationType):
            raise TypeError("EdgeIdentity.relation must be a RelationType.")

    @property
    def sort_key(self) -> tuple[NodeIdentity, NodeIdentity, str]:
        return self.source, self.target, self.relation.value

    @property
    def value(self) -> str:
        return "graph-edge:v1:" + _canonical([
            self.source.value, self.target.value, self.relation.value
        ])


@dataclass(frozen=True, slots=True)
class GraphEdge:
    identity: EdgeIdentity
    evidence: tuple[RelationEvidence, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.evidence, tuple):
            raise TypeError("GraphEdge.evidence must be a tuple.")
        if not self.evidence:
            raise ValueError("GraphEdge requires relation evidence.")
        object.__setattr__(self, "evidence", tuple(sorted(
            set(self.evidence), key=lambda item: item.sort_key
        )))

    def merge(self, other: GraphEdge) -> GraphEdge:
        """Union evidence for one identity; commutative and idempotent."""
        if self.identity != other.identity:
            raise ValueError("Cannot merge different edge identities.")
        return GraphEdge(self.identity, self.evidence + other.evidence)
