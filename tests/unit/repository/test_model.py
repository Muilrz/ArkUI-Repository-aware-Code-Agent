from __future__ import annotations

import json
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path, PurePosixPath

from arkui_agent.repository import (
    RepositoryFile,
    SourceLocation,
    SourceRange,
    Symbol,
    SymbolIdentity,
    SymbolKind,
)


def source_range(
    file: RepositoryFile,
    start_line: int,
    start_column: int,
    end_line: int,
    end_column: int,
) -> SourceRange:
    return SourceRange(
        start=SourceLocation(file, start_line, start_column),
        end=SourceLocation(file, end_line, end_column),
    )


class RepositoryFileContractTests(unittest.TestCase):
    def test_file_identity_is_canonical_repository_relative_path(self) -> None:
        file = RepositoryFile.from_path(Path("include") / "fixture" / "widget.h")

        self.assertEqual(file.path, PurePosixPath("include/fixture/widget.h"))
        self.assertEqual(file.to_dict(), {"path": "include/fixture/widget.h"})
        self.assertEqual(
            file,
            RepositoryFile.from_path("include/fixture/widget.h"),
        )

    def test_file_identity_rejects_noncanonical_or_escaping_paths(self) -> None:
        for path in (
            "",
            ".",
            "../widget.h",
            "include/../widget.h",
            "include\\widget.h",
            "/absolute/widget.h",
            "C:/absolute/widget.h",
        ):
            with self.subTest(path=path):
                with self.assertRaises(ValueError):
                    RepositoryFile.from_path(path)

        for path in (
            PurePosixPath("include\\widget.h"),
            PurePosixPath("C:/widget.h"),
        ):
            with self.subTest(direct_path=path):
                with self.assertRaises(ValueError):
                    RepositoryFile(path)


class SourceContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.file = RepositoryFile.from_path("src/widget.cpp")

    def test_location_uses_one_based_coordinates_and_is_immutable(self) -> None:
        location = SourceLocation(self.file, line=4, column=7)

        self.assertEqual(
            location.to_dict(),
            {"file": "src/widget.cpp", "line": 4, "column": 7},
        )
        with self.assertRaises(FrozenInstanceError):
            location.line = 5  # type: ignore[misc]

        for line, column in ((0, 1), (1, 0)):
            with self.subTest(line=line, column=column):
                with self.assertRaises(ValueError):
                    SourceLocation(self.file, line, column)

    def test_range_is_half_open_ordered_and_single_file(self) -> None:
        range_ = source_range(self.file, 3, 2, 5, 1)

        self.assertEqual(range_.file, self.file)
        self.assertEqual(range_.start, SourceLocation(self.file, 3, 2))
        self.assertEqual(range_.end, SourceLocation(self.file, 5, 1))

        with self.assertRaisesRegex(ValueError, "must not precede"):
            source_range(self.file, 5, 1, 3, 2)

        other_file = RepositoryFile.from_path("include/widget.h")
        with self.assertRaisesRegex(ValueError, "same file"):
            SourceRange(
                SourceLocation(self.file, 1, 1),
                SourceLocation(other_file, 1, 2),
            )


class SymbolContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.header = RepositoryFile.from_path("include/fixture/widget.h")
        self.source = RepositoryFile.from_path("src/widget.cpp")
        self.declaration = source_range(self.header, 8, 5, 8, 23)
        self.definition = source_range(self.source, 5, 1, 8, 2)

    def test_required_symbol_kinds_and_test_extensions_are_available(self) -> None:
        self.assertEqual(
            set(SymbolKind),
            {
                SymbolKind.NAMESPACE,
                SymbolKind.CLASS,
                SymbolKind.STRUCT,
                SymbolKind.FUNCTION,
                SymbolKind.METHOD,
                SymbolKind.FIELD,
                SymbolKind.ENUM,
                SymbolKind.TEST_FIXTURE,
                SymbolKind.TEST_CASE,
            },
        )

    def test_identity_is_distinct_from_names(self) -> None:
        first = Symbol(
            identity=SymbolIdentity("backend:function:widget-value:int"),
            kind=SymbolKind.FUNCTION,
            display_name="value",
            qualified_name="fixture::value",
            declaration=self.declaration,
        )
        second = Symbol(
            identity=SymbolIdentity("backend:function:widget-value:double"),
            kind=SymbolKind.FUNCTION,
            display_name="value",
            qualified_name="fixture::value",
            declaration=self.declaration,
        )

        self.assertEqual(first.display_name, second.display_name)
        self.assertEqual(first.qualified_name, second.qualified_name)
        self.assertNotEqual(first.identity, second.identity)
        self.assertNotEqual(first, second)

    def test_parent_namespace_and_declaration_definition_are_independent(self) -> None:
        namespace_identity = SymbolIdentity("backend:namespace:fixture")
        class_identity = SymbolIdentity("backend:class:fixture-widget")
        method = Symbol(
            identity=SymbolIdentity("backend:method:fixture-widget-value"),
            kind=SymbolKind.METHOD,
            display_name="value",
            qualified_name="fixture::Widget::value",
            declaration=self.declaration,
            definition=self.definition,
            parent_identity=class_identity,
            namespace_identity=namespace_identity,
        )

        self.assertEqual(method.parent_identity, class_identity)
        self.assertEqual(method.namespace_identity, namespace_identity)
        self.assertEqual(method.declaration.file, self.header)
        self.assertEqual(method.definition.file, self.source)
        self.assertNotEqual(method.declaration, method.definition)

    def test_symbol_converts_to_json_compatible_record(self) -> None:
        symbol = Symbol(
            identity=SymbolIdentity("backend:method:fixture-widget-value"),
            kind=SymbolKind.METHOD,
            display_name="value",
            qualified_name="fixture::Widget::value",
            declaration=self.declaration,
            definition=self.definition,
            parent_identity=SymbolIdentity("backend:class:fixture-widget"),
            namespace_identity=SymbolIdentity("backend:namespace:fixture"),
        )

        record = symbol.to_dict()

        json.dumps(record)
        self.assertEqual(record["identity"], symbol.identity.value)
        self.assertEqual(record["kind"], "method")
        self.assertEqual(record["display_name"], "value")
        self.assertEqual(record["qualified_name"], "fixture::Widget::value")
        self.assertEqual(
            record["declaration"],
            self.declaration.to_dict(),
        )
        self.assertEqual(record["definition"], self.definition.to_dict())

    def test_symbol_requires_a_source_fact(self) -> None:
        with self.assertRaisesRegex(ValueError, "declaration or definition"):
            Symbol(
                identity=SymbolIdentity("backend:namespace:fixture"),
                kind=SymbolKind.NAMESPACE,
                display_name="fixture",
                qualified_name="fixture",
            )


if __name__ == "__main__":
    unittest.main()
