"""P3-E: observed task views and source evidence, without further retrieval."""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass, replace
from enum import Enum
from typing import Iterator

from arkui_agent.context.inputs import Change, Task
from arkui_agent.graph.creation import CreationPath, PatternArgument
from arkui_agent.graph.domain import ComponentMapping, RoleMapping
from arkui_agent.graph.layout import LayoutDependency
from arkui_agent.graph.model import GraphEdge, GraphNode, NodeIdentity, RelationEvidence
from arkui_agent.graph.overlay import OverlayPath
from arkui_agent.graph.property import PropertyBinding, PropertyPath
from arkui_agent.graph.query import NodeVisit
from arkui_agent.knowledge import BindingReference, FileHash, SnapshotIdentity, SnapshotSession
from arkui_agent.repository.index import TestedSymbolMapping
from arkui_agent.repository.model import SourceLocation, SourceRange, Symbol, SymbolIdentity, TestCase, TestFixture
from arkui_agent.retrieval.candidates import CandidateFact, EvidenceSide, RangeFact, canonical, fact_key, stable_id
from arkui_agent.retrieval.change_mapping import RangeMapping
from arkui_agent.retrieval.expansion import ChangeExpansionResult, ExpansionResult
from arkui_agent.retrieval.reference_call import DirectCallRelation


class MaterializationError(ValueError):
    """Malformed or mixed observation input; not a retrieval miss."""


class ContextKind(str, Enum):
    NODE = "node"
    FACT = "fact"
    RANGE = "range"
    RELATION = "relation"
    ASSOCIATION = "trace_association"
    BINDING = "property_binding"
    EVIDENCE = "supporting_evidence"
    CHANGE = "change_range"


Payload = (CandidateFact | NodeIdentity | SourceRange | RelationEvidence | PatternArgument
           | LayoutDependency | PropertyBinding | CreationPath | PropertyPath | OverlayPath | RangeMapping)
_ASSOCIATIONS = (PatternArgument, LayoutDependency, CreationPath, PropertyPath, OverlayPath)
_FACTS = (Symbol, RangeFact, DirectCallRelation, GraphEdge, GraphNode, TestFixture,
          TestCase, TestedSymbolMapping, RoleMapping, ComponentMapping)
_RECORDS = (*_FACTS, NodeIdentity, SourceRange, RelationEvidence, *_ASSOCIATIONS, PropertyBinding, RangeMapping)


@dataclass(frozen=True, slots=True)
class CandidateOrigin:
    channel: str
    reference_id: str  # C1 candidate ID, D query ID, or C2 mapping ID
    query_ids: tuple[str, ...]
    seed: NodeIdentity | None
    distance: int | None  # only an observed BFS depth, never inferred from trace order
    reason: str
    observation_path: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CandidateLimitations:
    ambiguous: bool = False
    unresolved: bool = False
    truncated: bool = False
    notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ContextCandidate:
    candidate_id: str
    kind: ContextKind
    repository: str
    revision: str | None
    snapshot: SnapshotIdentity | None
    side: EvidenceSide
    observations: tuple[Payload, ...]
    origins: tuple[CandidateOrigin, ...]
    source_hashes: tuple[FileHash, ...]
    source_ranges: tuple[SourceRange, ...]
    dependencies: tuple[str, ...]
    limitations: CandidateLimitations


@dataclass(frozen=True, slots=True)
class TaskSubgraph:
    nodes: tuple[str, ...]
    relations: tuple[str, ...]
    associations: tuple[str, ...]
    bindings: tuple[str, ...]
    supporting: tuple[str, ...]
    boundary: str = "observed retrieval/expansion only; endpoint/evidence closure; not induced"


class SnippetStatus(str, Enum):
    AVAILABLE = "available"
    SOURCE_UNAVAILABLE = "source_unavailable"
    BINDING_MISMATCH = "binding_mismatch"
    CONSISTENCY_FAILURE = "consistency_failure"
    HASH_MISMATCH = "source_hash_mismatch"
    RANGE_INVALID = "range_invalid"
    RANGE_MISSING = "range_missing"
    LIMIT = "materialization_limit"


@dataclass(frozen=True, slots=True)
class SnippetBounds:
    max_file_bytes: int = 4 * 1024 * 1024
    max_backing_characters: int = 65536

    def __post_init__(self) -> None:
        if any(type(getattr(self, f.name)) is not int or getattr(self, f.name) < 1 for f in fields(self)):
            raise MaterializationError("Snippet bounds must be positive integers.")


