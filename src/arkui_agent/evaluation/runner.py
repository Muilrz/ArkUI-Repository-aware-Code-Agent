"""Unified execution, metrics, and failure analysis for P1 retrieval baselines."""

from __future__ import annotations

import json
import time
from collections import Counter
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Protocol

from arkui_agent.evaluation.environment import (
    BenchmarkEnvironment,
    validate_repository_revision,
)
from arkui_agent.evaluation.model import (
    BENCHMARK_SCHEMA_VERSION,
    BenchmarkCase,
    BenchmarkQuery,
    BenchmarkSuite,
    ExpectedRelation,
    ExpectedResults,
    ExpectedTest,
    QualifiedSymbol,
    RetrievalKind,
)


class FailureCategory(str, Enum):
    QUERY_REJECTED = "query_rejected"
    BACKEND_UNAVAILABLE = "backend_unavailable"
    BACKEND_FAILURE = "backend_failure"
    INDEX_FAILURE = "index_failure"
    UNEXPECTED_ERROR = "unexpected_error"
    EMPTY_RESULT = "empty_result"
    TARGET_FILE_MISS = "target_file_miss"
    TARGET_SYMBOL_MISS = "target_symbol_miss"
    TARGET_TEST_MISS = "target_test_miss"
    SYMBOL_IDENTITY_MISMATCH = "symbol_identity_mismatch"
    UNEXPECTED_FILE = "unexpected_file"
    UNEXPECTED_SYMBOL = "unexpected_symbol"
    UNEXPECTED_TEST = "unexpected_test"
    DIRECT_RELATION_MISS = "direct_relation_miss"
    UNEXPECTED_DIRECT_RELATION = "unexpected_direct_relation"


class RetrievalExecutionError(RuntimeError):
    """An executor-classified operational failure safe for benchmark reports."""

    def __init__(self, category: FailureCategory, message: str) -> None:
        if category not in {
            FailureCategory.QUERY_REJECTED,
            FailureCategory.BACKEND_UNAVAILABLE,
            FailureCategory.BACKEND_FAILURE,
            FailureCategory.INDEX_FAILURE,
        }:
            raise ValueError(f"Invalid execution failure category: {category.value}")
        self.category = category
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class RetrievedSymbol:
    """Observed symbol; missing qualified names stay explicit for dangling facts."""

    identity: str
    qualified_name: str | None

    def to_dict(self) -> dict[str, object]:
        return {"identity": self.identity, "qualified_name": self.qualified_name}


@dataclass(frozen=True, slots=True)
class RetrievedTest:
    identity: str
    display_name: str
    file: str

    def to_dict(self) -> dict[str, str]:
        return {
            "identity": self.identity,
            "display_name": self.display_name,
            "file": self.file,
        }


@dataclass(frozen=True, slots=True)
class RetrievedRelation:
    caller: RetrievedSymbol
    callee: RetrievedSymbol

    def to_dict(self) -> dict[str, object]:
        return {"caller": self.caller.to_dict(), "callee": self.callee.to_dict()}


@dataclass(frozen=True, slots=True)
class RetrievalOutput:
    """Normalized executor output; tuple order preserves backend ranking."""

    files: tuple[str, ...] = ()
    symbols: tuple[RetrievedSymbol, ...] = ()
    tests: tuple[RetrievedTest, ...] = ()
    relations: tuple[RetrievedRelation, ...] = ()

    def is_empty(self) -> bool:
        return not (self.files or self.symbols or self.tests or self.relations)

    def to_dict(self) -> dict[str, object]:
        return {
            "files": list(self.files),
            "symbols": [item.to_dict() for item in self.symbols],
            "tests": [item.to_dict() for item in self.tests],
            "relations": [item.to_dict() for item in self.relations],
        }


class RetrievalExecutor(Protocol):
    """Backend adapter boundary consumed by the baseline runner."""

    def execute(self, query: BenchmarkQuery) -> RetrievalOutput:
        """Execute exactly one normalized retrieval query."""


@dataclass(frozen=True, slots=True)
class CaseMetrics:
    """Deterministic metrics; ``None`` means the dimension was not annotated.

    Target recalls use exact set membership and an annotated-target denominator.
    Recall@K and MRR use the ranked symbol tuple and require exact agreement on
    both opaque identity and qualified name. Direct relation correctness is true
    only when the observed and annotated direct-edge sets are exactly equal.
    """

    target_file_recall: float | None
    target_symbol_recall: float | None
    recall_at_k: tuple[tuple[int, float], ...]
    mrr: float | None
    direct_relation_correctness: bool | None
    target_test_recall: float | None

    def to_dict(self) -> dict[str, object]:
        return {
            "target_file_recall": self.target_file_recall,
            "target_symbol_recall": self.target_symbol_recall,
            "recall_at_k": {str(k): value for k, value in self.recall_at_k},
            "mrr": self.mrr,
            "direct_relation_correctness": self.direct_relation_correctness,
            "target_test_recall": self.target_test_recall,
        }


