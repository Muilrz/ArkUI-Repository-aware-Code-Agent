from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from arkui_agent.repository import (
    RepositoryFile,
    SourceLocation,
    SourceRange,
    Symbol,
    SymbolIdentity,
    SymbolIndex,
    SymbolKind,
    SymbolSemanticFacts,
)
from tests.fixtures.fake_semantic_provider import FakeSemanticProvider
from tests.fixtures.synthetic_cpp_repository import synthetic_cpp_repository


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


class SymbolIndexIntegrationTests(unittest.TestCase):
    def test_provider_model_facts_persist_across_index_reopen(self) -> None:
        repository_context = synthetic_cpp_repository()
        repository = repository_context.__enter__()
        self.addCleanup(repository_context.__exit__, None, None, None)
        header = RepositoryFile.from_path(
            repository.header.relative_to(repository.root).as_posix()
        )
        source = RepositoryFile.from_path(
            repository.source.relative_to(repository.root).as_posix()
        )
        value = Symbol(
            identity=SymbolIdentity("provider:value"),
            kind=SymbolKind.METHOD,
            display_name="value",
            qualified_name="fixture::Widget::value",
            declaration=source_range(header, 8, 5, 8, 10),
            definition=source_range(source, 5, 5, 5, 10),
        )
        doubled_value = Symbol(
            identity=SymbolIdentity("provider:doubled-value"),
            kind=SymbolKind.METHOD,
            display_name="doubled_value",
            qualified_name="fixture::DerivedWidget::doubled_value",
            declaration=source_range(header, 13, 5, 13, 18),
            definition=source_range(source, 10, 5, 10, 18),
        )
        reference = source_range(source, 12, 12, 12, 17)
        provider = FakeSemanticProvider(
            (value, doubled_value),
            references={value.identity: (reference,)},
            callers={value.identity: (doubled_value,)},
            callees={doubled_value.identity: (value,)},
        )
        facts = tuple(
            SymbolSemanticFacts(
                identity=symbol.identity,
                references=provider.references(symbol.identity),
                callers=tuple(
                    caller.identity for caller in provider.callers(symbol.identity)
                ),
                callees=tuple(
                    callee.identity for callee in provider.callees(symbol.identity)
                ),
            )
            for symbol in (value, doubled_value)
        )

        with TemporaryDirectory(prefix="symbol-index-integration-") as temporary:
            database_path = Path(temporary) / "runtime" / "symbols.sqlite3"
            with SymbolIndex(database_path) as index:
                index.rebuild((value, doubled_value), semantic_facts=facts)

            with SymbolIndex(database_path) as reopened:
                self.assertEqual(reopened.get(value.identity), value)
                self.assertEqual(
                    reopened.semantic_facts(value.identity),
                    facts[0],
                )
                self.assertEqual(
                    reopened.semantic_facts(doubled_value.identity),
                    facts[1],
                )


if __name__ == "__main__":
    unittest.main()