@dataclass(frozen=True, slots=True)
class SnippetBacking:
    backing_id: str
    snapshot: SnapshotIdentity
    side: EvidenceSide
    source_range: SourceRange
    source_sha256: str  # raw file bytes, as in B
    text: str  # exact UTF-8 decoded bytes, including original newlines


@dataclass(frozen=True, slots=True)
class CandidateSnippet:
    candidate_id: str
    source_range: SourceRange | None
    status: SnippetStatus
    backing_id: str | None = None
    start_offset: int | None = None
    end_offset: int | None = None
    diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ContextCandidateSet:
    input: Task | Change
    input_id: str
    bindings: tuple[BindingReference, ...]
    upstream: ExpansionResult | ChangeExpansionResult
    candidates: tuple[ContextCandidate, ...]
    subgraph: TaskSubgraph
    snippets: tuple[CandidateSnippet, ...]
    backings: tuple[SnippetBacking, ...]
    snippet_bounds: SnippetBounds

    def __post_init__(self) -> None:
        ids = {c.candidate_id for c in self.candidates}
        if len(ids) != len(self.candidates) or self.input_id != stable_id(self.input):
            raise MaterializationError("Duplicate candidate or incorrect input identity.")
        for candidate in self.candidates:
            if not candidate.observations or not candidate.origins or any(
                candidate.candidate_id != stable_id((candidate.snapshot, candidate.repository,
                    candidate.revision, candidate.side, _key(v))) for v in candidate.observations
            ):
                raise MaterializationError("Candidate identity/provenance mismatch.")
            if candidate.snapshot is not None and (candidate.repository != candidate.snapshot.repository
                                                    or candidate.revision != candidate.snapshot.revision):
                raise MaterializationError("Candidate snapshot scope mismatch.")
            if candidate.candidate_id in candidate.dependencies or not set(candidate.dependencies) <= ids:
                raise MaterializationError("Dangling or self candidate dependency.")
            if any(_kind(v) is not candidate.kind for v in candidate.observations):
                raise MaterializationError("Candidate kind disagrees with observations.")
            for value in candidate.observations:
                if isinstance(value, GraphEdge):
                    endpoints = (value.identity.source, value.identity.target)
                elif isinstance(value, DirectCallRelation):
                    endpoints = (NodeIdentity.for_symbol(value.caller_identity), NodeIdentity.for_symbol(value.callee_identity))
                else:
                    continue
                if any(stable_id((candidate.snapshot, candidate.repository, candidate.revision, candidate.side, _key(node)))
                       not in candidate.dependencies for node in endpoints):
                    raise MaterializationError("Relation endpoint closure missing.")
        for name in ("nodes", "relations", "associations", "bindings", "supporting"):
            if not set(getattr(self.subgraph, name)) <= ids:
                raise MaterializationError("Dangling subgraph reference.")
        backings = {b.backing_id: b for b in self.backings}
        if len(backings) != len(self.backings):
            raise MaterializationError("Duplicate snippet backing.")
        for backing in self.backings:
            if backing.backing_id != stable_id((backing.snapshot, backing.side, backing.source_range, backing.source_sha256)):
                raise MaterializationError("Backing identity mismatch.")
        by_id = {c.candidate_id: c for c in self.candidates}
        for snippet in self.snippets:
            if snippet.candidate_id not in ids:
                raise MaterializationError("Dangling snippet candidate.")
            if snippet.status is SnippetStatus.AVAILABLE:
                backing = backings.get(snippet.backing_id)
                candidate = by_id[snippet.candidate_id]
                if (backing is None or backing.snapshot != candidate.snapshot or backing.side != candidate.side
                        or snippet.source_range is None or snippet.source_range.file != backing.source_range.file
                        or type(snippet.start_offset) is not int or type(snippet.end_offset) is not int
                        or not 0 <= snippet.start_offset <= snippet.end_offset <= len(backing.text)):
                    raise MaterializationError("Invalid snippet backing scope or offsets.")
                if snippet.source_range not in candidate.source_ranges:
                    raise MaterializationError("Snippet range not observed by candidate.")
                from .snippets import _offset
                def relative(location: SourceLocation) -> SourceLocation:
                    return replace(location, line=location.line - backing.source_range.start.line + 1,
                        column=location.column - backing.source_range.start.column + 1
                        if location.line == backing.source_range.start.line else location.column)
                if (snippet.start_offset != _offset(backing.text, relative(snippet.source_range.start))
                        or snippet.end_offset != _offset(backing.text, relative(snippet.source_range.end))):
                    raise MaterializationError("Snippet offsets disagree with declared source range.")
            elif any(v is not None for v in (snippet.backing_id, snippet.start_offset, snippet.end_offset)):
                raise MaterializationError("Unavailable snippet cannot contain backing content.")

    def to_json(self) -> str:
        from .candidate_serialization import dumps
        return dumps(self)

    @classmethod
    def from_json(cls, text: str) -> ContextCandidateSet:
        from .candidate_serialization import loads
        return loads(text)


