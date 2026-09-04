from __future__ import annotations

import re
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from arkui_agent.graph import (
    MappingStatus, NodeIdentity, RelationType, default_role_mapper, extract_framework_relations, project_index,
)
from arkui_agent.repository import (
    RepositoryFile, RepositoryWorkspace, SourceLocation, SourceRange, Symbol, SymbolIdentity, SymbolIndex, SymbolKind,
    TestCase, TestFixture,
)
from arkui_agent.repository.index import SymbolSemanticFacts
from tests.fixtures.framework_repository import FACTORY, MACROS, ROOT, queries, write_repository


class FrameworkTests(unittest.TestCase):
    """Hand-authored P1 facts for unit isolation; integration uses actual clangd."""

    def setUp(self):
        temporary = TemporaryDirectory(prefix="framework-unit-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        write_repository(self.root)
        self.workspace = RepositoryWorkspace(self.root)
        self.index = SymbolIndex(self.root / "p1.sqlite3")
        self.addCleanup(self.index.close)
        self.symbols = []
        for path, names in queries().items():
            for number, name in enumerate(names):
                short = name.rsplit("::", 1)[-1]
                range_ = self.token(path, short)
                self.symbols.append(Symbol(SymbolIdentity(name), SymbolKind.CLASS if number == 0 else SymbolKind.METHOD,
                                           short, name, range_, range_,
                                           None if number == 0 else SymbolIdentity(names[0])))
        factory = "OHOS::Ace::Referenced::MakeRefPtr"
        range_ = self.token(FACTORY, "MakeRefPtr")
        self.symbols.append(Symbol(SymbolIdentity(factory), SymbolKind.METHOD, "MakeRefPtr", factory, range_, range_))
        self.facts = []
        for component in ("Button", "Text", "Menu"):
            prefix = f"OHOS::Ace::NG::{component}"
            slug = component.lower()
            refs = (self.token(f"{ROOT}/{slug}/{slug}_pattern.h", component + "LayoutProperty"),
                    self.token(f"{ROOT}/{slug}/{slug}_model_ng.h", component + "LayoutProperty"))
            self.facts.append(SymbolSemanticFacts(SymbolIdentity(prefix + "LayoutProperty"), references=refs))
            self.facts.append(SymbolSemanticFacts(SymbolIdentity(prefix + "Pattern::CreateLayoutProperty"),
                                                  callees=(SymbolIdentity(factory),)))

    def token(self, path, token):
        text = (self.root / path).read_text(encoding="utf-8")
        match = re.search(r"\b" + re.escape(token) + r"\b", text)
        self.assertIsNotNone(match)
        file = RepositoryFile.from_path(path)
        line = text.count("\n", 0, match.start()) + 1
        column = match.start() - text.rfind("\n", 0, match.start())
        return SourceRange(SourceLocation(file, line, column), SourceLocation(file, line, column + len(token)))

    def build(self, *, domain_change=None, **kwargs):
        self.index.rebuild(self.symbols, semantic_facts=self.facts, **kwargs)
        self.generic = project_index(self.index, repository_key="unit", snapshot_key="v1")
        domain = default_role_mapper().map(self.index, self.generic)
        if domain_change:
            domain = domain_change(domain)
        return extract_framework_relations(self.index, self.generic, domain, self.workspace)

    def edges(self, result, relation):
        return [e for e in result.graph.edges if e.identity.relation == relation]

    def test_six_primitives_and_provenance(self):
        result = self.build()
        for relation, count in ((RelationType.CREATE, 3), (RelationType.UPDATE_PROPERTY, 3),
                                (RelationType.MEASURE, 3), (RelationType.LAYOUT, 1),
                                (RelationType.SHOW, 1), (RelationType.CLOSE, 1)):
            found = self.edges(result, relation)
            self.assertEqual(len(found), count, result.diagnostics)
            for edge in found:
                self.assertTrue(any(e.provenance.endswith(".generic") for e in edge.evidence))
                self.assertTrue(any(e.provenance.startswith("p1.") for e in edge.evidence))
                self.assertTrue(any(e.provenance.startswith("arkui.role.") for e in edge.evidence))
                self.assertTrue(any(e.anchor.source_range is not None and "sha256" in e.description
                                    for e in edge.evidence))

    def test_missing_reference_never_infers_target_by_name(self):
        self.facts = [replace(f, references=()) for f in self.facts]
        result = self.build()
        self.assertEqual(self.edges(result, RelationType.CREATE), [])
        self.assertEqual(self.edges(result, RelationType.UPDATE_PROPERTY), [])
        self.assertTrue(any(d.reason == "missing_reference" for d in result.diagnostics))

    def test_missing_factory_call_does_not_accept_make_ref_ptr_text(self):
        self.facts = [replace(f, callees=()) for f in self.facts]
        result = self.build()
        self.assertEqual(self.edges(result, RelationType.CREATE), [])
        self.assertTrue(any(d.reason == "missing_or_ambiguous_semantic_factory_call" for d in result.diagnostics))

    def test_factory_implementation_must_allocate(self):
        path = self.root / FACTORY
        path.write_text(path.read_text().replace("new T(std::forward<Args>(args)...)", "nullptr"))
        self.assertEqual(self.edges(self.build(), RelationType.CREATE), [])

    def test_noop_or_redefined_macro_is_not_update(self):
        path = self.root / MACROS
        original = path.read_text()
        for content in (original.replace("cast##target->Update##name(value);", "(void)value;"),
                        original + "\n#define ACE_UPDATE_LAYOUT_PROPERTY(target, name, value) ((void)0)\n"):
            path.write_text(content)
            result = self.build()
            self.assertEqual(self.edges(result, RelationType.UPDATE_PROPERTY), [])
            self.assertTrue(any(d.reason == "unsupported_macro_definition" for d in result.diagnostics))

    def test_paint_property_macro_uses_the_same_semantic_contract(self):
        macro = self.root / MACROS
        macro.write_text(macro.read_text() + macro.read_text().replace("LAYOUT", "PAINT").replace("Layout", "Paint"))
        path = f"{ROOT}/menu/menu_paint_property.h"
        (self.root / path).write_text("class MenuPaintProperty {};\n")
        range_ = self.token(path, "MenuPaintProperty")
        identity = SymbolIdentity("paint")
        self.symbols.append(Symbol(identity, SymbolKind.CLASS, "MenuPaintProperty",
                                   "OHOS::Ace::NG::MenuPaintProperty", range_, range_))
        model_path = f"{ROOT}/menu/menu_model_ng.h"
        model = self.root / model_path
        model.write_text(model.read_text().replace("ACE_UPDATE_LAYOUT_PROPERTY(MenuLayoutProperty",
                                                   "ACE_UPDATE_PAINT_PROPERTY(MenuPaintProperty"))
        self.facts.append(SymbolSemanticFacts(identity, references=(self.token(model_path, "MenuPaintProperty"),)))
        result = self.build()
        self.assertTrue(any(e.identity.target == NodeIdentity.for_symbol(identity)
                            for e in self.edges(result, RelationType.UPDATE_PROPERTY)))

    def test_operation_requires_signature_and_semantic_parent(self):
        path = self.root / f"{ROOT}/menu/menu_layout_algorithm.h"
        path.write_text(path.read_text().replace("void Layout(LayoutWrapper* layoutWrapper) override;", "void Layout(int x);"))
        result = self.build()
        self.assertEqual(self.edges(result, RelationType.LAYOUT), [])
        self.symbols = [replace(s, parent_identity=None) if s.kind == SymbolKind.METHOD else s for s in self.symbols]
        result = self.build()
        self.assertEqual(self.edges(result, RelationType.MEASURE), [])

    def test_complex_body_is_diagnostic_and_does_not_scan_later_method(self):
        path = self.root / f"{ROOT}/button/button_pattern.h"
        path.write_text(path.read_text().replace("return MakeRefPtr", "if (false) return nullptr;\n        return MakeRefPtr"))
        result = self.build()
        self.assertEqual(len(self.edges(result, RelationType.CREATE)), 2)
        self.assertTrue(any(d.reason == "unsupported_body_template" for d in result.diagnostics))

    def test_second_overload_on_same_line_cannot_borrow_first_signature(self):
        path = f"{ROOT}/menu/menu_layout_algorithm.h"
        file = self.root / path
        file.write_text(file.read_text().replace("void Layout(LayoutWrapper* layoutWrapper) override;",
                                                "void Layout(LayoutWrapper* layoutWrapper) override; void Layout(int x);"))
        original = next(s for s in self.symbols if s.qualified_name.endswith("MenuLayoutAlgorithm::Layout"))
        start = original.declaration.start
        # Calculate the actual second token position; both overloads have the
        # same parent/name/file but must retain distinct P1 identities.
        line = file.read_text().splitlines()[start.line - 1]
        start = replace(start, column=line.rindex("Layout(") + 1)
        range_ = SourceRange(start, replace(start, column=start.column + 6))
        self.symbols.append(replace(original, identity=SymbolIdentity("second-overload"),
                                    declaration=range_, definition=range_))
        result = self.build()
        found = self.edges(result, RelationType.LAYOUT)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].identity.target, NodeIdentity.for_symbol(original.identity))

    def test_unknown_ambiguous_and_cross_component_are_excluded(self):
        target = NodeIdentity.for_symbol(SymbolIdentity("OHOS::Ace::NG::ButtonLayoutProperty"))
        for status in (MappingStatus.UNKNOWN, MappingStatus.AMBIGUOUS):
            result = self.build(domain_change=lambda d: replace(d, mappings=tuple(
                replace(m, status=status) if m.identity == target else m for m in d.mappings)))
            self.assertFalse(any(e.identity.target == target for r in (RelationType.CREATE, RelationType.UPDATE_PROPERTY)
                                 for e in self.edges(result, r)))
        result = self.build(domain_change=lambda d: replace(d, mappings=tuple(
            replace(m, candidates=(replace(m.resolved, component=NodeIdentity("arkui.component", "menu")),))
            if m.identity == target else m for m in d.mappings)))
        self.assertFalse(any(e.identity.target == target for e in self.edges(result, RelationType.CREATE)))

    def test_multiple_reference_identities_are_ambiguous(self):
        original = next(s for s in self.symbols if s.qualified_name == "OHOS::Ace::NG::ButtonLayoutProperty")
        other = replace(original, identity=SymbolIdentity("distinct-identity"))
        self.symbols.append(other)
        self.facts.append(replace(next(f for f in self.facts if f.identity == original.identity), identity=other.identity))
        result = self.build()
        self.assertEqual(len(self.edges(result, RelationType.CREATE)), 2)
        self.assertTrue(any(d.reason == "ambiguous_reference" for d in result.diagnostics))

    def test_rebuild_dedup_and_order_are_deterministic(self):
        result = self.build()
        self.symbols.reverse()
        self.facts = list(reversed(self.facts)) + self.facts
        self.assertEqual(self.build(), result)
        self.assertEqual(result.graph.nodes, self.generic.nodes)

    def test_scope_stale_projection_and_reextract_fail_explicitly(self):
        result = self.build()
        domain = default_role_mapper().map(self.index, self.generic)
        with self.assertRaisesRegex(ValueError, "scope mismatch"):
            extract_framework_relations(self.index, self.generic, replace(domain, snapshot_key="stale"), self.workspace)
        with self.assertRaisesRegex(ValueError, "generic projection"):
            extract_framework_relations(self.index, result.graph, domain, self.workspace)
        self.index.rebuild(())
        with self.assertRaisesRegex(ValueError, "generic projection"):
            extract_framework_relations(self.index, self.generic, domain, self.workspace)

    def test_test_mapping_enrichment_and_mock_unavailable(self):
        target = self.symbols[1]
        file = RepositoryFile.from_path("tests/case.cpp")
        body = SourceRange(SourceLocation(file, 2, 1), SourceLocation(file, 8, 1))
        ref = SourceRange(SourceLocation(file, 4, 3), SourceLocation(file, 4, 8))
        fixture = TestFixture(SymbolIdentity("fixture"), "Fixture", body)
        case = TestCase(SymbolIdentity("case"), "Case", fixture.identity, body, body)
        self.facts.append(SymbolSemanticFacts(target.identity, references=(ref,)))
        result = self.build(test_fixtures=(fixture,), test_cases=(case,))
        found = self.edges(result, RelationType.TEST)
        self.assertEqual(len(found), 2)
        direct = next(e for e in found if e.identity.target == NodeIdentity.for_symbol(target.identity))
        self.assertTrue(any(e.provenance == "arkui.framework.v1.test.generic" for e in direct.evidence))
        self.assertTrue(any(e.provenance == "p1.tested_symbol_mapping.references" for e in direct.evidence))
        self.assertEqual(self.edges(result, RelationType.MOCK), [])
        self.assertTrue(any(d.reason == "unsupported_p1_mock_facts" for d in result.diagnostics))
