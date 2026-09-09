"""C2: side-bound changed intervals to existing P1 symbol extents only."""
from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass, fields
from enum import Enum
from typing import Callable

from arkui_agent.context import Change, ChangeKind, LineKind, LineRange, Provenance, Side
from arkui_agent.knowledge import BindingReference, BoundKnowledge, SnapshotSession
from arkui_agent.repository.index import SymbolIndexError
from arkui_agent.repository.model import RepositoryFile, SourceRange, Symbol
from arkui_agent.repository.scanner import RepositoryFileType, classify_repository_path
from .candidates import (
    CandidateInputError, CandidateQuery, CandidateRetrievalResult, Channel, EvidenceSide,
    QueryOrigin, RetrievalRequest, SymbolSeed, canonical,
)
from .planning import SEED_CHANNELS
from .service import CandidateRetriever


class MappingStatus(str, Enum):
    MAPPED = "mapped"
    UNRESOLVED = "unresolved"
    UNSUPPORTED = "unsupported"
    NOT_APPLICABLE = "not_applicable"
    TRUNCATED = "truncated"
    FAILURE = "failure"


class MatchKind(str, Enum):
    ENCLOSING = "enclosing"
    INTERSECTING = "intersecting"
    POINT_INTERIOR = "point_interior"


class MappingReason(str, Enum):
    REVISION_ABSENT = "revision_absent"
    SESSION_ABSENT = "session_absent"
    BINDING_MISMATCH = "binding_repository_revision_mismatch"
    FILE_ABSENT = "file_absent_on_side"
    NO_EDIT_RANGE = "no_edit_range"
    SCOPE_INSUFFICIENT = "semantic_scope_insufficient"
    SOURCE_UNCOVERED = "source_not_fingerprinted"
    UNSUPPORTED = "language_or_backend_unsupported"
    NO_MATCH = "no_proven_symbol_extent"
    NO_ENCLOSING = "intersection_only_no_enclosing_extent"
    LIMIT = "mapping_limit"
    BACKEND_FAILURE = "public_backend_failure"
    INVALID_RANGE = "range_outside_bound_source"


@dataclass(frozen=True, slots=True)
class MappingDiagnostic:
    reason: MappingReason
    detail: str


@dataclass(frozen=True, slots=True)
class MappingBounds:
    max_ranges: int = 512
    max_files_per_side: int = 128
    max_symbols_per_file: int = 10000
    max_candidates_per_range: int = 128

    def __post_init__(self) -> None:
        if any(type(getattr(self, f.name)) is not int or getattr(self, f.name) < 1 for f in fields(self)):
            raise CandidateInputError("Mapping bounds must be positive integers.")


@dataclass(frozen=True, slots=True)
class ChangeRangeAnchor:
    file_index: int
    hunk_index: int | None
    block_index: int | None
    side: Side
    path: str | None
    change_kind: ChangeKind
    changed_range: LineRange | None
    file_provenance: Provenance
    hunk_provenance: Provenance | None


@dataclass(frozen=True, slots=True)
class ExtentMatch:
    field: str  # declaration or definition; retain both proofs when available
    extent: SourceRange
    relation: MatchKind


@dataclass(frozen=True, slots=True)
class MappedSymbol:
    seed: SymbolSeed
    evidence: tuple[ExtentMatch, ...]


@dataclass(frozen=True, slots=True)
class RangeMapping:
    anchor: ChangeRangeAnchor
    binding: BindingReference | None
    status: MappingStatus
    symbols: tuple[MappedSymbol, ...]
    diagnostics: tuple[MappingDiagnostic, ...]
    ambiguous: bool = False


