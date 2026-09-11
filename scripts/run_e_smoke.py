"""Explicit P3-E selected-source audit; emits observations, never new frozen gold."""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PROJECT / "src"), str(PROJECT)]

from scripts.run_d_smoke import REPOSITORY, REVISION, bind, requests, source_checks, original_trace, walk
from scripts.run_c1_smoke import now, write, sha
from arkui_agent.context import parse_task
from arkui_agent.context.materialization import ContextCandidateSet, ContextKind, SnippetBounds, SnippetStatus, materialize_context
from arkui_agent.graph.creation import CreationPath, PatternArgument
from arkui_agent.graph.layout import LayoutDependency
from arkui_agent.graph.model import GraphEdge, GraphNode, NodeIdentity, RelationEvidence, RelationType
from arkui_agent.graph.overlay import OverlayPath
from arkui_agent.graph.property import PropertyBinding, PropertyPath
from arkui_agent.knowledge import GitSourceReader
from arkui_agent.repository.model import SourceRange, SymbolIdentity
from arkui_agent.retrieval.candidates import CandidateQuery, Channel, EvidenceSide, NameSelector, QueryOrigin, RetrievalRequest, SymbolSeed, canonical
from arkui_agent.retrieval.expansion import ExpansionPolicy, GraphExpander
from arkui_agent.retrieval.service import CandidateRetriever


def slice_source(text, source_range):
    """Independent line-slicing oracle; preserves original newline characters."""
    lines = text.splitlines(keepends=True)
    start, end = source_range.start, source_range.end
    if start.line == end.line:
        return "" if start.line == len(lines) + 1 else lines[start.line - 1][start.column - 1:end.column - 1]
    last = "" if end.line == len(lines) + 1 else lines[end.line - 1][:end.column - 1]
    return lines[start.line - 1][start.column - 1:] + "".join(lines[start.line:end.line - 1]) + last


