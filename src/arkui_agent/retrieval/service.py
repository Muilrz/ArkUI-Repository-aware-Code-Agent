"""Bounded candidate retrieval in one KnowledgeSnapshot read scope."""

from __future__ import annotations

from dataclasses import replace
from typing import Callable

from arkui_agent.context import Task
from arkui_agent.knowledge import BoundKnowledge, SnapshotSession
from .candidates import (
    Candidate, CandidateQuery, CandidateRetrievalResult, Channel, EvidenceSide, GraphSeed,
    QueryReport, RetrievalBounds, RetrievalRequest, RetrievalStatus, SymbolSeed, canonical,
    fact_key, stable_id,
)
from .channels import PublicChannelAdapter, fact_paths, fact_uncertainty


def _queries(queries: tuple[CandidateQuery, ...]) -> tuple[CandidateQuery, ...]:
    merged: dict[str, CandidateQuery] = {}
    for query in queries:
        previous = merged.get(query.query_id)
        origins = query.origins + (() if previous is None else previous.origins)
        unique = {canonical(origin): origin for origin in origins}
        merged[query.query_id] = replace(query, origins=tuple(unique[key] for key in sorted(unique)))
    return tuple(sorted(merged.values(), key=lambda q: canonical((q.channel, q.selector))))


AdapterFactory = Callable[[BoundKnowledge, RetrievalBounds], PublicChannelAdapter]


class CandidateRetriever:
    def __init__(self, *, bounds: RetrievalBounds = RetrievalBounds(),
                 adapter_factory: AdapterFactory = PublicChannelAdapter) -> None:
        self.bounds = bounds
        self.adapter_factory = adapter_factory

    def retrieve(self, request: RetrievalRequest, session: SnapshotSession) -> CandidateRetrievalResult:
        request = replace(request, queries=_queries(request.queries), diagnostics=tuple(sorted(set(request.diagnostics))))
        reference = session.reference
        snapshot = reference.snapshot.identity
        if isinstance(request.input, Task):
            revision = request.input.target_revision.value
        else:
            revision = (request.input.base_revision.value if request.side is EvidenceSide.OLD else request.input.head_revision.value)
        if request.input.repository != snapshot.repository or revision is None or revision != snapshot.revision:
            return CandidateRetrievalResult(reference, request, self.bounds, (), (),
                                             ("input_repository_revision_not_bound",))
        reports: list[QueryReport] = []
        candidates: dict[str, Candidate] = {}
        channel_ids: dict[Channel, set[str]] = {}
        diagnostics = list(request.diagnostics)
        truncated = len(request.queries) > self.bounds.max_queries
        if truncated:
            diagnostics.append(f"query_limit:omitted={len(request.queries) - self.bounds.max_queries}")
        # No retrieval result escapes until B's exit validation succeeds. Drift aborts the whole operation.
        with session.read() as view:
            adapter = self.adapter_factory(view, self.bounds)
            hashes = {item.path: item for item in reference.snapshot.source.files}
            for query in request.queries[:self.bounds.max_queries]:
                selector = query.selector
                if isinstance(selector, (SymbolSeed, GraphSeed)) and (selector.snapshot != snapshot or selector.side is not request.side):
                    reports.append(QueryReport(query, RetrievalStatus.UNRESOLVED, (), ("seed_snapshot_or_side_mismatch",), 0, 0,
                                               unresolved=True))
                    continue
                result = adapter.execute(query)
                retained: set[str] = set()
                channel_diagnostics = list(result.diagnostics)
                was_truncated = result.truncated
                admitted = channel_ids.setdefault(query.channel, set())
                for fact in result.facts:
                    candidate_id = stable_id((snapshot, request.side, fact_key(fact)))
                    if candidate_id not in admitted and len(admitted) >= self.bounds.max_candidates_per_channel:
                        was_truncated = True
                        channel_diagnostics.append("channel_candidate_limit")
                        continue
                    admitted.add(candidate_id)
                    retained.add(candidate_id)
                    existing = candidates.get(candidate_id)
                    observations = {canonical(f): f for f in (() if existing is None else existing.observations)}
                    observations[canonical(fact)] = fact
                    provenance = {q.query_id: q for q in (() if existing is None else existing.provenance)}
                    provenance[query.query_id] = query
                    source_hashes = {h.path: h for h in (() if existing is None else existing.source_hashes)}
                    source_hashes.update((path, hashes[path]) for path in fact_paths(fact))
                    ambiguous, unresolved = fact_uncertainty(fact)
                    candidates[candidate_id] = Candidate(
                        candidate_id, snapshot, request.side,
                        tuple(observations[key] for key in sorted(observations)),
                        tuple(provenance[key] for key in sorted(provenance)),
                        tuple(source_hashes[key] for key in sorted(source_hashes)),
                        result.ambiguous or ambiguous or (existing.ambiguous if existing else False),
                        unresolved or canonical(fact_key(fact)) in result.unresolved_fact_keys
                        or (existing.unresolved if existing else False),
                    )
                status = result.status
                if was_truncated and status is not RetrievalStatus.FAILURE:
                    status = RetrievalStatus.TRUNCATED
                reports.append(QueryReport(query, status, tuple(sorted(retained)), tuple(sorted(set(channel_diagnostics))),
                                           result.calls, result.observed, result.ambiguous, result.unresolved, was_truncated))
        selected = tuple(sorted(candidates))[:self.bounds.max_candidates]
        selected_set = set(selected)
        if len(candidates) > len(selected):
            truncated = True
            diagnostics.append(f"total_candidate_limit:omitted={len(candidates) - len(selected)}")
            reports = [replace(report, candidate_ids=tuple(i for i in report.candidate_ids if i in selected_set),
                               status=RetrievalStatus.TRUNCATED, truncated=True,
                               diagnostics=tuple(sorted(set(report.diagnostics + ("total_candidate_limit",)))))
                       if any(i not in selected_set for i in report.candidate_ids) else report for report in reports]
        return CandidateRetrievalResult(reference, request, self.bounds, tuple(candidates[i] for i in selected),
                                         tuple(reports), tuple(sorted(set(diagnostics))),
                                         truncated or any(report.truncated for report in reports))
