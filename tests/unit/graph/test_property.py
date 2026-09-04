from __future__ import annotations

import re
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from arkui_agent.graph import (
    MappingStatus, NodeIdentity, NodeKind, PropertyBounds, PropertyStatus, RelationType,
    default_role_mapper, extract_framework_relations, project_index, trace_property_update,
)
from arkui_agent.repository import (
    RepositoryFile, RepositoryWorkspace, SourceLocation, SourceRange, Symbol, SymbolIdentity, SymbolIndex, SymbolKind,
)
from arkui_agent.repository.index import SymbolSemanticFacts
from tests.fixtures.property_cases import MACROS, ROOT, write_property_repository


def nid(key):
    return NodeIdentity.for_symbol(SymbolIdentity(key))


class PropertyTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory(prefix="property-unit-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        write_property_repository(self.root)
        self.workspace = RepositoryWorkspace(self.root)
        self.index = SymbolIndex(self.root / "index.sqlite3")
        self.addCleanup(self.index.close)
        self.symbols = []
        self.facts = []
        for name in ("Button", "Text", "Menu"):
            key = name.lower()
            kind = "Paint" if name == "Menu" else "Layout"
            model = f"{ROOT}/{key}/{key}_model_ng.h"
            prop = f"{ROOT}/{key}/{key}_{kind.lower()}_property.h"
            entry = f"{ROOT}/{key}/property_entry.cpp"
            self.add(key + ".model", name + "ModelNG", model, name + "ModelNG", SymbolKind.CLASS)
            self.add(key + ".setter", name + "ModelNG::SetFontWeight", model, "SetFontWeight", SymbolKind.METHOD, key + ".model")
            self.add(key + ".overload", name + "ModelNG::SetFontWeight", model, "SetFontWeight", SymbolKind.METHOD,
                     key + ".model", occurrence=1)
            self.add(key + ".property", name + kind + "Property", prop, name + kind + "Property", SymbolKind.CLASS)
            self.add(key + ".writer", name + kind + "Property::UpdateFontWeight", prop, "UpdateFontWeight", SymbolKind.METHOD, key + ".property")
            self.add(key + ".reader", name + kind + "Property::ReadWeight", prop, "ReadWeight", SymbolKind.METHOD, key + ".property")
            self.add(key + ".state", name + kind + "Property::weight", prop, "weight", SymbolKind.FIELD, key + ".property")
            self.add(key + ".entry", "Apply" + name + "Weight", entry, "Apply" + name + "Weight", SymbolKind.FUNCTION)
            self.add(key + ".consumer", "Consume" + name + "Weight", entry, "Consume" + name + "Weight", SymbolKind.FUNCTION)
            self.facts.extend((
                SymbolSemanticFacts(SymbolIdentity(key + ".entry"), callees=(SymbolIdentity(key + ".setter"),)),
                SymbolSemanticFacts(SymbolIdentity(key + ".setter"), callees=(SymbolIdentity(key + ".writer"),)),
                SymbolSemanticFacts(SymbolIdentity(key + ".consumer"), callees=(SymbolIdentity(key + ".reader"),)),
                SymbolSemanticFacts(SymbolIdentity(key + ".property"), references=(self.range(model, name + kind + "Property"),)),
                SymbolSemanticFacts(SymbolIdentity(key + ".state"), references=(self.range(prop, "weight", 1), self.range(prop, "weight", 2))),
            ))

    def range(self, path, token, occurrence=0):
        text = (self.root / path).read_text(encoding="utf-8")
        match = list(re.finditer(r"\b" + re.escape(token) + r"\b", text))[occurrence]
        file = RepositoryFile.from_path(path)
        start = SourceLocation(file, text.count("\n", 0, match.start()) + 1, match.start() - text.rfind("\n", 0, match.start()))
        return SourceRange(start, replace(start, column=start.column + len(token)))

    def add(self, key, qualified, path, token, kind, parent=None, occurrence=0):
        range_ = self.range(path, token, occurrence)
        self.symbols.append(Symbol(SymbolIdentity(key), kind, token, "OHOS::Ace::NG::" + qualified,
                                   range_, range_, SymbolIdentity(parent) if parent else None))

    def build(self):
        self.index.rebuild(self.symbols, semantic_facts=self.facts)
        generic = project_index(self.index, repository_key="unit", snapshot_key="v1")
        domain = default_role_mapper().map(self.index, generic)
        return extract_framework_relations(self.index, generic, domain, self.workspace).graph, domain

    def query(self, graph=None, domain=None, component="button", **kwargs):
        if graph is None:
            graph, domain = self.build()
        return trace_property_update(self.index, graph, domain, self.workspace,
            seed=kwargs.pop("seed", nid(component + ".entry")), setter=kwargs.pop("setter", nid(component + ".setter")),
            component=NodeIdentity("arkui.component", component), **kwargs)

    def test_complete_layout_and_paint_with_exact_state_identity(self):
        for component, kind in (("button", "layout_property"), ("text", "layout_property"), ("menu", "paint_property")):
            result = self.query(component=component)
            self.assertEqual(result.status, PropertyStatus.COMPLETE, result)
            path = result.paths[0]
            self.assertEqual([n.stage.value for n in path.nodes], ["entry", "model", kind, "writer", "state", "reader", "consumer"])
            self.assertEqual(path.binding.token, "FontWeight")
            self.assertEqual(len(path.calls), 1)
            self.assertEqual(path.nodes[4].node.identity, nid(component + ".state"))
            self.assertTrue(all(n.evidence and any(a.source_range for a in n.node.anchors) for n in path.nodes))
            self.assertEqual(path.support[-1].identity.source, nid(component + ".consumer"))
            self.assertEqual(path.support[-1].identity.target, nid(component + ".reader"))
            self.assertTrue(any("sha256=" in e.description for n in path.nodes for e in n.evidence))

    def test_same_name_overload_is_not_substituted(self):
        result = self.query(setter=nid("button.overload"))
        self.assertEqual(result.status, PropertyStatus.INCOMPLETE)
        self.assertEqual(result.paths[0].gaps, ("missing_setter_call",))

    def test_namespace_and_parent_are_not_name_guesses(self):
        self.symbols = [replace(s, parent_identity=SymbolIdentity("text.model")) if s.identity.value == "button.setter" else s
                        for s in self.symbols]
        result = self.query()
        self.assertEqual(result.status, PropertyStatus.INCOMPLETE)
        self.assertIn("unknown_or_cross_component_model", result.paths[0].gaps)

    def test_missing_call_reference_domain_binding_and_consumer(self):
        graph, domain = self.build()
        for remove, gap in (
            (lambda e: e.identity.relation == RelationType.CALL and e.identity.source == nid("button.entry"), "missing_setter_call"),
            (lambda e: e.identity.relation == RelationType.REFERENCE and e.identity.target == nid("button.property"), "missing_property_reference"),
            (lambda e: e.identity.relation == RelationType.UPDATE_PROPERTY, "missing_update_binding"),
            (lambda e: e.identity.relation == RelationType.CALL and e.identity.source == nid("button.consumer"), "missing_downstream_consumer"),
        ):
            result = self.query(replace(graph, edges=tuple(e for e in graph.edges if not remove(e))), domain)
            self.assertEqual(result.status, PropertyStatus.INCOMPLETE)
            self.assertIn(gap, result.paths[0].gaps)

    def test_same_named_reader_of_other_state_is_not_a_consumer(self):
        self.facts = [replace(f, references=f.references[:1]) if f.identity.value == "button.state" else f for f in self.facts]
        result = self.query()
        self.assertEqual(result.paths[0].gaps, ("missing_downstream_consumer",))

    def test_macro_call_artifact_cannot_impersonate_member_identity(self):
        self.facts = [replace(f, callees=(SymbolIdentity("button.property"),)) if f.identity.value == "button.setter" else f for f in self.facts]
        result = self.query()
        self.assertEqual(result.paths[0].gaps, ("missing_property_writer",))

    def test_ambiguous_property_identity_and_role(self):
        graph, domain = self.build()
        for status in (MappingStatus.AMBIGUOUS, MappingStatus.UNKNOWN):
            changed = replace(domain, mappings=tuple(replace(m, status=status) if m.identity == nid("button.property") else m for m in domain.mappings))
            result = self.query(graph, changed)
            self.assertEqual(result.status, PropertyStatus.AMBIGUOUS if status == MappingStatus.AMBIGUOUS else PropertyStatus.INCOMPLETE)
            self.assertEqual(result.paths[0].candidates, (nid("button.property"),))
        prop = next(s for s in self.symbols if s.identity.value == "button.property")
        self.symbols.append(replace(prop, identity=SymbolIdentity("duplicate")))
        self.facts.append(replace(next(f for f in self.facts if f.identity == prop.identity), identity=SymbolIdentity("duplicate")))
        self.assertEqual(self.query().status, PropertyStatus.AMBIGUOUS)

    def test_layout_paint_conflict_is_ambiguous(self):
        graph, domain = self.build()
        domain = replace(domain, mappings=tuple(replace(m, candidates=(replace(m.resolved, role=NodeKind.PAINT_PROPERTY),))
                         if m.identity == nid("button.property") else m for m in domain.mappings))
        self.assertEqual(self.query(graph, domain).status, PropertyStatus.AMBIGUOUS)

    def diamond(self):
        (self.root / "helpers.cpp").write_text("void Left() {}\nvoid Right() {}\n", encoding="utf-8")
        for name in ("Left", "Right"):
            self.add(name, name, "helpers.cpp", name, SymbolKind.FUNCTION)
            self.facts.append(SymbolSemanticFacts(SymbolIdentity(name), callees=(SymbolIdentity("button.setter"),)))
        self.facts = [replace(f, callees=(SymbolIdentity("Left"), SymbolIdentity("Right"))) if f.identity.value == "button.entry" else f for f in self.facts]

    def test_multiple_paths_preserved_and_deterministic(self):
        self.diamond()
        result = self.query()
        self.assertEqual(result.status, PropertyStatus.AMBIGUOUS)
        self.assertEqual(len(result.paths), 2)
        self.assertTrue(all(p.status == PropertyStatus.COMPLETE for p in result.paths))
        self.symbols.reverse()
        self.facts.reverse()
        self.assertEqual(self.query(), result)

    def test_bounds_and_cycle_do_not_claim_unique_complete(self):
        self.diamond()
        for bounds in (PropertyBounds(max_depth=1), PropertyBounds(max_paths=1), PropertyBounds(max_states=1)):
            result = self.query(bounds=bounds)
            self.assertFalse(result.exhaustive)
            self.assertNotEqual(result.status, PropertyStatus.COMPLETE)
        self.facts.append(SymbolSemanticFacts(SymbolIdentity("Left"), callees=(SymbolIdentity("button.entry"),)))
        result = self.query()
        self.assertIn("cycle_cut", result.diagnostics)
        for invalid in (0, -1, True, 1.2):
            with self.assertRaises(ValueError):
                PropertyBounds(max_depth=invalid)

    def test_changed_macro_invalidates_previous_domain_binding(self):
        graph, domain = self.build()
        path = self.root / MACROS
        path.write_text(path.read_text(encoding="utf-8").replace("Update##name(value)", "Ignore##name(value)"), encoding="utf-8")
        self.assertEqual(self.query(graph, domain).paths[0].gaps, ("missing_update_binding",))

    def test_multiple_consumers_retain_ambiguity(self):
        consumer = next(s for s in self.symbols if s.identity.value == "button.consumer")
        self.symbols.append(replace(consumer, identity=SymbolIdentity("consumer2")))
        self.facts.append(SymbolSemanticFacts(SymbolIdentity("consumer2"), callees=(SymbolIdentity("button.reader"),)))
        self.assertEqual(self.query().status, PropertyStatus.AMBIGUOUS)

    def test_scope_mismatch_fails(self):
        graph, domain = self.build()
        with self.assertRaises(ValueError):
            self.query(graph, replace(domain, snapshot_key="other"))

    def test_unsupported_native_macro_does_not_borrow_stack_overload_binding(self):
        graph, domain = self.build()
        path = self.root / ROOT / "button/button_model_ng.h"
        text = path.read_text(encoding="utf-8").replace(
            "ACE_UPDATE_LAYOUT_PROPERTY(ButtonLayoutProperty, FontWeight, value)",
            "ACE_UPDATE_NODE_LAYOUT_PROPERTY(ButtonLayoutProperty, FontWeight, value, frameNode)")
        path.write_text(text, encoding="utf-8")
        result = self.query(graph, domain)
        self.assertEqual(result.paths[0].gaps, ("missing_update_binding",))
        self.assertIsNone(result.paths[0].binding)

    def test_ambiguous_field_reference_keeps_candidates_and_evidence(self):
        state = next(s for s in self.symbols if s.identity.value == "button.state")
        self.symbols.append(replace(state, identity=SymbolIdentity("duplicate-state")))
        self.facts.append(replace(next(f for f in self.facts if f.identity == state.identity), identity=SymbolIdentity("duplicate-state")))
        result = self.query()
        self.assertEqual(result.status, PropertyStatus.AMBIGUOUS)
        self.assertIn(nid("duplicate-state"), result.paths[0].candidates)
        self.assertTrue(any(e.anchor.symbol_identity == SymbolIdentity("duplicate-state")
                            for e in result.paths[0].candidate_evidence))

    def test_assignment_must_use_the_actual_writer_parameter(self):
        graph, domain = self.build()
        path = self.root / ROOT / "button/button_layout_property.h"
        path.write_text(path.read_text(encoding="utf-8").replace("weight = value;", "weight = 123;"), encoding="utf-8")
        # Even a genuine CALL to this member no longer proves value propagation.
        result = self.query(graph, domain)
        self.assertEqual(result.status, PropertyStatus.INCOMPLETE)
        self.assertIn("unsupported_property_write", result.paths[0].gaps)
