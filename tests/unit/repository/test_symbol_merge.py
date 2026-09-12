"""Public semantic merge regressions; no smoke gold or ArkUI checkout required."""
from dataclasses import replace
from itertools import permutations
import unittest

from arkui_agent.repository import (
    RepositoryFile, SourceLocation, SourceRange, Symbol, SymbolIdentity, SymbolKind,
    SymbolObservation, SymbolMergeConflict, canonicalize_symbols,
    canonicalize_symbol_groups,
)


def extent(path, line):
    file = RepositoryFile.from_path(path)
    return SourceRange(SourceLocation(file, line, 3), SourceLocation(file, line, 4))


class CanonicalSymbolMergeTests(unittest.TestCase):
    def test_reopened_namespace_preserves_all_observations_and_is_order_independent(self):
        identity = SymbolIdentity("namespace-n")
        a, b, local = extent("a.h", 2), extent("b.cpp", 7), extent("c.h", 3)
        symbol = Symbol(identity, SymbolKind.NAMESPACE, "N", "N", a, a)
        first = SymbolObservation(symbol, local, None)
        second = SymbolObservation(replace(symbol, declaration=b, definition=b), b, None)
        groups = canonicalize_symbol_groups((first, second, first))
        self.assertEqual(groups, canonicalize_symbol_groups((second, first)))
        self.assertEqual(groups[0].symbol, symbol)
        self.assertEqual(set(groups[0].observations), {first, second})
        self.assertEqual(canonicalize_symbols((second, first)), (symbol,))
        for field, value in (("kind", SymbolKind.CLASS), ("qualified_name", "Other"),
                             ("display_name", "Other"), ("parent_identity", SymbolIdentity("wrong")),
                             ("namespace_identity", SymbolIdentity("wrong"))):
            original = replace(first, symbol=replace(symbol, namespace_identity=identity, parent_identity=identity))
            base = replace(second.symbol, namespace_identity=identity, parent_identity=identity)
            changed = replace(second, symbol=replace(base, **{field: value}))
            for ordered in ((original, changed), (changed, original)):
                with self.subTest(field=field), self.assertRaises(SymbolMergeConflict):
                    canonicalize_symbol_groups(ordered)

    def test_non_namespace_multiple_sites_still_conflict(self):
        for kind in (SymbolKind.FUNCTION, SymbolKind.CLASS, SymbolKind.FIELD):
            a, b = extent("a.cpp", 1), extent("b.cpp", 1)
            symbol = Symbol(SymbolIdentity("same"), kind, "s", "s", a, a)
            with self.subTest(kind=kind), self.assertRaises(SymbolMergeConflict):
                canonicalize_symbols((SymbolObservation(symbol, a, None),
                                      SymbolObservation(replace(symbol, declaration=b), b, None)))

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

    def test_partial_related_observation_enriches_without_losing_evidence(self):
        partial = SymbolObservation(replace(self.symbol, parent_identity=None, namespace_identity=None))
        for ordered in permutations((self.header, partial)):
            group, = canonicalize_symbol_groups(ordered)
            self.assertEqual(group.symbol, self.symbol)
            self.assertEqual(set(group.observations), {self.header, partial})
        for ordered in permutations((self.header, self.source, partial)):
            self.assertEqual(canonicalize_symbols(ordered), (self.symbol,))

    def test_known_related_containment_conflicts(self):
        for field in ("parent_identity", "namespace_identity"):
            other = SymbolObservation(replace(self.symbol, **{field: SymbolIdentity("other")}))
            for ordered in permutations((self.header, other)):
                with self.subTest(field=field), self.assertRaises(SymbolMergeConflict):
                    canonicalize_symbol_groups(ordered)

    def test_complementary_partial_observations_are_order_independent(self):
        partials = (
            SymbolObservation(replace(self.symbol, definition=None, namespace_identity=None)),
            SymbolObservation(replace(self.symbol, declaration=None, parent_identity=None)),
            SymbolObservation(replace(self.symbol, parent_identity=None, namespace_identity=None)),
        )
        expected = canonicalize_symbol_groups(partials)
        self.assertEqual(expected[0].symbol, self.symbol)
        self.assertEqual(set(expected[0].observations), set(partials))
        for ordered in permutations(partials):
            self.assertEqual(canonicalize_symbol_groups(ordered), expected)

    def test_partial_metadata_never_relaxes_names_kind_or_ranges(self):
        for field, value in (("display_name", "different"), ("qualified_name", "Other::f"),
                             ("kind", SymbolKind.FUNCTION), ("declaration", extent("other.h", 2)),
                             ("definition", extent("other.cpp", 5))):
            partial = SymbolObservation(replace(self.symbol, parent_identity=None,
                                                namespace_identity=None, **{field: value}))
            for ordered in permutations((self.header, partial)):
                with self.subTest(field=field), self.assertRaises(SymbolMergeConflict):
                    canonicalize_symbol_groups(ordered)

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