@dataclass(frozen=True, slots=True)
class ChangeMappingResult:
    change: Change
    ranges: tuple[RangeMapping, ...]
    bounds: MappingBounds

    def request(self, side: Side, *, channels: tuple[Channel, ...] = SEED_CHANNELS) -> RetrievalRequest:
        if not isinstance(side, Side):
            raise CandidateInputError("C2 retrieval requires old/new side.")
        queries = []
        for item in self.ranges:
            if item.anchor.side is not side:
                continue
            anchor = item.anchor
            label = f"c2:file={anchor.file_index}:hunk={anchor.hunk_index}:block={anchor.block_index}:side={side.value}"
            origins = (QueryOrigin(anchor.file_provenance, label + ":file"),)
            if anchor.hunk_provenance is not None:
                origins += (QueryOrigin(anchor.hunk_provenance, label + ":hunk"),)
            for symbol in item.symbols:
                for channel in channels:
                    queries.append(CandidateQuery(channel, symbol.seed, origins))
        notes = tuple(sorted({"c2:" + d.reason.value for r in self.ranges if r.anchor.side is side for d in r.diagnostics}))
        if not queries:
            notes += ("c2:no_proven_symbol_seeds;retain_mapping_file_ranges",)
        return RetrievalRequest(self.change, EvidenceSide(side.value), tuple(queries), notes)

    def to_json(self) -> str:
        return canonical({"schema": "p3-c2-mapping-v1", "result": self})


@dataclass(frozen=True, slots=True)
class ChangeRetrievalResult:
    mapping: ChangeMappingResult  # unresolved file/range candidates always survive
    old: CandidateRetrievalResult | None
    new: CandidateRetrievalResult | None

    def to_json(self) -> str:
        return canonical({"schema": "p3-c2-retrieval-v1", "result": self})


def changed_anchors(change: Change) -> tuple[ChangeRangeAnchor, ...]:
    """Split edit blocks, not context lines; keep paired empty-side positions."""
    if not isinstance(change, Change):
        raise CandidateInputError("C2 needs a typed Change; rejected parse results have no file identities.")
    anchors = []
    for fi, file in enumerate(change.files):
        emitted = False
        for hi, hunk in enumerate(file.hunks):
            old, new = hunk.old_range.start_line, hunk.new_range.start_line
            start = None
            block = 0
            # Sentinel flushes the last run; newline markers never consume a line.
            for line in (*hunk.lines, None):
                if line is not None and line.kind is LineKind.NO_NEWLINE:
                    continue
                if line is None or line.kind is LineKind.CONTEXT:
                    if start is not None:
                        for side, path, first, end in ((Side.OLD, file.old_path, start[0], old),
                                                       (Side.NEW, file.new_path, start[1], new)):
                            anchors.append(ChangeRangeAnchor(fi, hi, block, side, path, file.kind,
                                                             LineRange(side, first, end), file.provenance, hunk.provenance))
                        block += 1
                        emitted = True
                        start = None
                    if line is not None:
                        old += 1
                        new += 1
                else:
                    if start is None:
                        start = (old, new)
                    old += line.kind is LineKind.DELETE
                    new += line.kind is LineKind.ADD
        if not emitted:
            for side, path in ((Side.OLD, file.old_path), (Side.NEW, file.new_path)):
                anchors.append(ChangeRangeAnchor(fi, None, None, side, path, file.kind, None, file.provenance, None))
    return tuple(anchors)


def extent_relation(changed: LineRange, extent: SourceRange) -> MatchKind | None:
    start, end = (changed.start_line, 1), (changed.end_line, 1)
    left, right = (extent.start.line, extent.start.column), (extent.end.line, extent.end.column)
    if left == right:
        return None
    if start == end:
        return MatchKind.POINT_INTERIOR if left < start < right else None
    if left <= start and end <= right:
        return MatchKind.ENCLOSING
    if max(start, left) < min(end, right):
        return MatchKind.INTERSECTING
    return None


class MappingUnsupportedError(RuntimeError):
    """An explicit adapter capability rejection, not an empty symbol result."""


class PublicSymbolRangeReader:
    def __init__(self, view: BoundKnowledge) -> None:
        self.view = view

    def read(self, file: RepositoryFile) -> tuple[Symbol, ...]:
        if classify_repository_path(file.path) is RepositoryFileType.OTHER:
            raise MappingUnsupportedError("No P1 C/C++ range provider for " + file.path.as_posix())
        return self.view.index.symbols_in_file(file)

    def source_lines(self, file: RepositoryFile) -> tuple[str, ...]:
        # Coordinate validation only: no identifiers or semantics extracted.
        return tuple(self.view.workspace.resolve(file.path).read_text(encoding="utf-8").splitlines())


