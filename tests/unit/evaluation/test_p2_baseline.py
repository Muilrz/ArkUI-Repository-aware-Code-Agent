from __future__ import annotations

import unittest

from arkui_agent.evaluation import (
    BenchmarkEnvironment,
    BenchmarkRevisionMismatchError,
    P2Annotation,
    P2BaselineSuite,
    P2Capability,
    P2ExpectedCase,
    P2FailureCategory,
    P2Observation,
    P2Relation,
    P2StageLatency,
    P2TraceStatus,
    evaluate_p2_baseline,
)
from tests.fixtures.p2_baseline_cases import ARKUI_REVISION, build_p2_baseline_suite


def edge(ordinal: int, relation: str, source: str, target: str) -> P2Relation:
    return P2Relation("path", ordinal, relation, source, target)


ANNOTATION = P2Annotation("tests/fixtures/source.py", "Reviewed before execution.")


class P2BaselineMetricTests(unittest.TestCase):
    def test_incomplete_expected_case_conforms_but_scores_zero_call_chain_accuracy(self) -> None:
        present = edge(0, "CALL", "entry", "model")
        missing = edge(1, "CREATE", "model", "pattern")
        expected = P2ExpectedCase(
            "creation-gap",
            P2Capability.CREATION_TRACE,
            "menu",
            P2TraceStatus.INCOMPLETE,
            (present,),
            (missing,),
            ("unsupported_pattern_callback",),
            annotation=ANNOTATION,
        )
        suite = P2BaselineSuite("suite", "repo", "revision", (expected,))
        observation = P2Observation(
            expected.case_id,
            P2TraceStatus.INCOMPLETE,
            (present,),
            ("unsupported_pattern_callback",),
        )

        report = evaluate_p2_baseline(
            suite,
            (observation,),
            stage_latencies=(P2StageLatency("creation", 2.5),),
            environment=BenchmarkEnvironment("revision", ()),
        )

        result = report.results[0]
        self.assertTrue(result.metrics.expected_conformance)
        self.assertEqual(result.metrics.relation_coverage, 0.5)
        self.assertEqual(result.metrics.call_chain_score, 0.0)
        self.assertEqual(report.summary.call_chain_accuracy, 0.0)
        self.assertEqual(report.summary.status_counts, ((P2TraceStatus.INCOMPLETE, 1),))
        self.assertEqual(report.summary.gap_counts, (("unsupported_pattern_callback", 1),))
        self.assertEqual(report.summary.total_latency_ms, 2.5)

    def test_only_unique_exhaustive_gap_free_complete_exact_chain_scores_one(self) -> None:
        relations = (
            edge(0, "CALL", "entry", "model"),
            edge(1, "CALL", "model", "frame"),
        )
        expected = P2ExpectedCase(
            "creation-complete",
            P2Capability.CREATION_TRACE,
            "button",
            P2TraceStatus.COMPLETE,
            relations,
            annotation=ANNOTATION,
        )
        suite = P2BaselineSuite("suite", "repo", "revision", (expected,))

        report = evaluate_p2_baseline(
            suite,
            (P2Observation(expected.case_id, P2TraceStatus.COMPLETE, relations),),
            stage_latencies=(),
            environment=BenchmarkEnvironment("revision", ()),
        )

        self.assertEqual(report.results[0].metrics.call_chain_score, 1.0)
        self.assertEqual(report.summary.call_chain_accuracy, 1.0)

    def test_relation_provenance_and_shape_regressions_have_distinct_taxonomy(self) -> None:
        first = edge(0, "CALL", "entry", "model")
        second = edge(1, "CALL", "model", "frame")
        wrong = edge(1, "CALL", "model", "wrong")
        expected = P2ExpectedCase(
            "creation-regression",
            P2Capability.CREATION_TRACE,
            "button",
            P2TraceStatus.COMPLETE,
            (first, second),
            annotation=ANNOTATION,
        )
        suite = P2BaselineSuite("suite", "repo", "revision", (expected,))

        result = evaluate_p2_baseline(
            suite,
            (
                P2Observation(
                    expected.case_id,
                    P2TraceStatus.COMPLETE,
                    (first, wrong),
                    provenance_valid=False,
                ),
            ),
            stage_latencies=(),
            environment=BenchmarkEnvironment("revision", ()),
        ).results[0]

        self.assertEqual(result.missing_relations, (second,))
        self.assertEqual(result.incorrect_relations, (wrong,))
        self.assertEqual(
            {failure.category for failure in result.failures},
            {
                P2FailureCategory.MISSING_EXPECTED_RELATION,
                P2FailureCategory.INCORRECT_RELATION,
                P2FailureCategory.PROVENANCE_MISSING,
            },
        )
        self.assertEqual(result.metrics.call_chain_score, 0.0)

    def test_revision_mismatch_fails_before_metrics(self) -> None:
        expected = P2ExpectedCase(
            "graph",
            P2Capability.SYMBOL_GRAPH,
            None,
            P2TraceStatus.COMPLETE,
            (),
            annotation=ANNOTATION,
        )
        suite = P2BaselineSuite("suite", "repo", "expected", (expected,))
        with self.assertRaises(BenchmarkRevisionMismatchError):
            evaluate_p2_baseline(
                suite,
                (),
                stage_latencies=(),
                environment=BenchmarkEnvironment("actual", ()),
            )


class FormalP2SuiteContractTests(unittest.TestCase):
    def test_suite_reuses_frozen_cases_and_covers_all_p2_capabilities(self) -> None:
        suite = build_p2_baseline_suite()

        self.assertEqual(suite.repository_revision, ARKUI_REVISION)
        self.assertEqual(len(suite.repository_revision), 40)
        self.assertEqual(len(suite.cases), 18)
        self.assertEqual({case.capability for case in suite.cases}, set(P2Capability))
        self.assertEqual(
            {case.component for case in suite.cases if case.component is not None},
            {"button", "text", "menu"},
        )
        self.assertTrue(
            all(case.annotation.source_fixture for case in suite.cases)
        )
        self.assertEqual(
            next(case for case in suite.cases if case.case_id == "overlay-show-menu").status,
            P2TraceStatus.INCOMPLETE,
        )
        self.assertEqual(
            next(case for case in suite.cases if case.case_id == "overlay-close-menu").status,
            P2TraceStatus.AMBIGUOUS,
        )
        self.assertEqual(
            sum(case.capability.is_trace for case in suite.cases),
            14,
        )


if __name__ == "__main__":
    unittest.main()
