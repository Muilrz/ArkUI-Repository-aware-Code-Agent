from __future__ import annotations

import unittest
from dataclasses import replace
from itertools import permutations

from arkui_agent.graph import (
    Direction, EdgeIdentity, GraphEdge, GraphNode, GraphQuery, MemoryGraph,
    NodeIdentity, NodeKind, RelationEvidence, RelationType, SourceAnchor,
    TraversalBounds, TraversalStop,
)
from arkui_agent.repository.model import SymbolIdentity


def node(key: str) -> GraphNode:
    symbol = SymbolIdentity(key)
    return GraphNode(NodeIdentity.for_symbol(symbol), NodeKind.SYMBOL,
                     "same display name", (SourceAnchor(symbol),))


def edge(source: str, target: str, relation: RelationType = RelationType.CALL) -> GraphEdge:
    return GraphEdge(
        EdgeIdentity(node(source).identity, node(target).identity, relation),
        (RelationEvidence("fixture.explicit_fact", SourceAnchor(SymbolIdentity(source)),
                          "symbol-level evidence; source range unavailable"),),
    )


class GraphQueryContractTests(unittest.TestCase):
    # Future storage implementations can run the same behavioral contract suite.
    graph_factory = MemoryGraph

    def setUp(self) -> None:
        self.nodes = tuple(node(key) for key in "abcde")
        self.edges = (
            edge("a", "b"), edge("a", "c", RelationType.REFERENCE),
            edge("b", "d"), edge("c", "d"), edge("d", "a"), edge("b", "b"),
        )
        self.graph: GraphQuery = self.graph_factory(reversed(self.nodes), reversed(self.edges))
        self.a = node("a").identity

    def test_protocol_and_exact_lookup(self) -> None:
        self.assertIsInstance(self.graph, GraphQuery)
        self.assertEqual(self.graph.node(self.a), node("a"))
        self.assertNotEqual(self.graph.node(self.a), self.graph.node(node("b").identity))

    def test_incoming_and_outgoing_order(self) -> None:
        self.assertEqual(self.graph.incoming_edges(self.a), (edge("d", "a"),))
        self.assertEqual(self.graph.outgoing_edges(self.a), self.edges[:2])
        self.assertEqual(self.graph.incoming_edges(node("d").identity),
                         (edge("b", "d"), edge("c", "d")))

    def test_relation_filter_none_empty_and_multiple(self) -> None:
        calls = frozenset({RelationType.CALL})
        self.assertEqual(self.graph.outgoing_edges(self.a, relations=calls), (edge("a", "b"),))
        self.assertEqual(self.graph.incoming_edges(self.a, relations=frozenset()), ())
        self.assertEqual(self.graph.neighbors(self.a, relations=frozenset()), ())
        self.assertEqual(self.graph.outgoing_edges(self.a, relations=frozenset({
            RelationType.CALL, RelationType.REFERENCE
        })), self.edges[:2])

    def test_neighbors_directions_sorted_unique_and_self_loop(self) -> None:
        self.assertEqual(self.graph.neighbors(self.a), (node("b"), node("c")))
        self.assertEqual(self.graph.neighbors(self.a, direction=Direction.INCOMING), (node("d"),))
        self.assertEqual(self.graph.neighbors(self.a, direction=Direction.BOTH),
                         (node("b"), node("c"), node("d")))
        self.assertEqual(self.graph.neighbors(node("b").identity, direction=Direction.BOTH),
                         (node("a"), node("b"), node("d")))
        graph = self.graph_factory(self.nodes, (edge("a", "b"), edge("b", "a"),
                                               edge("a", "b", RelationType.REFERENCE)))
        self.assertEqual(graph.neighbors(self.a, direction=Direction.BOTH), (node("b"),))

    def test_unknown_and_isolated_nodes(self) -> None:
        unknown = node("missing").identity
        self.assertIsNone(self.graph.node(unknown))
        for identity in (unknown, node("e").identity):
            with self.subTest(identity=identity):
                self.assertEqual(self.graph.incoming_edges(identity), ())
                self.assertEqual(self.graph.outgoing_edges(identity), ())
                self.assertEqual(self.graph.neighbors(identity), ())
                result = self.graph.traverse(identity, bounds=TraversalBounds(5))
                self.assertEqual(result.edges, ())
                self.assertIsNone(result.stopped_by)
                self.assertEqual(len(result.visits), 0 if identity == unknown else 1)

    def test_breadth_first_depth_cycles_cross_edges_and_self_loop(self) -> None:
        result = self.graph.traverse(self.a, bounds=TraversalBounds(10))
        self.assertEqual([(visit.node.identity.key, visit.depth) for visit in result.visits],
                         [("a", 0), ("b", 1), ("c", 1), ("d", 2)])
        self.assertEqual(result.edges, tuple(sorted(self.edges, key=lambda item: item.identity.sort_key)))
        self.assertIsNone(result.stopped_by)

    def test_depth_zero_one_and_terminal_layer_edges(self) -> None:
        zero = self.graph.traverse(self.a, bounds=TraversalBounds(0))
        self.assertEqual(tuple(visit.node for visit in zero.visits), (node("a"),))
        self.assertEqual(zero.edges, ())
        one = self.graph.traverse(self.a, bounds=TraversalBounds(1))
        self.assertEqual(tuple(visit.node for visit in one.visits), (node("a"), node("b"), node("c")))
        self.assertEqual(one.edges, self.edges[:2])
        self.assertIsNone(one.stopped_by)

    def test_traversal_directions_and_filter_at_every_hop(self) -> None:
        incoming = self.graph.traverse(self.a, bounds=TraversalBounds(2), direction=Direction.INCOMING)
        self.assertEqual([(v.node.identity.key, v.depth) for v in incoming.visits],
                         [("a", 0), ("d", 1), ("b", 2), ("c", 2)])
        both = self.graph.traverse(self.a, bounds=TraversalBounds(8), direction=Direction.BOTH)
        self.assertEqual([(v.node.identity.key, v.depth) for v in both.visits],
                         [("a", 0), ("b", 1), ("c", 1), ("d", 1)])
        self.assertEqual(len(both.edges), len(self.edges))
        calls = self.graph.traverse(self.a, bounds=TraversalBounds(8), relations=frozenset({RelationType.CALL}))
        self.assertEqual([v.node.identity.key for v in calls.visits], ["a", "b", "d"])
        self.assertTrue(all(item.identity.relation == RelationType.CALL for item in calls.edges))
        empty = self.graph.traverse(self.a, bounds=TraversalBounds(8), relations=frozenset())
        self.assertEqual(len(empty.visits), 1)
        self.assertEqual(empty.edges, ())

    def test_node_budget_counts_seed_and_stops_before_incomplete_edge(self) -> None:
        result = self.graph.traverse(self.a, bounds=TraversalBounds(5, max_nodes=2))
        self.assertEqual([v.node.identity.key for v in result.visits], ["a", "b"])
        self.assertEqual(result.edges, (edge("a", "b"),))
        self.assertEqual(result.stopped_by, TraversalStop.NODE_LIMIT)
        seed_only = self.graph.traverse(self.a, bounds=TraversalBounds(5, max_nodes=1))
        self.assertEqual(len(seed_only.visits), 1)
        self.assertEqual(seed_only.edges, ())

    def test_edge_budget_stops_before_admitting_endpoint(self) -> None:
        result = self.graph.traverse(self.a, bounds=TraversalBounds(5, max_edges=1))
        self.assertEqual(result.edges, (edge("a", "b"),))
        self.assertEqual([v.node.identity.key for v in result.visits], ["a", "b"])
        self.assertEqual(result.stopped_by, TraversalStop.EDGE_LIMIT)
        zero = self.graph.traverse(self.a, bounds=TraversalBounds(5, max_nodes=1, max_edges=0))
        self.assertEqual(zero.edges, ())
        self.assertEqual(zero.stopped_by, TraversalStop.EDGE_LIMIT)

    def test_exact_budget_is_not_reported_as_truncation(self) -> None:
        result = self.graph.traverse(self.a, bounds=TraversalBounds(5, max_nodes=4, max_edges=6))
        self.assertIsNone(result.stopped_by)
        terminal = self.graph.traverse(self.a, bounds=TraversalBounds(0, max_nodes=1, max_edges=0))
        self.assertIsNone(terminal.stopped_by)

    def test_order_and_budget_selection_ignore_input_permutations(self) -> None:
        small_edges = (edge("a", "c"), edge("a", "b"), edge("b", "d"))
        for records in permutations(small_edges):
            with self.subTest(records=records):
                graph = self.graph_factory(reversed(self.nodes), records)
                result = graph.traverse(self.a, bounds=TraversalBounds(3, max_nodes=2))
                self.assertEqual([v.node.identity.key for v in result.visits], ["a", "b"])
                self.assertEqual(result.edges, (edge("a", "b"),))
                self.assertEqual(result.stopped_by, TraversalStop.NODE_LIMIT)
                self.assertEqual(graph.neighbors(self.a), (node("b"), node("c")))

    def test_duplicate_nodes_edges_merge_evidence_without_losing_parallel_types(self) -> None:
        original = edge("a", "b")
        extra = replace(original, evidence=(replace(original.evidence[0], provenance="other.producer"),))
        records = (original, extra, original, edge("a", "b", RelationType.REFERENCE))
        graph = self.graph_factory((*self.nodes, node("a")), records)
        reverse = self.graph_factory(self.nodes, reversed(records))
        expected = (original.merge(extra), edge("a", "b", RelationType.REFERENCE))
        self.assertEqual(graph.outgoing_edges(self.a), expected)
        self.assertEqual(reverse.outgoing_edges(self.a), expected)

    def test_conflicting_nodes_and_dangling_edges_fail(self) -> None:
        conflicting = replace(node("a"), display_name="different")
        for nodes in ((node("a"), conflicting), (conflicting, node("a"))):
            with self.subTest(nodes=nodes), self.assertRaisesRegex(ValueError, "Conflicting"):
                self.graph_factory(nodes, ())
        for relation in (edge("a", "missing"), edge("missing", "a")):
            with self.subTest(relation=relation), self.assertRaisesRegex(ValueError, "Dangling"):
                self.graph_factory(self.nodes, (relation,))

    def test_invalid_bounds_and_queries_fail_even_for_unknown_node(self) -> None:
        for field, value in (("max_depth", -1), ("max_nodes", 0), ("max_edges", -1)):
            with self.subTest(field=field), self.assertRaises(ValueError):
                replace(TraversalBounds(1), **{field: value})
        for value in (True, 1.5, "2"):
            with self.subTest(value=value), self.assertRaises(TypeError):
                TraversalBounds(value)
        for identity in (self.a, node("unknown").identity):
            for invalid in ({"direction": "outgoing"}, {"relations": {RelationType.CALL}},
                            {"relations": frozenset({"CALL"})}):
                with self.subTest(invalid=invalid), self.assertRaises(TypeError):
                    self.graph.traverse(identity, bounds=TraversalBounds(1), **invalid)
            with self.assertRaises(TypeError):
                self.graph.neighbors(identity, direction="invalid")
            with self.assertRaises(TypeError):
                self.graph.outgoing_edges(identity, relations={RelationType.CALL})
            with self.assertRaises(TypeError):
                self.graph.incoming_edges(identity, relations={RelationType.CALL})
            with self.assertRaises(TypeError):
                self.graph.traverse(identity, bounds=1)