class ChangedRangeMapper:
    def __init__(self, bounds: MappingBounds = MappingBounds(), *,
                 reader_factory: Callable[[BoundKnowledge], PublicSymbolRangeReader] = PublicSymbolRangeReader) -> None:
        self.bounds = bounds
        self.reader_factory = reader_factory

    def map(self, change: Change, *, base: SnapshotSession | None, head: SnapshotSession | None) -> ChangeMappingResult:
        anchors = changed_anchors(change)
        sessions = {Side.OLD: base, Side.NEW: head}
        revisions = {Side.OLD: change.base_revision.value, Side.NEW: change.head_revision.value}
        issues = {}
        readers = {}
        bindings = {}
        caches = {side: {} for side in Side}
        results = []
        with ExitStack() as stack:
            for side in Side:
                session, revision = sessions[side], revisions[side]
                if revision is None:
                    issues[side] = MappingDiagnostic(MappingReason.REVISION_ABSENT, side.value + " revision is absent; no fallback")
                elif session is None:
                    issues[side] = MappingDiagnostic(MappingReason.SESSION_ABSENT, side.value + " snapshot session is absent")
                elif (session.reference.snapshot.identity.repository, session.reference.snapshot.identity.revision) != (change.repository, revision):
                    issues[side] = MappingDiagnostic(MappingReason.BINDING_MISMATCH, side.value + " requires its own repository/revision")
                else:
                    view = stack.enter_context(session.read())
                    bindings[side] = view.reference
                    readers[side] = self.reader_factory(view)
            for ordinal, anchor in enumerate(anchors):
                side = anchor.side
                binding = bindings.get(side)
                diagnostics = []
                status = MappingStatus.UNRESOLVED
                matches = ()
                ambiguous = False
                if side in issues:
                    diagnostics.append(issues[side])
                if anchor.path is None:
                    status = MappingStatus.NOT_APPLICABLE
                    diagnostics.append(MappingDiagnostic(MappingReason.FILE_ABSENT, "This file does not exist on this side"))
                elif side not in issues:
                    if anchor.changed_range is None:
                        diagnostics.append(MappingDiagnostic(MappingReason.NO_EDIT_RANGE, "File metadata retained; no changed lines to map"))
                    elif ordinal >= self.bounds.max_ranges:
                        status = MappingStatus.TRUNCATED
                        diagnostics.append(MappingDiagnostic(MappingReason.LIMIT, "max_ranges"))
                    elif anchor.path not in binding.snapshot.scope.semantic_files:
                        diagnostics.append(MappingDiagnostic(MappingReason.SCOPE_INSUFFICIENT, anchor.path))
                    elif anchor.path not in {f.path for f in binding.snapshot.source.files}:
                        diagnostics.append(MappingDiagnostic(MappingReason.SOURCE_UNCOVERED, anchor.path))
                    else:
                        cache = caches[side]
                        if anchor.path not in cache and len(cache) >= self.bounds.max_files_per_side:
                            status = MappingStatus.TRUNCATED
                            diagnostics.append(MappingDiagnostic(MappingReason.LIMIT, "max_files_per_side"))
                        else:
                            if anchor.path not in cache:
                                try:
                                    file = RepositoryFile.from_path(anchor.path)
                                    cache[anchor.path] = (readers[side].read(file), readers[side].source_lines(file))
                                except (MappingUnsupportedError, SymbolIndexError, OSError, UnicodeError) as error:
                                    cache[anchor.path] = error
                            found = cache[anchor.path]
                            if isinstance(found, MappingUnsupportedError):
                                status = MappingStatus.UNSUPPORTED
                                diagnostics.append(MappingDiagnostic(MappingReason.UNSUPPORTED, str(found)))
                            elif isinstance(found, (SymbolIndexError, OSError, UnicodeError)):
                                status = MappingStatus.FAILURE
                                diagnostics.append(MappingDiagnostic(MappingReason.BACKEND_FAILURE, str(found)))
                            else:
                                matches, status, ambiguous, notes = self._match(anchor, found[0], binding, found[1])
                                diagnostics.extend(notes)
                results.append(RangeMapping(anchor, binding, status, matches, tuple(diagnostics), ambiguous))
        # No result escapes until BOTH side read guards have validated on exit.
        return ChangeMappingResult(change, tuple(results), self.bounds)

    def _match(self, anchor: ChangeRangeAnchor, found: tuple[Symbol, ...], binding: BindingReference,
               lines: tuple[str, ...]) -> tuple[tuple[MappedSymbol, ...], MappingStatus, bool, list[MappingDiagnostic]]:
        notes = []

        def valid_position(line, column):
            return (line == len(lines) + 1 and column == 1
                    or 1 <= line <= len(lines) and 1 <= column <= len(lines[line - 1]) + 1)

        changed = anchor.changed_range
        if not valid_position(changed.start_line, 1) or not valid_position(changed.end_line, 1):
            return (), MappingStatus.UNRESOLVED, False, [MappingDiagnostic(MappingReason.INVALID_RANGE, "Changed range exceeds bound source lines")]
        ordered = sorted(found, key=lambda s: s.identity.value)
        truncated = len(ordered) > self.bounds.max_symbols_per_file
        if truncated:
            notes.append(MappingDiagnostic(MappingReason.LIMIT, "max_symbols_per_file"))
        by_identity = {}
        for symbol in ordered[:self.bounds.max_symbols_per_file]:
            proofs = []
            for field in ("declaration", "definition"):
                extent = getattr(symbol, field)
                if extent is not None and extent.file.path.as_posix() == anchor.path:
                    if not (valid_position(extent.start.line, extent.start.column) and valid_position(extent.end.line, extent.end.column)):
                        notes.append(MappingDiagnostic(MappingReason.INVALID_RANGE, "Stored " + field + " extent exceeds bound source: " + symbol.identity.value))
                        continue
                    relation = extent_relation(anchor.changed_range, extent)
                    if relation is not None:
                        proofs.append(ExtentMatch(field, extent, relation))
            if proofs:
                by_identity[symbol.identity] = MappedSymbol(SymbolSeed(symbol.identity, binding.snapshot.identity,
                                                                       EvidenceSide(anchor.side.value)), tuple(proofs))
        matches = tuple(by_identity.values())
        ambiguous = len(matches) > 1
        if len(matches) > self.bounds.max_candidates_per_range:
            truncated = True
            notes.append(MappingDiagnostic(MappingReason.LIMIT, "max_candidates_per_range"))
        if not matches:
            notes.append(MappingDiagnostic(MappingReason.NO_MATCH, "No stored extent proves intersection; no name/text inference"))
        elif not any(p.relation is not MatchKind.INTERSECTING for m in matches for p in m.evidence):
            notes.append(MappingDiagnostic(MappingReason.NO_ENCLOSING, "Only stored extent intersections are proven, not function-body containment"))
        status = MappingStatus.TRUNCATED if truncated else MappingStatus.MAPPED if matches else MappingStatus.UNRESOLVED
        return matches[:self.bounds.max_candidates_per_range], status, ambiguous, notes

    def retrieve(self, change: Change, *, base: SnapshotSession | None, head: SnapshotSession | None,
                 retriever: CandidateRetriever | None = None, channels: tuple[Channel, ...] = SEED_CHANNELS) -> ChangeRetrievalResult:
        mapping = self.map(change, base=base, head=head)
        service = retriever if retriever is not None else CandidateRetriever()
        outputs = {}
        with ExitStack() as stack:
            usable = {}
            for side, session in ((Side.OLD, base), (Side.NEW, head)):
                if session is not None and any(r.anchor.side is side and r.binding is not None for r in mapping.ranges):
                    stack.enter_context(session.read())
                    usable[side] = session
            for side, session in usable.items():
                outputs[side] = service.retrieve(mapping.request(side, channels=channels), session)
        return ChangeRetrievalResult(mapping, outputs.get(Side.OLD), outputs.get(Side.NEW))
