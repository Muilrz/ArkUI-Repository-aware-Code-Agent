"""P3-D bounded observations over C1/C2 seeds and unchanged public P2 queries."""

from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass, fields, is_dataclass, replace
from enum import Enum
from typing import Iterator

from arkui_agent.context import Change, HintKind, Task
from arkui_agent.graph.creation import CreationBounds, CreationTrace, trace_component_creation
from arkui_agent.graph.domain import RoleMapping
from arkui_agent.graph.layout import LayoutBounds, LayoutTrace, trace_measure_layout
from arkui_agent.graph.model import EdgeIdentity, GraphEdge, GraphNode, NodeIdentity, NodeKind, RelationType
from arkui_agent.graph.overlay import OverlayBounds, OverlayTrace, trace_overlay
from arkui_agent.graph.property import PropertyBounds, PropertyTrace, trace_property_update
from arkui_agent.graph.query import Direction, GraphQueryError, TraversalBounds, TraversalResult
from arkui_agent.knowledge import BoundKnowledge, FileHash, SnapshotSession
from arkui_agent.repository.index import SymbolIndexError
from arkui_agent.repository.model import RepositoryFile, Symbol, SymbolIdentity, TestCase, TestFixture
from .candidates import (
    CandidateInputError, CandidateRetrievalResult, EvidenceSide, GraphSeed, RangeFact,
    SymbolSeed, canonical, stable_id,
)
from .change_mapping import ChangeRetrievalResult


class TraceFamily(str, Enum):
    CREATION = "creation"
    PROPERTY = "property"
    LAYOUT = "layout"
    OVERLAY = "overlay"


@dataclass(frozen=True, slots=True)
class ExpansionPolicy:
    version: str = "p3.expansion.v1"
    task_direction: Direction = Direction.OUTGOING
    change_direction: Direction = Direction.BOTH
    relations: frozenset[RelationType] = frozenset({
        RelationType.CALL, RelationType.CREATE, RelationType.UPDATE_PROPERTY,
        RelationType.MEASURE, RelationType.LAYOUT, RelationType.SHOW, RelationType.CLOSE,
        RelationType.TEST,
    })
    trace_families: frozenset[TraceFamily] = frozenset(TraceFamily)
    max_depth: int = 2
    max_nodes_per_seed: int = 100
    max_edges_per_seed: int = 200
    max_queries_per_seed: int = 8
    max_paths_per_seed: int = 32
    max_states_per_trace: int = 1000
    max_layout_candidates: int = 32
    max_queries: int = 64
    max_nodes: int = 500
    max_edges: int = 1000
    max_paths: int = 128

    def __post_init__(self) -> None:
        if self.version != "p3.expansion.v1":
            raise CandidateInputError("Unsupported expansion policy version.")
        if not isinstance(self.task_direction, Direction) or not isinstance(self.change_direction, Direction):
            raise CandidateInputError("Expansion directions must be typed Direction values.")
        for name, kind in (("relations", RelationType), ("trace_families", TraceFamily)):
            value = getattr(self, name)
            if type(value) is not frozenset or any(not isinstance(item, kind) for item in value):
                raise CandidateInputError(f"{name} must be a typed frozenset.")
        for field in fields(self):
            if field.name.startswith("max_"):
                value = getattr(self, field.name)
                minimum = 0 if field.name in {"max_depth", "max_nodes", "max_queries", "max_edges", "max_edges_per_seed", "max_paths"} else 1
                if type(value) is not int or value < minimum:
                    raise CandidateInputError(f"Invalid {field.name}.")

    @property
    def policy_id(self) -> str:
        return stable_id(self)


@dataclass(frozen=True, slots=True)
class ExpansionSeed:
    seed: GraphSeed
    candidate_ids: tuple[str, ...]
    query_ids: tuple[str, ...]
    reasons: tuple[str, ...]
    ambiguous: bool
    unresolved: bool


