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
)
from arkui_agent.retrieval import (
    AmbiguousSymbolCandidateError,
    DefinitionDeclarationRetriever,
    SymbolCandidateMatch,
    SymbolCandidateNotFoundError,
    UnknownSymbolIdentityError,
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


class DefinitionDeclarationRetrieverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory(prefix="definition-retrieval-test-")
        self.header = RepositoryFile.from_path("include/fixture/widget.h")
        self.source = RepositoryFile.from_path("src/widget.cpp")
        self.alpha_namespace = SymbolIdentity("opaque:namespace-alpha")
        self.beta_namespace = SymbolIdentity("opaque:namespace-beta")
        self.class_a = SymbolIdentity("opaque:class-a")
        self.class_b = SymbolIdentity("opaque:class-b")
        self.separate = Symbol(
            identity=SymbolIdentity("opaque:separate"),
            kind=SymbolKind.METHOD,
            display_name="separate",
            qualified_name="alpha::A::separate",
            declaration=source_range(self.header, 10, 5, 10, 13),
            definition=source_range(self.source, 20, 8, 20, 16),
            parent_identity=self.class_a,
            namespace_identity=self.alpha_namespace,
        )
        self.namespace_symbols = (
            Symbol(
                SymbolIdentity("opaque:detail-alpha"),
                SymbolKind.NAMESPACE,
                "detail",
                "alpha::detail",
                declaration=source_range(self.header, 1, 1, 1, 7),
                namespace_identity=self.alpha_namespace,
            ),
            Symbol(
                SymbolIdentity("opaque:detail-beta"),
                SymbolKind.NAMESPACE,
                "detail",
                "beta::detail",
                declaration=source_range(self.header, 2, 1, 2, 7),
                namespace_identity=self.beta_namespace,
            ),
        )
        self.member_symbols = (
            Symbol(
                SymbolIdentity("opaque:run-a"),
                SymbolKind.METHOD,
                "run",
                "alpha::A::run",
                declaration=source_range(self.header, 12, 5, 12, 8),
                parent_identity=self.class_a,
                namespace_identity=self.alpha_namespace,
            ),
            Symbol(
                SymbolIdentity("opaque:run-b"),
                SymbolKind.METHOD,
                "run",
                "alpha::B::run",
                declaration=source_range(self.header, 18, 5, 18, 8),
                parent_identity=self.class_b,
                namespace_identity=self.alpha_namespace,
            ),
        )
        self.overloads = (
            Symbol(
                SymbolIdentity("opaque:convert-int"),
                SymbolKind.FUNCTION,
                "convert",
                "alpha::convert",
                declaration=source_range(self.header, 25, 1, 25, 8),
            ),
            Symbol(
                SymbolIdentity("opaque:convert-double"),
                SymbolKind.FUNCTION,
                "convert",
                "alpha::convert",
                declaration=source_range(self.header, 26, 1, 26, 8),
            ),
        )
        self.fallback_split = (
            Symbol(
                SymbolIdentity("opaque:fallback-declaration"),
                SymbolKind.METHOD,
                "fallback",
                "alpha::A::fallback",
                declaration=source_range(self.header, 30, 5, 30, 13),
            ),
            Symbol(
                SymbolIdentity("opaque:fallback-definition"),
                SymbolKind.METHOD,
                "fallback",
                "alpha::A::fallback",
                definition=source_range(self.source, 35, 8, 35, 16),
            ),
        )
        database = Path(self.temporary.name) / "symbols.sqlite3"
        self.index = SymbolIndex(database)
        self.index.rebuild(
            (
                self.separate,
                *reversed(self.namespace_symbols),
                *reversed(self.member_symbols),
                *reversed(self.overloads),
                *reversed(self.fallback_split),
            )
        )
        self.retriever = DefinitionDeclarationRetriever(self.index)

    def tearDown(self) -> None:
        self.index.close()
        self.temporary.cleanup()

    def test_declaration_and_definition_are_identity_based_and_separate(self) -> None:
        identity = self.retriever.resolve_unique(
            self.retriever.candidates_by_qualified_name("alpha::A::separate")
        )

        self.assertEqual(identity, self.separate.identity)
        self.assertEqual(
            self.retriever.declaration(identity), self.separate.declaration
        )
        self.assertEqual(self.retriever.definition(identity), self.separate.definition)

    def test_source_range_preserves_repository_relative_provenance(self) -> None:
        declaration = self.retriever.declaration(self.separate.identity)
        definition = self.retriever.definition(self.separate.identity)

        self.assertIsNotNone(declaration)
        self.assertIsNotNone(definition)
        assert declaration is not None and definition is not None
        self.assertEqual(declaration.file, self.header)
        self.assertEqual(definition.file, self.source)
        self.assertEqual((declaration.start.line, declaration.start.column), (10, 5))
        self.assertEqual((definition.start.line, definition.start.column), (20, 8))

    def test_same_namespace_names_return_distinct_candidates(self) -> None:
        candidates = self.retriever.candidates_by_name("detail")

        self.assertEqual(candidates.match, SymbolCandidateMatch.DISPLAY_NAME)
        self.assertEqual(candidates.symbols, self.namespace_symbols)
        with self.assertRaises(AmbiguousSymbolCandidateError):
            self.retriever.resolve_unique(candidates)

    def test_same_member_names_remain_distinct_by_parent_identity(self) -> None:
        candidates = self.retriever.candidates_by_name("run")

        self.assertEqual(
            {symbol.parent_identity for symbol in candidates.symbols},
            {self.class_a, self.class_b},
        )
        with self.assertRaises(AmbiguousSymbolCandidateError):
            self.retriever.resolve_unique(candidates)

    def test_overloaded_qualified_name_is_explicitly_ambiguous(self) -> None:
        candidates = self.retriever.candidates_by_qualified_name("alpha::convert")

        self.assertEqual(candidates.match, SymbolCandidateMatch.QUALIFIED_NAME)
        self.assertEqual(len(candidates.symbols), 2)
        with self.assertRaises(AmbiguousSymbolCandidateError) as raised:
            self.retriever.resolve_unique(candidates)
        self.assertEqual(raised.exception.candidates, candidates)

    def test_qualified_name_candidate_can_resolve_unique_identity(self) -> None:
        candidates = self.retriever.candidates_by_qualified_name(
            "alpha::A::separate"
        )

        self.assertEqual(candidates.symbols, (self.separate,))
        self.assertEqual(
            self.retriever.resolve_unique(candidates), self.separate.identity
        )

    def test_fallback_split_identities_are_not_reconciled_by_qualified_name(
        self,
    ) -> None:
        candidates = self.retriever.candidates_by_qualified_name(
            "alpha::A::fallback"
        )

        with self.assertRaises(AmbiguousSymbolCandidateError):
            self.retriever.resolve_unique(candidates)
        declaration_symbol, definition_symbol = self.fallback_split
        self.assertIsNotNone(
            self.retriever.declaration(declaration_symbol.identity)
        )
        self.assertIsNone(self.retriever.definition(declaration_symbol.identity))
        self.assertIsNone(self.retriever.declaration(definition_symbol.identity))
        self.assertIsNotNone(
            self.retriever.definition(definition_symbol.identity)
        )

    def test_candidate_order_is_deterministic(self) -> None:
        first = self.retriever.candidates_by_name("convert")
        second = self.retriever.candidates_by_name("convert")

        self.assertEqual(first, second)
        self.assertEqual(
            tuple(symbol.identity.value for symbol in first.symbols),
            tuple(sorted(symbol.identity.value for symbol in self.overloads)),
        )

    def test_empty_candidate_set_reports_not_found(self) -> None:
        candidates = self.retriever.candidates_by_name("missing")

        with self.assertRaises(SymbolCandidateNotFoundError):
            self.retriever.resolve_unique(candidates)

    def test_unknown_identity_is_not_reconciled_by_name(self) -> None:
        with self.assertRaises(UnknownSymbolIdentityError):
            self.retriever.declaration(SymbolIdentity("opaque:not-indexed"))


if __name__ == "__main__":
    unittest.main()