def walk(value: object, path: tuple[str, ...] = ()) -> Iterator[tuple[tuple[str, ...], object]]:
    yield path, value
    if is_dataclass(value) and not isinstance(value, type):
        for field in fields(value):
            yield from walk(getattr(value, field.name), (*path, field.name))
    elif isinstance(value, (tuple, frozenset)):
        sequence = sorted(value, key=canonical) if isinstance(value, frozenset) else value
        for index, item in enumerate(sequence):
            yield from walk(item, (*path, str(index)))


def _kind(value: Payload) -> ContextKind:
    if isinstance(value, NodeIdentity):
        return ContextKind.NODE
    if isinstance(value, (GraphEdge, DirectCallRelation)):
        return ContextKind.RELATION
    if isinstance(value, SourceRange):
        return ContextKind.RANGE
    if isinstance(value, RelationEvidence):
        return ContextKind.EVIDENCE
    if isinstance(value, _ASSOCIATIONS):
        return ContextKind.ASSOCIATION
    if isinstance(value, PropertyBinding):
        return ContextKind.BINDING
    if isinstance(value, RangeMapping):
        return ContextKind.CHANGE
    return ContextKind.FACT


def _key(value: Payload) -> object:
    return fact_key(value) if isinstance(value, _FACTS) else (type(value).__name__, value)


def _notes(value: object) -> tuple[str, ...]:
    notes = set()
    for path, item in walk(value):
        if isinstance(item, str) and any(p in {"gaps", "issues", "diagnostics", "limitations"} for p in path):
            notes.add(item)
        if isinstance(item, Enum) and path and path[-1] in {"status", "animation"}:
            notes.add(item.value)
    return tuple(sorted(notes))


