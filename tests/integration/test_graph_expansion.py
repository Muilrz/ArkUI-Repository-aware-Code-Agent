from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from arkui_agent.context import parse_task, parse_unified_diff
from arkui_agent.graph.creation import CreationBounds, trace_component_creation
from arkui_agent.graph.layout import LayoutBounds, trace_measure_layout
from arkui_agent.graph.memory import MemoryGraph
from arkui_agent.graph.model import NodeIdentity, RelationType
from arkui_agent.graph.overlay import OverlayBounds, trace_overlay
from arkui_agent.graph.property import PropertyBounds, trace_property_update
from arkui_agent.graph.query import Direction, GraphQueryError, TraversalResult
from arkui_agent.knowledge import SnapshotReadError
from arkui_agent.retrieval.candidates import (
    CandidateInputError, CandidateQuery, Channel, EvidenceSide, GraphSeed, NameSelector,
    QueryOrigin, RetrievalRequest,
)
from arkui_agent.retrieval.change_mapping import ChangedRangeMapper
from arkui_agent.retrieval.expansion import ExpansionPolicy, GraphExpander, TraceFamily, TraceRequest
from arkui_agent.retrieval.service import CandidateRetriever
from tests.fixtures.candidate_retrieval import CandidateFixture
from tests.fixtures.change_mapping import DualRevisionFixture, REPOSITORY
from tests.fixtures.expansion import OverlayExpansionFixture
from tests.fixtures.overlay_cases import NS


class GraphExpansionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.fixture = CandidateFixture(Path(temporary.name))
        self.session = self.fixture.reader.bind(self.fixture.requirement)
        self.addCleanup(self.session.close)
        self.task = parse_task("[symbol:Caller]", repository=self.fixture.requirement.repository,
                               target_revision=self.fixture.requirement.revision, source_id="expansion-task").value

    def retrieve(self, *names, task=None):
        task = task or self.task
        queries = tuple(CandidateQuery(Channel.SYMBOL, NameSelector(name),
                                       (QueryOrigin(task.provenance, "explicit-symbol"),)) for name in names)
        return CandidateRetriever().retrieve(RetrievalRequest(task, EvidenceSide.TARGET, queries), self.session)

    def trace_request(self, family, seed="caller", **kwargs):
        return TraceRequest(family, GraphSeed(NodeIdentity("symbol", seed),
                            self.session.reference.snapshot.identity, EvidenceSide.TARGET),
                            NodeIdentity("arkui.component", "widget"), "explicit test intent", **kwargs)

    def test_task_direct_call_expansion_retains_dangling_source_and_real_evidence(self):
        direct = self.retrieve("Caller")
        result = GraphExpander().expand(direct, self.session)
        report = result.reports[0]
        self.assertIsInstance(report.observation, TraversalResult)
        self.assertEqual({e.identity.target.key for e in report.observation.edges}, {"external", "set:int"})
        self.assertIn("unresolved_node_source", report.diagnostics)
        self.assertEqual(result.upstream, direct)
        self.assertTrue(report.source_hashes)
        self.assertEqual(report.seed.candidate_ids, (direct.candidates[0].candidate_id,))
        with self.session.read() as view:
            self.assertTrue(set(report.observation.edges).issubset(view.graph.edges))

    def test_multi_seed_convergence_deduplicates_counts_and_preserves_all_origins(self):
        direct = self.retrieve("Caller", "Set")
        result = GraphExpander(ExpansionPolicy(task_direction=Direction.BOTH,
            relations=frozenset({RelationType.CALL}))).expand(direct, self.session)
        self.assertEqual(result.node_count, 4)
        self.assertEqual(result.edge_count, 2)
        self.assertEqual(len(result.seeds), 3)
        self.assertEqual(sum(s.ambiguous for s in result.seeds), 2)
        self.assertEqual(result.to_json(), GraphExpander(result.policy).expand(
            self.retrieve("Set", "Caller"), self.session).to_json())

    def test_exact_and_exceeded_node_edge_query_limits_are_distinct(self):
        direct = self.retrieve("Caller")
        exact = GraphExpander(ExpansionPolicy(max_nodes=3, max_edges=2, max_queries=1)).expand(direct, self.session)
        self.assertFalse(exact.truncated)
        for policy, reason in ((ExpansionPolicy(max_nodes=2), "global_node_limit"),
                               (ExpansionPolicy(max_edges=1), "global_edge_limit"),
                               (ExpansionPolicy(max_queries=0), "global_query_limit")):
            with self.subTest(reason=reason):
                result = GraphExpander(policy).expand(direct, self.session)
                self.assertTrue(result.truncated)
                self.assertIn(reason, result.reports[0].diagnostics)
                self.assertIsNone(result.reports[0].observation)
        per_seed = GraphExpander(ExpansionPolicy(max_nodes_per_seed=2)).expand(direct, self.session)
        self.assertTrue(per_seed.truncated)
        self.assertEqual(per_seed.node_count, 2)

    def test_depth_boundary_and_unsupported_relations_remain_explicit(self):
        policy = ExpansionPolicy(max_depth=0, relations=frozenset({RelationType.INHERIT, RelationType.MOCK}))
        result = GraphExpander(policy).expand(self.retrieve("Caller"), self.session)
        self.assertEqual(result.node_count, 1)
        self.assertEqual(result.edge_count, 0)
        self.assertIn("unsupported_relation:INHERIT", result.reports[0].diagnostics)
        self.assertIn(RelationType.OVERRIDE, result.unavailable_relations)
        self.assertIn("depth_scope:0", result.reports[0].diagnostics)

    def test_all_four_public_traces_keep_the_original_partial_result(self):
        direct = self.retrieve("Caller", "Set", "Widget")
        requests = (
            self.trace_request(TraceFamily.CREATION),
            self.trace_request(TraceFamily.PROPERTY, setter=NodeIdentity("symbol", "set:int")),
            self.trace_request(TraceFamily.LAYOUT, seed="widget"),
            self.trace_request(TraceFamily.OVERLAY, manager=NodeIdentity("symbol", "widget"),
                               close_seeds=(NodeIdentity("symbol", "set:int"), NodeIdentity("symbol", "set:double"))),
        )
        # These intentionally lack ArkUI stages: compare real P2 queries, not canned traces.
        with self.session.read() as view:
            args = (view.index, view.graph, view.domain, view.workspace)
            component = requests[0].component
            expected = {
                TraceFamily.CREATION: trace_component_creation(*args, seed=requests[0].seed.identity,
                    component=component, bounds=CreationBounds(2, 32, 1000)),
                TraceFamily.PROPERTY: trace_property_update(*args, seed=requests[1].seed.identity,
                    setter=requests[1].setter, component=component, bounds=PropertyBounds(2, 32, 1000)),
                TraceFamily.LAYOUT: trace_measure_layout(*args, seed=requests[2].seed.identity,
                    component=component, bounds=LayoutBounds(32, 200)),
                TraceFamily.OVERLAY: trace_overlay(*args, show_seed=requests[3].seed.identity,
                    manager=requests[3].manager, close_seeds=requests[3].close_seeds,
                    component=component, bounds=OverlayBounds(2, 32, 1000)),
            }
        result = GraphExpander().expand(direct, self.session, traces=requests)
        reports = [r for r in result.reports if r.trace_request is not None]
        self.assertEqual(len(reports), 4)
        for report in reports:
            self.assertEqual(report.observation, expected[report.trace_request.family])
            self.assertEqual(report.summary.p2_status, report.observation.status.value)
            self.assertNotEqual(report.summary.p2_status, "complete")
        self.assertEqual(result.to_json(), GraphExpander().expand(direct, self.session, traces=tuple(reversed(requests))).to_json())

    def test_automatic_layout_uses_role_evidence_and_trace_limit_preserves_summary(self):
        task = parse_task("[symbol:Widget] [action:layout]", repository=self.task.repository,
                          target_revision=self.task.target_revision.value, source_id="layout-task").value
        direct = self.retrieve("Widget", task=task)
        result = GraphExpander().expand(direct, self.session)
        self.assertEqual(len(result.reports), 2)
        trace = result.reports[1]
        self.assertEqual(trace.trace_request.family, TraceFamily.LAYOUT)
        self.assertTrue(trace.summary.limitations)
        limited = GraphExpander(ExpansionPolicy(max_nodes=1)).expand(direct, self.session)
        self.assertIsNone(limited.reports[1].observation)
        self.assertEqual(limited.reports[1].summary, trace.summary)
        self.assertTrue(limited.truncated)

    def test_missing_explicit_parameters_and_wrong_side_are_not_guessed(self):
        direct = self.retrieve("Caller")
        request = self.trace_request(TraceFamily.PROPERTY, setter=NodeIdentity("symbol", "missing"))
        result = GraphExpander().expand(direct, self.session, traces=(request,))
        self.assertEqual(result.reports[-1].status, "unresolved")
        self.assertIsNone(result.reports[-1].observation)
        with self.assertRaises(CandidateInputError):
            GraphExpander().expand(direct, self.session, traces=(replace(request, seed=replace(request.seed, side=EvidenceSide.OLD)),))

    def test_backend_failure_and_source_drift_do_not_become_empty_success(self):
        direct = self.retrieve("Caller")
        with patch.object(MemoryGraph, "traverse", side_effect=GraphQueryError("storage unavailable")):
            result = GraphExpander().expand(direct, self.session)
        self.assertEqual(result.reports[0].status, "failure")
        self.assertIsNone(result.reports[0].observation)
        original = MemoryGraph.traverse

        def drift(graph, *args, **kwargs):
            observation = original(graph, *args, **kwargs)
            with (self.fixture.repo / "src/widget.cpp").open("a", encoding="utf-8") as stream:
                stream.write("// changed during expansion\n")
            return observation

        with patch.object(MemoryGraph, "traverse", drift), self.assertRaises(SnapshotReadError):
            GraphExpander().expand(direct, self.session)


