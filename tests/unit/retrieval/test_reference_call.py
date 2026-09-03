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
from arkui_agent.retrieval import (
    ReferenceCallRetriever,
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


class ReferenceCallRetrieverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory(prefix="reference-retrieval-test-")
        self.header = RepositoryFile.from_path("include/fixture/widget.h")
        self.source = RepositoryFile.from_path("src/widget.cpp")
        self.other_source = RepositoryFile.from_path("src/other.cpp")
        self.target = Symbol(
            SymbolIdentity("opaque:overload-int"),
            SymbolKind.FUNCTION,
            "overloaded",
            "fixture::overloaded",
            declaration=source_range(self.header, 5, 1, 5, 11),
            definition=source_range(self.source, 5, 1, 7, 2),
        )
        self.same_name_target = Symbol(
            SymbolIdentity("opaque:overload-double"),
            SymbolKind.FUNCTION,
            "overloaded",
            "fixture::overloaded",
            declaration=source_range(self.header, 8, 1, 8, 11),
            definition=source_range(self.source, 10, 1, 12, 2),
        )
        self.caller_a = Symbol(
            SymbolIdentity("opaque:caller-a"),
            SymbolKind.FUNCTION,
            "invoke",
            "fixture::first::invoke",
            definition=source_range(self.other_source, 3, 1, 6, 2),
        )
        self.caller_b = Symbol(
            SymbolIdentity("opaque:caller-b"),
            SymbolKind.FUNCTION,
            "invoke",
            "fixture::second::invoke",
            definition=source_range(self.other_source, 10, 1, 13, 2),
        )
        self.callee = Symbol(
            SymbolIdentity("opaque:callee"),
            SymbolKind.FUNCTION,
            "helper",
            "fixture::helper",
            declaration=source_range(self.header, 12, 1, 12, 7),
        )
        self.dangling_caller = SymbolIdentity("opaque:dangling-caller")
        self.dangling_callee = SymbolIdentity("opaque:dangling-callee")
        self.reference_a = source_range(self.source, 20, 4, 20, 14)
        self.reference_b = source_range(self.other_source, 8, 2, 8, 12)
        facts = (
            SymbolSemanticFacts(
                identity=self.target.identity,
                references=(self.reference_a, self.reference_b, self.reference_a),
                callers=(
                    self.caller_b.identity,
                    self.caller_a.identity,
                    self.caller_b.identity,
                    self.dangling_caller,
                ),
                callees=(
                    self.callee.identity,
                    self.callee.identity,
                    self.dangling_callee,
                ),
            ),
            SymbolSemanticFacts(
                identity=self.same_name_target.identity,
                references=(source_range(self.source, 30, 4, 30, 14),),
                callers=(self.caller_b.identity,),
            ),
        )
        self.index = SymbolIndex(Path(self.temporary.name) / "symbols.sqlite3")
        self.index.rebuild(
            (
                self.target,
                self.same_name_target,
                self.caller_a,
                self.caller_b,
                self.callee,
            ),
            semantic_facts=facts,
        )
        self.retriever = ReferenceCallRetriever(self.index)

    def tearDown(self) -> None:
        self.index.close()
        self.temporary.cleanup()

    def test_multiple_references_are_deduplicated_and_source_ordered(self) -> None:
        references = self.retriever.references(self.target.identity)

        self.assertEqual(
            tuple(result.source_range for result in references),
            (self.reference_b, self.reference_a),
        )
        self.assertTrue(
            all(result.identity == self.target.identity for result in references)
        )

    def test_direct_callers_are_deduplicated_and_identity_ordered(self) -> None:
        callers = self.retriever.callers(self.target.identity)

        self.assertEqual(
            tuple(relation.caller_identity.value for relation in callers),
            (
                "opaque:caller-a",
                "opaque:caller-b",
                "opaque:dangling-caller",
            ),
        )
        self.assertTrue(
            all(relation.callee_identity == self.target.identity for relation in callers)
        )

    def test_direct_callees_are_deduplicated_without_traversal(self) -> None:
        callees = self.retriever.callees(self.target.identity)

        self.assertEqual(
            tuple(relation.callee_identity.value for relation in callees),
            ("opaque:callee", "opaque:dangling-callee"),
        )
        self.assertEqual(self.retriever.callees(self.caller_a.identity), ())

    def test_call_relation_uses_caller_definition_as_source_provenance(self) -> None:
        caller_relation = next(
            relation
            for relation in self.retriever.callers(self.target.identity)
            if relation.caller_identity == self.caller_a.identity
        )
        callee_relation = next(
            relation
            for relation in self.retriever.callees(self.target.identity)
            if relation.callee_identity == self.callee.identity
        )

        self.assertEqual(caller_relation.source_range, self.caller_a.definition)
        self.assertEqual(callee_relation.source_range, self.target.definition)
        self.assertEqual(caller_relation.source_range.file, self.other_source)
        self.assertEqual(callee_relation.source_range.file, self.source)

    def test_dangling_endpoints_remain_explicit_and_are_not_guessed(self) -> None:
        dangling_caller = next(
            relation
            for relation in self.retriever.callers(self.target.identity)
            if relation.caller_identity == self.dangling_caller
        )
        dangling_callee = next(
            relation
            for relation in self.retriever.callees(self.target.identity)
            if relation.callee_identity == self.dangling_callee
        )

        self.assertTrue(dangling_caller.has_dangling_endpoint)
        self.assertIsNone(dangling_caller.caller)
        self.assertIsNone(dangling_caller.source_range)
        self.assertTrue(dangling_callee.has_dangling_endpoint)
        self.assertIsNone(dangling_callee.callee)
        self.assertEqual(dangling_callee.source_range, self.target.definition)

    def test_same_name_overloads_do_not_share_relations(self) -> None:
        target_references = self.retriever.references(self.target.identity)
        other_references = self.retriever.references(self.same_name_target.identity)

        self.assertNotEqual(target_references, other_references)
        self.assertEqual(len(other_references), 1)
        self.assertEqual(self.retriever.callees(self.same_name_target.identity), ())

    def test_unknown_source_identity_has_explicit_error(self) -> None:
        with self.assertRaises(UnknownSymbolIdentityError):
            self.retriever.references(SymbolIdentity("opaque:missing-source"))

    def test_results_are_deterministic_across_repeated_queries(self) -> None:
        self.assertEqual(
            self.retriever.references(self.target.identity),
            self.retriever.references(self.target.identity),
        )
        self.assertEqual(
            self.retriever.callers(self.target.identity),
            self.retriever.callers(self.target.identity),
        )
        self.assertEqual(
            self.retriever.callees(self.target.identity),
            self.retriever.callees(self.target.identity),
        )


if __name__ == "__main__":
    unittest.main()
