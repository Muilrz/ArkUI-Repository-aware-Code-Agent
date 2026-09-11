"""Bounded, guarded source reads for E; no repository writes or final selection."""

from __future__ import annotations

import hashlib
import re
from contextlib import ExitStack

from arkui_agent.knowledge import BindingReference, SnapshotReadError, SnapshotSession
from arkui_agent.graph.model import RelationEvidence
from arkui_agent.repository.model import SourceLocation, SourceRange
from arkui_agent.retrieval.candidates import EvidenceSide, stable_id
from .materialization import (
    CandidateSnippet, ContextCandidate, ContextKind, SnippetBacking, SnippetBounds,
    SnippetStatus, walk,
)


def _offset(text: str, location: SourceLocation) -> int:
    # P1 columns count Unicode code points; CRLF occupies two source characters.
    lines = text.splitlines(keepends=True)
    if location.line == len(lines) + 1 and location.column == 1:
        return len(text)
    if not 1 <= location.line <= len(lines):
        raise ValueError("Source line outside file.")
    line = lines[location.line - 1].rstrip("\r\n")
    if not 1 <= location.column <= len(line) + 1:
        raise ValueError("Source column outside line.")
    return sum(map(len, lines[:location.line - 1])) + location.column - 1


def materialize_snippets(candidates: tuple[ContextCandidate, ...], bindings: tuple[BindingReference, ...],
                         sessions: dict[EvidenceSide, SnapshotSession | None], bounds: SnippetBounds
                         ) -> tuple[tuple[CandidateSnippet, ...], tuple[SnippetBacking, ...]]:
    ranges = tuple(c for c in candidates if c.kind is ContextKind.RANGE)
    missing = tuple(CandidateSnippet(c.candidate_id, None, SnippetStatus.RANGE_MISSING,
                    diagnostics=("No observed source range; no name or line-number fallback.",))
                    for c in candidates if c.kind is not ContextKind.RANGE
                    and not c.source_ranges)
    references = {b.snapshot.identity: b for b in bindings}
    output: list[CandidateSnippet] = []
    backings: list[SnippetBacking] = []
    eligible: list[ContextCandidate] = []
    for candidate in ranges:
        session = sessions.get(candidate.side)
        status = (SnippetStatus.SOURCE_UNAVAILABLE if session is None or candidate.snapshot is None else
                  SnippetStatus.BINDING_MISMATCH if session.reference != references.get(candidate.snapshot) else None)
        if status is not None:
            output.append(CandidateSnippet(candidate.candidate_id, candidate.observations[0], status,
                                           diagnostics=("Original revision/generation session required.",)))
        else:
            eligible.append(candidate)
    pending: list[CandidateSnippet] = []
    try:
        # Both revision sides remain guarded until all output is prepared.
        with ExitStack() as stack:
            views = {side: stack.enter_context(sessions[side].read())
                     for side in sorted({c.side for c in eligible}, key=lambda side: side.value)}
            groups: dict[tuple, list[ContextCandidate]] = {}
            for candidate in eligible:
                source_range = candidate.observations[0]
                groups.setdefault((candidate.snapshot, candidate.side, source_range.file), []).append(candidate)
            for (snapshot, side, file), group in groups.items():
                source_hash = next((h.sha256 for h in references[snapshot].snapshot.source.files
                                    if h.path == file.path.as_posix()), None)
                failure = None
                reason = ""
                text = ""
                try:
                    with views[side].workspace.resolve(file.path).open("rb") as stream:
                        data = stream.read(bounds.max_file_bytes + 1)
                    if len(data) > bounds.max_file_bytes:
                        failure, reason = SnippetStatus.LIMIT, "max_file_bytes"
                    elif source_hash is None or hashlib.sha256(data).hexdigest() != source_hash:
                        failure, reason = SnippetStatus.HASH_MISMATCH, "Bound raw source hash missing or changed."
                    else:
                        text = data.decode("utf-8")
                except (OSError, UnicodeError, ValueError) as error:
                    failure, reason = SnippetStatus.SOURCE_UNAVAILABLE, str(error)
                # P2 framework evidence explicitly uses normalized-newline file hashes.
                normalized_hashes = {match.group(1) for candidate in candidates
                    if candidate.snapshot == snapshot and candidate.side == side
                    for _, value in walk(candidate.observations)
                    if isinstance(value, RelationEvidence)
                    and value.anchor.file == file
                    for match in re.finditer(r"normalized-newline source sha256=([0-9a-f]{64})", value.description)}
                normalized = text.replace("\r\n", "\n").replace("\r", "\n")
                if failure is None and normalized_hashes and normalized_hashes != {hashlib.sha256(normalized.encode()).hexdigest()}:
                    failure, reason = SnippetStatus.HASH_MISMATCH, "P2 normalized-newline evidence hash mismatch."
                intervals: list[tuple[int, int, ContextCandidate, SourceRange]] = []
                for candidate in group:
                    source_range = candidate.observations[0]
                    status, note = failure, reason
                    if status is None and ({h.sha256 for h in candidate.source_hashes if h.path == file.path.as_posix()} != {source_hash}):
                        status, note = SnippetStatus.HASH_MISMATCH, "Observation/source fingerprint disagreement."
                    if status is None:
                        try:
                            start, end = _offset(text, source_range.start), _offset(text, source_range.end)
                            intervals.append((start, end, candidate, source_range))
                        except ValueError as error:
                            status, note = SnippetStatus.RANGE_INVALID, str(error)
                    if status is not None:
                        pending.append(CandidateSnippet(candidate.candidate_id, source_range, status, diagnostics=(note,)))
                # Strictly overlapping intervals share backing; adjacent evidence stays separate.
                merged: list[list[tuple[int, int, ContextCandidate, SourceRange]]] = []
                for interval in sorted(intervals, key=lambda item: (item[0], item[1], item[2].candidate_id)):
                    if merged and interval[0] < max(item[1] for item in merged[-1]):
                        merged[-1].append(interval)
                    else:
                        merged.append([interval])
                for cluster in merged:
                    start, end = min(i[0] for i in cluster), max(i[1] for i in cluster)
                    if end - start > bounds.max_backing_characters:
                        pending.extend(CandidateSnippet(c.candidate_id, r, SnippetStatus.LIMIT,
                                       diagnostics=("max_backing_characters; entire overlap group deferred",))
                                       for _, _, c, r in cluster)
                        continue
                    left = min((i[3].start for i in cluster), key=lambda p: (p.line, p.column))
                    right = max((i[3].end for i in cluster), key=lambda p: (p.line, p.column))
                    source_range = SourceRange(left, right)
                    bid = stable_id((snapshot, side, source_range, source_hash))
                    backings.append(SnippetBacking(bid, snapshot, side, source_range, source_hash, text[start:end]))
                    pending.extend(CandidateSnippet(c.candidate_id, r, SnippetStatus.AVAILABLE,
                                   bid, a - start, b - start) for a, b, c, r in cluster)
    except SnapshotReadError as error:
        # Includes exit validation: never publish snippets from an invalid read scope.
        pending = [CandidateSnippet(c.candidate_id, c.observations[0], SnippetStatus.CONSISTENCY_FAILURE,
                   diagnostics=tuple(d.reason.value + ": " + d.detail for d in error.result.diagnostics)) for c in eligible]
        backings = []
    return (tuple(sorted((*missing, *output, *pending), key=lambda s: s.candidate_id)),
            tuple(sorted(backings, key=lambda b: b.backing_id)))
