from __future__ import annotations

import unittest

from arkui_agent.evaluation import (
    BaselineRunner,
    BenchmarkCase,
    BenchmarkEnvironment,
    BenchmarkRevisionMismatchError,
    BenchmarkSuite,
    ExpectedRelation,
    ExpectedResults,
    FailureCategory,
    ManualAnnotation,
    QualifiedSymbol,
    RetrievalExecutionError,
    RetrievalOutput,
    RetrievedRelation,
    RetrievedSymbol,
    SymbolQueryMatch,
    SymbolSearchInput,
)


TARGET = QualifiedSymbol("opaque:target", "fixture::target")
OTHER = QualifiedSymbol("opaque:other", "fixture::other")
ANNOTATION = ManualAnnotation("reviewer", "Checked against controlled source.")


class StaticExecutor:
    def __init__(self, result: RetrievalOutput | Exception) -> None:
        self.result = result
        self.calls = 0

    def execute(self, query: object) -> RetrievalOutput:
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def suite(expected: ExpectedResults) -> BenchmarkSuite:
    return BenchmarkSuite(
        "metrics",
        "synthetic-cpp",
        "fixture-v1",
        (
            BenchmarkCase(
                "ranked-symbol",
                SymbolSearchInput("target", SymbolQueryMatch.DISPLAY_NAME),
                expected,
                ANNOTATION,
            ),
        ),
    )


class BaselineRunnerMetricTests(unittest.TestCase):
    def test_metrics_use_exact_identity_rank_and_annotated_denominators(self) -> None:
        expected = ExpectedResults(
            files=("src/target.cpp", "include/target.h"),
            symbols=(TARGET, OTHER),
        )
        output = RetrievalOutput(
            files=("src/target.cpp",),
            symbols=(
                RetrievedSymbol("opaque:noise", "fixture::noise"),
                RetrievedSymbol(TARGET.identity, TARGET.qualified_name),
            ),
        )
        ticks = iter((1_000_000, 3_500_000))

        report = BaselineRunner(
            StaticExecutor(output),
            recall_ks=(1, 2),
            clock_ns=lambda: next(ticks),
        ).run(suite(expected))

        result = report.results[0]
        self.assertEqual(result.latency_ms, 2.5)
        self.assertEqual(result.metrics.target_file_recall, 0.5)
        self.assertEqual(result.metrics.target_symbol_recall, 0.5)
        self.assertEqual(result.metrics.recall_at_k, ((1, 0.0), (2, 0.5)))
        self.assertEqual(result.metrics.mrr, 0.5)
        self.assertEqual(
            tuple(failure.category for failure in result.failures),
            (FailureCategory.TARGET_FILE_MISS, FailureCategory.TARGET_SYMBOL_MISS),
        )

    def test_same_qualified_name_with_wrong_identity_is_not_semantically_correct(self) -> None:
        output = RetrievalOutput(
            symbols=(RetrievedSymbol("opaque:wrong", TARGET.qualified_name),)
        )

        result = BaselineRunner(StaticExecutor(output)).run(
            suite(ExpectedResults(symbols=(TARGET,)))
        ).results[0]

        self.assertEqual(result.metrics.target_symbol_recall, 0.0)
        self.assertEqual(result.metrics.mrr, 0.0)
        self.assertEqual(
            {failure.category for failure in result.failures},
            {
                FailureCategory.TARGET_SYMBOL_MISS,
                FailureCategory.SYMBOL_IDENTITY_MISMATCH,
            },
        )

    def test_direct_relation_correctness_requires_exact_edge_set(self) -> None:
        expected_relation = ExpectedRelation(OTHER, TARGET)
        unexpected = RetrievedRelation(
            RetrievedSymbol(TARGET.identity, TARGET.qualified_name),
            RetrievedSymbol(OTHER.identity, OTHER.qualified_name),
        )

        result = BaselineRunner(StaticExecutor(RetrievalOutput(relations=(unexpected,)))).run(
            suite(ExpectedResults(relations=(expected_relation,)))
        ).results[0]

        self.assertFalse(result.metrics.direct_relation_correctness)
        self.assertEqual(
            {failure.category for failure in result.failures},
            {
                FailureCategory.DIRECT_RELATION_MISS,
                FailureCategory.UNEXPECTED_DIRECT_RELATION,
            },
        )

    def test_annotated_empty_result_is_success_not_missing_output(self) -> None:
        result = BaselineRunner(StaticExecutor(RetrievalOutput())).run(
            suite(ExpectedResults(files=(), symbols=(), relations=()))
        ).results[0]

        self.assertTrue(result.passed)
        self.assertEqual(result.metrics.target_file_recall, 1.0)
        self.assertEqual(result.metrics.target_symbol_recall, 1.0)
        self.assertTrue(result.metrics.direct_relation_correctness)

    def test_annotated_empty_result_rejects_unexpected_candidates(self) -> None:
        result = BaselineRunner(
            StaticExecutor(
                RetrievalOutput(
                    files=("src/unexpected.cpp",),
                    symbols=(RetrievedSymbol("opaque:unexpected", "fixture::unexpected"),),
                )
            )
        ).run(suite(ExpectedResults(files=(), symbols=()))).results[0]

        self.assertEqual(
            {failure.category for failure in result.failures},
            {FailureCategory.UNEXPECTED_FILE, FailureCategory.UNEXPECTED_SYMBOL},
        )

    def test_operational_and_unexpected_exceptions_are_classified(self) -> None:
        expected = ExpectedResults(files=("src/target.cpp",))
        for error, category in (
            (
                RetrievalExecutionError(
                    FailureCategory.BACKEND_UNAVAILABLE, "rg unavailable"
                ),
                FailureCategory.BACKEND_UNAVAILABLE,
            ),
            (RuntimeError("boom"), FailureCategory.UNEXPECTED_ERROR),
        ):
            with self.subTest(category=category):
                result = BaselineRunner(StaticExecutor(error)).run(
                    suite(expected)
                ).results[0]
                self.assertEqual(result.failures[0].category, category)
                self.assertEqual(len(result.failures), 1)

    def test_revision_mismatch_fails_before_any_query_executes(self) -> None:
        executor = StaticExecutor(RetrievalOutput())

        with self.assertRaisesRegex(
            BenchmarkRevisionMismatchError, "revision mismatch"
        ):
            BaselineRunner(executor).run(
                suite(ExpectedResults(files=())),
                environment=BenchmarkEnvironment("different-revision", ()),
            )
        self.assertEqual(executor.calls, 0)


if __name__ == "__main__":
    unittest.main()
