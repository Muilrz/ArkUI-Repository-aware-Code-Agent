from __future__ import annotations

import json
import unittest
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from tempfile import TemporaryDirectory

from arkui_agent.graph import (
    ArkUIRoleMapper, ComponentSpec, MappingStatus, NodeIdentity, NodeKind,
    RoleRule, default_role_mapper, project_index,
)
from arkui_agent.graph.arkui_rules import COMPONENTS, ROLE_RULES
from arkui_agent.repository import (
    RepositoryFile, SourceLocation, SourceRange, Symbol, SymbolIdentity, SymbolIndex, SymbolKind,
)


def symbol_for(rule: RoleRule, key: str | None = None) -> Symbol:
    range_ = SourceRange(SourceLocation(rule.file, 2, 1), SourceLocation(rule.file, 6, 2))
    return Symbol(SymbolIdentity(key or rule.rule_id), SymbolKind.CLASS,
                  rule.qualified_name.rsplit("::", 1)[-1], rule.qualified_name,
                  declaration=range_, definition=range_)


class DomainMappingTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = TemporaryDirectory(prefix="domain-unit-")
        self.addCleanup(temporary.cleanup)
        self.index = SymbolIndex(Path(temporary.name) / "p1.sqlite3")
        self.addCleanup(self.index.close)
        self.mapper = default_role_mapper()
        self.rule = next(r for r in ROLE_RULES if r.rule_id == "button.pattern")
        self.symbol = symbol_for(self.rule)

    def build(self, symbols: tuple[Symbol, ...], mapper: ArkUIRoleMapper | None = None):
        self.index.rebuild(symbols)
        graph = project_index(self.index, repository_key="fixture", snapshot_key="v1")
        return (mapper or self.mapper).map(self.index, graph), graph

    def test_all_roles_components_and_shared_overlay_have_evidence(self) -> None:
        result, graph = self.build(tuple(symbol_for(rule) for rule in ROLE_RULES))
        self.assertTrue(all(m.status == MappingStatus.RECOGNIZED for m in result.mappings))
        self.assertEqual({c.node.display_name for c in result.components}, {"Button", "Text", "Menu"})
        self.assertEqual({c.node.kind for c in result.components}, {NodeKind.COMPONENT})
        self.assertEqual({m.resolved.role for m in result.mappings}, {
            NodeKind.BRIDGE, NodeKind.MODEL, NodeKind.PATTERN, NodeKind.LAYOUT_PROPERTY,
            NodeKind.PAINT_PROPERTY, NodeKind.LAYOUT_ALGORITHM, NodeKind.OVERLAY_MANAGER,
        })
        for m in result.mappings:
            self.assertTrue(m.resolved.evidence)
            self.assertEqual(m.resolved.evidence[0].anchor.symbol_identity.value, m.identity.key)
        for component in result.components:
            self.assertTrue(component.evidence)
            self.assertTrue(result.members(component.node.identity))
        overlay = next(m for m in result.mappings if m.resolved.role == NodeKind.OVERLAY_MANAGER)
        self.assertIsNone(overlay.resolved.component)
        self.assertTrue(all(n.kind not in {NodeKind.COMPONENT, NodeKind.PATTERN} for n in graph.nodes))
        self.assertEqual(self.index.get(self.symbol.identity), self.symbol)

    def test_wrong_namespace_file_kind_and_near_names_stay_unknown(self) -> None:
        wrong_file = SourceRange(SourceLocation(RepositoryFile.from_path("tests/button_pattern.h"), 2, 1),
                                 SourceLocation(RepositoryFile.from_path("tests/button_pattern.h"), 6, 2))
        for item, expected in (
            (replace(self.symbol, qualified_name="App::ButtonPattern"), "no_qualified_name_rule"),
            (replace(self.symbol, qualified_name="OHOS::Ace::NG::ToggleButtonPattern"), "no_qualified_name_rule"),
            (replace(self.symbol, declaration=wrong_file, definition=wrong_file), "source_file_mismatch"),
            (replace(self.symbol, kind=SymbolKind.FUNCTION), "unsupported_symbol_kind"),
            (replace(self.symbol, qualified_name="OHOS::Ace::NG::MenuItemPattern"), "no_qualified_name_rule"),
        ):
            with self.subTest(expected=expected, item=item):
                result, _ = self.build((item,))
                decision = result.lookup(NodeIdentity.for_symbol(item.identity))
                self.assertEqual(decision.status, MappingStatus.UNKNOWN)
                self.assertEqual(decision.reason, expected)
                self.assertIsNone(decision.resolved)
                self.assertEqual(result.components, ())

    def test_conflicting_source_evidence_is_not_silently_accepted(self) -> None:
        other = RepositoryFile.from_path("unrelated/button_pattern.h")
        conflicting = replace(self.symbol, definition=SourceRange(
            SourceLocation(other, 1, 1), SourceLocation(other, 1, 9)))
        result, _ = self.build((conflicting,))
        self.assertEqual(result.mappings[0].reason, "source_file_mismatch")
        self.assertEqual(result.mappings[0].status, MappingStatus.UNKNOWN)

    def test_definition_controls_role_despite_forward_declaration_elsewhere(self) -> None:
        other = RepositoryFile.from_path("common/forward_declarations.h")
        forward = replace(self.symbol, declaration=SourceRange(
            SourceLocation(other, 1, 1), SourceLocation(other, 1, 9)))
        result, _ = self.build((forward,))
        self.assertEqual(result.mappings[0].status, MappingStatus.RECOGNIZED)
        self.assertEqual(result.mappings[0].resolved.evidence[0].anchor.source_range, self.symbol.definition)
        self.assertIn(other, {e.anchor.file for e in result.mappings[0].evidence})
        declaration_only, _ = self.build((replace(self.symbol, definition=None),))
        self.assertEqual(declaration_only.mappings[0].status, MappingStatus.RECOGNIZED)

    def test_conflicting_roles_or_components_remain_ambiguous_without_membership(self) -> None:
        for conflicting in (
            replace(self.rule, rule_id="conflict", role=NodeKind.MODEL),
            replace(self.rule, rule_id="conflict", component_key="menu"),
        ):
            mapper = ArkUIRoleMapper(COMPONENTS, (conflicting, self.rule))
            result, _ = self.build((self.symbol,), mapper)
            decision = result.mappings[0]
            self.assertEqual(decision.status, MappingStatus.AMBIGUOUS)
            self.assertEqual(len(decision.candidates), 2)
            self.assertIsNone(decision.resolved)
            self.assertEqual(result.components, ())
            self.assertEqual(result.members(NodeIdentity("arkui.component", "button")), ())

    def test_equivalent_rules_merge_evidence_and_order_is_input_independent(self) -> None:
        rules = (self.rule, replace(self.rule, rule_id="second-proof"))
        mapper = ArkUIRoleMapper(COMPONENTS, rules)
        result, _ = self.build((self.symbol,), mapper)
        self.assertEqual(len(result.mappings[0].resolved.evidence), 2)
        reversed_mapper = ArkUIRoleMapper(tuple(reversed(COMPONENTS)), tuple(reversed(rules)))
        repeated, _ = self.build((self.symbol,), reversed_mapper)
        self.assertEqual(result, repeated)
        self.assertEqual(json.dumps(result.to_dict(), sort_keys=True), json.dumps(repeated.to_dict(), sort_keys=True))
        self.assertNotEqual(mapper.ruleset_identity, self.mapper.ruleset_identity)

    def test_empty_unresolved_and_stale_graph_have_explicit_outcomes(self) -> None:
        empty, _ = self.build(())
        self.assertEqual(empty.mappings, ())
        self.assertIsNone(empty.lookup(NodeIdentity("symbol", "absent")))
        _, graph = self.build((self.symbol,))
        self.index.rebuild(())
        result = self.mapper.map(self.index, graph)
        self.assertEqual(result.mappings[0].reason, "missing_p1_symbol")
        changed = replace(self.symbol, display_name="changed")
        self.index.rebuild((changed,))
        with self.assertRaisesRegex(ValueError, "snapshot mismatch"):
            self.mapper.map(self.index, graph)

    def test_no_role_propagation_to_members_or_unlisted_classes(self) -> None:
        method = replace(self.symbol, identity=SymbolIdentity("method"), kind=SymbolKind.METHOD,
                         qualified_name=self.symbol.qualified_name + "::OnModifyDone",
                         display_name="OnModifyDone", parent_identity=self.symbol.identity)
        result, graph = self.build((method, self.symbol))
        self.assertEqual(result.lookup(NodeIdentity.for_symbol(method.identity)).status, MappingStatus.UNKNOWN)
        self.assertEqual(len(result.members(NodeIdentity("arkui.component", "button"))), 1)
        self.assertEqual(self.mapper.map(self.index, graph), result)

    def test_invalid_catalog_and_immutable_decisions(self) -> None:
        with self.assertRaises(ValueError):
            ArkUIRoleMapper(COMPONENTS, (self.rule, self.rule))
        with self.assertRaises(ValueError):
            ArkUIRoleMapper((), (self.rule,))
        with self.assertRaises(ValueError):
            ArkUIRoleMapper((COMPONENTS[0], COMPONENTS[0]), ())
        with self.assertRaises(ValueError):
            replace(self.rule, role=NodeKind.FUNCTION)
        with self.assertRaises(ValueError):
            ComponentSpec("", "invalid")
        result, _ = self.build((self.symbol,))
        with self.assertRaises(FrozenInstanceError):
            result.mappings[0].reason = "changed"
