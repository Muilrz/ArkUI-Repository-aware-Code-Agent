import unittest
from dataclasses import replace

from arkui_agent.graph.layout import LayoutNode, LayoutStage, LayoutStageResult, LayoutStatus, LayoutTrace
from arkui_agent.graph.model import GraphNode, NodeIdentity, NodeKind, SourceAnchor
from arkui_agent.graph.query import Direction
from arkui_agent.repository.model import SymbolIdentity
from arkui_agent.retrieval.candidates import CandidateInputError
from arkui_agent.retrieval.expansion import ExpansionPolicy, _summary


class ExpansionPolicyTests(unittest.TestCase):
    def test_version_types_bounds_and_configuration_identity(self):
        policy = ExpansionPolicy()
        self.assertEqual(policy.policy_id, ExpansionPolicy().policy_id)
        self.assertNotEqual(policy.policy_id, replace(policy, task_direction=Direction.BOTH).policy_id)
        for kwargs in ({"version": "v2"}, {"max_queries": True}, {"max_depth": -1},
                       {"max_paths_per_seed": 0}, {"relations": set()}, {"trace_families": frozenset({"layout"})}):
            with self.subTest(kwargs=kwargs), self.assertRaises(CandidateInputError):
                ExpansionPolicy(**kwargs)

    def test_layout_candidate_ambiguity_survives_summary_without_fabricated_binding(self):
        # Metric unit fixture only: does not stand in for a production P2 query.
        candidates = tuple(LayoutNode(GraphNode(NodeIdentity("symbol", name), NodeKind.CLASS, name,
                           (SourceAnchor(SymbolIdentity(name)),)), ())
                           for name in ("MenuLayoutAlgorithm", "MultiMenuLayoutAlgorithm", "SubMenuLayoutAlgorithm"))
        trace = LayoutTrace("repo", "graph", NodeIdentity("symbol", "MenuPattern"),
            NodeIdentity("arkui.component", "menu"), (LayoutStageResult(LayoutStage.PATTERN, ()),),
            (), (), (), (), candidates, (), ("ambiguous_algorithm_identity", "missing_create_binding"),
            True, LayoutStatus.AMBIGUOUS)
        summary = _summary(trace)
        self.assertEqual(summary.p2_status, "ambiguous")
        self.assertEqual(summary.edge_count, 0)
        self.assertEqual(summary.node_count, 5)
        self.assertIn("missing_create_binding", summary.limitations)
        self.assertTrue(summary.exhaustive)
