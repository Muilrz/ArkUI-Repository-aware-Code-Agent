from __future__ import annotations

import os
import shutil
import unittest

from arkui_agent.repository import (
    ClangdSemanticProvider,
    RepositoryFile,
    RepositoryWorkspace,
    SemanticProvider,
    SemanticProviderClosedError,
    Symbol,
    SymbolKind,
)
from tests.fixtures.synthetic_cpp_repository import synthetic_cpp_repository


def _clangd_executable() -> str:
    configured = os.environ.get("CLANGD_EXECUTABLE", "clangd")
    executable = shutil.which(configured)
    if executable is None:
        raise unittest.SkipTest(
            f"clangd integration unavailable: executable {configured!r} was not found"
        )
    return executable


class ClangdSemanticProviderIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.executable = _clangd_executable()

    def setUp(self) -> None:
        self.repository_context = synthetic_cpp_repository()
        self.repository = self.repository_context.__enter__()
        self.workspace = RepositoryWorkspace(self.repository.root)
        self.provider = ClangdSemanticProvider(
            self.workspace,
            executable=self.executable,
            fallback_flags=(
                "-std=c++17",
                f"-I{self.repository.root / 'include'}",
            ),
        )

    def tearDown(self) -> None:
        self.provider.close()
        self.repository_context.__exit__(None, None, None)

    def _header_symbols(self) -> tuple[Symbol, ...]:
        return self.provider.symbols_in_file(
            RepositoryFile.from_path("include/fixture/widget.h")
        )

    def _source_symbols(self) -> tuple[Symbol, ...]:
        return self.provider.symbols_in_file(
            RepositoryFile.from_path("src/widget.cpp")
        )

    @staticmethod
    def _named(symbols: tuple[Symbol, ...], name: str) -> Symbol:
        matches = [symbol for symbol in symbols if symbol.display_name == name]
        if not matches:
            raise AssertionError(f"clangd did not return symbol {name!r}")
        return matches[0]

    def test_lifecycle_and_runtime_contract(self) -> None:
        self.assertIsInstance(self.provider, SemanticProvider)
        self.assertFalse(self.provider.is_closed)

        self.provider.close()
        self.provider.close()

        self.assertTrue(self.provider.is_closed)
        with self.assertRaises(SemanticProviderClosedError):
            self._header_symbols()

    def test_symbols_include_semantic_namespace_class_and_member(self) -> None:
        symbols = self._header_symbols()

        namespace = self._named(symbols, "fixture")
        widget = self._named(symbols, "Widget")
        value = self._named(symbols, "value")

        self.assertEqual(namespace.kind, SymbolKind.NAMESPACE)
        self.assertEqual(widget.kind, SymbolKind.CLASS)
        self.assertEqual(value.kind, SymbolKind.METHOD)
        self.assertEqual(widget.namespace_identity, namespace.identity)
        self.assertEqual(value.parent_identity, widget.identity)
        self.assertIn("Widget", value.qualified_name)

    def test_declaration_definition_and_references(self) -> None:
        self._source_symbols()
        value = self._named(self._header_symbols(), "value")

        declaration = self.provider.declaration(value.identity)
        definition = self.provider.definition(value.identity)
        references = self.provider.references(value.identity)

        self.assertIsNotNone(declaration)
        self.assertIsNotNone(definition)
        assert declaration is not None and definition is not None
        self.assertEqual(
            declaration.file.path.as_posix(), "include/fixture/widget.h"
        )
        self.assertEqual(definition.file.path.as_posix(), "src/widget.cpp")
        self.assertIn(
            "src/widget.cpp", {reference.file.path.as_posix() for reference in references}
        )

    def test_call_hierarchy_reports_direct_caller_and_callee(self) -> None:
        if not self.provider.supports_call_hierarchy:
            self.skipTest("installed clangd does not advertise call hierarchy support")
        self._source_symbols()
        header_symbols = self._header_symbols()
        value = self._named(header_symbols, "value")
        doubled_value = self._named(header_symbols, "doubled_value")

        callers = self.provider.callers(value.identity)
        callees = self.provider.callees(doubled_value.identity)

        self.assertIn("doubled_value", {symbol.display_name for symbol in callers})
        self.assertIn("value", {symbol.display_name for symbol in callees})


if __name__ == "__main__":
    unittest.main()
