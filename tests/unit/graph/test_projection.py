from __future__ import annotations

import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from arkui_agent.graph import GraphSnapshot, NodeIdentity, NodeKind, RelationType, project_index
from arkui_agent.repository import (
    RepositoryFile, SourceLocation, SourceRange, Symbol, SymbolIdentity, SymbolIndex,
    SymbolIndexClosedError, SymbolKind, SymbolSemanticFacts, TestCase, TestFixture,
)


def source_range(path: str, line: int, end_line: int | None = None) -> SourceRange:
    file = RepositoryFile.from_path(path)
    return SourceRange(SourceLocation(file, line, 1), SourceLocation(file, end_line or line, 9))


def symbol(key: str) -> Symbol:
    return Symbol(SymbolIdentity(key), SymbolKind.METHOD, "same", "fixture::same",
                  declaration=source_range("include/widget.h", 2),
                  definition=source_range("src/widget.cpp", 3, 6))


class ProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = TemporaryDirectory(prefix="projection-unit-")
        self.addCleanup(temporary.cleanup)
        self.index = SymbolIndex(Path(temporary.name) / "symbols.sqlite3")
        self.addCleanup(self.index.close)
        self.a, self.b = symbol("a(int)"), symbol("b(double)")
        self.fixture = TestFixture(SymbolIdentity("fixture"), "same", source_range("tests/widget.cpp", 2))
        self.case = TestCase(SymbolIdentity("case"), "same", self.fixture.identity,
                             source_range("tests/widget.cpp", 4), source_range("tests/widget.cpp", 5, 9))
        self.reference = source_range("tests/widget.cpp", 6)
        self.index.rebuild(
            (self.a, self.b),
            files=(RepositoryFile.from_path("empty.h"),),
            semantic_facts=(
                SymbolSemanticFacts(self.a.identity, references=(self.reference, self.reference),
                                    callees=(self.b.identity, self.b.identity)),
                SymbolSemanticFacts(self.b.identity, callers=(self.a.identity,)),
            ), test_fixtures=(self.fixture,), test_cases=(self.case,),
        )

    def project(self) -> GraphSnapshot:
        return project_index(self.index, repository_key="repo", snapshot_key="p1-snapshot")

    def test_file_symbol_declaration_definition_projection(self) -> None:
        snapshot = self.project()
        query = snapshot.query()
        a = query.node(NodeIdentity.for_symbol(self.a.identity))
        self.assertEqual(a.kind, NodeKind.METHOD)
        self.assertEqual({anchor.source_range for anchor in a.anchors},
                         {self.a.declaration, self.a.definition})
        for role, range_ in ((RelationType.DECLARE, self.a.declaration), (RelationType.DEFINE, self.a.definition)):
            edges = query.incoming_edges(a.identity, relations=frozenset({role}))
            self.assertEqual(len(edges), 1)
            self.assertEqual(edges[0].identity.source, NodeIdentity.for_file(range_.file))
            self.assertEqual(edges[0].evidence[0].anchor.source_range, range_)
        self.assertIsNotNone(query.node(NodeIdentity.for_file(RepositoryFile.from_path("empty.h"))))

    def test_calls_merge_both_stored_directions_and_preserve_coarse_provenance(self) -> None:
        edges = [edge for edge in self.project().edges if edge.identity.relation == RelationType.CALL]
        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0].identity.source, NodeIdentity.for_symbol(self.a.identity))
        self.assertEqual(edges[0].identity.target, NodeIdentity.for_symbol(self.b.identity))
        self.assertEqual({e.provenance for e in edges[0].evidence},
                         {"p1.semantic_facts.callers", "p1.semantic_facts.callees"})
        for evidence in edges[0].evidence:
            self.assertEqual(evidence.anchor.source_range, self.a.definition)
            self.assertIn("exact call site unavailable", evidence.description)

    def test_references_are_file_to_exact_symbol_without_enclosing_function_guess(self) -> None:
        references = [edge for edge in self.project().edges if edge.identity.relation == RelationType.REFERENCE]
        self.assertEqual(len(references), 1)
        self.assertEqual(references[0].identity.source, NodeIdentity.for_file(self.reference.file))
        self.assertEqual(references[0].identity.target, NodeIdentity.for_symbol(self.a.identity))
        self.assertEqual(references[0].evidence[0].anchor.source_range, self.reference)

    def test_multiple_occurrences_survive_reference_and_test_edge_dedup(self) -> None:
        second = source_range("tests/widget.cpp", 7)
        self.index.rebuild((self.a,), semantic_facts=(SymbolSemanticFacts(
            self.a.identity, references=(second, self.reference, second)),),
            test_fixtures=(self.fixture,), test_cases=(self.case,))
        for relation, source in (
            (RelationType.REFERENCE, NodeIdentity.for_file(self.reference.file)),
            (RelationType.TEST, NodeIdentity.for_symbol(self.case.identity)),
        ):
            edges = self.project().query().outgoing_edges(source, relations=frozenset({relation}))
            self.assertEqual(len(edges), 1)
            self.assertEqual({e.anchor.source_range for e in edges[0].evidence}, {self.reference, second})

    def test_call_projection_does_not_add_reciprocal_or_transitive_relations(self) -> None:
        c = symbol("c")
        self.index.rebuild((self.a, self.b, c), semantic_facts=(
            SymbolSemanticFacts(self.a.identity, callees=(self.b.identity,)),
            SymbolSemanticFacts(self.b.identity, callees=(c.identity,)),
        ))
        calls = {(edge.identity.source.key, edge.identity.target.key) for edge in self.project().edges
                 if edge.identity.relation == RelationType.CALL}
        self.assertEqual(calls, {(self.a.identity.value, self.b.identity.value), (self.b.identity.value, c.identity.value)})

    def test_test_entities_membership_and_direct_mapping_use_p1_facts(self) -> None:
        snapshot = self.project()
        query = snapshot.query()
        self.assertEqual(query.node(NodeIdentity.for_symbol(self.fixture.identity)).kind, NodeKind.TEST_FIXTURE)
        case_node = query.node(NodeIdentity.for_symbol(self.case.identity))
        self.assertEqual(case_node.kind, NodeKind.TEST_CASE)
        self.assertEqual({a.source_range for a in case_node.anchors}, {self.case.source_range, self.case.body_range})
        membership = query.outgoing_edges(NodeIdentity.for_symbol(self.fixture.identity))
        self.assertEqual(len(membership), 1)
        self.assertEqual(membership[0].identity.target, case_node.identity)
        self.assertEqual(membership[0].evidence[0].provenance, "p1.test_case.fixture_identity")
        mappings = query.outgoing_edges(case_node.identity)
        self.assertEqual(len(mappings), 1)
        self.assertEqual(mappings[0].identity.relation, RelationType.TEST)
        self.assertEqual(mappings[0].identity.target, NodeIdentity.for_symbol(self.a.identity))
        self.assertEqual(tuple(e.anchor.source_range for e in mappings[0].evidence),
                         self.index.tested_symbol_mappings_for_case(self.case.identity)[0].references)

    def test_same_name_unmapped_case_and_no_body_do_not_infer_tests(self) -> None:
        no_body = replace(self.case, identity=SymbolIdentity("no-body"), body_range=None)
        self.index.rebuild((self.a, self.b), semantic_facts=(SymbolSemanticFacts(self.a.identity, references=(self.reference,)),),
                           test_fixtures=(self.fixture,), test_cases=(no_body,))
        snapshot = self.project()
        query = snapshot.query()
        self.assertNotEqual(query.node(NodeIdentity.for_symbol(self.a.identity)).identity,
                            query.node(NodeIdentity.for_symbol(self.b.identity)).identity)
        self.assertEqual(query.outgoing_edges(NodeIdentity.for_symbol(no_body.identity)), ())

    def test_unresolved_calls_keep_identities_and_available_provenance(self) -> None:
        missing = SymbolIdentity("unknown")
        declaration_only = replace(self.a, definition=None)
        self.index.rebuild((declaration_only,), semantic_facts=(SymbolSemanticFacts(
            self.a.identity, callers=(missing,), callees=(missing,)),))
        snapshot = self.project()
        unknown = snapshot.query().node(NodeIdentity.for_symbol(missing))
        self.assertEqual(unknown.kind, NodeKind.SYMBOL)
        self.assertIsNone(unknown.anchors[0].source_range)
        calls = {edge.identity.source: edge for edge in snapshot.edges if edge.identity.relation == RelationType.CALL}
        self.assertEqual(len(calls), 2)
        self.assertIsNone(calls[unknown.identity].evidence[0].anchor.source_range)
        known = calls[NodeIdentity.for_symbol(self.a.identity)].evidence[0]
        self.assertEqual(known.anchor.source_range, self.a.declaration)
        self.assertIn("caller declaration", known.description)

    def test_exact_test_identity_enriches_symbol_without_duplicate_node(self) -> None:
        shared = replace(self.a, identity=self.fixture.identity, kind=SymbolKind.CLASS)
        self.index.rebuild((shared,), test_fixtures=(self.fixture,))
        result = self.project()
        nodes = [n for n in result.nodes if n.identity == NodeIdentity.for_symbol(shared.identity)]
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0].kind, NodeKind.TEST_FIXTURE)
        self.assertEqual(len(nodes[0].anchors), 3)

    def test_no_framework_inheritance_or_override_inference(self) -> None:
        a = replace(self.a, kind=SymbolKind.CLASS, parent_identity=self.b.identity, display_name="WidgetPattern")
        self.index.rebuild((a, self.b))
        result = self.project()
        self.assertEqual(result.query().node(NodeIdentity.for_symbol(a.identity)).kind, NodeKind.CLASS)
        self.assertEqual(set(result.unavailable_relations), {RelationType.INHERIT, RelationType.OVERRIDE})
        self.assertEqual({e.identity.relation for e in result.edges}, {RelationType.DECLARE, RelationType.DEFINE})

    def test_enumeration_is_complete_deterministic_and_closed_index_fails(self) -> None:
        orphan = replace(self.fixture, identity=SymbolIdentity("orphan"), source_range=source_range("a.cpp", 1))
        self.index.rebuild((), test_fixtures=(self.fixture, orphan), test_cases=(self.case,))
        self.assertEqual(self.index.test_fixtures(), (orphan, self.fixture))
        self.assertIsNotNone(self.project().query().node(NodeIdentity.for_symbol(orphan.identity)))
        self.index.close()
        with self.assertRaises(SymbolIndexClosedError):
            self.index.test_fixtures()
        with self.assertRaises(SymbolIndexClosedError):
            self.project()

    def test_rebuild_order_and_empty_snapshot(self) -> None:
        first = self.project()
        self.index.rebuild((self.b, self.a), files=(RepositoryFile.from_path("empty.h"),),
                           semantic_facts=(SymbolSemanticFacts(self.b.identity, callers=(self.a.identity,)),
                                           SymbolSemanticFacts(self.a.identity, references=(self.reference,), callees=(self.b.identity,))),
                           test_fixtures=(self.fixture,), test_cases=(self.case,))
        self.assertEqual(self.project(), first)
        self.index.rebuild(())
        empty = self.project()
        self.assertEqual(empty.nodes, ())
        self.assertEqual(empty.edges, ())
