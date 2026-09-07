from __future__ import annotations

import re
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from arkui_agent.graph import (
    MappingStatus, NodeIdentity, NodeKind, OverlayBounds, OverlayStatus, RelationType, RoleCandidate,
    default_role_mapper, extract_framework_relations, project_index, trace_overlay,
)
from arkui_agent.repository import RepositoryFile, RepositoryWorkspace, SourceLocation, SourceRange, Symbol, SymbolIdentity, SymbolIndex, SymbolKind
from arkui_agent.repository.index import SymbolSemanticFacts
from tests.fixtures.overlay_cases import ANIMATION_H, FRAME_H, MANAGER_CPP, MANAGER_H, NS, PATTERN_H, write_overlay_repository


class OverlayTests(unittest.TestCase):
    """Hand-authored P1 facts for unit isolation; integration uses real clangd."""

    def setUp(self):
        temporary = TemporaryDirectory(prefix="overlay-unit-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.workspace = RepositoryWorkspace(self.root)
        self.index = SymbolIndex(self.root / "p1.sqlite3")
        self.addCleanup(self.index.close)
        self.prepare()

    def prepare(self, animation=True):
        write_overlay_repository(self.root, animation=animation, multiple_close=True)
        self.symbols, self.facts = [], []
        for name, path in (("OverlayManager", MANAGER_H), ("FrameNode", FRAME_H), ("MenuPattern", PATTERN_H)):
            range_ = self.token(path, name)
            self.symbols.append(Symbol(self.sid(name), SymbolKind.CLASS, name, NS + name, range_, range_))
        for owner, method, header, implementation in (
            ("OverlayManager", "ShowMenu", MANAGER_H, MANAGER_CPP),
            ("OverlayManager", "HideMenu", MANAGER_H, MANAGER_CPP),
            ("MenuPattern", "OnModifyDone", PATTERN_H, PATTERN_H),
        ):
            self.symbols.append(Symbol(self.sid(owner + "::" + method), SymbolKind.METHOD, method, NS + owner + "::" + method,
                                       self.token(header, method), self.token(implementation, method), self.sid(owner)))
        for name in ("Open", "Close", "Dismiss", "Keyboard"):
            location = self.token("overlay_entry.cpp", name)
            self.symbols.append(Symbol(self.sid(name), SymbolKind.FUNCTION, name, NS + name, location, location))
        self.animate = SymbolIdentity("animation-overload")
        location = self.token(ANIMATION_H, "Animate")
        self.symbols.append(Symbol(self.animate, SymbolKind.METHOD, "Animate", "OHOS::Ace::AnimationUtils::Animate",
                                   location, location))
        for target, token in ((self.sid("FrameNode"), "FrameNode"), (self.sid("MenuPattern"), "MenuPattern"),
                              (self.sid("MenuPattern::OnModifyDone"), "OnModifyDone")):
            self.facts.append(SymbolSemanticFacts(target, references=(self.token(MANAGER_CPP, token),
                                                                      self.token(MANAGER_CPP, token, 1))))
        if animation:
            self.facts.append(SymbolSemanticFacts(self.animate, references=(self.token(MANAGER_CPP, "Animate"),
                                                                           self.token(MANAGER_CPP, "Animate", 1))))
        for source, targets in (
            ("Open", (self.sid("OverlayManager::ShowMenu"),)),
            ("Dismiss", (self.sid("OverlayManager::HideMenu"),)),
            ("Keyboard", (self.sid("OverlayManager::HideMenu"),)),
            ("Close", (self.sid("Dismiss"), self.sid("Keyboard"))),
            ("OverlayManager::ShowMenu", (self.sid("MenuPattern::OnModifyDone"),) + ((self.animate,) if animation else ())),
            ("OverlayManager::HideMenu", (self.sid("MenuPattern::OnModifyDone"),) + ((self.animate,) if animation else ())),
        ):
            self.facts.append(SymbolSemanticFacts(self.sid(source), callees=targets))

    @staticmethod
    def sid(name):
        return SymbolIdentity(NS + name)

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
        self.generic = project_index(self.index, repository_key="overlay-unit", snapshot_key="v1")
        self.domain = default_role_mapper().map(self.index, self.generic)
        return extract_framework_relations(self.index, self.generic, self.domain, self.workspace).graph

    def trace(self, graph=None, **kwargs):
        if graph is None:
            graph = self.build()
        args = dict(manager=self.nid("OverlayManager"), component=NodeIdentity("arkui.component", "menu"),
                    show_seed=self.nid("Open"), close_seeds=(self.nid("Dismiss"),))
        args.update(kwargs)
        return trace_overlay(self.index, graph, self.domain, self.workspace, **args)

    def test_complete_trace_separates_binding_calls_and_source_associations(self):
        trace = self.trace()
        self.assertEqual(trace.status, OverlayStatus.COMPLETE)
        for leg in (trace.show, trace.close):
            path = leg.paths[0]
            self.assertEqual([n.stage.value for n in path.nodes],
                             ["entry", "manager", "operation", "managed_node_type", "pattern", "animation"])
            self.assertEqual(len(path.calls), 1)
            self.assertEqual(path.binding.identity.source, trace.manager)
            self.assertEqual(path.binding.identity.relation, leg.operation)
            self.assertEqual(path.animation.value, "present")
            self.assertTrue(all(n.evidence for n in path.nodes))
            self.assertTrue(all(e.evidence for e in path.calls + path.support))
            self.assertTrue(any("sha256=" in p.description for p in path.source_evidence))

    def test_no_animation_creates_no_animation_node(self):
        self.prepare(animation=False)
        trace = self.trace()
        self.assertEqual(trace.status, OverlayStatus.COMPLETE)
        for leg in (trace.show, trace.close):
            self.assertEqual(leg.paths[0].animation.value, "not_observed_in_supported_body")
            self.assertNotIn("animation", [n.stage.value for n in leg.paths[0].nodes])

    def test_two_paths_from_same_close_seed_are_preserved(self):
        trace = self.trace(close_seeds=(self.nid("Close"),))
        self.assertEqual(trace.status, OverlayStatus.AMBIGUOUS)
        self.assertEqual(trace.show.status, OverlayStatus.COMPLETE)
        self.assertEqual(len(trace.close.paths), 2)
        self.assertTrue(all(p.status == OverlayStatus.COMPLETE for p in trace.close.paths))
        self.assertIn("ambiguous_paths", trace.close.gaps)
        self.assertEqual({p.calls[0].identity.target for p in trace.close.paths}, {self.nid("Dismiss"), self.nid("Keyboard")})

    def test_two_close_seeds_and_duplicate_seed_dedup(self):
        trace = self.trace(close_seeds=(self.nid("Keyboard"), self.nid("Dismiss"), self.nid("Dismiss")))
        self.assertEqual(len(trace.close.paths), 2)
        self.assertEqual(trace.close.status, OverlayStatus.AMBIGUOUS)

    def test_same_named_entry_overloads_keep_explicit_identities(self):
        self.symbols = [replace(s, qualified_name=NS + "Dismiss")
                        if s.identity == self.sid("Keyboard") else s for s in self.symbols]
        trace = self.trace(close_seeds=(self.nid("Keyboard"), self.nid("Dismiss")))
        self.assertEqual(trace.close.status, OverlayStatus.AMBIGUOUS)
        self.assertEqual({p.calls[0].identity.source for p in trace.close.paths},
                         {self.nid("Keyboard"), self.nid("Dismiss")})
        trace = self.trace(close_seeds=(self.nid("Keyboard"),))
        self.assertEqual(trace.close.status, OverlayStatus.COMPLETE)
        self.assertEqual(trace.close.paths[0].calls[0].identity.source, self.nid("Keyboard"))

    def test_missing_generic_or_domain_evidence_is_not_restored(self):
        graph = self.build()
        for relation, target, gap in (
            (RelationType.CALL, self.nid("OverlayManager::ShowMenu"), "missing_operation_call"),
            (RelationType.SHOW, None, "missing_operation_binding"),
            (RelationType.DECLARE, self.nid("OverlayManager::ShowMenu"), "missing_operation_binding"),
            (RelationType.DEFINE, self.nid("OverlayManager::ShowMenu"), "missing_operation_definition"),
            (RelationType.REFERENCE, self.nid("FrameNode"), "missing_managed_node_reference"),
            (RelationType.REFERENCE, self.nid("MenuPattern"), "missing_pattern_reference"),
            (RelationType.CALL, self.nid("MenuPattern::OnModifyDone"), "missing_pattern_operation_call"),
            (RelationType.REFERENCE, NodeIdentity.for_symbol(self.animate), "missing_animation_reference"),
            (RelationType.CALL, NodeIdentity.for_symbol(self.animate), "unverified_animation_call"),
        ):
            with self.subTest(relation=relation, target=target):
                partial = replace(graph, edges=tuple(e for e in graph.edges if not
                                  (e.identity.relation == relation and (target is None or e.identity.target == target))))
                trace = self.trace(partial)
                self.assertEqual(trace.show.status, OverlayStatus.INCOMPLETE)
                self.assertIn(gap, trace.show.gaps)

    def test_same_method_declaration_parameter_reference_is_sufficient(self):
        self.facts = [replace(f, references=(self.token(MANAGER_H, "FrameNode"),
                                            self.token(MANAGER_H, "FrameNode", 1)))
                      if f.identity == self.sid("FrameNode") else f for f in self.facts]
        trace = self.trace()
        self.assertEqual(trace.status, OverlayStatus.COMPLETE)
        path = trace.show.paths[0]
        self.assertTrue(any(p.provenance.endswith("declared_operation_signature") for p in path.source_evidence))
        self.assertTrue(any(e.identity.relation == RelationType.REFERENCE and
                            e.identity.source == NodeIdentity.for_file(RepositoryFile.from_path(MANAGER_H))
                            for e in path.support))
        graph = self.build()
        graph = replace(graph, edges=tuple(e for e in graph.edges if not
                        (e.identity.relation == RelationType.REFERENCE and e.identity.target == self.nid("FrameNode"))))
        self.assertIn("missing_managed_node_reference", self.trace(graph).show.gaps)

    def test_declaration_and_definition_parameter_identity_conflict(self):
        original = next(s for s in self.symbols if s.identity == self.sid("FrameNode"))
        other = replace(original, identity=SymbolIdentity("other-frame"))
        self.symbols.append(other)
        self.facts.append(SymbolSemanticFacts(other.identity, references=(self.token(MANAGER_H, "FrameNode"),)))
        trace = self.trace()
        self.assertEqual(trace.show.status, OverlayStatus.AMBIGUOUS)
        self.assertIn("ambiguous_managed_node_identity", trace.show.gaps)
        self.assertEqual(len(trace.show.paths[0].candidates), 2)

    def test_close_binding_is_required_independently_of_show(self):
        graph = self.build()
        graph = replace(graph, edges=tuple(e for e in graph.edges if e.identity.relation != RelationType.CLOSE))
        trace = self.trace(graph)
        self.assertEqual(trace.show.status, OverlayStatus.COMPLETE)
        self.assertIn("missing_operation_binding", trace.close.gaps)

    def test_roles_conflicts_and_all_candidate_evidence(self):
        for name, role in (("OverlayManager", NodeKind.PATTERN), ("MenuPattern", NodeKind.MODEL)):
            for ambiguous in (True, False):
                graph = self.build()
                identity = self.nid(name)
                mapping = self.domain.lookup(identity)
                other = RoleCandidate(role, mapping.resolved.component, mapping.resolved.evidence)
                changed = replace(mapping, status=MappingStatus.AMBIGUOUS if ambiguous else MappingStatus.RECOGNIZED,
                                  candidates=mapping.candidates + (other,) if ambiguous else (other,))
                self.domain = replace(self.domain, mappings=tuple(changed if m.identity == identity else m
                                                                 for m in self.domain.mappings))
                trace = self.trace(graph)
                self.assertEqual(trace.status, OverlayStatus.AMBIGUOUS)
                self.assertTrue(any(n.node.identity == identity and n.evidence for n in trace.show.paths[0].candidates))

    def test_exact_reference_identity_conflicts_return_ambiguous(self):
        originals = self.symbols[:], self.facts[:]
        for name, gap in (("FrameNode", "ambiguous_managed_node_identity"), ("MenuPattern", "ambiguous_pattern_identity"),
                          ("MenuPattern::OnModifyDone", "ambiguous_pattern_operation")):
            self.symbols, self.facts = originals[0][:], originals[1][:]
            symbol = next(s for s in self.symbols if s.identity == self.sid(name))
            duplicate = replace(symbol, identity=SymbolIdentity("duplicate:" + name))
            self.symbols.append(duplicate)
            facts = next(f for f in self.facts if f.identity == symbol.identity)
            self.facts.append(replace(facts, identity=duplicate.identity))
            trace = self.trace()
            self.assertEqual(trace.status, OverlayStatus.AMBIGUOUS)
            self.assertIn(gap, trace.show.gaps)
            self.assertEqual(len(trace.show.paths[0].candidates), 2)

    def test_animation_identity_conflict_is_not_sorted_away(self):
        symbol = next(s for s in self.symbols if s.identity == self.animate)
        other = replace(symbol, identity=SymbolIdentity("other-animation"))
        self.symbols.append(other)
        self.facts.append(replace(next(f for f in self.facts if f.identity == self.animate), identity=other.identity))
        trace = self.trace()
        self.assertEqual(trace.status, OverlayStatus.AMBIGUOUS)
        self.assertIn("ambiguous_animation_identity", trace.show.gaps)
        self.assertNotIn("animation", [n.stage.value for n in trace.show.paths[0].nodes])

    def test_missing_parent_does_not_match_by_method_name(self):
        self.symbols = [replace(s, parent_identity=None) if s.identity == self.sid("OverlayManager::ShowMenu") else s
                        for s in self.symbols]
        self.assertIn("missing_operation_call", self.trace().show.gaps)

    def test_same_name_wrong_animation_source_is_not_accepted(self):
        target = next(s for s in self.symbols if s.identity == self.animate)
        self.symbols = [replace(s, qualified_name="Other::AnimationUtils::Animate") if s == target else s for s in self.symbols]
        trace = self.trace()
        self.assertEqual(trace.show.status, OverlayStatus.AMBIGUOUS)
        self.assertIn("ambiguous_animation_target", trace.show.gaps)

    def test_resolved_wrong_frame_type_or_component_is_a_conflict(self):
        original = self.symbols[:]
        self.symbols = [replace(s, qualified_name="Other::FrameNode") if s.identity == self.sid("FrameNode") else s
                        for s in original]
        self.assertIn("ambiguous_managed_node_type", self.trace().show.gaps)
        self.symbols = original
        trace = self.trace(component=NodeIdentity("arkui.component", "button"))
        self.assertIn("ambiguous_component_role_conflict", trace.show.gaps)

    def test_unknown_role_is_incomplete_and_retains_evidence(self):
        graph = self.build()
        identity = self.nid("OverlayManager")
        self.domain = replace(self.domain, mappings=tuple(
            replace(m, status=MappingStatus.UNKNOWN, candidates=()) if m.identity == identity else m
            for m in self.domain.mappings))
        trace = self.trace(graph)
        self.assertEqual(trace.status, OverlayStatus.INCOMPLETE)
        self.assertIn("unknown_role", trace.show.gaps)
        self.assertEqual(trace.show.paths[0].candidates[0].node.identity, identity)

    def test_branch_comment_or_nearby_body_does_not_supply_managed_association(self):
        file = self.root / MANAGER_CPP
        original = file.read_text()
        for prefix in ("if (false) {", "// ", "return; }\nvoid Nearby() {", "/* "):
            file.write_text(original.replace("    CHECK_NULL_VOID(menu);", "    " + prefix + "CHECK_NULL_VOID(menu);", 1))
            trace = self.trace()
            self.assertIn("unsupported_manager_body", trace.show.gaps)
            self.assertEqual(trace.show.paths[0].animation.value, "unresolved")
            self.assertNotIn("pattern", [n.stage.value for n in trace.show.paths[0].nodes])

    def test_missing_seed_manager_and_definition(self):
        graph = self.build()
        trace = self.trace(graph, show_seed=NodeIdentity("symbol", "missing"))
        self.assertIn("missing_seed", trace.show.gaps)
        trace = self.trace(graph, manager=NodeIdentity("symbol", "missing"))
        self.assertIn("missing_manager", trace.show.gaps)
        self.symbols = [replace(s, definition=None) if s.identity == self.sid("OverlayManager::HideMenu") else s
                        for s in self.symbols]
        self.assertIn("missing_operation_definition", self.trace().close.gaps)

    def test_depth_state_and_path_limits_report_incomplete_enumeration(self):
        for bounds, gap in ((OverlayBounds(max_depth=1), "depth_limit"), (OverlayBounds(max_states=1), "state_limit"),
                            (OverlayBounds(max_paths=1), "path_limit")):
            trace = self.trace(close_seeds=(self.nid("Close"),), bounds=bounds)
            self.assertFalse(trace.close.exhaustive)
            self.assertIn(gap, trace.close.gaps)
            self.assertNotEqual(trace.status, OverlayStatus.COMPLETE)

    def test_cycle_does_not_hide_a_valid_alternative(self):
        self.facts = [replace(f, callees=f.callees + (self.sid("Close"),)) if f.identity == self.sid("Dismiss") else f
                      for f in self.facts]
        trace = self.trace(close_seeds=(self.nid("Close"),))
        self.assertFalse(trace.close.exhaustive)
        self.assertIn("cycle_cut", trace.close.gaps)
        self.assertEqual(len(trace.close.paths), 2)

    def test_bound_operation_seed_reports_missing_entry_call(self):
        trace = self.trace(show_seed=self.nid("OverlayManager::ShowMenu"))
        self.assertIn("missing_entry_call", trace.show.gaps)

    def test_partial_graph_does_not_restore_a_missing_node(self):
        graph = self.build()
        missing = self.nid("OverlayManager::ShowMenu")
        graph = replace(graph, nodes=tuple(n for n in graph.nodes if n.identity != missing),
                        edges=tuple(e for e in graph.edges if missing not in (e.identity.source, e.identity.target)))
        self.assertIn("missing_operation_call", self.trace(graph).show.gaps)

    def test_rebuild_is_deterministic(self):
        trace = self.trace()
        self.symbols.reverse()
        self.facts.reverse()
        self.assertEqual(self.trace(), trace)

    def test_input_and_source_failures_propagate(self):
        graph = self.build()
        with self.assertRaises(ValueError):
            self.trace(replace(graph, snapshot_key="other"))
        with self.assertRaises(TypeError):
            self.trace(graph, close_seeds=[self.nid("Dismiss")])
        for value in (True, 0, -1, 1.5):
            with self.assertRaises(ValueError):
                OverlayBounds(max_depth=value)
        (self.root / MANAGER_CPP).unlink()
        with self.assertRaises(FileNotFoundError):
            self.trace(graph)
