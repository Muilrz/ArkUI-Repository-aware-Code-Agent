from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from arkui_agent.context import parse_task, parse_unified_diff
from arkui_agent.context.materialization import (
    ContextCandidateSet, ContextKind, MaterializationError, SnippetBounds, SnippetStatus, materialize_context,
)
from arkui_agent.graph.model import GraphEdge, NodeIdentity, RelationType
from arkui_agent.repository.model import SourceLocation, SourceRange, SymbolIdentity
from arkui_agent.retrieval.candidates import (
    Candidate, CandidateQuery, Channel, EvidenceSide, GraphSeed, NameSelector, QueryOrigin,
    RangeFact, RetrievalRequest, stable_id,
)
from arkui_agent.retrieval.change_mapping import ChangedRangeMapper
from arkui_agent.retrieval.expansion import ExpansionPolicy, GraphExpander, TraceFamily, TraceRequest
from arkui_agent.retrieval.service import CandidateRetriever
from tests.fixtures.candidate_retrieval import CandidateFixture
from tests.fixtures.change_mapping import DualRevisionFixture, REPOSITORY
from tests.fixtures.expansion import OverlayExpansionFixture
from tests.fixtures.overlay_cases import NS


class ContextMaterializationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.fixture = CandidateFixture(Path(temporary.name))
        self.session = self.fixture.reader.bind(self.fixture.requirement)
        self.addCleanup(self.session.close)
        self.task = parse_task("[symbol:Caller]", repository=self.fixture.requirement.repository,
                               target_revision=self.fixture.requirement.revision, source_id="E-task").value

    def expansion(self, *names, policy=ExpansionPolicy()):
        queries = tuple(CandidateQuery(Channel.SYMBOL, NameSelector(name),
                         (QueryOrigin(self.task.provenance, "explicit symbol"),)) for name in names)
        direct = CandidateRetriever().retrieve(RetrievalRequest(self.task, EvidenceSide.TARGET, queries), self.session)
        return GraphExpander(policy).expand(direct, self.session)

    def test_observed_subgraph_closure_roundtrip_and_no_extra_graph_queries(self):
        expansion = self.expansion("Caller", policy=ExpansionPolicy(max_depth=1))
        # The guarded session may validate artifacts; E must never expand the graph.
        with patch("arkui_agent.graph.memory.MemoryGraph.traverse", side_effect=AssertionError("new expansion")):
            result = materialize_context(expansion, target=self.session)
        ids = {c.candidate_id for c in result.candidates}
        for candidate in result.candidates:
            self.assertTrue(set(candidate.dependencies) <= ids)
        observed = {e.identity for report in expansion.reports if report.observation is not None
                    for e in report.observation.edges}
        actual = {e.identity for c in result.candidates for e in c.observations if isinstance(e, GraphEdge)}
        self.assertEqual(actual, observed)
        self.assertIn("not induced", result.subgraph.boundary)
        external = next(c for c in result.candidates if c.observations == (NodeIdentity("symbol", "external"),))
        self.assertTrue(any(s.candidate_id == external.candidate_id and s.status is SnippetStatus.RANGE_MISSING
                            for s in result.snippets))
        self.assertTrue(any(o.distance == 1 for c in result.candidates for o in c.origins))
        reports = {r.query_id: r for r in expansion.reports}
        direct = {c.candidate_id: c for c in expansion.upstream.candidates}
        for candidate in result.candidates:
            for origin in candidate.origins:
                value = (direct[origin.reference_id].observations if origin.channel == "retrieval"
                         else reports[origin.reference_id].observation)
                for segment in origin.observation_path:
                    value = value[int(segment)] if isinstance(value, tuple) else getattr(value, segment)
                if isinstance(value, SymbolIdentity):
                    value = NodeIdentity.for_symbol(value)
                self.assertIn(value, candidate.observations)
        self.assertEqual(result.upstream, expansion)
        restored = ContextCandidateSet.from_json(result.to_json())
        self.assertEqual(restored, result)
        self.assertEqual(restored.to_json(), result.to_json())
        self.assertEqual(materialize_context(expansion, target=self.session), result)

    def test_shared_endpoints_overload_ambiguity_and_truncation_survive(self):
        result = materialize_context(self.expansion("Caller", "Set"), target=self.session)
        nodes = [c.observations[0] for c in result.candidates if c.kind is ContextKind.NODE]
        self.assertEqual(nodes.count(NodeIdentity("symbol", "set:int")), 1)
        self.assertIn(NodeIdentity("symbol", "set:double"), nodes)
        self.assertTrue(any(c.limitations.ambiguous for c in result.candidates))
        cut = self.expansion("Caller", policy=ExpansionPolicy(max_queries=0))
        limited = materialize_context(cut, target=self.session)
        self.assertTrue(limited.upstream.truncated)
        self.assertEqual(limited.upstream.reports, cut.reports)
        self.assertIn(RelationType.INHERIT, limited.upstream.unavailable_relations)

    def with_range(self, expansion, source_range, *, hashes=None):
        direct = expansion.upstream
        candidate = direct.candidates[0]
        fact = RangeFact("text", source_range, matched_text="Caller")
        extra = Candidate(stable_id(fact), candidate.snapshot, candidate.side, (fact,), candidate.provenance,
                          candidate.source_hashes if hashes is None else hashes, False, False)
        return replace(expansion, upstream=replace(direct, candidates=(*direct.candidates, extra)))

    def test_overlapping_text_semantic_ranges_share_exact_backing(self):
        expansion = self.expansion("Caller")
        symbol = expansion.upstream.candidates[0].observations[0]
        r = symbol.definition
        token = SourceRange(replace(r.start, column=5), replace(r.start, column=11))
        result = materialize_context(self.with_range(expansion, token), target=self.session)
        source = next(s for s in result.snippets if s.source_range == r)
        match = next(s for s in result.snippets if s.source_range == token)
        self.assertEqual(source.backing_id, match.backing_id)
        backing = next(b for b in result.backings if b.backing_id == match.backing_id)
        self.assertEqual(backing.text[match.start_offset:match.end_offset], "Caller")
        text_fact = next(c for c in result.candidates if any(isinstance(v, RangeFact) for v in c.observations))
        self.assertIsNone(text_fact.observations[0].identity)
        limited = materialize_context(self.with_range(expansion, token), target=self.session,
                                      bounds=SnippetBounds(max_backing_characters=1))
        self.assertEqual(limited.candidates, result.candidates)
        self.assertTrue(any(s.status is SnippetStatus.LIMIT for s in limited.snippets))

    def test_wrong_range_hash_absent_source_and_mixed_scope_are_explicit(self):
        expansion = self.expansion("Caller")
        r = expansion.upstream.candidates[0].observations[0].definition
        bad = SourceRange(replace(r.start, line=999), replace(r.end, line=999))
        result = materialize_context(self.with_range(expansion, bad), target=self.session)
        self.assertEqual(next(s.status for s in result.snippets if s.source_range == bad), SnippetStatus.RANGE_INVALID)
        hashes = tuple(replace(h, sha256="0" * 64) for h in expansion.upstream.candidates[0].source_hashes)
        result = materialize_context(self.with_range(expansion, r, hashes=hashes), target=self.session)
        self.assertEqual(next(s.status for s in result.snippets if s.source_range == r), SnippetStatus.HASH_MISMATCH)
        absent = materialize_context(expansion)
        self.assertFalse(absent.backings)
        self.assertTrue(any(s.status is SnippetStatus.SOURCE_UNAVAILABLE for s in absent.snippets))
        c = expansion.upstream.candidates[0]
        mixed = replace(expansion, upstream=replace(expansion.upstream, candidates=(replace(c, side=EvidenceSide.OLD),)))
        with self.assertRaises(MaterializationError):
            materialize_context(mixed, target=self.session)

    def test_source_drift_before_read_and_at_exit_discards_all_backings(self):
        expansion = self.expansion("Caller")
        original = self.session.validate
        calls = 0

        def drift():
            nonlocal calls
            calls += 1
            if calls == 2:
                with (self.fixture.repo / "src/widget.cpp").open("a", encoding="utf-8") as stream:
                    stream.write("// drift\n")
            return original()

        with patch.object(self.session, "validate", side_effect=drift):
            result = materialize_context(expansion, target=self.session)
        self.assertFalse(result.backings)
        self.assertTrue(any(s.status is SnippetStatus.CONSISTENCY_FAILURE for s in result.snippets))
        self.assertEqual(result.upstream, expansion)
        again = materialize_context(expansion, target=self.session)
        self.assertFalse(again.backings)

    def test_file_io_limit_and_deleted_source_are_explicit(self):
        expansion = self.expansion("Caller")
        limited = materialize_context(expansion, target=self.session, bounds=SnippetBounds(max_file_bytes=1))
        self.assertFalse(limited.backings)
        self.assertTrue(any(s.status is SnippetStatus.LIMIT for s in limited.snippets))
        (self.fixture.repo / "src/widget.cpp").unlink()
        missing = materialize_context(expansion, target=self.session)
        self.assertFalse(missing.backings)
        self.assertTrue(any(s.status is SnippetStatus.CONSISTENCY_FAILURE for s in missing.snippets))
        self.assertTrue(any(s.diagnostics for s in missing.snippets if s.source_range is not None))

    def test_wire_rejects_unknown_version_fields_types_and_dangling_dependency(self):
        result = materialize_context(self.expansion("Caller"), target=self.session)
        for mutate in (
            lambda d: d.update(schema="v2"),
            lambda d: d["result"].update(extra=True),
            lambda d: d["result"]["candidates"][0].update(dependencies=["missing"]),
            lambda d: d["result"]["snippet_bounds"].update(max_file_bytes=True),
            lambda d: d["result"]["candidates"][0].update(type="UntrustedClass"),
        ):
            document = json.loads(result.to_json())
            mutate(document)
            with self.assertRaises(MaterializationError):
                ContextCandidateSet.from_json(json.dumps(document))


