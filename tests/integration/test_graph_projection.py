from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from arkui_agent.graph import GraphStore, NodeIdentity, NodeKind, RelationType, TraversalBounds
from arkui_agent.repository import (
    ClangdSemanticProvider, RepositoryFile, RepositoryTestDiscoverer,
    RepositoryWorkspace, SymbolIndex, SymbolSemanticFacts,
)
from tests.fixtures.synthetic_cpp_repository import synthetic_cpp_repository
from tests.integration.test_reference_call_retrieval import (
    configured_clangd, indexed_symbols, symbol_by_qualified_name,
)


class GraphProjectionIntegrationTests(unittest.TestCase):
    def test_real_p1_pipeline_projects_persists_queries_and_rebuilds(self) -> None:
        with synthetic_cpp_repository() as repository, TemporaryDirectory(prefix="graph-integration-") as temporary:
            originals = {path: path.read_bytes() for path in (repository.header, repository.source, repository.test_source)}
            workspace = RepositoryWorkspace(repository.root)
            header = RepositoryFile.from_path("include/fixture/widget.h")
            source = RepositoryFile.from_path("src/widget.cpp")
            test_file = RepositoryFile.from_path("tests/widget_test.cpp")
            discovered = RepositoryTestDiscoverer(workspace).discover((test_file,))
            with ClangdSemanticProvider(
                workspace, executable=configured_clangd(),
                fallback_flags=("-std=c++17", f"-I{repository.root / 'include'}"),
            ) as provider:
                provider.symbols_in_file(source)
                provider.symbols_in_file(test_file)
                primary = provider.symbols_in_file(header)
                value = symbol_by_qualified_name(primary, "fixture::Widget::value")
                doubled = symbol_by_qualified_name(primary, "fixture::DerivedWidget::doubled_value")
                callers = provider.callers(value.identity)
                callees = provider.callees(doubled.identity)
                facts = (
                    SymbolSemanticFacts(value.identity, references=provider.references(value.identity),
                                        callers=tuple(item.identity for item in callers)),
                    SymbolSemanticFacts(doubled.identity, references=provider.references(doubled.identity),
                                        callees=tuple(item.identity for item in callees)),
                )
            self.assertIn(value.identity, {item.identity for item in callees})
            all_symbols = indexed_symbols(primary, (*callers, *callees))
            database = Path(temporary) / "p1.sqlite3"
            with SymbolIndex(database) as index:
                index.rebuild(all_symbols, semantic_facts=facts,
                              test_fixtures=discovered.fixtures, test_cases=discovered.cases)
            # Projection consumes the reopened index after the semantic provider closes.
            store = GraphStore(Path(temporary) / "runtime", repository_key="synthetic-fixture", snapshot_key="p1-v1")
            with SymbolIndex(database) as index:
                snapshot = store.rebuild(index)
                original_bytes = store.path.read_bytes()
                query = store.load().query()
                value_id = NodeIdentity.for_symbol(value.identity)
                doubled_id = NodeIdentity.for_symbol(doubled.identity)
                self.assertEqual(query.node(value_id).kind, NodeKind.METHOD)
                for relation, range_ in ((RelationType.DECLARE, value.declaration), (RelationType.DEFINE, value.definition)):
                    self.assertIsNotNone(range_)
                    edges = query.incoming_edges(value_id, relations=frozenset({relation}))
                    self.assertEqual(len(edges), 1)
                    self.assertEqual(edges[0].identity.source, NodeIdentity.for_file(range_.file))
                    self.assertEqual(edges[0].evidence[0].anchor.source_range, range_)
                calls = query.outgoing_edges(doubled_id, relations=frozenset({RelationType.CALL}))
                value_call = [edge for edge in calls if edge.identity.target == value_id]
                self.assertEqual(len(value_call), 1)
                self.assertEqual(value_call[0].evidence[0].anchor.source_range, doubled.definition or doubled.declaration)
                references = query.incoming_edges(value_id, relations=frozenset({RelationType.REFERENCE}))
                self.assertEqual({e.anchor.source_range for edge in references for e in edge.evidence}, set(facts[0].references))
                cases = index.test_cases_for_symbol(value.identity)
                self.assertEqual([case.display_name for case in cases], ["ValueIsTwentyOne"])
                for fixture in discovered.fixtures:
                    self.assertEqual(query.node(NodeIdentity.for_symbol(fixture.identity)).kind, NodeKind.TEST_FIXTURE)
                for case in discovered.cases:
                    self.assertEqual(query.node(NodeIdentity.for_symbol(case.identity)).kind, NodeKind.TEST_CASE)
                mapping_edges = query.outgoing_edges(NodeIdentity.for_symbol(cases[0].identity),
                                                      relations=frozenset({RelationType.TEST}))
                target_mapping = [edge for edge in mapping_edges if edge.identity.target == value_id]
                self.assertEqual(len(target_mapping), 1)
                expected_mapping = index.tested_symbol_mappings_for_symbol(value.identity)[0]
                self.assertEqual({e.anchor.source_range for e in target_mapping[0].evidence}, set(expected_mapping.references))
                self.assertTrue(all(edge.identity.relation in {
                    RelationType.DECLARE, RelationType.DEFINE, RelationType.CALL,
                    RelationType.REFERENCE, RelationType.TEST,
                } for edge in snapshot.edges))
                store.delete()
                self.assertFalse(store.path.exists())
                self.assertEqual(store.rebuild(index), snapshot)
                self.assertEqual(store.path.read_bytes(), original_bytes)
                self.assertEqual(store.load().query().traverse(doubled_id, bounds=TraversalBounds(2)),
                                 query.traverse(doubled_id, bounds=TraversalBounds(2)))
                index.rebuild(())
                self.assertEqual(store.rebuild(index).nodes, ())
                self.assertIsNone(store.load().query().node(value_id))
                self.assertIsNotNone(query.node(value_id))
            for path, original in originals.items():
                self.assertEqual(path.read_bytes(), original)
