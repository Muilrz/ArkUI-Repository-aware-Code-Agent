from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from arkui_agent.evaluation import (
    BaselineRunner,
    BenchmarkCase,
    BenchmarkSuite,
    ExpectedRelation,
    ExpectedResults,
    ExpectedTest,
    IdentityQueryInput,
    ManualAnnotation,
    P1RetrievalExecutor,
    QualifiedSymbol,
    RetrievalKind,
    SymbolQueryMatch,
    SymbolSearchInput,
    TextSearchInput,
)
from arkui_agent.repository import (
    RepositoryFile,
    RepositoryWorkspace,
    SourceLocation,
    SourceRange,
    Symbol,
    SymbolIdentity,
    SymbolIndex,
    SymbolKind,
    SymbolSemanticFacts,
    TestCase,
    TestFixture,
)
from scripts.run_retrieval_baseline import main as baseline_main
from tests.fixtures.synthetic_cpp_repository import synthetic_cpp_repository


ANNOTATION = ManualAnnotation(
    "controlled-fixture-reviewer", "Expected fact checked against synthetic source."
)


def source_range(file: RepositoryFile, line: int, end_column: int = 20) -> SourceRange:
    return SourceRange(
        SourceLocation(file, line, 1), SourceLocation(file, line, end_column)
    )


class RetrievalBaselineIntegrationTests(unittest.TestCase):
    def test_all_p1_retrieval_kinds_run_through_one_harness_and_entry_point(self) -> None:
        with (
            synthetic_cpp_repository() as repository,
            TemporaryDirectory(prefix="retrieval-baseline-") as temporary,
        ):
            runtime = Path(temporary)
            index_path = runtime / "symbol-index.sqlite3"
            output_path = runtime / "baseline-report.json"
            cases_path = runtime / "controlled-cases.json"
            workspace = RepositoryWorkspace(repository.root)
            header = RepositoryFile.from_path("include/fixture/widget.h")
            source = RepositoryFile.from_path("src/widget.cpp")
            test_file = RepositoryFile.from_path("tests/widget_test.cpp")

            target = Symbol(
                SymbolIdentity("opaque:value"),
                SymbolKind.METHOD,
                "value",
                "fixture::Widget::value",
                declaration=source_range(header, 8),
                definition=source_range(source, 5),
            )
            caller = Symbol(
                SymbolIdentity("opaque:doubled"),
                SymbolKind.METHOD,
                "doubled_value",
                "fixture::DerivedWidget::doubled_value",
                declaration=source_range(header, 13),
                definition=source_range(source, 10),
            )
            callee = Symbol(
                SymbolIdentity("opaque:leaf"),
                SymbolKind.FUNCTION,
                "leaf",
                "fixture::leaf",
                definition=source_range(source, 6),
            )
            fixture = TestFixture(
                SymbolIdentity("test-fixture:widget"),
                "WidgetTest",
                source_range(test_file, 6),
            )
            test_case = TestCase(
                SymbolIdentity("test-case:value"),
                "ValueIsTwentyOne",
                fixture.identity,
                source_range(test_file, 9),
                SourceRange(
                    SourceLocation(test_file, 10, 1),
                    SourceLocation(test_file, 13, 2),
                ),
            )
            test_reference = SourceRange(
                SourceLocation(test_file, 12, 11),
                SourceLocation(test_file, 12, 23),
            )
            target_ref = source_range(source, 12)
            facts = SymbolSemanticFacts(
                target.identity,
                references=(target_ref, test_reference),
                callers=(caller.identity,),
                callees=(callee.identity,),
            )

            with SymbolIndex(index_path) as index:
                index.rebuild(
                    (target, caller, callee),
                    semantic_facts=(facts,),
                    test_fixtures=(fixture,),
                    test_cases=(test_case,),
                )
                suite = _suite(target, caller, callee, test_case)
                report = BaselineRunner(P1RetrievalExecutor(workspace, index)).run(
                    suite
                )

            self.assertEqual(report.summary.case_count, len(tuple(RetrievalKind)))
            self.assertEqual(report.summary.passed_count, len(tuple(RetrievalKind)))
            self.assertEqual(
                tuple(result.case.kind for result in report.results),
                tuple(RetrievalKind),
            )
            self.assertTrue(all(result.latency_ms >= 0 for result in report.results))

            cases_path.write_text(
                json.dumps(suite.to_dict(), indent=2), encoding="utf-8"
            )
            exit_code = baseline_main(
                (
                    "--cases",
                    str(cases_path),
                    "--repository-root",
                    str(repository.root),
                    "--index",
                    str(index_path),
                    "--output",
                    str(output_path),
                )
            )

            self.assertEqual(exit_code, 0)
            generated = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(generated["summary"]["passed_count"], 8)
            self.assertEqual(len(generated["results"]), 8)


def _suite(
    target: Symbol, caller: Symbol, callee: Symbol, test_case: TestCase
) -> BenchmarkSuite:
    target_expected = QualifiedSymbol(target.identity.value, target.qualified_name)
    caller_expected = QualifiedSymbol(caller.identity.value, caller.qualified_name)
    callee_expected = QualifiedSymbol(callee.identity.value, callee.qualified_name)

    def identity_case(
        case_id: str, kind: RetrievalKind, expected: ExpectedResults
    ) -> BenchmarkCase:
        return BenchmarkCase(
            case_id,
            IdentityQueryInput(kind, target_expected),
            expected,
            ANNOTATION,
        )

    return BenchmarkSuite(
        "controlled-all-p1-kinds",
        "synthetic-cpp",
        "fixture-v1",
        (
            BenchmarkCase(
                "text-return-value",
                TextSearchInput("return 21;", path_scope="src"),
                ExpectedResults(files=("src/widget.cpp",)),
                ANNOTATION,
            ),
            BenchmarkCase(
                "symbol-widget-value",
                SymbolSearchInput(
                    target.qualified_name, SymbolQueryMatch.QUALIFIED_NAME
                ),
                ExpectedResults(
                    files=("src/widget.cpp",), symbols=(target_expected,)
                ),
                ANNOTATION,
            ),
            identity_case(
                "declaration-widget-value",
                RetrievalKind.FIND_DECLARATION,
                ExpectedResults(
                    files=("include/fixture/widget.h",), symbols=(target_expected,)
                ),
            ),
            identity_case(
                "definition-widget-value",
                RetrievalKind.FIND_DEFINITION,
                ExpectedResults(files=("src/widget.cpp",), symbols=(target_expected,)),
            ),
            identity_case(
                "references-widget-value",
                RetrievalKind.FIND_REFERENCES,
                ExpectedResults(
                    files=("src/widget.cpp", "tests/widget_test.cpp"),
                    symbols=(target_expected,),
                ),
            ),
            identity_case(
                "callers-widget-value",
                RetrievalKind.FIND_CALLERS,
                ExpectedResults(
                    files=("src/widget.cpp",),
                    relations=(ExpectedRelation(caller_expected, target_expected),),
                ),
            ),
            identity_case(
                "callees-widget-value",
                RetrievalKind.FIND_CALLEES,
                ExpectedResults(
                    files=("src/widget.cpp",),
                    relations=(ExpectedRelation(target_expected, callee_expected),),
                ),
            ),
            identity_case(
                "tests-widget-value",
                RetrievalKind.FIND_TESTS,
                ExpectedResults(
                    files=("tests/widget_test.cpp",),
                    tests=(
                        ExpectedTest(
                            test_case.identity.value,
                            test_case.display_name,
                            "tests/widget_test.cpp",
                        ),
                    ),
                ),
            ),
        ),
    )


if __name__ == "__main__":
    unittest.main()
