"""Deterministic contracts and metrics for the P2 real-ArkUI baseline."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from arkui_agent.evaluation.environment import BenchmarkEnvironment, validate_repository_revision


P2_BASELINE_SCHEMA_VERSION = 1


class P2BaselineValidationError(ValueError):
    """Raised when a P2 baseline fixture or observation is malformed."""


class P2Capability(str, Enum):
    SYMBOL_GRAPH = "symbol_graph"
    COMPONENT_GRAPH = "component_graph"
    TEST_GRAPH = "test_graph"
    FRAMEWORK_RELATIONS = "framework_relations"
    CREATION_TRACE = "creation_trace"
    PROPERTY_UPDATE_TRACE = "property_update_trace"
    MEASURE_LAYOUT_TRACE = "measure_layout_trace"
    OVERLAY_SHOW_TRACE = "overlay_show_trace"
    OVERLAY_CLOSE_TRACE = "overlay_close_trace"

    @property
    def is_trace(self) -> bool:
        return self in {
            P2Capability.CREATION_TRACE,
            P2Capability.PROPERTY_UPDATE_TRACE,
            P2Capability.MEASURE_LAYOUT_TRACE,
            P2Capability.OVERLAY_SHOW_TRACE,
            P2Capability.OVERLAY_CLOSE_TRACE,
        }


class P2TraceStatus(str, Enum):
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    AMBIGUOUS = "ambiguous"


class P2FailureCategory(str, Enum):
    MISSING_OBSERVATION = "missing_observation"
    UNEXPECTED_OBSERVATION = "unexpected_observation"
    STATUS_MISMATCH = "status_mismatch"
    MISSING_EXPECTED_RELATION = "missing_expected_relation"
    KNOWN_MISSING_RELATION_OBSERVED = "known_missing_relation_observed"
    INCORRECT_RELATION = "incorrect_relation"
    RELATION_ORDER_MISMATCH = "relation_order_mismatch"
    GAP_MISMATCH = "gap_mismatch"
    UNRESOLVED_MISMATCH = "unresolved_mismatch"
    PATH_COUNT_MISMATCH = "path_count_mismatch"
    EXHAUSTIVE_MISMATCH = "exhaustive_mismatch"
    PROVENANCE_MISSING = "provenance_missing"


@dataclass(frozen=True, slots=True, order=True)
class P2Relation:
    """One expected or observed relation in a named graph/trace path.

    ``path`` and ``ordinal`` make parallel and ambiguous chains explicit. The
    endpoint labels are human-readable qualified/source identities selected by
    the revision-bound fixtures; they are not used to query symbols by name.
    """

    path: str
    ordinal: int
    relation: str
    source: str
    target: str

    def __post_init__(self) -> None:
        for label, value in (
            ("path", self.path),
            ("relation", self.relation),
            ("source", self.source),
            ("target", self.target),
        ):
            _require_nonempty(value, label)
        if isinstance(self.ordinal, bool) or self.ordinal < 0:
            raise P2BaselineValidationError("relation ordinal must be non-negative")

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "ordinal": self.ordinal,
            "relation": self.relation,
            "source": self.source,
            "target": self.target,
        }


@dataclass(frozen=True, slots=True)
class P2Annotation:
    source_fixture: str
    rationale: str

    def __post_init__(self) -> None:
        _require_nonempty(self.source_fixture, "annotation source_fixture")
        _require_nonempty(self.rationale, "annotation rationale")

    def to_dict(self) -> dict[str, str]:
        return {"source_fixture": self.source_fixture, "rationale": self.rationale}


@dataclass(frozen=True, slots=True)
class P2ExpectedCase:
    case_id: str
    capability: P2Capability
    component: str | None
    status: P2TraceStatus
    present_relations: tuple[P2Relation, ...]
    known_missing_relations: tuple[P2Relation, ...] = ()
    gaps: tuple[str, ...] = ()
    unresolved: tuple[str, ...] = ()
    path_count: int = 1
    exhaustive: bool = True
    annotation: P2Annotation | None = None

    def __post_init__(self) -> None:
        _require_nonempty(self.case_id, "case id")
        if not isinstance(self.capability, P2Capability):
            raise P2BaselineValidationError("case capability must be P2Capability")
        if not isinstance(self.status, P2TraceStatus):
            raise P2BaselineValidationError("case status must be P2TraceStatus")
        _validate_relations(self.present_relations, "present_relations")
        _validate_relations(self.known_missing_relations, "known_missing_relations")
        overlap = set(self.present_relations).intersection(self.known_missing_relations)
        if overlap:
            raise P2BaselineValidationError("present and known-missing relations overlap")
        _validate_labels(self.gaps, "gaps")
        _validate_labels(self.unresolved, "unresolved")
        if isinstance(self.path_count, bool) or self.path_count < 0:
            raise P2BaselineValidationError("path_count must be non-negative")
        if not isinstance(self.exhaustive, bool):
            raise P2BaselineValidationError("exhaustive must be boolean")
        if not isinstance(self.annotation, P2Annotation):
            raise P2BaselineValidationError("case annotation is required")

    @property
    def target_relations(self) -> tuple[P2Relation, ...]:
        return self.present_relations + self.known_missing_relations

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.case_id,
            "capability": self.capability.value,
            "component": self.component,
            "status": self.status.value,
            "present_relations": [item.to_dict() for item in self.present_relations],
            "known_missing_relations": [
                item.to_dict() for item in self.known_missing_relations
            ],
            "gaps": list(self.gaps),
            "unresolved": list(self.unresolved),
            "path_count": self.path_count,
            "exhaustive": self.exhaustive,
            "annotation": self.annotation.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class P2BaselineSuite:
    suite_id: str
    repository: str
    repository_revision: str
    cases: tuple[P2ExpectedCase, ...]
    schema_version: int = P2_BASELINE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != P2_BASELINE_SCHEMA_VERSION:
            raise P2BaselineValidationError(
                f"unsupported P2 schema version {self.schema_version}"
            )
        _require_nonempty(self.suite_id, "suite id")
        _require_nonempty(self.repository, "repository")
        _require_nonempty(self.repository_revision, "repository revision")
        if not self.cases:
            raise P2BaselineValidationError("P2 baseline suite must contain cases")
        _require_unique(tuple(case.case_id for case in self.cases), "case ids")


@dataclass(frozen=True, slots=True)
class P2Observation:
    case_id: str
    status: P2TraceStatus
    relations: tuple[P2Relation, ...]
    gaps: tuple[str, ...] = ()
    unresolved: tuple[str, ...] = ()
    path_count: int = 1
    exhaustive: bool = True
    provenance_valid: bool = True

    def __post_init__(self) -> None:
        _require_nonempty(self.case_id, "observation case id")
        if not isinstance(self.status, P2TraceStatus):
            raise P2BaselineValidationError("observation status must be P2TraceStatus")
        _validate_relations(self.relations, "observation relations")
        _validate_labels(self.gaps, "observation gaps")
        _validate_labels(self.unresolved, "observation unresolved")
        if isinstance(self.path_count, bool) or self.path_count < 0:
            raise P2BaselineValidationError("observation path_count must be non-negative")
        if not isinstance(self.exhaustive, bool) or not isinstance(
            self.provenance_valid, bool
        ):
            raise P2BaselineValidationError(
                "observation exhaustive/provenance_valid must be boolean"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.case_id,
            "status": self.status.value,
            "relations": [item.to_dict() for item in self.relations],
            "gaps": list(self.gaps),
            "unresolved": list(self.unresolved),
            "path_count": self.path_count,
            "exhaustive": self.exhaustive,
            "provenance_valid": self.provenance_valid,
        }


@dataclass(frozen=True, slots=True)
class P2StageLatency:
    stage: str
    latency_ms: float

    def __post_init__(self) -> None:
        _require_nonempty(self.stage, "latency stage")
        if self.latency_ms < 0:
            raise P2BaselineValidationError("latency must be non-negative")

    def to_dict(self) -> dict[str, object]:
        return {"stage": self.stage, "latency_ms": self.latency_ms}


@dataclass(frozen=True, slots=True)
class P2CaseFailure:
    category: P2FailureCategory
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {"category": self.category.value, "detail": self.detail}


@dataclass(frozen=True, slots=True)
class P2CaseMetrics:
    target_relation_count: int
    matched_relation_count: int
    missing_relation_count: int
    incorrect_relation_count: int
    relation_coverage: float
    expected_conformance: bool
    call_chain_score: float | None

    def to_dict(self) -> dict[str, object]:
        return {
            "target_relation_count": self.target_relation_count,
            "matched_relation_count": self.matched_relation_count,
            "missing_relation_count": self.missing_relation_count,
            "incorrect_relation_count": self.incorrect_relation_count,
            "relation_coverage": self.relation_coverage,
            "expected_conformance": self.expected_conformance,
            "call_chain_score": self.call_chain_score,
        }


@dataclass(frozen=True, slots=True)
class P2CaseResult:
    expected: P2ExpectedCase
    observation: P2Observation | None
    metrics: P2CaseMetrics
    missing_relations: tuple[P2Relation, ...]
    incorrect_relations: tuple[P2Relation, ...]
    failures: tuple[P2CaseFailure, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "expected": self.expected.to_dict(),
            "observation": None if self.observation is None else self.observation.to_dict(),
            "metrics": self.metrics.to_dict(),
            "missing_relations": [item.to_dict() for item in self.missing_relations],
            "incorrect_relations": [item.to_dict() for item in self.incorrect_relations],
            "failures": [item.to_dict() for item in self.failures],
        }


@dataclass(frozen=True, slots=True)
class P2BaselineSummary:
    case_count: int
    conforming_case_count: int
    regression_failure_count: int
    trace_case_count: int
    call_chain_accuracy: float
    relation_coverage: float
    target_relation_count: int
    matched_relation_count: int
    missing_relation_count: int
    incorrect_relation_count: int
    provenance_valid_count: int
    status_counts: tuple[tuple[P2TraceStatus, int], ...]
    capability_case_counts: tuple[tuple[P2Capability, int], ...]
    gap_counts: tuple[tuple[str, int], ...]
    unresolved_counts: tuple[tuple[str, int], ...]
    failure_counts: tuple[tuple[P2FailureCategory, int], ...]
    total_latency_ms: float

    def to_dict(self) -> dict[str, object]:
        return {
            "case_count": self.case_count,
            "conforming_case_count": self.conforming_case_count,
            "regression_failure_count": self.regression_failure_count,
            "trace_case_count": self.trace_case_count,
            "call_chain_accuracy": self.call_chain_accuracy,
            "relation_coverage": self.relation_coverage,
            "target_relation_count": self.target_relation_count,
            "matched_relation_count": self.matched_relation_count,
            "missing_relation_count": self.missing_relation_count,
            "incorrect_relation_count": self.incorrect_relation_count,
            "provenance_valid_count": self.provenance_valid_count,
            "status_counts": {key.value: value for key, value in self.status_counts},
            "capability_case_counts": {
                key.value: value for key, value in self.capability_case_counts
            },
            "gap_counts": dict(self.gap_counts),
            "unresolved_counts": dict(self.unresolved_counts),
            "failure_counts": {
                key.value: value for key, value in self.failure_counts
            },
            "total_latency_ms": self.total_latency_ms,
        }


@dataclass(frozen=True, slots=True)
class P2BaselineReport:
    suite: P2BaselineSuite
    results: tuple[P2CaseResult, ...]
    summary: P2BaselineSummary
    stage_latencies: tuple[P2StageLatency, ...]
    environment: BenchmarkEnvironment

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": P2_BASELINE_SCHEMA_VERSION,
            "suite": {
                "suite_id": self.suite.suite_id,
                "repository": self.suite.repository,
                "repository_revision": self.suite.repository_revision,
            },
            "environment": self.environment.to_dict(),
            "metric_definitions": {
                "relation_coverage": (
                    "matched desired relations / all desired relations, including "
                    "relations frozen as currently missing"
                ),
                "call_chain_accuracy": (
                    "macro mean over trace cases; score 1 only for one exhaustive "
                    "complete path with exact ordered relations, valid provenance, "
                    "and no missing relation, gap, ambiguity, or unresolved state"
                ),
                "expected_conformance": (
                    "exact agreement with the revision-bound current-capability "
                    "expectation, including expected incomplete/ambiguous states"
                ),
            },
            "summary": self.summary.to_dict(),
            "stage_latencies": [item.to_dict() for item in self.stage_latencies],
            "results": [item.to_dict() for item in self.results],
        }

    def write_json(self, path: str | Path) -> None:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )


def evaluate_p2_baseline(
    suite: P2BaselineSuite,
    observations: tuple[P2Observation, ...],
    *,
    stage_latencies: tuple[P2StageLatency, ...],
    environment: BenchmarkEnvironment,
) -> P2BaselineReport:
    """Compare real observations with frozen expectations and calculate P2 metrics."""

    validate_repository_revision(
        suite.repository_revision, environment.repository_revision
    )
    _require_unique(tuple(item.case_id for item in observations), "observation case ids")
    expected_ids = {case.case_id for case in suite.cases}
    observations_by_id = {item.case_id: item for item in observations}
    unexpected = sorted(set(observations_by_id).difference(expected_ids))
    results = tuple(
        _evaluate_case(case, observations_by_id.get(case.case_id))
        for case in suite.cases
    )
    if unexpected:
        marker = P2CaseFailure(
            P2FailureCategory.UNEXPECTED_OBSERVATION,
            "Unexpected observation ids: " + ", ".join(unexpected),
        )
        first = results[0]
        results = (
            P2CaseResult(
                first.expected,
                first.observation,
                P2CaseMetrics(
                    first.metrics.target_relation_count,
                    first.metrics.matched_relation_count,
                    first.metrics.missing_relation_count,
                    first.metrics.incorrect_relation_count,
                    first.metrics.relation_coverage,
                    False,
                    first.metrics.call_chain_score,
                ),
                first.missing_relations,
                first.incorrect_relations,
                first.failures + (marker,),
            ),
            *results[1:],
        )
    return P2BaselineReport(
        suite,
        results,
        _summarize(results, stage_latencies),
        stage_latencies,
        environment,
    )


def _evaluate_case(
    expected: P2ExpectedCase, observation: P2Observation | None
) -> P2CaseResult:
    if observation is None:
        missing = expected.target_relations
        metrics = P2CaseMetrics(
            len(missing), 0, len(missing), 0, 1.0 if not missing else 0.0, False,
            0.0 if expected.capability.is_trace else None,
        )
        return P2CaseResult(
            expected,
            None,
            metrics,
            missing,
            (),
            (P2CaseFailure(P2FailureCategory.MISSING_OBSERVATION, "No observation returned."),),
        )

    target = set(expected.target_relations)
    actual = set(observation.relations)
    matched = target.intersection(actual)
    missing = tuple(sorted(target.difference(actual)))
    incorrect = tuple(sorted(actual.difference(target)))
    failures: list[P2CaseFailure] = []
    if observation.status is not expected.status:
        failures.append(
            P2CaseFailure(
                P2FailureCategory.STATUS_MISMATCH,
                f"expected {expected.status.value}, observed {observation.status.value}",
            )
        )
    unexpectedly_missing = set(expected.present_relations).difference(actual)
    if unexpectedly_missing:
        failures.append(
            P2CaseFailure(
                P2FailureCategory.MISSING_EXPECTED_RELATION,
                f"{len(unexpectedly_missing)} expected-present relation(s) are missing",
            )
        )
    newly_observed = set(expected.known_missing_relations).intersection(actual)
    if newly_observed:
        failures.append(
            P2CaseFailure(
                P2FailureCategory.KNOWN_MISSING_RELATION_OBSERVED,
                f"{len(newly_observed)} frozen missing relation(s) are now observed; re-review required",
            )
        )
    if incorrect:
        failures.append(
            P2CaseFailure(
                P2FailureCategory.INCORRECT_RELATION,
                f"{len(incorrect)} unannotated relation(s) were observed",
            )
        )
    if set(observation.relations) == set(expected.present_relations) and (
        observation.relations != expected.present_relations
    ):
        failures.append(
            P2CaseFailure(
                P2FailureCategory.RELATION_ORDER_MISMATCH,
                "Observed relation path ordering differs from the frozen order.",
            )
        )
    if observation.gaps != expected.gaps:
        failures.append(
            P2CaseFailure(P2FailureCategory.GAP_MISMATCH, "Observed gaps differ from expected gaps.")
        )
    if observation.unresolved != expected.unresolved:
        failures.append(
            P2CaseFailure(
                P2FailureCategory.UNRESOLVED_MISMATCH,
                "Observed unresolved states differ from expected states.",
            )
        )
    if observation.path_count != expected.path_count:
        failures.append(
            P2CaseFailure(
                P2FailureCategory.PATH_COUNT_MISMATCH,
                f"expected {expected.path_count} path(s), observed {observation.path_count}",
            )
        )
    if observation.exhaustive != expected.exhaustive:
        failures.append(
            P2CaseFailure(
                P2FailureCategory.EXHAUSTIVE_MISMATCH,
                f"expected exhaustive={expected.exhaustive}, observed {observation.exhaustive}",
            )
        )
    if not observation.provenance_valid:
        failures.append(
            P2CaseFailure(
                P2FailureCategory.PROVENANCE_MISSING,
                "One or more observed nodes/relations lack required source evidence.",
            )
        )

    target_count = len(target)
    relation_coverage = 1.0 if not target else len(matched) / target_count
    expected_conformance = not failures
    call_chain_score: float | None = None
    if expected.capability.is_trace:
        call_chain_score = float(
            observation.status is P2TraceStatus.COMPLETE
            and observation.exhaustive
            and observation.path_count == 1
            and not observation.gaps
            and not observation.unresolved
            and not expected.known_missing_relations
            and observation.relations == expected.present_relations
            and observation.provenance_valid
        )
    metrics = P2CaseMetrics(
        target_count,
        len(matched),
        len(missing),
        len(incorrect),
        relation_coverage,
        expected_conformance,
        call_chain_score,
    )
    return P2CaseResult(expected, observation, metrics, missing, incorrect, tuple(failures))


def _summarize(
    results: tuple[P2CaseResult, ...], stage_latencies: tuple[P2StageLatency, ...]
) -> P2BaselineSummary:
    target_count = sum(item.metrics.target_relation_count for item in results)
    matched_count = sum(item.metrics.matched_relation_count for item in results)
    chain_scores = [
        item.metrics.call_chain_score
        for item in results
        if item.metrics.call_chain_score is not None
    ]
    statuses = Counter(
        item.observation.status for item in results if item.observation is not None
    )
    capabilities = Counter(item.expected.capability for item in results)
    gaps = Counter(
        gap
        for item in results
        if item.observation is not None
        for gap in item.observation.gaps
    )
    unresolved = Counter(
        state
        for item in results
        if item.observation is not None
        for state in item.observation.unresolved
    )
    failures = Counter(
        failure.category for item in results for failure in item.failures
    )
    return P2BaselineSummary(
        case_count=len(results),
        conforming_case_count=sum(item.metrics.expected_conformance for item in results),
        regression_failure_count=sum(bool(item.failures) for item in results),
        trace_case_count=len(chain_scores),
        call_chain_accuracy=(0.0 if not chain_scores else sum(chain_scores) / len(chain_scores)),
        relation_coverage=(1.0 if not target_count else matched_count / target_count),
        target_relation_count=target_count,
        matched_relation_count=matched_count,
        missing_relation_count=sum(item.metrics.missing_relation_count for item in results),
        incorrect_relation_count=sum(item.metrics.incorrect_relation_count for item in results),
        provenance_valid_count=sum(
            item.observation is not None and item.observation.provenance_valid
            for item in results
        ),
        status_counts=tuple(
            (status, statuses[status]) for status in P2TraceStatus if statuses[status]
        ),
        capability_case_counts=tuple(
            (capability, capabilities[capability])
            for capability in P2Capability
            if capabilities[capability]
        ),
        gap_counts=tuple(sorted(gaps.items())),
        unresolved_counts=tuple(sorted(unresolved.items())),
        failure_counts=tuple(
            (category, failures[category])
            for category in P2FailureCategory
            if failures[category]
        ),
        total_latency_ms=sum(item.latency_ms for item in stage_latencies),
    )


def _validate_relations(value: tuple[P2Relation, ...], label: str) -> None:
    if not isinstance(value, tuple) or any(not isinstance(item, P2Relation) for item in value):
        raise P2BaselineValidationError(f"{label} must be a tuple of P2Relation")
    _require_unique(value, label)


def _validate_labels(value: tuple[str, ...], label: str) -> None:
    if not isinstance(value, tuple):
        raise P2BaselineValidationError(f"{label} must be a tuple")
    for item in value:
        _require_nonempty(item, label)


def _require_nonempty(value: str, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise P2BaselineValidationError(f"{label} must be a non-empty string")


def _require_unique(value: tuple[object, ...], label: str) -> None:
    if len(set(value)) != len(value):
        raise P2BaselineValidationError(f"{label} must not contain duplicates")