class ChangeContextMaterializationTests(unittest.TestCase):
    def test_change_revision_isolation_wrong_session_and_missing_base(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = DualRevisionFixture(Path(directory))
            with fixture.bind("base") as base, fixture.bind("head") as head:
                change = parse_unified_diff("--- old.cpp\n+++ new.cpp\n@@ -2 +2 @@\n-  int x = 1;\n+  int x = 1;\n",
                    repository=REPOSITORY, base_revision=fixture.base_revision,
                    head_revision=fixture.head_revision, source_id="E-rename").value
                retrieval = ChangedRangeMapper().retrieve(change, base=base, head=head, channels=(Channel.SYMBOL,))
                expansion = GraphExpander().expand_change(retrieval, base=base, head=head)
                result = materialize_context(expansion, base=base, head=head)
                self.assertEqual(ContextCandidateSet.from_json(result.to_json()), result)
                self.assertEqual({b.side for b in result.backings}, {EvidenceSide.OLD, EvidenceSide.NEW})
                wrong = materialize_context(expansion, base=head, head=head)
                old_ids = {c.candidate_id for c in wrong.candidates if c.side is EvidenceSide.OLD}
                self.assertTrue(any(s.candidate_id in old_ids and s.status is SnippetStatus.BINDING_MISMATCH
                                    for s in wrong.snippets))
                self.assertFalse(any(b.side is EvidenceSide.OLD for b in wrong.backings))
                missing = ChangedRangeMapper().retrieve(change, base=None, head=head, channels=(Channel.SYMBOL,))
                partial = materialize_context(GraphExpander().expand_change(missing, base=None, head=head), head=head)
                self.assertTrue(any(c.kind is ContextKind.CHANGE and c.side is EvidenceSide.OLD for c in partial.candidates))
                self.assertFalse(any(b.side is EvidenceSide.OLD for b in partial.backings))
                self.assertEqual(partial.input.raw_diff, change.raw_diff)

    def test_overlay_paths_bindings_and_animation_remain_independent(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = OverlayExpansionFixture(Path(directory))
            with fixture.reader.bind(fixture.requirement) as session:
                task = parse_task("overlay", repository=fixture.requirement.repository,
                                  target_revision=fixture.requirement.revision, source_id="E-overlay").value
                queries = tuple(CandidateQuery(Channel.SYMBOL, NameSelector(name),
                    (QueryOrigin(task.provenance, "explicit"),)) for name in ("Open", "Close", "OverlayManager"))
                direct = CandidateRetriever().retrieve(RetrievalRequest(task, EvidenceSide.TARGET, queries), session)
                request = TraceRequest(TraceFamily.OVERLAY, GraphSeed(NodeIdentity("symbol", NS + "Open"),
                    session.reference.snapshot.identity, EvidenceSide.TARGET), NodeIdentity("arkui.component", "menu"),
                    "explicit Menu API family", manager=NodeIdentity("symbol", NS + "OverlayManager"),
                    close_seeds=(NodeIdentity("symbol", NS + "Close"),))
                expansion = GraphExpander().expand(direct, session, traces=(request,))
                result = materialize_context(expansion, target=session)
                trace = next(r.observation for r in expansion.reports if r.trace_request is not None)
                self.assertEqual(len(trace.close.paths), 2)
                self.assertEqual(len(result.subgraph.associations), 3)
                self.assertTrue(any("ambiguous_paths" in c.limitations.notes for c in result.candidates))
                self.assertEqual(ContextCandidateSet.from_json(result.to_json()), result)
                self.assertTrue(all(s.status is SnippetStatus.AVAILABLE for s in result.snippets if s.source_range is not None))