class OverlayExpansionTests(unittest.TestCase):
    def test_multiple_close_paths_partial_graph_cycle_and_path_budget(self):
        for partial in (False, True):
            with self.subTest(partial=partial), tempfile.TemporaryDirectory() as directory:
                fixture = OverlayExpansionFixture(Path(directory), cycle=True, partial=partial)
                with fixture.reader.bind(fixture.requirement) as session:
                    task = parse_task("overlay paths", repository=fixture.requirement.repository,
                        target_revision=fixture.requirement.revision, source_id="overlay-task").value
                    queries = tuple(CandidateQuery(Channel.SYMBOL, NameSelector(name),
                        (QueryOrigin(task.provenance, "explicit-family-member"),))
                        for name in ("Open", "Close", "OverlayManager", "Recursive"))
                    direct = CandidateRetriever().retrieve(RetrievalRequest(task, EvidenceSide.TARGET, queries), session)
                    request = TraceRequest(TraceFamily.OVERLAY,
                        GraphSeed(NodeIdentity("symbol", NS + "Open"), session.reference.snapshot.identity, EvidenceSide.TARGET),
                        NodeIdentity("arkui.component", "menu"), "explicit Menu API pairing",
                        manager=NodeIdentity("symbol", NS + "OverlayManager"),
                        close_seeds=(NodeIdentity("symbol", NS + "Close"),))
                    result = GraphExpander().expand(direct, session, traces=(request,))
                    report = result.reports[-1]
                    trace = report.observation
                    self.assertIsNotNone(trace)
                    self.assertEqual(len(trace.close.paths), 1 if partial else 2)
                    self.assertEqual(report.summary.path_count, 2 if partial else 3)
                    if not partial:
                        self.assertEqual(trace.close.status.value, "ambiguous")
                        self.assertIn("ambiguous_paths", report.summary.limitations)
                    self.assertNotEqual(trace.status.value, "complete")
                    cycle = next(r for r in result.reports if r.seed.seed.identity.key == NS + "Recursive")
                    self.assertEqual(len(cycle.observation.visits), 1)
                    self.assertEqual(len(cycle.observation.edges), 1)
                    self.assertEqual(cycle.observation.edges[0].identity.source, cycle.observation.edges[0].identity.target)
                    exact = GraphExpander(ExpansionPolicy(max_paths=report.summary.path_count)).expand(direct, session, traces=(request,))
                    self.assertIsNotNone(exact.reports[-1].observation)
                    limited = GraphExpander(ExpansionPolicy(max_paths=1)).expand(direct, session, traces=(request,))
                    self.assertIsNone(limited.reports[-1].observation)
                    self.assertEqual(limited.reports[-1].summary, report.summary)
                    self.assertIn("global_path_limit", limited.reports[-1].diagnostics)
                    with session.read() as view:
                        for path in trace.close.paths:
                            self.assertTrue(set(path.calls).issubset(view.graph.edges))


class ChangeExpansionTests(unittest.TestCase):
    def test_dual_revision_mapping_seeds_and_global_budget_keep_sides_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = DualRevisionFixture(Path(directory))
            with fixture.bind("base") as base, fixture.bind("head") as head:
                change = parse_unified_diff("--- old.cpp\n+++ new.cpp\n@@ -2 +2 @@\n-  int x = 1;\n+  int x = 1;\n",
                    repository=REPOSITORY, base_revision=fixture.base_revision,
                    head_revision=fixture.head_revision, source_id="rename").value
                upstream = ChangedRangeMapper().retrieve(change, base=base, head=head, channels=(Channel.SYMBOL,))
                result = GraphExpander().expand_change(upstream, base=base, head=head)
                self.assertEqual(result.upstream, upstream)
                self.assertEqual(result.old.seeds[0].seed.identity, result.new.seeds[0].seed.identity)
                self.assertNotEqual(result.old.seeds[0].seed.snapshot, result.new.seeds[0].seed.snapshot)
                self.assertNotEqual(result.old.reports[0].query_id, result.new.reports[0].query_id)
                limited = GraphExpander(ExpansionPolicy(max_queries=1)).expand_change(upstream, base=base, head=head)
                self.assertEqual(limited.old.query_count + limited.new.query_count, 1)
                self.assertTrue(limited.old.truncated)
                missing = ChangedRangeMapper().retrieve(change, base=None, head=head, channels=(Channel.SYMBOL,))
                partial = GraphExpander().expand_change(missing, base=None, head=head)
                self.assertIsNone(partial.old)
                self.assertEqual(partial.upstream.mapping, missing.mapping)