def audit(result, expansion, view):
    observed = tuple(v for c in expansion.upstream.candidates for v in c.observations) + tuple(
        r.observation for r in expansion.reports if r.observation is not None)
    items = tuple(walk(observed))
    candidates = {c.candidate_id: c for c in result.candidates}
    payloads = tuple(v for c in result.candidates for v in c.observations)
    graph = {e.identity: e for e in view.graph.edges}
    checks = {}
    checks["upstream_and_input_preserved"] = result.upstream == expansion and result.input == expansion.upstream.request.input
    checks["typed_facts_preserved"] = all(v in payloads for v in items if isinstance(v, (
        GraphEdge, GraphNode, RelationEvidence, SourceRange, PatternArgument, LayoutDependency,
        PropertyBinding, CreationPath, PropertyPath, OverlayPath)))
    actual_edges = {v for v in payloads if isinstance(v, GraphEdge)}
    checks["relations_exactly_observed"] = actual_edges == {v for v in items if isinstance(v, GraphEdge)}
    checks["relations_from_bound_graph"] = all(e.identity in graph and set(e.evidence) <= set(graph[e.identity].evidence)
                                               for e in actual_edges)
    nodes = {c.observations[0]: c for c in result.candidates if c.kind is ContextKind.NODE}
    checks["endpoint_dependency_closure"] = all(all(n in nodes and nodes[n].candidate_id in c.dependencies
        for n in (e.identity.source, e.identity.target)) for c in result.candidates for e in c.observations if isinstance(e, GraphEdge))
    checks["all_dependency_ids_resolve"] = all(set(c.dependencies) <= candidates.keys() for c in result.candidates)
    checks["snapshot_side_scope"] = all(c.snapshot == view.reference.snapshot.identity and c.side is EvidenceSide.TARGET
                                       and c.repository == REPOSITORY and c.revision == REVISION for c in result.candidates)
    direct = {c.candidate_id: c for c in expansion.upstream.candidates}
    reports = {r.query_id: r for r in expansion.reports}
    provenance_errors = []
    for c in result.candidates:
        for origin in c.origins:
            source = direct.get(origin.reference_id) if origin.channel == "retrieval" else reports.get(origin.reference_id)
            if source is None:
                provenance_errors.append((c.candidate_id, "missing origin"))
                continue
            value = source.observations if origin.channel == "retrieval" else source.observation
            for segment in origin.observation_path:
                value = value[int(segment)] if isinstance(value, tuple) else getattr(value, segment)
            if isinstance(value, SymbolIdentity):
                value = NodeIdentity.for_symbol(value)
            if value not in c.observations:
                provenance_errors.append((c.candidate_id, "wrong observation path"))
            if origin.channel == "retrieval":
                if set(origin.query_ids) != {q.query_id for q in source.provenance}:
                    provenance_errors.append((c.candidate_id, "query mismatch"))
            elif origin.seed != source.seed.seed.identity or origin.query_ids != source.seed.query_ids:
                provenance_errors.append((c.candidate_id, "seed mismatch"))
    checks["origin_paths_queries_seeds_resolve"] = not provenance_errors
    checks["unsupported_preserved"] = set(result.upstream.unavailable_relations) == {
        RelationType.INHERIT, RelationType.OVERRIDE, RelationType.MOCK}
    restored = ContextCandidateSet.from_json(result.to_json())
    checks["typed_roundtrip"] = restored == result and restored.to_json() == result.to_json()
    files = {}
    for h in view.reference.snapshot.source.files:
        data = view.workspace.resolve(h.path).read_bytes()
        files[h.path] = (data.decode("utf-8"), hashlib.sha256(data).hexdigest())
    backings = {b.backing_id: b for b in result.backings}
    checks["backing_source_range_hash"] = all(b.text == slice_source(files[b.source_range.file.path.as_posix()][0], b.source_range)
        and b.source_sha256 == files[b.source_range.file.path.as_posix()][1]
        and b.snapshot == view.reference.snapshot.identity and b.side is EvidenceSide.TARGET for b in result.backings)
    checks["every_observed_range_available"] = all(s.status is SnippetStatus.AVAILABLE for s in result.snippets if s.source_range is not None)
    checks["every_candidate_hash_matches_source"] = all(files[h.path][1] == h.sha256 for c in result.candidates for h in c.source_hashes)
    checks["exact_snippet_slice"] = all(slice_source(files[s.source_range.file.path.as_posix()][0], s.source_range) ==
        backings[s.backing_id].text[s.start_offset:s.end_offset] for s in result.snippets if s.status is SnippetStatus.AVAILABLE)
    normalized = []
    for v in payloads:
        if isinstance(v, RelationEvidence) and "normalized-newline source sha256=" in v.description:
            expected = v.description.split("normalized-newline source sha256=", 1)[1][:64]
            text = files[v.anchor.file.path.as_posix()][0].replace("\r\n", "\n").replace("\r", "\n")
            normalized.append(hashlib.sha256(text.encode()).hexdigest() == expected)
    checks["p2_normalized_hashes"] = all(normalized)
    snippets = [s for s in result.snippets if s.status is SnippetStatus.AVAILABLE]
    overlap_pairs = 0
    overlap_ok = True
    for i, a in enumerate(snippets):
        for b in snippets[i + 1:]:
            ar, br = a.source_range, b.source_range
            if ar.file == br.file and max((ar.start.line, ar.start.column), (br.start.line, br.start.column)) < min(
                    (ar.end.line, ar.end.column), (br.end.line, br.end.column)):
                overlap_pairs += 1
                overlap_ok &= a.backing_id == b.backing_id
    checks["overlap_shares_backing"] = overlap_ok
    # Non-available states have no content; known source gaps are not fake snippets.
    checks["missing_range_explicit"] = all(any(s.candidate_id == c.candidate_id and s.status is SnippetStatus.RANGE_MISSING
        for s in result.snippets) for c in result.candidates if not c.source_ranges)
    details = dict(kind_counts=dict(Counter(c.kind.value for c in result.candidates)),
        relation_types=dict(Counter(e.identity.relation.value for e in actual_edges)),
        snippet_statuses=dict(Counter(s.status.value for s in result.snippets)), backings=len(backings),
        shared_backings=sum(count > 1 for count in Counter(s.backing_id for s in snippets).values()),
        overlapping_range_pairs=overlap_pairs, normalized_evidence_hashes=len(normalized),
        ambiguous_candidates=sum(c.limitations.ambiguous for c in result.candidates),
        unresolved_candidates=sum(c.limitations.unresolved for c in result.candidates),
        provenance_errors=provenance_errors,
        source_unresolved_nodes=[n.value for n, c in nodes.items() if c.limitations.unresolved],
        sample_snippets=[dict(candidate_id=s.candidate_id, range=json.loads(canonical(s.source_range)),
            backing=s.backing_id, file_sha256=backings[s.backing_id].source_sha256,
            text=backings[s.backing_id].text[s.start_offset:s.end_offset]) for s in snippets[:3]])
    return checks, details


