from __future__ import annotations

import re
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from arkui_agent.graph import (
    LayoutBounds, LayoutStatus, MappingStatus, NodeIdentity, NodeKind,
    RelationType, RoleCandidate, default_role_mapper, extract_framework_relations, project_index, trace_measure_layout,
)
from arkui_agent.repository import RepositoryFile, RepositoryWorkspace, SourceLocation, SourceRange, Symbol, SymbolIdentity, SymbolIndex, SymbolKind
from arkui_agent.repository.index import SymbolSemanticFacts
from tests.fixtures.framework_repository import FACTORY
from tests.fixtures.layout_cases import ROOT, write_layout_repository


class LayoutTests(unittest.TestCase):
    """Isolated P1 facts; synthetic integration separately uses actual clangd."""

    def setUp(self):
        temp = TemporaryDirectory(prefix="layout-unit-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        write_layout_repository(self.root)
        self.workspace = RepositoryWorkspace(self.root)
        self.index = SymbolIndex(self.root / "p1.sqlite3")
        self.addCleanup(self.index.close)
        self.symbols, self.facts = [], []
        self.pattern_file = f"{ROOT}/button/button_pattern.h"
        self.header = f"{ROOT}/button/button_layout_algorithm.h"
        self.cpp = f"{ROOT}/button/button_layout_algorithm.cpp"
        for suffix, path in (("Pattern", self.pattern_file), ("LayoutAlgorithm", self.header),
                             ("LayoutProperty", f"{ROOT}/button/button_layout_property.h")):
            name = "Button" + suffix
            location = self.token(path, name)
            self.symbols.append(Symbol(self.sid(name), SymbolKind.CLASS, name, self.qualified(name), location, location))
        for owner, method, header in (("ButtonPattern", "CreateLayoutAlgorithm", self.pattern_file),
                                      ("ButtonLayoutAlgorithm", "Measure", self.header),
                                      ("ButtonLayoutAlgorithm", "Layout", self.header)):
            name = owner + "::" + method
            declaration = self.token(header, method)
            definition = declaration if owner == "ButtonPattern" else self.token(self.cpp, method)
            self.symbols.append(Symbol(self.sid(name), SymbolKind.METHOD, method, self.qualified(name),
                                       declaration, definition, self.sid(owner)))
        factory = "OHOS::Ace::Referenced::MakeRefPtr"
        location = self.token(FACTORY, "MakeRefPtr")
        self.symbols.append(Symbol(SymbolIdentity(factory), SymbolKind.METHOD, "MakeRefPtr", factory, location, location))
        self.facts = [
            SymbolSemanticFacts(self.sid("ButtonPattern::CreateLayoutAlgorithm"), callees=(SymbolIdentity(factory),)),
            SymbolSemanticFacts(self.sid("ButtonLayoutAlgorithm"), references=(self.token(self.pattern_file, "ButtonLayoutAlgorithm"),)),
            SymbolSemanticFacts(self.sid("ButtonLayoutProperty"), references=(self.token(self.cpp, "ButtonLayoutProperty"),
                               self.token(self.cpp, "ButtonLayoutProperty", 1))),
        ]

    @staticmethod
    def qualified(name):
        return "OHOS::Ace::NG::" + name

    def sid(self, name):
        return SymbolIdentity(self.qualified(name))

    def nid(self, name):
        return NodeIdentity.for_symbol(self.sid(name))

    def token(self, path, token, occurrence=0):
        text = (self.root / path).read_text(encoding="utf-8")
        match = tuple(re.finditer(r"\b" + re.escape(token) + r"\b", text))[occurrence]
        file = RepositoryFile.from_path(path)
        line = text.count("\n", 0, match.start()) + 1
        column = match.start() - text.rfind("\n", 0, match.start())
        return SourceRange(SourceLocation(file, line, column), SourceLocation(file, line, column + len(token)))

    def build(self):
        self.index.rebuild(self.symbols, semantic_facts=self.facts)
        self.generic = project_index(self.index, repository_key="layout-unit", snapshot_key="v1")
        self.domain = default_role_mapper().map(self.index, self.generic)
        return extract_framework_relations(self.index, self.generic, self.domain, self.workspace).graph

    def trace(self, graph=None, **kwargs):
        if graph is None:
            graph = self.build()
        return trace_measure_layout(self.index, graph, self.domain, self.workspace,
                                    seed=self.nid("ButtonPattern"), component=NodeIdentity("arkui.component", "button"), **kwargs)

    def test_complete_separate_bindings_definitions_and_property_references(self):
        trace = self.trace()
        self.assertEqual(trace.status, LayoutStatus.COMPLETE)
        self.assertEqual(tuple(s.stage.value for s in trace.stages),
                         ("pattern", "factory", "algorithm", "measure", "layout", "layout_property"))
        self.assertEqual([e.identity.relation for e in trace.bindings],
                         [RelationType.CREATE, RelationType.MEASURE, RelationType.LAYOUT])
        self.assertEqual(len(trace.calls), 1)  # actual factory allocation only
        self.assertEqual(len(trace.dependencies), 2)
        self.assertTrue(all(d.reference.identity.source.namespace == "file" for d in trace.dependencies))
        self.assertTrue(all(n.evidence and all(p.anchor.source_range for p in n.evidence)
                            for s in trace.stages for n in s.candidates))
        self.assertTrue(all(any("sha256=" in p.description for p in e.evidence) for e in trace.bindings))

    def test_missing_support_never_backfilled_from_index(self):
        graph = self.build()
        for relation, target, gap in (
            (RelationType.CALL, None, "missing_create_binding"),
            (RelationType.REFERENCE, self.nid("ButtonLayoutAlgorithm"), "missing_algorithm_reference"),
            (RelationType.DEFINE, self.nid("ButtonPattern::CreateLayoutAlgorithm"), "missing_factory_definition"),
            (RelationType.DEFINE, self.nid("ButtonLayoutAlgorithm::Measure"), "missing_measure_implementation"),
            (RelationType.DECLARE, self.nid("ButtonLayoutAlgorithm::Layout"), "missing_layout_binding"),
            (RelationType.CREATE, None, "missing_create_binding"),
            (RelationType.MEASURE, None, "missing_measure_binding"),
            (RelationType.LAYOUT, None, "missing_layout_binding"),
            (RelationType.REFERENCE, self.nid("ButtonLayoutProperty"), "missing_property_reference"),
        ):
            with self.subTest(relation=relation, target=target):
                partial = replace(graph, edges=tuple(e for e in graph.edges if not
                                  (e.identity.relation == relation and (target is None or e.identity.target == target))))
                trace = self.trace(partial)
                self.assertEqual(trace.status, LayoutStatus.INCOMPLETE)
                self.assertIn(gap, trace.gaps)

    def test_missing_node_does_not_restore_factory(self):
        graph = self.build()
        target = self.nid("ButtonPattern::CreateLayoutAlgorithm")
        graph = replace(graph, nodes=tuple(n for n in graph.nodes if n.identity != target),
                        edges=tuple(e for e in graph.edges if target not in (e.identity.source, e.identity.target)))
        self.assertIn("missing_factory", self.trace(graph).gaps)

    def test_missing_semantic_parent_is_not_replaced_by_qualified_name(self):
        self.symbols = [replace(s, parent_identity=None) if s.display_name == "Layout" else s for s in self.symbols]
        self.assertIn("missing_layout_binding", self.trace().gaps)

    def test_declaration_is_not_implementation(self):
        self.symbols = [replace(s, definition=None) if s.display_name == "Layout" else s for s in self.symbols]
        trace = self.trace()
        self.assertIn("missing_layout_implementation", trace.gaps)
        self.assertNotIn("layout", [s.stage.value for s in trace.stages])

    def test_multiple_operation_and_factory_identities_are_ambiguous(self):
        original = self.symbols[:]
        for method, gap in (("Measure", "ambiguous_measure_identity"), ("Layout", "ambiguous_layout_identity"),
                             ("CreateLayoutAlgorithm", "ambiguous_factory_identity")):
            symbol = next(s for s in original if s.display_name == method)
            self.symbols = original + [replace(symbol, identity=SymbolIdentity("overload:" + method))]
            trace = self.trace()
            self.assertEqual(trace.status, LayoutStatus.AMBIGUOUS)
            self.assertIn(gap, trace.gaps)
            stage = next(s for s in trace.stages if s.stage.value == {"Measure": "measure", "Layout": "layout",
                                                                    "CreateLayoutAlgorithm": "factory"}[method])
            self.assertEqual(len(stage.candidates), 2)

    def test_conflicting_algorithm_reference_identities(self):
        original = next(s for s in self.symbols if s.display_name == "ButtonLayoutAlgorithm")
        other = replace(original, identity=SymbolIdentity("other-algorithm"))
        self.symbols.append(other)
        self.facts.append(SymbolSemanticFacts(other.identity, references=(self.token(self.pattern_file, "ButtonLayoutAlgorithm"),)))
        trace = self.trace()
        self.assertEqual(trace.status, LayoutStatus.AMBIGUOUS)
        self.assertEqual(len(trace.candidates), 2)
        self.assertFalse(trace.bindings)

    def test_property_conflicting_identity_keeps_candidates(self):
        original = next(s for s in self.symbols if s.display_name == "ButtonLayoutProperty")
        other = replace(original, identity=SymbolIdentity("other-property"))
        self.symbols.append(other)
        self.facts.append(SymbolSemanticFacts(other.identity, references=(self.token(self.cpp, "ButtonLayoutProperty"),)))
        trace = self.trace()
        self.assertEqual(trace.status, LayoutStatus.AMBIGUOUS)
        self.assertIn("ambiguous_property_identity", trace.gaps)
        self.assertEqual(len(trace.candidates), 2)

    def test_conditional_factory_keeps_all_referenced_types_without_create(self):
        path = self.root / self.pattern_file
        path.write_text(path.read_text().replace("CreateLayoutAlgorithm()", "CreateLayoutAlgorithm(int mode)").replace(
            "return MakeRefPtr<ButtonLayoutAlgorithm>();",
            "switch (mode) { case 1: return MakeRefPtr<TextLayoutAlgorithm>(); "
            "default: return MakeRefPtr<ButtonLayoutAlgorithm>(); }"))
        location = self.token(f"{ROOT}/text/text_layout_algorithm.h", "TextLayoutAlgorithm")
        self.symbols.append(Symbol(self.sid("TextLayoutAlgorithm"), SymbolKind.CLASS, "TextLayoutAlgorithm",
                                   self.qualified("TextLayoutAlgorithm"), location, location))
        self.facts.append(SymbolSemanticFacts(self.sid("TextLayoutAlgorithm"),
                          references=(self.token(self.pattern_file, "TextLayoutAlgorithm"),)))
        self.facts = [replace(f, references=(self.token(self.pattern_file, "ButtonLayoutAlgorithm"),))
                      if f.identity == self.sid("ButtonLayoutAlgorithm") else f for f in self.facts]
        trace = self.trace()
        self.assertEqual(trace.status, LayoutStatus.AMBIGUOUS)
        self.assertEqual(len(trace.candidates), 2)
        self.assertEqual(trace.gaps, ("ambiguous_algorithm_identity", "missing_create_binding"))
        self.assertFalse(trace.bindings)
        self.assertEqual(len(trace.calls), 1)
        self.assertTrue(any(p.provenance == "p2.layout.v1.factory_candidates" for p in trace.source_evidence))

    def test_parameterized_factory_cannot_borrow_simple_create(self):
        graph = self.build()
        path = self.root / self.pattern_file
        path.write_text(path.read_text().replace("MakeRefPtr<ButtonLayoutAlgorithm>()", "MakeRefPtr<ButtonLayoutAlgorithm>(value)"))
        trace = self.trace(graph)
        self.assertIn("missing_create_binding", trace.gaps)
        self.assertEqual(len(trace.candidates), 1)
        self.assertFalse(trace.bindings)

    def test_measure_content_is_measure_and_competes_with_measure(self):
        header = self.root / self.header
        header.write_text(header.read_text().replace("    void Layout(",
                         "    std::optional<SizeF> MeasureContent(\n"
                         "        const LayoutConstraintF& contentConstraint, LayoutWrapper* layoutWrapper) override;\n"
                         "    void Layout("))
        cpp = self.root / self.cpp
        cpp.write_text(cpp.read_text() + "\nstd::optional<SizeF> ButtonLayoutAlgorithm::MeasureContent(\n"
                       "    const LayoutConstraintF& contentConstraint, LayoutWrapper* layoutWrapper)\n{\n"
                       "    auto property = DynamicCast<ButtonLayoutProperty>(layoutWrapper->GetLayoutProperty());\n}\n")
        # Refresh changed P1 anchors instead of borrowing the old Layout line.
        self.symbols = [replace(s, declaration=self.token(self.header, "Layout")) if s.display_name == "Layout" else s
                        for s in self.symbols]
        self.symbols.append(Symbol(self.sid("ButtonLayoutAlgorithm::MeasureContent"), SymbolKind.METHOD, "MeasureContent",
                                   self.qualified("ButtonLayoutAlgorithm::MeasureContent"), self.token(self.header, "MeasureContent"),
                                   self.token(self.cpp, "MeasureContent"), self.sid("ButtonLayoutAlgorithm")))
        self.facts = [replace(f, references=f.references + (self.token(self.cpp, "ButtonLayoutProperty", 2),))
                      if f.identity == self.sid("ButtonLayoutProperty") else f for f in self.facts]
        trace = self.trace()
        self.assertEqual(trace.status, LayoutStatus.AMBIGUOUS)
        self.assertIn("ambiguous_measure_identity", trace.gaps)
        self.assertEqual(sum(e.identity.relation == RelationType.MEASURE for e in trace.bindings), 2)
        self.assertEqual(sum(e.identity.relation == RelationType.LAYOUT for e in trace.bindings), 1)

    def test_property_reference_in_another_function_is_not_a_dependency(self):
        self.facts = [replace(f, references=(self.token(f"{ROOT}/button/button_layout_property.h", "ButtonLayoutProperty"),))
                      if f.identity == self.sid("ButtonLayoutProperty") else f for f in self.facts]
        trace = self.trace()
        self.assertEqual(trace.status, LayoutStatus.INCOMPLETE)
        self.assertIn("missing_property_reference", trace.gaps)
        self.assertFalse(trace.dependencies)

    def test_role_conflicts_and_ambiguity_are_not_selected(self):
        for name, label in (("ButtonPattern", "pattern"), ("ButtonLayoutAlgorithm", "algorithm"),
                            ("ButtonLayoutProperty", "property")):
            for ambiguous in (False, True):
                graph = self.build()
                identity = self.nid(name)
                mapping = self.domain.lookup(identity)
                wrong = RoleCandidate(NodeKind.PAINT_PROPERTY, mapping.resolved.component, mapping.resolved.evidence)
                changed = replace(mapping, status=MappingStatus.AMBIGUOUS if ambiguous else MappingStatus.RECOGNIZED,
                                  candidates=mapping.candidates + (wrong,) if ambiguous else (wrong,))
                self.domain = replace(self.domain, mappings=tuple(changed if m.identity == identity else m for m in self.domain.mappings))
                trace = self.trace(graph)
                self.assertEqual(trace.status, LayoutStatus.AMBIGUOUS, (name, ambiguous, trace.gaps))
                self.assertIn("ambiguous_" + label + ("_role" if ambiguous else "_role_conflict"), trace.gaps)
                self.assertTrue(any(c.node.identity == identity for c in trace.candidates))

    def test_nearby_or_comment_property_cannot_be_borrowed(self):
        original = (self.root / self.cpp).read_text()
        for prefix in ("return; }\nvoid Nearby() {", "// ", "if (true) { ", "/* "):
            (self.root / self.cpp).write_text(original.replace("    auto property", "    " + prefix + "auto property", 1))
            trace = self.trace()
            self.assertEqual(trace.status, LayoutStatus.INCOMPLETE)
            self.assertTrue(any(g.startswith("unsupported_property_preamble:") for g in trace.gaps))
            self.assertFalse(any(d.operation == self.nid("ButtonLayoutAlgorithm::Measure") for d in trace.dependencies))

    def test_source_change_invalidates_create(self):
        graph = self.build()
        path = self.root / self.pattern_file
        path.write_text(path.read_text().replace("return MakeRefPtr", "if (false) return nullptr; return MakeRefPtr"))
        self.assertIn("unsupported_factory_body", self.trace(graph).gaps)

    def test_actual_call_cycle_is_retained_once_without_recursive_expansion(self):
        identity = self.sid("ButtonLayoutAlgorithm::Measure")
        self.facts.append(SymbolSemanticFacts(identity, callees=(identity, self.sid("ButtonLayoutAlgorithm::Layout"))))
        trace = self.trace()
        self.assertEqual(trace.status, LayoutStatus.COMPLETE)
        self.assertEqual(len(trace.calls), 3)
        self.assertEqual(len(trace.bindings), 3)
        limited = self.trace(bounds=LayoutBounds(max_calls=1))
        self.assertFalse(limited.exhaustive)
        self.assertEqual(limited.status, LayoutStatus.INCOMPLETE)
        self.assertIn("support_call_limit", limited.gaps)

    def test_candidate_limit_does_not_turn_ambiguity_into_unique_result(self):
        method = next(s for s in self.symbols if s.display_name == "Measure")
        self.symbols.append(replace(method, identity=SymbolIdentity("second-measure")))
        trace = self.trace(bounds=LayoutBounds(max_candidates=1))
        self.assertEqual(trace.status, LayoutStatus.AMBIGUOUS)
        self.assertFalse(trace.exhaustive)
        self.assertIn("measure_candidate_limit", trace.gaps)

    def test_snapshot_mismatch_and_backend_failures_propagate(self):
        graph = self.build()
        with self.assertRaises(ValueError):
            self.trace(replace(graph, snapshot_key="other"))
        with self.assertRaises(FileNotFoundError):
            (self.root / self.pattern_file).unlink()
            self.trace(graph)

    def test_missing_seed(self):
        graph = self.build()
        trace = trace_measure_layout(self.index, graph, self.domain, self.workspace,
                                     seed=NodeIdentity("symbol", "absent"), component=NodeIdentity("arkui.component", "button"))
        self.assertEqual(trace.gaps, ("missing_seed",))

    def test_bounds_validation(self):
        for value in (0, -1, True, 1.5):
            with self.assertRaises(ValueError):
                LayoutBounds(max_candidates=value)

    def test_reversed_rebuild_is_identical(self):
        trace = self.trace()
        self.symbols.reverse()
        self.facts.reverse()
        self.assertEqual(self.trace(), trace)