class _Extractor:
    def __init__(self) -> None:
        self.records: dict[str, ContextCandidate] = {}

    def add(self, value: object, *, snapshot: SnapshotIdentity | None, side: EvidenceSide,
            repository: str, revision: str | None, origin: CandidateOrigin,
            hashes: tuple[FileHash, ...], limits: CandidateLimitations) -> tuple[str, ...]:
        selected: list[tuple[tuple[str, ...], Payload]] = []
        for path, item in walk(value):
            if isinstance(item, SymbolIdentity):
                selected.append((path, NodeIdentity.for_symbol(item)))
            elif isinstance(item, _RECORDS):
                selected.append((path, item))
        keys = [stable_id((snapshot, repository, revision, side, _key(item))) for _, item in selected]
        for (path, item), cid in zip(selected, keys):
            deps = tuple(sorted({key for (child, _), key in zip(selected, keys)
                                 if len(child) > len(path) and child[:len(path)] == path and key != cid}))
            paths = {v.file.path.as_posix() for _, v in walk(item) if isinstance(v, SourceRange)}
            relevant_hashes = tuple(h for h in hashes if h.path in paths)
            local_notes = _notes(item)
            local = CandidateLimitations(limits.ambiguous or any("ambiguous" in n for n in local_notes),
                                        limits.unresolved, limits.truncated,
                                        tuple(sorted(set(limits.notes + local_notes))))
            record = ContextCandidate(cid, _kind(item), repository, revision, snapshot, side, (item,),
                (replace(origin, observation_path=origin.observation_path + path),), relevant_hashes,
                tuple(sorted({v for _, v in walk(item) if isinstance(v, SourceRange)}, key=canonical)), deps, local)
            old = self.records.get(cid)
            if old is not None:
                def union(a: tuple, b: tuple) -> tuple:
                    return tuple(sorted(set(a + b), key=canonical))
                record = replace(record, observations=union(old.observations, record.observations),
                    origins=union(old.origins, record.origins), source_hashes=union(old.source_hashes, relevant_hashes),
                    source_ranges=union(old.source_ranges, record.source_ranges),
                    dependencies=union(old.dependencies, deps), limitations=CandidateLimitations(
                        old.limitations.ambiguous or local.ambiguous, old.limitations.unresolved or local.unresolved,
                        old.limitations.truncated or local.truncated, union(old.limitations.notes, local.notes)))
            self.records[cid] = record
        return tuple(sorted(set(keys)))

    def expansion(self, result: ExpansionResult) -> None:
        direct = result.upstream
        scope = direct.binding.snapshot.identity
        side = direct.request.side
        for candidate in direct.candidates:
            if candidate.snapshot != scope or candidate.side != side:
                raise MaterializationError("C1 candidate scope mismatch.")
            reports = tuple(r for r in direct.reports if candidate.candidate_id in r.candidate_ids)
            limits = CandidateLimitations(candidate.ambiguous, candidate.unresolved,
                direct.truncated or any(r.truncated for r in reports),
                tuple(sorted(set(direct.diagnostics + tuple(n for r in reports for n in r.diagnostics)))))
            self.add(candidate.observations, snapshot=scope, side=side, repository=scope.repository,
                revision=scope.revision, hashes=candidate.source_hashes, limits=limits,
                origin=CandidateOrigin("retrieval", candidate.candidate_id,
                    tuple(q.query_id for q in candidate.provenance), None, None, "direct retrieval", ()))
        for report in result.reports:
            if report.seed.seed.snapshot != scope or report.seed.seed.side != side:
                raise MaterializationError("D observation scope mismatch.")
            notes = report.diagnostics + (() if report.summary is None else report.summary.limitations)
            limits = CandidateLimitations(report.seed.ambiguous or (report.summary is not None
                and report.summary.p2_status == "ambiguous"), report.seed.unresolved,
                result.truncated, tuple(sorted(set(notes))))
            origin = CandidateOrigin("expansion", report.query_id, report.seed.query_ids,
                report.seed.seed.identity, None, "; ".join(report.seed.reasons), ())
            self.add(report.observation, snapshot=scope, side=side, repository=scope.repository,
                revision=scope.revision, hashes=report.source_hashes, limits=limits, origin=origin)
            # Distance belongs to this query/visit; trace architectural order is not distance.
            for path, item in walk(report.observation):
                if isinstance(item, NodeVisit):
                    self.add(item.node, snapshot=scope, side=side, repository=scope.repository,
                        revision=scope.revision, hashes=report.source_hashes, limits=limits,
                        origin=replace(origin, distance=item.depth, observation_path=(*path, "node")))


