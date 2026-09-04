from __future__ import annotations

import re
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from arkui_agent.graph import default_role_mapper, project_index
from arkui_agent.graph.creation import CreationBounds, CreationStage, CreationStatus, trace_component_creation
from arkui_agent.graph.domain import MappingStatus
from arkui_agent.graph.model import EdgeIdentity, GraphEdge, NodeIdentity, RelationType
from arkui_agent.repository import (
    RepositoryFile, RepositoryWorkspace, SourceLocation, SourceRange, Symbol, SymbolIdentity, SymbolIndex, SymbolKind,
)
from arkui_agent.repository.index import SymbolSemanticFacts
from tests.fixtures.creation_cases import FRAME_HEADER, ROOT, write_creation_repository
from tests.fixtures.framework_repository import FACTORY


class CreationTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory(prefix="creation-unit-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.cases = write_creation_repository(self.root)
        self.workspace = RepositoryWorkspace(self.root)
        self.index = SymbolIndex(self.root / "p1.sqlite3")
        self.addCleanup(self.index.close)
        self.symbols = []
        self.facts = []
        self.add("frame", "OHOS::Ace::NG::FrameNode", FRAME_HEADER, "FrameNode", SymbolKind.CLASS)
        self.add("frame.create", "OHOS::Ace::NG::FrameNode::CreateFrameNode", FRAME_HEADER,
                 "CreateFrameNode", SymbolKind.METHOD, "frame")
        self.add("allocate", "OHOS::Ace::Referenced::MakeRefPtr", FACTORY, "MakeRefPtr", SymbolKind.METHOD)
        refs = []
        for case in self.cases:
            key = case.component
            prefix = f"OHOS::Ace::NG::{key.title()}"
            path = f"{ROOT}/{key}/{key}_model_ng.h"
            self.add(key + ".model", prefix + "ModelNG", path, key.title() + "ModelNG", SymbolKind.CLASS)
            self.add(key + ".create", prefix + "ModelNG::CreateFrameNode", path, "CreateFrameNode",
                     SymbolKind.METHOD, key + ".model")
            self.add(key + ".pattern", prefix + "Pattern", f"{ROOT}/{key}/{key}_pattern.h",
                     key.title() + "Pattern", SymbolKind.CLASS)
            self.add(key + ".entry", "OHOS::Ace::NG::" + case.entry_name, case.entry_file,
                     case.entry_name, SymbolKind.FUNCTION)
            self.facts.extend((
                SymbolSemanticFacts(SymbolIdentity(key + ".entry"), callees=(SymbolIdentity(key + ".create"),)),
                SymbolSemanticFacts(SymbolIdentity(key + ".create"), callees=(SymbolIdentity("frame.create"), SymbolIdentity("allocate"))),
                SymbolSemanticFacts(SymbolIdentity(key + ".pattern"), references=(self.range(path, key.title() + "Pattern"),)),
            ))
            refs.append(self.range(path, "CreateFrameNode", occurrence=1))
        self.facts.append(SymbolSemanticFacts(SymbolIdentity("frame.create"), references=tuple(refs)))

    def range(self, path, token, *, occurrence=0):
        text = (self.root / path).read_text(encoding="utf-8")
        match = list(re.finditer(r"\b" + re.escape(token) + r"\b", text))[occurrence]
        file = RepositoryFile.from_path(path)
        start = SourceLocation(file, text.count("\n", 0, match.start()) + 1,
                               match.start() - text.rfind("\n", 0, match.start()))
        return SourceRange(start, replace(start, column=start.column + len(token)))

    def add(self, key, qualified, file, token, kind, parent=None):
        range_ = self.range(file, token)
        self.symbols.append(Symbol(SymbolIdentity(key), kind, token, qualified, range_, range_,
                                   None if parent is None else SymbolIdentity(parent)))

    def build(self):
        self.index.rebuild(self.symbols, semantic_facts=self.facts)
        graph = project_index(self.index, repository_key="unit", snapshot_key="v1")
        return graph, default_role_mapper().map(self.index, graph)

    def query(self, graph=None, domain=None, **kwargs):
        if graph is None:
            graph, domain = self.build()
        return trace_component_creation(self.index, graph, domain, self.workspace,
            seed=NodeIdentity.for_symbol(SymbolIdentity("button.entry")),
            component=NodeIdentity("arkui.component", "button"), **kwargs)

    def test_complete_order_and_argument_is_not_a_fabricated_call(self):
        result = self.query()
        self.assertEqual(result.status, CreationStatus.COMPLETE)
        path = result.paths[0]
        self.assertEqual([n.stage for n in path.nodes], [CreationStage.ENTRY, CreationStage.MODEL,
                                                       CreationStage.FRAME_NODE, CreationStage.PATTERN])
        self.assertEqual(len(path.relations), 2)
        self.assertEqual(path.pattern_argument.caller, path.nodes[1].node.identity)
        self.assertEqual(path.pattern_argument.frame_factory, path.nodes[2].node.identity)
        self.assertTrue(all(n.evidence and any(a.source_range for a in n.node.anchors) for n in path.nodes))
        self.assertTrue(all(e.identity.relation == RelationType.CALL for e in path.relations))
        self.assertFalse(any(e.identity.source == path.nodes[2].node.identity and
                             e.identity.target == path.nodes[3].node.identity for e in path.pattern_argument.supporting_relations))

    def test_graph_missing_call_returns_partial_without_index_backfill(self):
        graph, domain = self.build()
        for target, node_count in (("button.create", 1), ("frame.create", 2)):
            partial = replace(graph, edges=tuple(e for e in graph.edges if not (
                e.identity.relation == RelationType.CALL and e.identity.target.key == target)))
            result = self.query(partial, domain)
            self.assertEqual(result.status, CreationStatus.INCOMPLETE)
            self.assertEqual(len(result.paths[0].nodes), node_count)

    def test_missing_reference_keeps_verified_call_chain(self):
        graph, domain = self.build()
        result = self.query(replace(graph, edges=tuple(e for e in graph.edges if e.identity.relation != RelationType.REFERENCE)), domain)
        self.assertEqual(result.status, CreationStatus.INCOMPLETE)
        self.assertEqual(len(result.paths[0].relations), 2)
        self.assertIn("missing_argument_reference", result.paths[0].issues)

    def test_operation_binding_cannot_replace_call(self):
        graph, domain = self.build()
        call = next(e for e in graph.edges if e.identity.source.key == "button.entry" and e.identity.relation == RelationType.CALL)
        operation = GraphEdge(EdgeIdentity(call.identity.source, call.identity.target, RelationType.SHOW), call.evidence)
        partial = replace(graph, edges=tuple(e for e in graph.edges if e != call) + (operation,))
        self.assertEqual(self.query(partial, domain).status, CreationStatus.INCOMPLETE)

    def diamond(self):
        (self.root / "helpers.cpp").write_text("void Left() {}\nvoid Right() {}\n", encoding="utf-8")
        for helper in ("Left", "Right"):
            self.add(helper, helper, "helpers.cpp", helper, SymbolKind.FUNCTION)
            self.facts.append(SymbolSemanticFacts(SymbolIdentity(helper), callees=(SymbolIdentity("button.create"),)))
        self.facts = [replace(f, callees=(SymbolIdentity("Left"), SymbolIdentity("Right")))
                      if f.identity.value == "button.entry" else f for f in self.facts]

    def test_diamond_preserves_both_direct_supporting_paths(self):
        self.diamond()
        result = self.query()
        self.assertEqual(result.status, CreationStatus.AMBIGUOUS)
        self.assertEqual(len(result.paths), 2)
        self.assertTrue(all(p.status == CreationStatus.COMPLETE and len(p.relations) == 3 for p in result.paths))
        self.assertEqual({p.nodes[1].node.display_name for p in result.paths}, {"Left", "Right"})

    def test_limits_never_claim_unique_complete_from_truncated_paths(self):
        self.diamond()
        for bounds in (CreationBounds(max_paths=1), CreationBounds(max_depth=1), CreationBounds(max_states=1)):
            result = self.query(bounds=bounds)
            self.assertFalse(result.exhaustive)
            self.assertNotEqual(result.status, CreationStatus.COMPLETE)
            self.assertTrue(result.diagnostics)

    def test_cycles_are_cut_per_path_and_reported(self):
        self.diamond()
        self.facts.append(SymbolSemanticFacts(SymbolIdentity("Left"), callees=(SymbolIdentity("button.entry"),)))
        result = self.query()
        self.assertIn("cycle_cut", result.diagnostics)
        self.assertFalse(result.exhaustive)
        self.assertTrue(all(len({n.node.identity for n in p.nodes}) == len(p.nodes) for p in result.paths))

    def test_unknown_ambiguous_and_other_component_patterns(self):
        graph, domain = self.build()
        for status, expected in ((MappingStatus.UNKNOWN, CreationStatus.INCOMPLETE),
                                 (MappingStatus.AMBIGUOUS, CreationStatus.AMBIGUOUS)):
            changed = replace(domain, mappings=tuple(replace(m, status=status) if m.identity.key == "button.pattern"
                                                     else m for m in domain.mappings))
            result = self.query(graph, changed)
            self.assertEqual(result.status, expected)
            self.assertEqual(result.paths[0].pattern_candidates,
                             (NodeIdentity.for_symbol(SymbolIdentity("button.pattern")),))
        changed = replace(domain, mappings=tuple(replace(m, candidates=(replace(m.resolved,
            component=NodeIdentity("arkui.component", "menu")),)) if m.identity.key == "button.pattern"
            else m for m in domain.mappings))
        self.assertEqual(self.query(graph, changed).status, CreationStatus.INCOMPLETE)

    def test_reference_identity_ambiguity_is_not_resolved_by_name(self):
        pattern = next(s for s in self.symbols if s.identity.value == "button.pattern")
        self.symbols.append(replace(pattern, identity=SymbolIdentity("other-pattern")))
        self.facts.append(replace(next(f for f in self.facts if f.identity == pattern.identity), identity=SymbolIdentity("other-pattern")))
        self.assertEqual(self.query().status, CreationStatus.AMBIGUOUS)

    def test_missing_allocation_and_unsupported_body_are_incomplete(self):
        self.facts = [replace(f, callees=tuple(c for c in f.callees if c.value != "allocate")) for f in self.facts]
        result = self.query()
        self.assertIn("missing_allocation_call", result.paths[0].issues)
        path = self.root / f"{ROOT}/button/button_model_ng.h"
        path.write_text(path.read_text().replace("auto frameNode =", "if (nodeId) return nullptr;\n        auto frameNode ="))
        result = self.query()
        self.assertIn("unsupported_pattern_argument", result.paths[0].issues)

    def test_rebuild_dedup_order_and_no_input_mutation(self):
        graph, domain = self.build()
        result = self.query(graph, domain)
        self.symbols.reverse()
        self.facts = list(reversed(self.facts)) + self.facts
        self.assertEqual(self.query(), result)
        self.assertEqual(self.build()[0], graph)

    def test_missing_seed_and_missing_node_are_incomplete(self):
        graph, domain = self.build()
        empty = replace(graph, nodes=(), edges=())
        result = self.query(empty, domain)
        self.assertEqual(result.status, CreationStatus.INCOMPLETE)
        self.assertIn("missing_node", result.paths[0].issues)

    def test_scope_mismatch_and_invalid_bounds_fail_explicitly(self):
        graph, domain = self.build()
        with self.assertRaisesRegex(ValueError, "scope mismatch"):
            self.query(graph, replace(domain, snapshot_key="other"))
        for value in (0, -1, True, 1.5):
            with self.assertRaises(ValueError):
                CreationBounds(max_depth=value)

    def test_frame_factory_requires_semantic_owner_and_reviewed_file(self):
        original = self.symbols[:]
        self.symbols = [replace(s, parent_identity=None) if s.identity.value == "frame.create" else s for s in original]
        self.assertEqual(self.query().status, CreationStatus.INCOMPLETE)

        fake_file = RepositoryFile.from_path("unrelated/frame_node.h")
        self.symbols = []
        for symbol in original:
            if symbol.identity.value == "frame":
                location = SourceRange(SourceLocation(fake_file, 1, 1), SourceLocation(fake_file, 1, 10))
                symbol = replace(symbol, declaration=location, definition=location)
            self.symbols.append(symbol)
        self.assertEqual(self.query().status, CreationStatus.INCOMPLETE)

    def test_other_component_branch_does_not_become_a_creation_candidate(self):
        self.facts.append(SymbolSemanticFacts(SymbolIdentity("button.entry"), callees=(SymbolIdentity("text.create"),)))
        result = self.query()
        self.assertEqual(result.status, CreationStatus.COMPLETE)
        self.assertEqual(len(result.paths), 1)
        self.assertTrue(all(n.node.identity.key != "text.create" for n in result.paths[0].nodes))
