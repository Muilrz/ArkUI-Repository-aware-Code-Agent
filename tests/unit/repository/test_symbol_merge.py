"""Public semantic merge regressions; no smoke gold or ArkUI checkout required."""
from dataclasses import replace
import unittest

from arkui_agent.repository import (
    RepositoryFile, SourceLocation, SourceRange, Symbol, SymbolIdentity, SymbolKind,
    SymbolObservation, SymbolMergeConflict, canonicalize_symbols,
)


def extent(path, line):
    file = RepositoryFile.from_path(path)
    return SourceRange(SourceLocation(file, line, 3), SourceLocation(file, line, 4))


class CanonicalSymbolMergeTests(unittest.TestCase):
    def setUp(self):
        self.declaration = extent("interface.any", 2)
        self.definition = extent("implementation.any", 5)
        self.symbol = Symbol(SymbolIdentity("method"), SymbolKind.METHOD, "f", "N::C::f",
                             self.declaration, self.definition, SymbolIdentity("class"), SymbolIdentity("namespace"))
        self.header = SymbolObservation(self.symbol, self.declaration, SymbolKind.CLASS)
        self.source = SymbolObservation(replace(self.symbol, display_name="C::f", parent_identity=SymbolIdentity("namespace")),
                                        self.definition, SymbolKind.NAMESPACE)

    def test_declaration_wins_both_orders_and_namespace_does_not_replace_class(self):
        for facts in ((self.header, self.source), (self.source, self.header)):
            self.assertEqual(canonicalize_symbols(facts), (self.symbol,))

    def test_duplicate_observations_are_idempotent(self):
        self.assertEqual(canonicalize_symbols((self.header, self.source, self.header)), (self.symbol,))

    def test_conflicting_declaration_or_definition_range_rejected(self):
        for field in ("declaration", "definition"):
            with self.subTest(field=field):
                bad = replace(self.source, symbol=replace(self.source.symbol, **{field: extent("other", 3)}))
                for facts in ((self.header, bad), (bad, self.header)):
                    with self.assertRaises(SymbolMergeConflict) as caught:
                        canonicalize_symbols(facts)
                    self.assertEqual(caught.exception.field, field)

    def test_missing_range_can_be_supplemented(self):
        partial = replace(self.header, symbol=replace(self.symbol, definition=None))
        self.assertEqual(canonicalize_symbols((partial, self.source)), (self.symbol,))

    def test_same_file_different_site_is_not_declaration_evidence(self):
        unproven = replace(self.header, site=extent("interface.any", 20))
        with self.assertRaises(SymbolMergeConflict):
            canonicalize_symbols((unproven, self.source))

    def test_disagreeing_declaration_hierarchy_fails(self):
        other = replace(self.header, symbol=replace(self.symbol, parent_identity=SymbolIdentity("other-class")))
        with self.assertRaises(SymbolMergeConflict):
            canonicalize_symbols((self.header, self.source, other))

    def test_namespace_declaration_cannot_prove_class_containment(self):
        with self.assertRaises(SymbolMergeConflict):
            canonicalize_symbols((replace(self.header, parent_kind=SymbolKind.NAMESPACE), self.source))

    def test_overload_identities_never_merge_by_name(self):
        overload = replace(self.header, symbol=replace(self.symbol, identity=SymbolIdentity("overload")))
        merged = canonicalize_symbols((overload, self.source, self.header))
        self.assertEqual({s.identity.value for s in merged}, {"method", "overload"})
        self.assertEqual(merged, canonicalize_symbols((self.header, self.source, overload)))

    def test_same_identity_different_qualified_identity_or_kind_fails(self):
        for field, value in (("qualified_name", "Unrelated::f"), ("kind", SymbolKind.FUNCTION)):
            with self.subTest(field=field), self.assertRaises(SymbolMergeConflict):
                canonicalize_symbols((self.header, replace(self.source, symbol=replace(self.source.symbol, **{field: value}))))