def materialize_context(upstream: ExpansionResult | ChangeExpansionResult, *,
                        target: SnapshotSession | None = None, base: SnapshotSession | None = None,
                        head: SnapshotSession | None = None,
                        bounds: SnippetBounds = SnippetBounds()) -> ContextCandidateSet:
    """Extract all accepted observations and materialize their bounded source ranges."""
    extractor = _Extractor()
    if isinstance(upstream, ExpansionResult):
        input_value = upstream.upstream.request.input
        if not isinstance(input_value, Task):
            raise MaterializationError("Change requires its full dual-side expansion envelope.")
        parts = (upstream,)
        sessions = {EvidenceSide.TARGET: target}
    elif isinstance(upstream, ChangeExpansionResult):
        input_value = upstream.upstream.mapping.change
        parts = tuple(p for p in (upstream.old, upstream.new) if p is not None)
        sessions = {EvidenceSide.OLD: base, EvidenceSide.NEW: head}
        for part, expected, side in ((upstream.old, upstream.upstream.old, EvidenceSide.OLD),
                                     (upstream.new, upstream.upstream.new, EvidenceSide.NEW)):
            if part is not None and (part.upstream != expected or part.upstream.request.side is not side):
                raise MaterializationError("Change side/envelope mismatch.")
        for mapping in upstream.upstream.mapping.ranges:
            side = EvidenceSide(mapping.anchor.side.value)
            revision = input_value.base_revision.value if side is EvidenceSide.OLD else input_value.head_revision.value
            snapshot = None if mapping.binding is None else mapping.binding.snapshot.identity
            if snapshot is not None and (snapshot.repository != input_value.repository or snapshot.revision != revision):
                raise MaterializationError("Change mapping binding mismatch.")
            extractor.add(mapping, snapshot=snapshot, side=side, repository=input_value.repository,
                revision=revision, hashes=() if mapping.binding is None else mapping.binding.snapshot.source.files,
                limits=CandidateLimitations(mapping.ambiguous, mapping.status.value != "mapped",
                    mapping.status.value == "truncated", tuple(d.reason.value for d in mapping.diagnostics)),
                origin=CandidateOrigin("change_mapping", stable_id(mapping.anchor), (), None, None,
                                       "declared changed range and C2 extent proofs", ()))
            anchor = mapping.anchor
            if anchor.path is not None and anchor.changed_range is not None:
                from arkui_agent.repository.model import RepositoryFile
                file = RepositoryFile.from_path(anchor.path)
                source_range = SourceRange(SourceLocation(file, anchor.changed_range.start_line, 1),
                                           SourceLocation(file, anchor.changed_range.end_line, 1))
                ids = extractor.add(source_range, snapshot=snapshot, side=side, repository=input_value.repository,
                    revision=revision, hashes=() if mapping.binding is None else mapping.binding.snapshot.source.files,
                    limits=CandidateLimitations(unresolved=mapping.status.value != "mapped"),
                    origin=CandidateOrigin("change_mapping", stable_id(anchor), (), None, None,
                                           "input range; source existence requires validation", ()))
                cid = stable_id((snapshot, input_value.repository, revision, side, _key(mapping)))
                record = extractor.records[cid]
                extractor.records[cid] = replace(record, dependencies=tuple(sorted(set(record.dependencies + ids))))
    else:
        raise MaterializationError("Expected typed P3-D observations.")
    for part in parts:
        if part.upstream.request.input != input_value:
            raise MaterializationError("Expansion input mismatch.")
        scope = part.upstream.binding.snapshot.identity
        side = part.upstream.request.side
        revision = (input_value.target_revision.value if isinstance(input_value, Task) else
                    input_value.base_revision.value if side is EvidenceSide.OLD else input_value.head_revision.value)
        if scope.repository != input_value.repository or scope.revision != revision:
            raise MaterializationError("Input repository/revision differs from observation binding.")
        extractor.expansion(part)
    candidates = tuple(sorted(extractor.records.values(), key=lambda c: c.candidate_id))
    # Identity records are explicit endpoint references, not fabricated P2 GraphNodes.
    evidence_by_node: dict[tuple, list[ContextCandidate]] = {}
    for candidate in candidates:
        for value in candidate.observations:
            if isinstance(value, (Symbol, GraphNode, TestCase, TestFixture)):
                identity = value.identity if isinstance(value, GraphNode) else NodeIdentity.for_symbol(value.identity)
                evidence_by_node.setdefault((candidate.snapshot, candidate.side, identity), []).append(candidate)
    for candidate in candidates:
        if candidate.kind is not ContextKind.NODE:
            continue
        facts = evidence_by_node.get((candidate.snapshot, candidate.side, candidate.observations[0]), ())
        ranges = tuple(sorted({r for fact in facts for r in fact.source_ranges}, key=canonical))
        # Link to ranges directly, avoiding a node <-> symbol-record dependency cycle.
        dependencies = tuple(sorted({stable_id((candidate.snapshot, candidate.repository, candidate.revision,
                                               candidate.side, _key(r))) for r in ranges}))
        notes = () if ranges else ("endpoint_source_unresolved" if facts else "endpoint_not_observed",)
        extractor.records[candidate.candidate_id] = replace(candidate, source_ranges=ranges,
            source_hashes=tuple(sorted({h for fact in facts for h in fact.source_hashes}, key=canonical)),
            dependencies=dependencies, limitations=replace(candidate.limitations,
                unresolved=candidate.limitations.unresolved or not ranges,
                notes=tuple(sorted(set(candidate.limitations.notes + notes)))))
    candidates = tuple(sorted(extractor.records.values(), key=lambda c: c.candidate_id))
    binding_set = {p.upstream.binding for p in parts}
    if isinstance(upstream, ChangeExpansionResult):
        binding_set.update(r.binding for r in upstream.upstream.mapping.ranges if r.binding is not None)
    bindings = tuple(sorted(binding_set, key=canonical))
    graph = TaskSubgraph(*(tuple(c.candidate_id for c in candidates if c.kind in kinds) for kinds in (
        {ContextKind.NODE}, {ContextKind.RELATION}, {ContextKind.ASSOCIATION}, {ContextKind.BINDING},
        {ContextKind.EVIDENCE, ContextKind.RANGE, ContextKind.FACT, ContextKind.CHANGE})))
    from .snippets import materialize_snippets
    snippets, backings = materialize_snippets(candidates, bindings, sessions, bounds)
    return ContextCandidateSet(input_value, stable_id(input_value), bindings, upstream,
                               candidates, graph, snippets, backings, bounds)