@dataclass(frozen=True, slots=True)
class TraceRequest:
    """Explicit P2 identities; every symbol parameter must have C1/C2 provenance.

    Component is checked against domain metadata. Overlay pairing is caller
    intent, never a relation inferred from component membership or names.
    """

    family: TraceFamily
    seed: GraphSeed
    component: NodeIdentity
    reason: str
    setter: NodeIdentity | None = None
    manager: NodeIdentity | None = None
    close_seeds: tuple[NodeIdentity, ...] = ()

    def __post_init__(self) -> None:
        if (not isinstance(self.family, TraceFamily) or not isinstance(self.seed, GraphSeed)
                or not isinstance(self.component, NodeIdentity) or self.component.namespace != "arkui.component"
                or type(self.reason) is not str or not self.reason.strip()):
            raise CandidateInputError("Trace requires typed family, scoped seed, component and reason.")
        if type(self.close_seeds) is not tuple or any(not isinstance(s, NodeIdentity) for s in self.close_seeds):
            raise CandidateInputError("close_seeds must be a tuple of identities.")
        if self.family is TraceFamily.PROPERTY:
            if not isinstance(self.setter, NodeIdentity) or self.manager is not None or self.close_seeds:
                raise CandidateInputError("Property requires only a setter parameter.")
        elif self.family is TraceFamily.OVERLAY:
            if not isinstance(self.manager, NodeIdentity) or self.setter is not None or not self.close_seeds:
                raise CandidateInputError("Overlay requires manager and explicit Close seeds.")
        elif self.setter is not None or self.manager is not None or self.close_seeds:
            raise CandidateInputError("Unexpected trace parameters.")
        object.__setattr__(self, "close_seeds", tuple(sorted(set(self.close_seeds))))


Trace = CreationTrace | PropertyTrace | LayoutTrace | OverlayTrace
Observation = TraversalResult | Trace


@dataclass(frozen=True, slots=True)
class ObservationSummary:
    p2_status: str | None
    ruleset: str | None
    exhaustive: bool | None
    limitations: tuple[str, ...]
    node_count: int
    edge_count: int
    path_count: int


@dataclass(frozen=True, slots=True)
class ExpansionReport:
    query_id: str
    seed: ExpansionSeed
    trace_request: TraceRequest | None
    status: str
    diagnostics: tuple[str, ...]
    observation: Observation | None
    summary: ObservationSummary | None
    source_hashes: tuple[FileHash, ...]


@dataclass(frozen=True, slots=True)
class ExpansionResult:
    upstream: CandidateRetrievalResult
    policy: ExpansionPolicy
    seeds: tuple[ExpansionSeed, ...]
    reports: tuple[ExpansionReport, ...]
    unavailable_relations: tuple[RelationType, ...]
    diagnostics: tuple[str, ...]
    node_count: int
    edge_count: int
    path_count: int
    query_count: int

    @property
    def truncated(self) -> bool:
        return self.upstream.truncated or any(
            report.status == "truncated" or (report.summary is not None and any(
                "limit" in note or "cut" in note for note in report.summary.limitations
            )) for report in self.reports
        )

    def to_json(self) -> str:
        return canonical({"schema": "p3-d-expansion-v1", "result": self, "truncated": self.truncated})


@dataclass(frozen=True, slots=True)
class ChangeExpansionResult:
    upstream: ChangeRetrievalResult
    policy: ExpansionPolicy
    old: ExpansionResult | None
    new: ExpansionResult | None

    def to_json(self) -> str:
        return canonical({"schema": "p3-d-change-expansion-v1", "result": self})


def _walk(value: object) -> Iterator[object]:
    """Inspect typed observations only; does not create edges or source facts."""
    yield value
    if is_dataclass(value) and not isinstance(value, type):
        for field in fields(value):
            yield from _walk(getattr(value, field.name))
    elif isinstance(value, (tuple, list, frozenset)):
        for item in value:
            yield from _walk(item)


def _inventory(value: object) -> tuple[set[NodeIdentity], set[EdgeIdentity], set[str], int]:
    nodes: set[NodeIdentity] = set()
    edges: set[EdgeIdentity] = set()
    paths: set[str] = set()
    count = 0
    for item in _walk(value):
        if isinstance(item, NodeIdentity):
            nodes.add(item)
        elif isinstance(item, GraphEdge):
            edges.add(item.identity)
        elif isinstance(item, RepositoryFile):
            paths.add(item.path.as_posix())
        elif type(item).__name__ in {"CreationPath", "PropertyPath", "OverlayPath"}:
            count += 1
    return nodes, edges, paths, count


def _summary(value: Observation) -> ObservationSummary:
    nodes, edges, _, paths = _inventory(value)
    notes: set[str] = set()
    exhaustive = []
    for item in _walk(value):
        if is_dataclass(item) and not isinstance(item, type):
            for name in ("gaps", "issues", "diagnostics"):
                notes.update(getattr(item, name, ()))
            if hasattr(item, "exhaustive"):
                exhaustive.append(item.exhaustive)
    if isinstance(value, TraversalResult) and value.stopped_by is not None:
        notes.add(value.stopped_by.value)
    status = getattr(value, "status", None)
    return ObservationSummary(None if status is None else status.value,
                              getattr(value, "ruleset_identity", None),
                              all(exhaustive) if exhaustive else None,
                              tuple(sorted(notes)), len(nodes), len(edges), paths)


