from __future__ import annotations

import unittest

from arkui_agent.repository import (
    RepositoryFile,
    SemanticProvider,
    SemanticProviderClosedError,
    SemanticProviderError,
    SourceLocation,
    SourceRange,
    Symbol,
    SymbolIdentity,
    SymbolKind,
)
from tests.fixtures.fake_semantic_provider import FakeSemanticProvider


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


class SemanticProviderContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.header = RepositoryFile.from_path("include/fixture/widget.h")
        self.source = RepositoryFile.from_path("src/widget.cpp")
        self.value = Symbol(
            identity=SymbolIdentity("opaque:value-method"),
            kind=SymbolKind.METHOD,
            display_name="value",
            qualified_name="fixture::Widget::value",
            declaration=source_range(self.header, 8, 5, 8, 23),
            definition=source_range(self.source, 5, 1, 8, 2),
        )
        self.doubled_value = Symbol(
            identity=SymbolIdentity("opaque:doubled-value-method"),
            kind=SymbolKind.METHOD,
            display_name="doubled_value",
            qualified_name="fixture::DerivedWidget::doubled_value",
            declaration=source_range(self.header, 13, 5, 13, 31),
            definition=source_range(self.source, 10, 1, 13, 2),
        )
        self.reference = source_range(self.source, 12, 12, 12, 19)
        self.provider = FakeSemanticProvider(
            symbols=(self.value, self.doubled_value),
            references={self.value.identity: (self.reference,)},
            callers={self.value.identity: (self.doubled_value,)},
            callees={self.doubled_value.identity: (self.value,)},
        )

    def test_fake_provider_satisfies_runtime_protocol(self) -> None:
        self.assertIsInstance(self.provider, SemanticProvider)

    def test_symbols_in_file_return_p1_model_symbols_in_stable_order(self) -> None:
        self.assertEqual(
            self.provider.symbols_in_file(self.header),
            (self.value, self.doubled_value),
        )
        self.assertEqual(
            self.provider.symbols_in_file(self.source),
            (self.value, self.doubled_value),
        )

    def test_declaration_and_definition_are_independent_queries(self) -> None:
        self.assertEqual(
            self.provider.declaration(self.value.identity),
            self.value.declaration,
        )
        self.assertEqual(
            self.provider.definition(self.value.identity),
            self.value.definition,
        )

    def test_reference_caller_and_callee_results_use_p1_models(self) -> None:
        self.assertEqual(
            self.provider.references(self.value.identity),
            (self.reference,),
        )
        self.assertEqual(
            self.provider.callers(self.value.identity),
            (self.doubled_value,),
        )
        self.assertEqual(
            self.provider.callees(self.doubled_value.identity),
            (self.value,),
        )

    def test_missing_facts_return_none_or_empty_tuple(self) -> None:
        missing = SymbolIdentity("opaque:missing")

        self.assertEqual(
            self.provider.symbols_in_file(
                RepositoryFile.from_path("src/missing.cpp")
            ),
            (),
        )
        self.assertIsNone(self.provider.declaration(missing))
        self.assertIsNone(self.provider.definition(missing))
        self.assertEqual(self.provider.references(missing), ())
        self.assertEqual(self.provider.callers(missing), ())
        self.assertEqual(self.provider.callees(missing), ())

    def test_context_manager_closes_provider_and_close_is_idempotent(self) -> None:
        with self.provider as provider:
            self.assertIs(provider, self.provider)
            self.assertEqual(
                provider.definition(self.value.identity),
                self.value.definition,
            )

        self.provider.close()
        with self.assertRaises(SemanticProviderClosedError):
            self.provider.symbols_in_file(self.source)

    def test_operational_failure_uses_provider_error_boundary(self) -> None:
        failure = SemanticProviderError("backend unavailable")
        provider = FakeSemanticProvider(query_error=failure)

        with self.assertRaises(SemanticProviderError) as raised:
            provider.references(SymbolIdentity("opaque:any-symbol"))

        self.assertIs(raised.exception, failure)


if __name__ == "__main__":
    unittest.main()
