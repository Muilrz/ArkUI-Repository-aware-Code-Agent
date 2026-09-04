from __future__ import annotations

import json
import unittest
from dataclasses import FrozenInstanceError, replace

from arkui_agent.graph import (
    EdgeIdentity, GraphEdge, GraphNode, NodeIdentity, NodeKind, RelationEvidence,
    RelationType, SourceAnchor,
)
from arkui_agent.repository.model import (
    RepositoryFile, SourceLocation, SourceRange, Symbol, SymbolIdentity, SymbolKind,
)


class GraphModelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.file = RepositoryFile.from_path("src/widget.cpp")
        self.range = SourceRange(
            SourceLocation(self.file, 2, 1), SourceLocation(self.file, 4, 2)
        )
        self.symbol = Symbol(
            SymbolIdentity("cpp:Widget::Update(int)"), SymbolKind.METHOD,
            "Update", "Widget::Update", definition=self.range,
        )
        self.anchor = SourceAnchor(self.symbol.identity, source_range=self.range)
        self.node = GraphNode(
            NodeIdentity.for_symbol(self.symbol.identity), NodeKind.METHOD,
            self.symbol.display_name, (self.anchor,),
        )
        self.edge_id = EdgeIdentity(
            self.node.identity, NodeIdentity("symbol", "cpp:Apply"), RelationType.CALL
        )
        self.evidence = RelationEvidence(
            "p1.reference_call.callees", self.anchor, "caller definition; call site unavailable"
        )

    def test_contract_vocabulary(self) -> None:
        self.assertEqual({kind.value for kind in NodeKind}, {
            "file", "symbol", "function", "method", "class", "component", "arkts_api",
            "bridge", "model", "pattern", "layout_property", "paint_property",
            "layout_algorithm", "overlay_manager", "test_fixture", "test_case",
        })
        self.assertEqual({relation.value for relation in RelationType}, {
            "DECLARE", "DEFINE", "CALL", "REFERENCE", "INHERIT", "OVERRIDE", "CREATE",
            "UPDATE_PROPERTY", "MEASURE", "LAYOUT", "SHOW", "CLOSE", "TEST", "MOCK",
        })

    def test_identity_uses_p1_identity_not_name_kind_or_location(self) -> None:
        self.assertEqual(self.node.identity.key, self.symbol.identity.value)
        renamed = replace(self.node, display_name="Other", kind=NodeKind.SYMBOL)
        self.assertEqual(renamed.identity, self.node.identity)
        overload = SymbolIdentity("cpp:Widget::Update(double)")
        self.assertNotEqual(NodeIdentity.for_symbol(overload), self.node.identity)
        moved = replace(self.node, anchors=(SourceAnchor(self.symbol.identity),))
        self.assertEqual(moved.identity, self.node.identity)
        self.assertNotEqual(NodeIdentity("component", self.symbol.identity.value), self.node.identity)

    def test_versioned_identity_encoding_is_lossless_and_unambiguous(self) -> None:
        first = NodeIdentity("a:b", 'c\\\"组件')
        second = NodeIdentity("a", 'b:c\\\"组件')
        self.assertNotEqual(first.value, second.value)
        self.assertEqual(json.loads(first.value.removeprefix("graph-node:v1:")),
                         [first.namespace, first.key])
        self.assertEqual(NodeIdentity("symbol", "a").value, 'graph-node:v1:["symbol","a"]')
        self.assertEqual(json.loads(self.edge_id.value.removeprefix("graph-edge:v1:")),
                         [self.node.identity.value, self.edge_id.target.value, "CALL"])

    def test_anchor_reuses_p1_file_range_and_symbol_objects(self) -> None:
        self.assertIs(self.anchor.symbol_identity, self.symbol.identity)
        self.assertIs(self.anchor.source_range, self.symbol.definition)
        self.assertIs(self.anchor.file, self.file)
        self.assertEqual(self.anchor, SourceAnchor(self.symbol.identity, self.file, self.range))
        self.assertEqual(self.anchor.source_range.start.line, 2)
        file_node = GraphNode(NodeIdentity.for_file(self.file), NodeKind.FILE,
                              "widget.cpp", (SourceAnchor(file=self.file),))
        self.assertEqual(file_node.identity.key, "src/widget.cpp")

    def test_coarse_or_unresolved_sources_do_not_invent_ranges(self) -> None:
        unresolved = SourceAnchor(SymbolIdentity("cpp:unresolved"))
        self.assertIsNone(unresolved.file)
        self.assertIsNone(unresolved.source_range)
        self.assertIsNone(SourceAnchor(file=self.file).source_range)
        self.assertEqual(self.evidence.anchor.source_range, self.symbol.definition)
        self.assertIn("call site unavailable", self.evidence.description)

    def test_multiple_node_anchors_are_canonical_and_immutable(self) -> None:
        header = SourceAnchor(self.symbol.identity, RepositoryFile.from_path("include/widget.h"))
        left = replace(self.node, anchors=(self.anchor, header, self.anchor))
        right = replace(self.node, anchors=(header, self.anchor))
        self.assertEqual(left, right)
        self.assertEqual(len(left.anchors), 2)
        with self.assertRaises(FrozenInstanceError):
            left.display_name = "changed"  # type: ignore[misc]

    def test_domain_node_has_explicit_p1_anchors(self) -> None:
        component = GraphNode(NodeIdentity("arkui.component", "stable-key"),
                              NodeKind.COMPONENT, "Widget", (self.anchor,))
        self.assertEqual(component.anchors, self.node.anchors)

    def test_invalid_identities_and_source_links_fail(self) -> None:
        for namespace, key in (("", "a"), ("symbol", " ")):
            with self.subTest(namespace=namespace, key=key), self.assertRaises(ValueError):
                NodeIdentity(namespace, key)
        with self.assertRaises(ValueError):
            SourceAnchor()
        with self.assertRaises(ValueError):
            SourceAnchor(file=RepositoryFile.from_path("wrong.cpp"), source_range=self.range)
        for changes in (
            {"anchors": ()}, {"display_name": " "},
            {"identity": NodeIdentity("symbol", "wrong")},
            {"identity": NodeIdentity("file", "wrong.cpp")},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(self.node, **changes)
        with self.assertRaises(TypeError):
            replace(self.node, anchors=[self.anchor])
        with self.assertRaises(TypeError):
            replace(self.node, kind="method")

    def test_edge_identity_separates_direction_and_relation(self) -> None:
        self.assertNotEqual(self.edge_id, replace(self.edge_id, relation=RelationType.REFERENCE))
        self.assertNotEqual(self.edge_id, EdgeIdentity(
            self.edge_id.target, self.edge_id.source, RelationType.CALL
        ))
        with self.assertRaises(TypeError):
            replace(self.edge_id, relation="CALL")

    def test_relation_merge_preserves_all_occurrences_and_producers(self) -> None:
        reference = RelationEvidence("p1.references", SourceAnchor(source_range=self.range),
                                     "reference occurrence")
        later_range = SourceRange(SourceLocation(self.file, 6, 1), SourceLocation(self.file, 6, 8))
        later = replace(reference, anchor=SourceAnchor(source_range=later_range))
        first = GraphEdge(self.edge_id, (self.evidence, reference, self.evidence))
        second = GraphEdge(self.edge_id, (later,))
        self.assertEqual(first.merge(second), second.merge(first))
        self.assertEqual(first.merge(first), first)
        merged = first.merge(second)
        self.assertEqual(merged.identity, first.identity)
        self.assertEqual(len(merged.evidence), 3)
        self.assertEqual(merged.evidence, tuple(sorted(
            (self.evidence, reference, later), key=lambda item: item.sort_key
        )))
        with self.assertRaises(ValueError):
            first.merge(GraphEdge(replace(self.edge_id, relation=RelationType.CREATE), (reference,)))

    def test_invalid_evidence_fails_and_edge_is_immutable(self) -> None:
        for field in ("provenance", "description"):
            with self.subTest(field=field), self.assertRaises(ValueError):
                replace(self.evidence, **{field: " "})
        with self.assertRaises(ValueError):
            GraphEdge(self.edge_id, ())
        with self.assertRaises(TypeError):
            GraphEdge(self.edge_id, [self.evidence])  # type: ignore[arg-type]
        edge = GraphEdge(self.edge_id, (self.evidence,))
        with self.assertRaises(FrozenInstanceError):
            edge.evidence = ()  # type: ignore[misc]
