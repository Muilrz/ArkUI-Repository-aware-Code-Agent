"""Provisional C1 candidate contracts, not ranked context or a Context Pack."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
from pathlib import PurePath

from arkui_agent.context import Change, Provenance, Task
from arkui_agent.graph.domain import ComponentMapping, RoleMapping
from arkui_agent.graph.model import GraphEdge, GraphNode, NodeIdentity
from arkui_agent.knowledge import BindingReference, FileHash, SnapshotIdentity
from arkui_agent.repository.index import TestedSymbolMapping
from arkui_agent.repository.model import SourceRange, Symbol, SymbolIdentity, TestCase, TestFixture
from .reference_call import DirectCallRelation


class CandidateInputError(ValueError):
    pass


def canonical(value: object) -> str:
    """Stable structural encoding for keys/output; no dynamic deserialization."""
    def encode(item: object) -> object:
        if isinstance(item, Enum):
            return item.value
        if isinstance(item, PurePath):
            return item.as_posix()
        if is_dataclass(item) and not isinstance(item, type):
            return {"type": type(item).__name__, **{f.name: encode(getattr(item, f.name)) for f in fields(item)}}
        if isinstance(item, (tuple, list)):
            return [encode(x) for x in item]
        if isinstance(item, (set, frozenset)):
            return sorted((encode(x) for x in item), key=lambda x: json.dumps(x, sort_keys=True))
        if isinstance(item, dict):
            return {str(k): encode(v) for k, v in item.items()}
        return item
    return json.dumps(encode(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def stable_id(value: object) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


class EvidenceSide(str, Enum):
    TARGET = "target"
    OLD = "old"
    NEW = "new"


class Channel(str, Enum):
    TEXT = "text"
    SYMBOL = "symbol"
    DECLARATION = "declaration"
    DEFINITION = "definition"
    REFERENCE = "reference"
    CALLERS = "callers"
    CALLEES = "callees"
    TEST_FIXTURES = "test_fixtures"
    TEST_CASES = "test_cases"
    TESTS_FOR_FIXTURE = "tests_for_fixture"
    TESTS_FOR_SYMBOL = "tests_for_symbol"
    TEST_MAPPING = "test_mapping"
    GRAPH_NODE = "graph_node"
    GRAPH_INCOMING = "graph_incoming"
    GRAPH_OUTGOING = "graph_outgoing"
    DOMAIN_LOOKUP = "domain_lookup"
    DOMAIN_MEMBERS = "domain_members"
    DOMAIN_COMPONENT = "domain_component"
    INHERIT = "inherit"
    OVERRIDE = "override"
    MOCK = "mock"


class RetrievalStatus(str, Enum):
    OK = "ok"
    EMPTY = "empty"
    UNSUPPORTED = "unsupported"
    FAILURE = "failure"
    TRUNCATED = "truncated"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True, slots=True)
class RetrievalBounds:
    max_queries: int = 64
    max_calls_per_channel: int = 64
    max_name_candidates: int = 20
    max_results_per_query: int = 100
    max_records_per_query: int = 500
    max_candidates_per_channel: int = 200
    max_candidates: int = 500
    max_query_characters: int = 4096

    def __post_init__(self) -> None:
        for field in fields(self):
            value = getattr(self, field.name)
            if type(value) is not int or value < 1:
                raise CandidateInputError(f"{field.name} must be a positive integer.")


@dataclass(frozen=True, slots=True)
class NameSelector:
    text: str
    qualified: bool = False

    def __post_init__(self) -> None:
        if type(self.text) is not str or not self.text.strip() or type(self.qualified) is not bool:
            raise CandidateInputError("Name selector requires nonempty text and a boolean match mode.")


@dataclass(frozen=True, slots=True)
class SymbolSeed:
    identity: SymbolIdentity
    snapshot: SnapshotIdentity
    side: EvidenceSide

    def __post_init__(self) -> None:
        if not isinstance(self.identity, SymbolIdentity) or not isinstance(self.snapshot, SnapshotIdentity) or not isinstance(self.side, EvidenceSide):
            raise CandidateInputError("Symbol seed requires an explicit identity, snapshot and side.")


@dataclass(frozen=True, slots=True)
class GraphSeed:
    identity: NodeIdentity
    snapshot: SnapshotIdentity
    side: EvidenceSide

    def __post_init__(self) -> None:
        if not isinstance(self.identity, NodeIdentity) or not isinstance(self.snapshot, SnapshotIdentity) or not isinstance(self.side, EvidenceSide):
            raise CandidateInputError("Graph seed requires an explicit identity, snapshot and side.")


@dataclass(frozen=True, slots=True)
class QueryOrigin:
    provenance: Provenance
    label: str

    def __post_init__(self) -> None:
        if not isinstance(self.provenance, Provenance) or type(self.label) is not str or not self.label.strip():
            raise CandidateInputError("Query origin requires input provenance and a label.")


@dataclass(frozen=True, slots=True)
class CandidateQuery:
    channel: Channel
    selector: NameSelector | SymbolSeed | GraphSeed
    origins: tuple[QueryOrigin, ...]

    def __post_init__(self) -> None:
        if (not isinstance(self.channel, Channel) or not isinstance(self.selector, (NameSelector, SymbolSeed, GraphSeed))
                or type(self.origins) is not tuple or not self.origins
                or any(not isinstance(item, QueryOrigin) for item in self.origins)):
            raise CandidateInputError("Invalid query channel, selector or provenance.")

    @property
    def query_id(self) -> str:
        return stable_id((self.channel, self.selector))


@dataclass(frozen=True, slots=True)
class RetrievalRequest:
    input: Task | Change
    side: EvidenceSide
    queries: tuple[CandidateQuery, ...]
    diagnostics: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.input, (Task, Change)) or not isinstance(self.side, EvidenceSide):
            raise CandidateInputError("Expected typed Task/Change and side.")
        if (isinstance(self.input, Task)) != (self.side is EvidenceSide.TARGET):
            raise CandidateInputError("Task uses target; Change requires explicit old/new side.")
        if type(self.queries) is not tuple or any(not isinstance(q, CandidateQuery) for q in self.queries):
            raise CandidateInputError("Queries must be a tuple of CandidateQuery.")
        if type(self.diagnostics) is not tuple or any(type(d) is not str or not d for d in self.diagnostics):
            raise CandidateInputError("Request diagnostics must be a tuple of nonempty strings.")


@dataclass(frozen=True, slots=True)
class RangeFact:
    role: str
    source_range: SourceRange
    identity: SymbolIdentity | None = None
    matched_text: str | None = None
    line_text: str | None = None


CandidateFact = Symbol | RangeFact | DirectCallRelation | GraphEdge | GraphNode | TestFixture | TestCase | TestedSymbolMapping | RoleMapping | ComponentMapping


def fact_key(fact: CandidateFact) -> tuple[object, ...]:
    if isinstance(fact, Symbol):
        return "symbol", fact.identity.value
    if isinstance(fact, RangeFact):
        return "range", fact.role, fact.identity, fact.source_range
    if isinstance(fact, DirectCallRelation):
        return "relation", NodeIdentity.for_symbol(fact.caller_identity), NodeIdentity.for_symbol(fact.callee_identity), "CALL"
    if isinstance(fact, GraphEdge):
        return "relation", fact.identity.source, fact.identity.target, fact.identity.relation.value
    if isinstance(fact, GraphNode):
        return "graph_node", fact.identity
    if isinstance(fact, (TestFixture, TestCase)):
        return "test", type(fact).__name__, fact.identity.value
    if isinstance(fact, TestedSymbolMapping):
        return "test_mapping", fact.test_case_identity.value, fact.symbol_identity.value
    if isinstance(fact, RoleMapping):
        return "domain_mapping", fact.identity
    if isinstance(fact, ComponentMapping):
        return "domain_component", fact.node.identity
    raise TypeError("Unsupported candidate fact type.")


@dataclass(frozen=True, slots=True)
class Candidate:
    candidate_id: str
    snapshot: SnapshotIdentity
    side: EvidenceSide
    observations: tuple[CandidateFact, ...]
    provenance: tuple[CandidateQuery, ...]
    source_hashes: tuple[FileHash, ...]
    ambiguous: bool
    unresolved: bool


@dataclass(frozen=True, slots=True)
class QueryReport:
    query: CandidateQuery
    status: RetrievalStatus
    candidate_ids: tuple[str, ...]
    diagnostics: tuple[str, ...]
    calls: int
    observed: int
    ambiguous: bool = False
    unresolved: bool = False
    truncated: bool = False


@dataclass(frozen=True, slots=True)
class CandidateRetrievalResult:
    binding: BindingReference
    request: RetrievalRequest
    bounds: RetrievalBounds
    candidates: tuple[Candidate, ...]
    reports: tuple[QueryReport, ...]
    diagnostics: tuple[str, ...]
    truncated: bool = False

    @property
    def status(self) -> RetrievalStatus:
        states = {report.status for report in self.reports}
        if RetrievalStatus.FAILURE in states:
            return RetrievalStatus.FAILURE
        if self.truncated:
            return RetrievalStatus.TRUNCATED
        for state in (RetrievalStatus.FAILURE, RetrievalStatus.TRUNCATED, RetrievalStatus.UNRESOLVED, RetrievalStatus.UNSUPPORTED):
            if state in states:
                return state
        if self.diagnostics:
            return RetrievalStatus.UNRESOLVED
        return RetrievalStatus.OK if self.candidates else RetrievalStatus.EMPTY

    def to_json(self) -> str:
        return canonical({"schema": "p3-c1-candidates-v1", "result": self, "status": self.status})