def expansion_seeds(result: CandidateRetrievalResult) -> tuple[ExpansionSeed, ...]:
    """Use identities, never text hits, relation endpoints or component fanout."""
    snapshot = result.binding.snapshot.identity
    merged: dict[NodeIdentity, ExpansionSeed] = {}

    def offer(identity: NodeIdentity, candidates: tuple[str, ...], queries: tuple[str, ...],
              reason: str, ambiguous: bool = False, unresolved: bool = False) -> None:
        previous = merged.get(identity)
        merged[identity] = ExpansionSeed(
            GraphSeed(identity, snapshot, result.request.side),
            tuple(sorted(set(candidates + (() if previous is None else previous.candidate_ids)))),
            tuple(sorted(set(queries + (() if previous is None else previous.query_ids)))),
            tuple(sorted({reason} | (set() if previous is None else set(previous.reasons)))),
            ambiguous or (previous.ambiguous if previous else False),
            unresolved or (previous.unresolved if previous else False),
        )

    for candidate in result.candidates:
        if candidate.snapshot != snapshot or candidate.side is not result.request.side:
            raise CandidateInputError("Candidate snapshot/side mismatch.")
        for fact in candidate.observations:
            identity = None
            if isinstance(fact, (Symbol, TestFixture, TestCase)):
                identity = NodeIdentity.for_symbol(fact.identity)
            elif isinstance(fact, (GraphNode, RoleMapping)):
                identity = fact.identity
            elif isinstance(fact, RangeFact) and fact.identity is not None:
                identity = NodeIdentity.for_symbol(fact.identity)
            if identity is not None:
                offer(identity, (candidate.candidate_id,), tuple(q.query_id for q in candidate.provenance),
                      "c1:" + type(fact).__name__, candidate.ambiguous, candidate.unresolved)
    # C2 selectors remain available even if C1 channel/candidate limits cut them.
    for query in result.request.queries:
        selector = query.selector
        if isinstance(selector, (SymbolSeed, GraphSeed)):
            if selector.snapshot != snapshot or selector.side is not result.request.side:
                raise CandidateInputError("Query seed snapshot/side mismatch.")
            identity = NodeIdentity.for_symbol(selector.identity) if isinstance(selector, SymbolSeed) else selector.identity
            offer(identity, (), (query.query_id,), "explicit_scoped_query_seed")
    return tuple(merged[key] for key in sorted(merged))


def _automatic_traces(result: CandidateRetrievalResult, seeds: tuple[ExpansionSeed, ...],
                      view: BoundKnowledge) -> tuple[TraceRequest, ...]:
    if not isinstance(result.request.input, Task):
        return ()  # Change does not imply an API family or a Show/Close pairing.
    hints = result.request.input.hints
    actions = {h.value.casefold() for h in hints if h.kind is HintKind.ACTION}
    creation = bool(actions & {"create", "creation", "创建"})
    layout = bool(actions & {"layout", "measure", "布局", "测量"})
    requests = []
    for seed in seeds:
        identity = seed.seed.identity
        mapping = view.domain.lookup(identity)
        if layout and mapping is not None and mapping.resolved is not None:
            if mapping.resolved.role is NodeKind.PATTERN and mapping.resolved.component is not None:
                requests.append(TraceRequest(TraceFamily.LAYOUT, seed.seed, mapping.resolved.component,
                                             "task_action+P2_pattern_role"))
        if creation and identity.namespace == "symbol":
            symbol = view.index.get(SymbolIdentity(identity.key))
            parent = None if symbol is None or symbol.parent_identity is None else view.domain.lookup(
                NodeIdentity.for_symbol(symbol.parent_identity))
            if parent is not None and parent.resolved is not None and parent.resolved.component is not None:
                if parent.resolved.role in {NodeKind.BRIDGE, NodeKind.MODEL}:
                    requests.append(TraceRequest(TraceFamily.CREATION, seed.seed, parent.resolved.component,
                                                 "task_action+P1_parent+P2_role"))
    return tuple(requests)


def _trace(view: BoundKnowledge, request: TraceRequest, policy: ExpansionPolicy) -> Trace:
    args = (view.index, view.graph, view.domain, view.workspace)
    common = dict(seed=request.seed.identity, component=request.component)
    bounds = (max(1, policy.max_depth), policy.max_paths_per_seed, policy.max_states_per_trace)
    if request.family is TraceFamily.CREATION:
        return trace_component_creation(*args, **common, bounds=CreationBounds(*bounds))
    if request.family is TraceFamily.PROPERTY:
        return trace_property_update(*args, **common, setter=request.setter, bounds=PropertyBounds(*bounds))
    if request.family is TraceFamily.LAYOUT:
        return trace_measure_layout(*args, **common,
                                    bounds=LayoutBounds(policy.max_layout_candidates, max(1, policy.max_edges_per_seed)))
    return trace_overlay(*args, manager=request.manager, component=request.component,
                         show_seed=request.seed.identity, close_seeds=request.close_seeds,
                         bounds=OverlayBounds(*bounds))