@dataclass(frozen=True, slots=True)
class CaseFailure:
    category: FailureCategory
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {"category": self.category.value, "detail": self.detail}


@dataclass(frozen=True, slots=True)
class BenchmarkCaseResult:
    case: BenchmarkCase
    latency_ms: float
    output: RetrievalOutput
    metrics: CaseMetrics
    failures: tuple[CaseFailure, ...]

    @property
    def passed(self) -> bool:
        return not self.failures

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.case.case_id,
            "kind": self.case.kind.value,
            "query": self.case.query.to_dict(),
            "expected": self.case.expected.to_dict(),
            "annotation": self.case.annotation.to_dict(),
            "passed": self.passed,
            "latency_ms": self.latency_ms,
            "metrics": self.metrics.to_dict(),
            "failures": [failure.to_dict() for failure in self.failures],
            "output": self.output.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class BenchmarkSummary:
    case_count: int
    passed_count: int
    failed_count: int
    mean_latency_ms: float
    target_file_recall: float | None
    target_symbol_recall: float | None
    recall_at_k: tuple[tuple[int, float], ...]
    mrr: float | None
    direct_relation_correctness: float | None
    target_test_recall: float | None
    failure_counts: tuple[tuple[FailureCategory, int], ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "case_count": self.case_count,
            "passed_count": self.passed_count,
            "failed_count": self.failed_count,
            "mean_latency_ms": self.mean_latency_ms,
            "target_file_recall": self.target_file_recall,
            "target_symbol_recall": self.target_symbol_recall,
            "recall_at_k": {str(k): value for k, value in self.recall_at_k},
            "mrr": self.mrr,
            "direct_relation_correctness": self.direct_relation_correctness,
            "target_test_recall": self.target_test_recall,
            "failure_counts": {
                category.value: count for category, count in self.failure_counts
            },
        }


@dataclass(frozen=True, slots=True)
class BenchmarkReport:
    suite: BenchmarkSuite
    results: tuple[BenchmarkCaseResult, ...]
    summary: BenchmarkSummary
    environment: BenchmarkEnvironment | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": BENCHMARK_SCHEMA_VERSION,
            "suite": {
                "suite_id": self.suite.suite_id,
                "repository": self.suite.repository,
                "repository_revision": self.suite.repository_revision,
            },
            "environment": (
                None if self.environment is None else self.environment.to_dict()
            ),
            "summary": self.summary.to_dict(),
            "results": [result.to_dict() for result in self.results],
        }

    def write_json(self, path: str | Path) -> None:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


class BaselineRunner:
    """Run a suite sequentially and preserve one latency/failure record per case."""

    def __init__(
        self,
        executor: RetrievalExecutor,
        *,
        recall_ks: tuple[int, ...] = (1, 5, 10),
        clock_ns: Callable[[], int] = time.perf_counter_ns,
    ) -> None:
        if not recall_ks or any(
            isinstance(k, bool) or not isinstance(k, int) or k < 1
            for k in recall_ks
        ):
            raise ValueError("recall_ks must contain positive integers.")
        if len(set(recall_ks)) != len(recall_ks):
            raise ValueError("recall_ks must not contain duplicates.")
        self._executor = executor
        self._recall_ks = tuple(sorted(recall_ks))
        self._clock_ns = clock_ns

    def run(
        self,
        suite: BenchmarkSuite,
        *,
        environment: BenchmarkEnvironment | None = None,
    ) -> BenchmarkReport:
        if environment is not None:
            validate_repository_revision(
                suite.repository_revision, environment.repository_revision
            )
        results = tuple(self._run_case(case) for case in suite.cases)
        return BenchmarkReport(
            suite,
            results,
            _summarize(results, self._recall_ks),
            environment,
        )

    def _run_case(self, case: BenchmarkCase) -> BenchmarkCaseResult:
        started = self._clock_ns()
        execution_failure: CaseFailure | None = None
        try:
            output = self._executor.execute(case.query)
        except RetrievalExecutionError as exc:
            output = RetrievalOutput()
            execution_failure = CaseFailure(exc.category, str(exc))
        except Exception as exc:
            output = RetrievalOutput()
            execution_failure = CaseFailure(
                FailureCategory.UNEXPECTED_ERROR,
                f"{type(exc).__name__}: {exc}",
            )
        finished = self._clock_ns()
        latency_ms = (finished - started) / 1_000_000
        metrics = calculate_metrics(
            case.kind, case.expected, output, recall_ks=self._recall_ks
        )
        failures = () if execution_failure is None else (execution_failure,)
        if execution_failure is None:
            failures = classify_result_failures(case.expected, output)
        return BenchmarkCaseResult(case, latency_ms, output, metrics, failures)