def query(source, family, artifacts, output):
    source_observations = source_checks(source, family)
    report = dict(schema="p3-e-smoke-observations-v1", family=family, started=now(),
                  gold_status="proposed-not-human-frozen", source_observations=source_observations,
                  manifest_sha256=sha(artifacts / "manifest.json"), cases=[])
    allowed = {"creation": {"creation-button"}, "property": {"property-button-native", "property-button-stack"},
               "layout": {"layout-menu"}, "overlay": {"overlay-menu"}}[family]
    with bind(source, artifacts) as session:
        report["snapshot"] = json.loads(canonical(session.reference))
        with session.read() as view:
            planned = [(name, r) for name, r in requests(view, family) if name in allowed]
        if {name for name, _ in planned} != allowed:
            raise ValueError("Required source-anchored cases missing")
        for name, request in planned:
            print("E query: " + name, flush=True)
            task = parse_task(name, repository=REPOSITORY, target_revision=REVISION, source_id="D-smoke:" + name).value
            ids = {request.seed.identity, *request.close_seeds} | {n for n in (request.setter, request.manager) if n is not None}
            queries = tuple(CandidateQuery(Channel.SYMBOL, SymbolSeed(SymbolIdentity(n.key), request.seed.snapshot, EvidenceSide.TARGET),
                (QueryOrigin(task.provenance, "source-anchored-trace-parameter"),)) for n in sorted(ids))
            direct = CandidateRetriever().retrieve(RetrievalRequest(task, EvidenceSide.TARGET, queries), session)
            expansion = GraphExpander().expand(direct, session, traces=(request,))
            result = materialize_context(expansion, target=session)
            trace = next(r for r in expansion.reports if r.trace_request == request)
            with session.read() as view:
                checks, details = audit(result, expansion, view)
                checks["original_p2_trace_preserved"] = trace.observation == original_trace(view, request)
            # Bounded-source limit is not final candidate selection.
            limited = materialize_context(expansion, target=session, bounds=SnippetBounds(max_backing_characters=1))
            checks["source_limit_preserves_candidates"] = limited.candidates == result.candidates and limited.subgraph == result.subgraph
            checks["source_limit_explicit"] = any(s.status is SnippetStatus.LIMIT for s in limited.snippets)
            cut = GraphExpander(ExpansionPolicy(max_nodes=1)).expand(direct, session, traces=(request,))
            cut_result = materialize_context(cut, target=session)
            checks["expansion_cut_preserved"] = cut.truncated and cut_result.upstream == cut
            cut_trace = next(r for r in cut.reports if r.trace_request == request)
            checks["cut_negative_summary_preserved"] = cut_trace.summary == trace.summary
            supplement = None
            if family == "creation":
                text_query = CandidateQuery(Channel.TEXT, NameSelector("ButtonModelNG::CreateFrameNode"),
                                           (QueryOrigin(task.provenance, "E explicit text evidence"),))
                text_direct = CandidateRetriever().retrieve(RetrievalRequest(task, EvidenceSide.TARGET, queries + (text_query,)), session)
                text_expansion = GraphExpander().expand(text_direct, session, traces=(request,))
                text_result = materialize_context(text_expansion, target=session)
                with session.read() as view:
                    text_checks, text_details = audit(text_result, text_expansion, view)
                from arkui_agent.retrieval.candidates import RangeFact
                matches = [v for c in text_result.candidates for v in c.observations if isinstance(v, RangeFact)]
                text_checks["text_has_no_symbol_identity"] = bool(matches) and all(v.identity is None for v in matches)
                checks["supplemental_text_audit"] = all(text_checks.values())
                supplement = dict(checks=text_checks, details=text_details, actual=json.loads(text_result.to_json()))
            item = dict(case=name, checks=checks, details=details, p2_summary=json.loads(canonical(trace.summary)),
                source_limit_statuses=dict(Counter(s.status.value for s in limited.snippets)),
                cut_summary=json.loads(canonical(cut_trace.summary)), cut_diagnostics=cut_trace.diagnostics,
                supplemental_text=supplement, actual=json.loads(result.to_json()), passed=all(checks.values()))
            report["cases"].append(item)
            print(json.dumps({k: item[k] for k in ("case", "checks", "details", "p2_summary", "passed")}), flush=True)
    report["finished"] = now()
    report["passed"] = all(item["passed"] for item in report["cases"])
    output.parent.mkdir(parents=True, exist_ok=True)
    write(output, report)
    return report["passed"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--family", required=True, choices=("creation", "property", "layout", "overlay"))
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Refusing to overwrite an existing observation report")
    sys.exit(0 if query(GitSourceReader(args.repository_root, repository=REPOSITORY), args.family,
                       args.artifacts.resolve(), args.output.resolve()) else 1)
