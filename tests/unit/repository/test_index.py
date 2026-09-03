from __future__ import annotations

import sqlite3
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from arkui_agent.repository import (
    RepositoryFile,
    SourceLocation,
    SourceRange,
    Symbol,
    SymbolIdentity,
    SymbolIndex,
    SymbolIndexClosedError,
    SymbolIndexError,
    SymbolKind,
    SymbolSemanticFacts,
    TestCase,
    TestFixture,
)


def source_range(
    file: RepositoryFile,
    start_line: int,
    start_column: int,
    end_line: int,
    end_column: int,
) -> SourceRange:
    return SourceRange(
        SourceLocation(file, start_line, start_column),
        SourceLocation(file, end_line, end_column),
    )


class SymbolIndexTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory(prefix="symbol-index-test-")
        self.runtime_directory = Path(self.temporary_directory.name) / "runtime"
        self.database_path = self.runtime_directory / "custom.sqlite3"
        self.header = RepositoryFile.from_path("include/fixture/widget.h")
        self.source = RepositoryFile.from_path("src/widget.cpp")
        self.test_source = RepositoryFile.from_path("tests/widget_test.cpp")
        self.empty_file = RepositoryFile.from_path("include/fixture/empty.h")
        self.namespace_identity = SymbolIdentity("opaque:namespace")
        self.parent_identity = SymbolIdentity("opaque:widget")
        self.value = Symbol(
            identity=SymbolIdentity("opaque:value-int"),
            kind=SymbolKind.METHOD,
            display_name="value",
            qualified_name="fixture::Widget::value",
            declaration=source_range(self.header, 8, 5, 8, 10),
            definition=source_range(self.source, 5, 5, 5, 10),
            parent_identity=self.parent_identity,
            namespace_identity=self.namespace_identity,
        )
        self.overload = Symbol(
            identity=SymbolIdentity("opaque:value-double"),
            kind=SymbolKind.METHOD,
            display_name="value",
            qualified_name="fixture::Widget::value",
            declaration=source_range(self.header, 9, 5, 9, 10),
            definition=source_range(self.source, 10, 5, 10, 10),
            parent_identity=self.parent_identity,
            namespace_identity=self.namespace_identity,
        )
        self.fixture = TestFixture(
            identity=SymbolIdentity("test:fixture:widget"),
            display_name="WidgetTest",
            source_range=source_range(self.test_source, 20, 10, 20, 20),
        )
        self.test_case = TestCase(
            identity=SymbolIdentity("test:case:widget:value"),
            display_name="ValueIsTwentyOne",
            fixture_identity=self.fixture.identity,
            source_range=source_range(self.test_source, 20, 22, 20, 38),
            body_range=source_range(self.test_source, 21, 1, 25, 2),
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _index(self) -> SymbolIndex:
        return SymbolIndex(self.database_path)

    def test_rebuild_and_exact_identity_query_round_trip_unified_model(self) -> None:
        with self._index() as index:
            index.rebuild((self.value,), files=(self.empty_file,))

            self.assertEqual(index.get(self.value.identity), self.value)
            self.assertEqual(
                index.files(),
                (self.empty_file, self.header, self.source),
            )
            self.assertEqual(index.symbols_in_file(self.header), (self.value,))

    def test_same_name_and_overload_identities_remain_independent(self) -> None:
        with self._index() as index:
            index.rebuild((self.value, self.overload))

            expected = (self.overload, self.value)
            self.assertEqual(index.find_by_name("value"), expected)
            self.assertEqual(
                index.find_by_qualified_name("fixture::Widget::value"),
                expected,
            )
            self.assertEqual(index.get(self.value.identity), self.value)
            self.assertEqual(index.get(self.overload.identity), self.overload)

    def test_fallback_split_declaration_and_definition_are_not_reconciled(self) -> None:
        declaration = replace(
            self.value,
            identity=SymbolIdentity("opaque:fallback-declaration"),
            definition=None,
        )
        definition = replace(
            self.value,
            identity=SymbolIdentity("opaque:fallback-definition"),
            declaration=None,
        )
        with self._index() as index:
            index.rebuild((definition, declaration))

            matches = index.find_by_qualified_name(self.value.qualified_name)

        self.assertEqual(
            {symbol.identity for symbol in matches},
            {declaration.identity, definition.identity},
        )
        self.assertIsNone(indexed_by_identity(matches, declaration.identity).definition)
        self.assertIsNone(indexed_by_identity(matches, definition.identity).declaration)

    def test_semantic_facts_round_trip_with_deterministic_deduplication(self) -> None:
        caller_b = SymbolIdentity("opaque:caller-b")
        caller_a = SymbolIdentity("opaque:caller-a")
        reference_b = source_range(self.source, 20, 8, 20, 13)
        reference_a = source_range(self.header, 8, 5, 8, 10)
        facts = SymbolSemanticFacts(
            identity=self.value.identity,
            references=(reference_b, reference_a, reference_b),
            callers=(caller_b, caller_a, caller_b),
            callees=(self.overload.identity,),
        )
        with self._index() as index:
            index.rebuild((self.value,), semantic_facts=(facts,))

            stored = index.semantic_facts(self.value.identity)

        self.assertEqual(
            stored,
            SymbolSemanticFacts(
                identity=self.value.identity,
                references=(reference_a, reference_b),
                callers=(caller_a, caller_b),
                callees=(self.overload.identity,),
            ),
        )

    def test_query_order_is_independent_of_ingest_order(self) -> None:
        with self._index() as index:
            index.rebuild((self.value, self.overload))
            first = index.find_by_name("value")
            index.rebuild((self.overload, self.value))
            second = index.find_by_name("value")

        self.assertEqual(first, second)

    def test_rebuild_replaces_previous_snapshot(self) -> None:
        with self._index() as index:
            index.rebuild((self.value,))
            index.rebuild((self.overload,))

            self.assertIsNone(index.get(self.value.identity))
            self.assertEqual(index.get(self.overload.identity), self.overload)

    def test_conflicting_records_for_one_identity_fail_without_changing_index(self) -> None:
        conflicting = replace(self.value, display_name="different")
        with self._index() as index:
            index.rebuild((self.value,))

            with self.assertRaisesRegex(SymbolIndexError, "Conflicting symbol records"):
                index.rebuild((self.value, conflicting))

            self.assertEqual(index.get(self.value.identity), self.value)

    def test_database_can_be_deleted_and_rebuilt_from_models(self) -> None:
        with self._index() as index:
            index.rebuild((self.value,))
        self.database_path.unlink()

        with self._index() as rebuilt:
            rebuilt.rebuild((self.value,))
            self.assertEqual(rebuilt.get(self.value.identity), self.value)

    def test_runtime_directory_uses_ignored_index_filename(self) -> None:
        with SymbolIndex.in_runtime_directory(self.runtime_directory) as index:
            index.rebuild(())
            self.assertEqual(index.database_path.parent, self.runtime_directory)
            self.assertEqual(index.database_path.name, "symbol-index.sqlite3")

    def test_schema_contains_generic_file_symbol_range_and_relation_tables(self) -> None:
        with self._index() as index:
            index.rebuild((self.value,))
        connection = sqlite3.connect(self.database_path)
        try:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            symbol_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(symbols)")
            }
        finally:
            connection.close()

        self.assertTrue(
            {
                "metadata",
                "files",
                "symbols",
                "symbol_ranges",
                "symbol_references",
                "symbol_relations",
            }.issubset(tables)
        )
        self.assertNotIn("clangd_id", symbol_columns)
        self.assertNotIn("usr", symbol_columns)

    def test_test_entities_and_fixture_case_relation_round_trip(self) -> None:
        with self._index() as index:
            index.rebuild(
                (),
                test_fixtures=(self.fixture,),
                test_cases=(self.test_case,),
            )

            self.assertEqual(index.get_test_fixture(self.fixture.identity), self.fixture)
            self.assertEqual(index.get_test_case(self.test_case.identity), self.test_case)
            self.assertEqual(
                index.test_cases_for_fixture(self.fixture.identity),
                (self.test_case,),
            )
            self.assertIn(self.test_source, index.files())

    def test_same_name_test_entities_are_not_merged_and_order_is_stable(self) -> None:
        other_fixture = TestFixture(
            identity=SymbolIdentity("test:fixture:other"),
            display_name=self.fixture.display_name,
            source_range=source_range(self.header, 30, 10, 30, 20),
        )
        other_case = TestCase(
            identity=SymbolIdentity("test:case:other:value"),
            display_name=self.test_case.display_name,
            fixture_identity=other_fixture.identity,
            source_range=source_range(self.header, 30, 22, 30, 38),
        )
        with self._index() as index:
            index.rebuild(
                (),
                test_fixtures=(self.fixture, other_fixture),
                test_cases=(self.test_case, other_case),
            )
            first_fixtures = index.find_test_fixtures(self.fixture.display_name)
            first_cases = index.find_test_cases(self.test_case.display_name)
            index.rebuild(
                (),
                test_fixtures=(other_fixture, self.fixture),
                test_cases=(other_case, self.test_case),
            )
            second_fixtures = index.find_test_fixtures(self.fixture.display_name)
            second_cases = index.find_test_cases(self.test_case.display_name)

        self.assertEqual(first_fixtures, second_fixtures)
        self.assertEqual(first_cases, second_cases)
        self.assertEqual(
            {fixture.identity for fixture in first_fixtures},
            {self.fixture.identity, other_fixture.identity},
        )
        self.assertEqual(
            {case.fixture_identity for case in first_cases},
            {self.fixture.identity, other_fixture.identity},
        )

    def test_test_case_requires_exact_indexed_fixture_identity(self) -> None:
        missing_fixture_case = replace(
            self.test_case,
            fixture_identity=SymbolIdentity("test:fixture:missing"),
        )
        with self._index() as index:
            index.rebuild((), test_fixtures=(self.fixture,))

            with self.assertRaisesRegex(SymbolIndexError, "indexed fixture identity"):
                index.rebuild(
                    (),
                    test_fixtures=(self.fixture,),
                    test_cases=(missing_fixture_case,),
                )

            self.assertEqual(index.get_test_fixture(self.fixture.identity), self.fixture)

    def test_schema_keeps_test_recognition_details_out_of_storage(self) -> None:
        with self._index() as index:
            index.rebuild(
                (),
                test_fixtures=(self.fixture,),
                test_cases=(self.test_case,),
            )
        connection = sqlite3.connect(self.database_path)
        try:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(test_entities)")
            }
        finally:
            connection.close()

        self.assertTrue(
            {
                "test_entities",
                "test_fixture_cases",
                "test_case_bodies",
                "test_symbol_references",
            }.issubset(tables)
        )
        self.assertNotIn("macro", columns)
        self.assertNotIn("framework", columns)

    def test_direct_symbol_test_mapping_is_identity_safe_and_explainable(self) -> None:
        second_case = TestCase(
            identity=SymbolIdentity("test:case:widget:second"),
            display_name="SecondValueCase",
            fixture_identity=self.fixture.identity,
            source_range=source_range(self.test_source, 30, 22, 30, 37),
            body_range=source_range(self.test_source, 31, 1, 34, 2),
        )
        value_first = source_range(self.test_source, 22, 8, 22, 13)
        value_second = source_range(self.test_source, 32, 8, 32, 13)
        overload_first = source_range(self.test_source, 23, 8, 23, 13)
        outside_all_cases = source_range(self.test_source, 28, 8, 28, 13)
        facts = (
            SymbolSemanticFacts(
                self.value.identity,
                references=(
                    value_second,
                    outside_all_cases,
                    value_first,
                    value_first,
                ),
                callees=(SymbolIdentity("opaque:dangling-same-name"),),
            ),
            SymbolSemanticFacts(
                self.overload.identity,
                references=(overload_first,),
            ),
        )

        with self._index() as index:
            index.rebuild(
                (self.value, self.overload),
                semantic_facts=facts,
                test_fixtures=(self.fixture,),
                test_cases=(second_case, self.test_case),
            )
            first_snapshot = index.tested_symbol_mappings_for_case(
                self.test_case.identity
            )
            index.rebuild(
                (self.overload, self.value),
                semantic_facts=tuple(reversed(facts)),
                test_fixtures=(self.fixture,),
                test_cases=(self.test_case, second_case),
            )
            self.assertEqual(
                index.tested_symbol_mappings_for_case(self.test_case.identity),
                first_snapshot,
            )

        with self._index() as reopened:
            first_symbols = reopened.directly_referenced_symbols(
                self.test_case.identity
            )
            value_cases = reopened.test_cases_for_symbol(self.value.identity)
            overload_cases = reopened.test_cases_for_symbol(self.overload.identity)
            mappings = reopened.tested_symbol_mappings_for_case(
                self.test_case.identity
            )
            reverse_mappings = reopened.tested_symbol_mappings_for_symbol(
                self.value.identity
            )

        self.assertEqual(
            tuple(symbol.identity for symbol in first_symbols),
            (self.overload.identity, self.value.identity),
        )
        self.assertEqual(value_cases, (self.test_case, second_case))
        self.assertEqual(overload_cases, (self.test_case,))
        by_symbol = {mapping.symbol_identity: mapping for mapping in mappings}
        self.assertEqual(by_symbol[self.value.identity].references, (value_first,))
        self.assertEqual(
            by_symbol[self.overload.identity].references,
            (overload_first,),
        )
        self.assertEqual(
            tuple(mapping.test_case_identity for mapping in reverse_mappings),
            (self.test_case.identity, second_case.identity),
        )
        self.assertEqual(reverse_mappings[1].references, (value_second,))

    def test_case_without_body_has_no_inferred_symbol_mapping(self) -> None:
        case_without_body = replace(self.test_case, body_range=None)
        facts = SymbolSemanticFacts(
            self.value.identity,
            references=(source_range(self.test_source, 22, 8, 22, 13),),
        )

        with self._index() as index:
            index.rebuild(
                (self.value,),
                semantic_facts=(facts,),
                test_fixtures=(self.fixture,),
                test_cases=(case_without_body,),
            )

            self.assertEqual(
                index.directly_referenced_symbols(case_without_body.identity),
                (),
            )
            self.assertEqual(index.test_cases_for_symbol(self.value.identity), ())

    def test_operations_after_close_fail(self) -> None:
        index = self._index()
        index.close()
        index.close()

        with self.assertRaises(SymbolIndexClosedError):
            index.find_by_name("value")


def indexed_by_identity(
    symbols: tuple[Symbol, ...], identity: SymbolIdentity
) -> Symbol:
    return next(symbol for symbol in symbols if symbol.identity == identity)


if __name__ == "__main__":
    unittest.main()