def calculate_metrics(
    kind: RetrievalKind,
    expected: ExpectedResults,
    output: RetrievalOutput,
    *,
    recall_ks: tuple[int, ...] = (1, 5, 10),
) -> CaseMetrics:
    """Calculate exact, deterministic P1 metrics for one normalized result."""

    expected_files = None if expected.files is None else set(expected.files)
    actual_files = set(output.files)
    expected_symbols = (
        None if expected.symbols is None else {_symbol_key(item) for item in expected.symbols}
    )
    ranked_symbols = tuple(_retrieved_symbol_key(item) for item in output.symbols)
    actual_symbols = set(ranked_symbols)
    expected_tests = (
        None if expected.tests is None else {_test_key(item) for item in expected.tests}
    )
    actual_tests = {_retrieved_test_key(item) for item in output.tests}
    expected_relations = (
        None
        if expected.relations is None
        else {_relation_key(item) for item in expected.relations}
    )
    actual_relations = {_retrieved_relation_key(item) for item in output.relations}

    ranked_metric = kind is RetrievalKind.SEARCH_SYMBOL and bool(expected_symbols)
    recall_at_k: tuple[tuple[int, float], ...] = ()
    mrr: float | None = None
    if ranked_metric:
        recall_at_k = tuple(
            (
                k,
                _recall(expected_symbols, set(ranked_symbols[:k])),
            )
            for k in recall_ks
        )
        first_rank = next(
            (
                rank
                for rank, symbol in enumerate(ranked_symbols, start=1)
                if symbol in expected_symbols
            ),
            None,
        )
        mrr = 0.0 if first_rank is None else 1.0 / first_rank

    return CaseMetrics(
        target_file_recall=(
            None if expected_files is None else _recall(expected_files, actual_files)
        ),
        target_symbol_recall=(
            None
            if expected_symbols is None
            else _recall(expected_symbols, actual_symbols)
        ),
        recall_at_k=recall_at_k,
        mrr=mrr,
        direct_relation_correctness=(
            None if expected_relations is None else expected_relations == actual_relations
        ),
        target_test_recall=(
            None if expected_tests is None else _recall(expected_tests, actual_tests)
        ),
    )


def classify_result_failures(
    expected: ExpectedResults, output: RetrievalOutput
) -> tuple[CaseFailure, ...]:
    """Classify annotation mismatches without collapsing them into pass/fail."""

    failures: list[CaseFailure] = []
    if output.is_empty() and any(
        value
        for value in (expected.files, expected.symbols, expected.tests, expected.relations)
        if value is not None
    ):
        failures.append(CaseFailure(FailureCategory.EMPTY_RESULT, "No results returned."))

    if expected.files is not None:
        missing_files = sorted(set(expected.files).difference(output.files))
        if missing_files:
            failures.append(
                CaseFailure(
                    FailureCategory.TARGET_FILE_MISS,
                    f"Missing target files: {', '.join(missing_files)}",
                )
            )
        if not expected.files and output.files:
            failures.append(
                CaseFailure(
                    FailureCategory.UNEXPECTED_FILE,
                    f"Expected no files but returned {len(set(output.files))}.",
                )
            )

    if expected.symbols is not None:
        expected_symbols = {_symbol_key(item) for item in expected.symbols}
        actual_symbols = {_retrieved_symbol_key(item) for item in output.symbols}
        missing_symbols = sorted(expected_symbols.difference(actual_symbols))
        if missing_symbols:
            failures.append(
                CaseFailure(
                    FailureCategory.TARGET_SYMBOL_MISS,
                    "Missing target symbols: "
                    + ", ".join(f"{identity} ({qualified})" for identity, qualified in missing_symbols),
                )
            )
        if _has_symbol_identity_mismatch(expected.symbols, output.symbols):
            failures.append(
                CaseFailure(
                    FailureCategory.SYMBOL_IDENTITY_MISMATCH,
                    "A symbol matched only identity or qualified name, not both.",
                )
            )
        if not expected.symbols and output.symbols:
            failures.append(
                CaseFailure(
                    FailureCategory.UNEXPECTED_SYMBOL,
                    f"Expected no symbols but returned {len(set(actual_symbols))}.",
                )
            )

    if expected.tests is not None:
        missing_tests = sorted(
            {_test_key(item) for item in expected.tests}.difference(
                _retrieved_test_key(item) for item in output.tests
            )
        )
        if missing_tests:
            failures.append(
                CaseFailure(
                    FailureCategory.TARGET_TEST_MISS,
                    "Missing target tests: "
                    + ", ".join(f"{identity} ({name}, {file})" for identity, name, file in missing_tests),
                )
            )
        if not expected.tests and output.tests:
            failures.append(
                CaseFailure(
                    FailureCategory.UNEXPECTED_TEST,
                    f"Expected no tests but returned {len(set(_retrieved_test_key(item) for item in output.tests))}.",
                )
            )

    if expected.relations is not None:
        expected_relations = {_relation_key(item) for item in expected.relations}
        actual_relations = {_retrieved_relation_key(item) for item in output.relations}
        missing_relations = expected_relations.difference(actual_relations)
        unexpected_relations = actual_relations.difference(expected_relations)
        if missing_relations:
            failures.append(
                CaseFailure(
                    FailureCategory.DIRECT_RELATION_MISS,
                    f"Missing {len(missing_relations)} annotated direct relation(s).",
                )
            )
        if unexpected_relations:
            failures.append(
                CaseFailure(
                    FailureCategory.UNEXPECTED_DIRECT_RELATION,
                    f"Returned {len(unexpected_relations)} unannotated direct relation(s).",
                )
            )
    return tuple(failures)