class GraphExpander:
    def __init__(self, policy: ExpansionPolicy = ExpansionPolicy()) -> None:
        if not isinstance(policy, ExpansionPolicy):
            raise CandidateInputError("Expected ExpansionPolicy.")
        self.policy = policy

    def expand(self, result: CandidateRetrievalResult, session: SnapshotSession, *,
               traces: tuple[TraceRequest, ...] = ()) -> ExpansionResult:
        if not isinstance(result, CandidateRetrievalResult) or result.binding != session.reference:
            raise CandidateInputError("Expansion requires the original C1 binding.")
        if type(traces) is not tuple or any(not isinstance(t, TraceRequest) for t in traces):
            raise CandidateInputError("Expected a tuple of TraceRequest.")
        input = result.request.input
        revision = (input.target_revision.value if isinstance(input, Task) else
                    input.base_revision.value if result.request.side is EvidenceSide.OLD else input.head_revision.value)
        if input.repository != result.binding.snapshot.identity.repository or revision != result.binding.snapshot.identity.revision:
            raise CandidateInputError("Input revision is not bound.")
        seeds = expansion_seeds(result)
        by_identity = {s.seed.identity: s for s in seeds}
        policy = self.policy
        reports: list[ExpansionReport] = []
        nodes: set[NodeIdentity] = set()
        edges: set[EdgeIdentity] = set()
        path_count = 0
        query_count = 0
        per_seed: dict[NodeIdentity, tuple[set[NodeIdentity], set[EdgeIdentity], int, int]] = {}
        diagnostics = []
        with session.read() as view:
            query = view.graph.query()
            unavailable = tuple(sorted(set(view.graph.unavailable_relations) | {RelationType.MOCK}, key=lambda r: r.value))
            hashes = {f.path: f for f in view.reference.snapshot.source.files}
            automatic = _automatic_traces(result, seeds, view)
            requests = {canonical(t): t for t in traces + automatic}
            jobs: list[tuple[ExpansionSeed, TraceRequest | None]] = [(seed, None) for seed in seeds]
            for key in sorted(requests):
                request = requests[key]
                if request.seed.identity not in by_identity or request.seed != by_identity[request.seed.identity].seed:
                    raise CandidateInputError("Trace seed has no same-side C1/C2 provenance.")
                jobs.append((by_identity[request.seed.identity], request))
            if not seeds:
                diagnostics.append("no_proven_expansion_seeds")
            if isinstance(input, Task) and not requests:
                diagnostics.append("trace_not_selected:requires_supported_action_and_role_or_explicit_identity_parameters")
            # Full P2 trace source footprint may exceed its returned evidence.
            # Validate the supplied graph, domain and P1 file inventory before invoking it.
            trace_source_ok = None
            for seed, request in jobs:
                query_id = stable_id((policy.policy_id, seed.seed, request))
                reason: list[str] = []
                status = "ok"
                observation = None
                summary = None
                source_hashes: tuple[FileHash, ...] = ()
                sn, se, sp, sq = per_seed.get(seed.seed.identity, (set(), set(), 0, 0))
                if query_count >= policy.max_queries or sq >= policy.max_queries_per_seed:
                    reason.append("global_query_limit" if query_count >= policy.max_queries else "seed_query_limit")
                    status = "truncated"
                elif request is not None and request.family not in policy.trace_families:
                    status, reason = "unsupported", ["trace_family_disabled"]
                else:
                    query_count += 1
                    per_seed[seed.seed.identity] = (sn, se, sp, sq + 1)
                    try:
                        if request is None:
                            direction = policy.task_direction if isinstance(input, Task) else policy.change_direction
                            observation = query.traverse(seed.seed.identity,
                                bounds=TraversalBounds(policy.max_depth, policy.max_nodes_per_seed, policy.max_edges_per_seed),
                                direction=direction, relations=policy.relations - set(unavailable))
                            reason.extend("unsupported_relation:" + r.value for r in unavailable if r in policy.relations)
                            reason.append("depth_scope:" + str(policy.max_depth))
                            if not observation.visits:
                                status = "unresolved"
                                reason.append("seed_absent_from_graph")
                        else:
                            required = (request.seed.identity,) + request.close_seeds + tuple(
                                n for n in (request.setter, request.manager) if n is not None)
                            if any(n not in by_identity or n.namespace != "symbol" or query.node(n) is None for n in required):
                                status, reason = "unresolved", ["trace_parameter_missing_C1_C2_or_graph_identity"]
                            elif not any(c.node.identity == request.component for c in view.domain.components):
                                status, reason = "unresolved", ["component_not_in_domain_catalog"]
                            elif policy.max_depth == 0 and request.family is not TraceFamily.LAYOUT:
                                status, reason = "truncated", ["trace_depth_limit"]
                            else:
                                if trace_source_ok is None:
                                    trace_paths = _inventory((view.graph, view.domain))[2]
                                    for file in view.index.files():
                                        trace_paths.add(file.path.as_posix())
                                        trace_paths.update(_inventory(view.index.symbols_in_file(file))[2])
                                    trace_source_ok = trace_paths.issubset(hashes)
                                if not trace_source_ok:
                                    status, reason = "unresolved", ["trace_source_outside_fingerprint"]
                                else:
                                    observation = _trace(view, request, policy)
                    except (GraphQueryError, SymbolIndexError, OSError, UnicodeError) as error:
                        status, reason = "failure", [type(error).__name__ + ": " + str(error)]
                    if observation is not None:
                        summary = _summary(observation)
                        on, oe, files, op = _inventory(observation)
                        if not files.issubset(hashes):
                            status = "unresolved"
                            reason.append("observation_source_outside_fingerprint")
                            observation = None
                        else:
                            limits = ((len(nodes | on), policy.max_nodes, "global_node_limit"),
                                      (len(edges | oe), policy.max_edges, "global_edge_limit"),
                                      (path_count + op, policy.max_paths, "global_path_limit"),
                                      (len(sn | on), policy.max_nodes_per_seed, "seed_node_limit"),
                                      (len(se | oe), policy.max_edges_per_seed, "seed_edge_limit"),
                                      (sp + op, policy.max_paths_per_seed, "seed_path_limit"))
                            exceeded = [name for count, cap, name in limits if count > cap]
                            if exceeded:
                                status = "truncated"
                                reason.extend(exceeded)
                                observation = None  # Atomic admission preserves trace structure/associations.
                            else:
                                nodes.update(on)
                                edges.update(oe)
                                path_count += op
                                per_seed[seed.seed.identity] = (sn | on, se | oe, sp + op, sq + 1)
                                source_hashes = tuple(hashes[f] for f in sorted(files))
                                if isinstance(observation, TraversalResult):
                                    if observation.stopped_by is not None:
                                        status = "truncated"
                                    if any(not visit.node.anchors or not _inventory(visit.node)[2] for visit in observation.visits):
                                        reason.append("unresolved_node_source")
                                elif summary.p2_status != "complete":
                                    status = "partial"
                reports.append(ExpansionReport(query_id, seed, request, status, tuple(sorted(set(reason))),
                                                observation, summary, source_hashes))
        return ExpansionResult(result, policy, seeds, tuple(reports), unavailable,
                               tuple(diagnostics), len(nodes), len(edges), path_count, query_count)

    def expand_change(self, result: ChangeRetrievalResult, *, base: SnapshotSession | None,
                      head: SnapshotSession | None, old_traces: tuple[TraceRequest, ...] = (),
                      new_traces: tuple[TraceRequest, ...] = ()) -> ChangeExpansionResult:
        if not isinstance(result, ChangeRetrievalResult):
            raise CandidateInputError("Expected C2 ChangeRetrievalResult.")
        with ExitStack() as stack:
            for upstream, session, traces, side in ((result.old, base, old_traces, EvidenceSide.OLD),
                                                    (result.new, head, new_traces, EvidenceSide.NEW)):
                if upstream is not None:
                    if session is None or upstream.request.side is not side or upstream.request.input != result.mapping.change:
                        raise CandidateInputError("Change side/input/session mismatch.")
                    stack.enter_context(session.read())
                elif traces:
                    raise CandidateInputError("Cannot trace an unavailable revision side.")
            new = None if result.new is None else self.expand(result.new, head, traces=new_traces)
            remaining = self.policy if new is None else replace(
                self.policy, max_nodes=self.policy.max_nodes - new.node_count,
                max_edges=self.policy.max_edges - new.edge_count,
                max_paths=self.policy.max_paths - new.path_count,
                max_queries=self.policy.max_queries - new.query_count)
            old = None if result.old is None else GraphExpander(remaining).expand(result.old, base, traces=old_traces)
        return ChangeExpansionResult(result, self.policy, old, new)