def _summarize(
    results: tuple[BenchmarkCaseResult, ...], recall_ks: tuple[int, ...]
) -> BenchmarkSummary:
    failure_counts = Counter(
        failure.category for result in results for failure in result.failures
    )
    return BenchmarkSummary(
        case_count=len(results),
        passed_count=sum(result.passed for result in results),
        failed_count=sum(not result.passed for result in results),
        mean_latency_ms=sum(result.latency_ms for result in results) / len(results),
        target_file_recall=_mean_metric(results, "target_file_recall"),
        target_symbol_recall=_mean_metric(results, "target_symbol_recall"),
        recall_at_k=tuple(
            (
                k,
                sum(dict(result.metrics.recall_at_k)[k] for result in results if result.metrics.recall_at_k)
                / sum(bool(result.metrics.recall_at_k) for result in results),
            )
            for k in recall_ks
            if any(result.metrics.recall_at_k for result in results)
        ),
        mrr=_mean_metric(results, "mrr"),
        direct_relation_correctness=_mean_metric(
            results, "direct_relation_correctness"
        ),
        target_test_recall=_mean_metric(results, "target_test_recall"),
        failure_counts=tuple(
            (category, failure_counts[category])
            for category in FailureCategory
            if failure_counts[category]
        ),
    )


def _mean_metric(
    results: tuple[BenchmarkCaseResult, ...], attribute: str
) -> float | None:
    values = [
        value
        for result in results
        if (value := getattr(result.metrics, attribute)) is not None
    ]
    return None if not values else sum(values) / len(values)


def _recall(expected: set[object], actual: set[object]) -> float:
    if not expected:
        return 1.0
    return len(expected.intersection(actual)) / len(expected)


def _symbol_key(symbol: QualifiedSymbol) -> tuple[str, str]:
    return symbol.identity, symbol.qualified_name


def _retrieved_symbol_key(symbol: RetrievedSymbol) -> tuple[str, str | None]:
    return symbol.identity, symbol.qualified_name


def _test_key(test: ExpectedTest) -> tuple[str, str, str]:
    return test.identity, test.display_name, test.file


def _retrieved_test_key(test: RetrievedTest) -> tuple[str, str, str]:
    return test.identity, test.display_name, test.file


def _relation_key(
    relation: ExpectedRelation,
) -> tuple[str, str, str, str]:
    return (
        relation.caller.identity,
        relation.caller.qualified_name,
        relation.callee.identity,
        relation.callee.qualified_name,
    )


def _retrieved_relation_key(
    relation: RetrievedRelation,
) -> tuple[str, str | None, str, str | None]:
    return (
        relation.caller.identity,
        relation.caller.qualified_name,
        relation.callee.identity,
        relation.callee.qualified_name,
    )


def _has_symbol_identity_mismatch(
    expected: tuple[QualifiedSymbol, ...], actual: tuple[RetrievedSymbol, ...]
) -> bool:
    expected_by_identity = {item.identity: item.qualified_name for item in expected}
    expected_by_qualified = {item.qualified_name: item.identity for item in expected}
    return any(
        (
            item.identity in expected_by_identity
            and item.qualified_name != expected_by_identity[item.identity]
        )
        or (
            item.qualified_name in expected_by_qualified
            and item.identity != expected_by_qualified[item.qualified_name]
        )
        for item in actual
    )
