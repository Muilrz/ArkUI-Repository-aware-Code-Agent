"""Real-ArkUI execution adapter for the unified P2-I baseline command."""

from __future__ import annotations

import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Callable

from arkui_agent.evaluation import (
    P2BaselineSuite,
    P2Observation,
    P2Relation,
    P2StageLatency,
    P2TraceStatus,
    load_benchmark_suite,
    load_p1_index_preparation,
    prepare_p1_index,
)
from arkui_agent.graph import NodeIdentity, RelationType, project_index
from arkui_agent.repository import RepositoryFile, RepositoryWorkspace, SymbolIdentity, SymbolIndex
from tests.fixtures.creation_cases import CASES as CREATION_CASES
from tests.fixtures.overlay_cases import REAL_CLOSE, REAL_SHOW
from tests.fixtures.p2_baseline_cases import P1_SUITE_PATH, PROJECT_ROOT
from tests.integration.test_arkui_role_mapping import run_role_cases
from tests.integration.test_creation_trace import run_creation_cases
from tests.integration.test_framework_relations import run_cases as run_framework_cases
from tests.integration.test_layout_trace import run_layout_cases
from tests.integration.test_overlay_trace import run_overlay_case
from tests.integration.test_property_trace import run_property_cases
from tests.integration.test_reference_call_retrieval import configured_clangd


def run_real_p2_baseline(
    workspace: RepositoryWorkspace, suite: P2BaselineSuite
) -> tuple[tuple[P2Observation, ...], tuple[P2StageLatency, ...]]:
    """Run existing P1/P2 real validation paths and normalize their results."""

    test = unittest.TestCase()
    observations: list[P2Observation] = []
    latencies: list[P2StageLatency] = []

    graph_observations, latency = _timed(
        lambda: _run_graph_cases(test, workspace, suite)
    )
    observations.extend(graph_observations)
    latencies.append(P2StageLatency("symbol-and-test-graph", latency))

    role_report, latency = _timed(lambda: run_role_cases(test, workspace))
    observations.append(_role_observation(suite, role_report))
    latencies.append(P2StageLatency("component-graph", latency))

    framework_report, latency = _timed(
        lambda: run_framework_cases(test, workspace, real=True)
    )
    observations.append(_framework_observation(suite, framework_report))
    latencies.append(P2StageLatency("framework-relations", latency))

    creation_report, latency = _timed(
        lambda: run_creation_cases(test, workspace, CREATION_CASES, real=True)
    )
    observations.extend(_creation_observations(suite, creation_report))
    latencies.append(P2StageLatency("creation-traces", latency))

    property_report, latency = _timed(
        lambda: run_property_cases(test, workspace, real=True)
    )
    observations.extend(_property_observations(suite, property_report))
    latencies.append(P2StageLatency("property-update-traces", latency))

    layout_report, latency = _timed(
        lambda: run_layout_cases(test, workspace, real=True)
    )
    observations.extend(_layout_observations(suite, layout_report))
    latencies.append(P2StageLatency("measure-layout-traces", latency))

    overlay_report, latency = _timed(
        lambda: run_overlay_case(test, workspace, real=True)
    )
    observations.extend(_overlay_observations(suite, overlay_report))
    latencies.append(P2StageLatency("overlay-show-close-traces", latency))
    return tuple(observations), tuple(latencies)


def _run_graph_cases(
    test: unittest.TestCase,
    workspace: RepositoryWorkspace,
    suite: P2BaselineSuite,
) -> tuple[P2Observation, P2Observation]:
    p1_suite = load_benchmark_suite(P1_SUITE_PATH)
    preparation = load_p1_index_preparation(
        PROJECT_ROOT / "benchmarks" / "p1" / "arkui-button-text-menu.preparation.json"
    )
    symbol_expected = _expected_case(suite, "symbol-graph")
    test_expected = _expected_case(suite, "test-graph")
    with TemporaryDirectory(prefix="p2-baseline-graph-") as temporary:
        database = Path(temporary) / "p1.sqlite3"
        prepare_p1_index(
            workspace,
            p1_suite,
            preparation,
            database,
            clangd_executable=configured_clangd(),
        )
        with SymbolIndex(database) as index:
            graph = project_index(
                index,
                repository_key="arkui-p2-baseline",
                snapshot_key=suite.repository_revision,
            )
            symbol_relations, symbol_provenance = _observe_graph_relations(
                graph, symbol_expected.present_relations
            )
            test_relations, test_provenance = _observe_graph_relations(
                graph, test_expected.target_relations
            )
            query = graph.query()
            for item in test_expected.target_relations:
                case_identity = _node_identity(item.source)
                case = index.get_test_case(SymbolIdentity(case_identity.key))
                test.assertIsNotNone(case, item.source)
                membership = query.incoming_edges(
                    case_identity, relations=frozenset({RelationType.TEST})
                )
                test.assertTrue(
                    any(
                        edge.identity.source
                        == NodeIdentity.for_symbol(case.fixture_identity)
                        and edge.evidence
                        for edge in membership
                    ),
                    f"missing fixture membership for {item.source}",
                )
                case_node = query.node(case_identity)
                test_provenance = test_provenance and bool(
                    case_node is not None
                    and case_node.anchors
                    and all(edge.evidence for edge in membership)
                )
    return (
        P2Observation(
            "symbol-graph",
            P2TraceStatus.COMPLETE,
            symbol_relations,
            provenance_valid=symbol_provenance,
        ),
        P2Observation(
            "test-graph",
            P2TraceStatus.INCOMPLETE,
            test_relations,
            ("missing_test_mapping",) if not test_relations else (),
            provenance_valid=test_provenance,
        ),
    )


def _observe_graph_relations(
    graph: object, expected: tuple[P2Relation, ...]
) -> tuple[tuple[P2Relation, ...], bool]:
    query = graph.query()
    observed: list[P2Relation] = []
    provenance_valid = True
    for item in expected:
        source = _node_identity(item.source)
        target = _node_identity(item.target)
        relation_type = RelationType(item.relation)
        matches = [
            edge
            for edge in query.outgoing_edges(
                source, relations=frozenset({relation_type})
            )
            if edge.identity.target == target
        ]
        if not matches:
            continue
        observed.append(item)
        edge = matches[0]
        source_node = query.node(source)
        target_node = query.node(target)
        provenance_valid = provenance_valid and bool(
            edge.evidence
            and all(evidence.anchor is not None for evidence in edge.evidence)
            and source_node is not None
            and source_node.anchors
            and target_node is not None
            and target_node.anchors
        )
    return tuple(observed), provenance_valid


def _node_identity(label: str) -> NodeIdentity:
    if label.startswith("file:"):
        return NodeIdentity.for_file(RepositoryFile.from_path(label.removeprefix("file:")))
    if label.startswith("symbol:"):
        identity = label.removeprefix("symbol:").split("|", 1)[0]
        return NodeIdentity.for_symbol(SymbolIdentity(identity))
    if label.startswith("test:"):
        identity = label.removeprefix("test:").split("|", 1)[0]
        return NodeIdentity.for_symbol(SymbolIdentity(identity))
    raise ValueError(f"Unsupported graph endpoint label: {label}")


def _role_observation(
    suite: P2BaselineSuite, report: dict[str, object]
) -> P2Observation:
    expected = _expected_case(suite, "component-graph")
    by_target = {item.target: item for item in expected.present_relations}
    observed = []
    provenance_valid = True
    for check in report["checks"]:
        if "actual_role" not in check:
            continue
        target = "OHOS::Ace::NG::" + check["symbol"]
        item = by_target.get(target)
        if item is not None and item.relation == "ROLE:" + check["actual_role"]:
            observed.append(item)
        provenance_valid = provenance_valid and bool(check.get("identity"))
    return P2Observation(
        expected.case_id,
        P2TraceStatus.COMPLETE,
        tuple(sorted(observed, key=lambda item: item.ordinal)),
        provenance_valid=provenance_valid and bool(report["source_sha256"]),
    )


def _framework_observation(
    suite: P2BaselineSuite, report: dict[str, object]
) -> P2Observation:
    expected = _expected_case(suite, "framework-relations")
    expected_by_key = {
        (item.source, item.target, item.relation): item
        for item in expected.present_relations
    }
    observed = []
    for source, target, relation_type in report["checks"]:
        item = expected_by_key.get((source, target, relation_type))
        observed.append(
            item
            if item is not None
            else P2Relation("framework", len(observed), relation_type, source, target)
        )
    provenance = report["provenance"]
    provenance_valid = len(provenance) == len(observed) and all(
        item["evidence"] for item in provenance
    )
    return P2Observation(
        expected.case_id,
        P2TraceStatus.COMPLETE,
        tuple(sorted(observed)),
        provenance_valid=provenance_valid,
    )


def _creation_observations(
    suite: P2BaselineSuite, report: dict[str, object]
) -> tuple[P2Observation, ...]:
    observations = []
    for check in report["checks"]:
        expected = _expected_case(suite, "creation-" + check["component"])
        actual_nodes = check["actual_nodes"]
        relations: list[P2Relation] = []
        for item in expected.target_relations:
            if item.relation == "CALL" and item.source in actual_nodes and item.target in actual_nodes:
                relations.append(item)
            if (
                item.relation == "PATTERN_ARGUMENT"
                and item.target in actual_nodes
                and check["argument_evidence"]
            ):
                relations.append(item)
        provenance_valid = bool(check["node_evidence"] and check["calls"]) and all(
            node["evidence"] for node in check["node_evidence"]
        ) and all(call["evidence"] for call in check["calls"])
        observations.append(
            P2Observation(
                expected.case_id,
                P2TraceStatus(check["status"]),
                tuple(relations),
                tuple(check["issues"]),
                path_count=1,
                exhaustive=True,
                provenance_valid=provenance_valid,
            )
        )
    return tuple(observations)


def _property_observations(
    suite: P2BaselineSuite, report: dict[str, object]
) -> tuple[P2Observation, ...]:
    observations = []
    for record in report["traces"]:
        case_id = f"property-{record['component']}-{record['mode']}"
        expected = _expected_case(suite, case_id)
        trace = record["trace"]
        path = trace["paths"][0]
        relations = []
        for item in expected.target_relations:
            if item.relation == "CALL" and path["calls"]:
                relations.append(item)
            elif item.relation == "UPDATE_PROPERTY" and path["binding"]:
                relations.append(item)
            elif item.relation == "PROPERTY_WRITER" and any(
                node["stage"] == "writer" for node in path["nodes"]
            ):
                relations.append(item)
        provenance_valid = all(node["evidence"] for node in path["nodes"])
        provenance_valid = provenance_valid and all(
            edge["evidence"] for edge in path["calls"] + path["support"]
        )
        if path["binding"]:
            provenance_valid = provenance_valid and bool(
                path["binding"]["relation"]["evidence"]
            )
        observations.append(
            P2Observation(
                case_id,
                P2TraceStatus(trace["status"]),
                tuple(relations),
                tuple(path["gaps"]),
                path_count=len(trace["paths"]),
                exhaustive=trace["exhaustive"],
                provenance_valid=provenance_valid,
            )
        )
    return tuple(observations)


def _layout_observations(
    suite: P2BaselineSuite, report: dict[str, object]
) -> tuple[P2Observation, ...]:
    observations = []
    for record in report["traces"]:
        case_id = "layout-" + record["component"].lower()
        expected = _expected_case(suite, case_id)
        trace = record["trace"]
        stages = {stage["stage"] for stage in trace["stages"]}
        bindings = {binding["identity"]["relation"] for binding in trace["bindings"]}
        relations = []
        for item in expected.target_relations:
            if item.relation == "MEMBER" and {"pattern", "factory"}.issubset(stages):
                relations.append(item)
            elif item.relation in bindings:
                relations.append(item)
            elif item.relation == "LAYOUT_PROPERTY" and trace["dependencies"]:
                relations.append(item)
        provenance_valid = all(
            candidate["evidence"]
            for stage in trace["stages"]
            for candidate in stage["candidates"]
        ) and all(binding["evidence"] for binding in trace["bindings"])
        observations.append(
            P2Observation(
                case_id,
                P2TraceStatus(trace["status"]),
                tuple(relations),
                tuple(trace["gaps"]),
                path_count=1,
                exhaustive=trace["exhaustive"],
                provenance_valid=provenance_valid,
            )
        )
    return tuple(observations)


def _overlay_observations(
    suite: P2BaselineSuite, report: dict[str, object]
) -> tuple[P2Observation, ...]:
    trace = report["trace"]
    results = []
    for leg_name, case_id, _paths in (
        ("show", "overlay-show-menu", (REAL_SHOW,)),
        ("close", "overlay-close-menu", REAL_CLOSE),
    ):
        expected = _expected_case(suite, case_id)
        leg = trace[leg_name]
        relations = []
        provenance_valid = True
        for index, path in enumerate(leg["paths"]):
            expected_path = f"{leg_name}-{index}"
            path_relations = [
                item for item in expected.target_relations if item.path == expected_path
            ]
            for item in path_relations:
                if item.relation == "CALL" and path["calls"]:
                    relations.append(item)
                elif item.relation in {"SHOW", "CLOSE"} and path["binding"]:
                    relations.append(item)
                elif item.relation == "MANAGED_NODE_TYPE" and any(
                    node["stage"] == "managed_node_type" for node in path["nodes"]
                ):
                    relations.append(item)
                elif item.relation == "MANAGER_DISPATCH" and any(
                    node["stage"] in {"pattern", "animation"} for node in path["nodes"]
                ):
                    relations.append(item)
            provenance_valid = provenance_valid and all(
                node["evidence"] for node in path["nodes"]
            ) and all(edge["evidence"] for edge in path["calls"] + path["support"])
            provenance_valid = provenance_valid and bool(
                path["binding"]["evidence"] and path["source_evidence"]
            )
        gaps = tuple(dict.fromkeys(gap for path in leg["paths"] for gap in path["gaps"]))
        unresolved = (
            ("animation",)
            if any(path["animation"] == "unresolved" for path in leg["paths"])
            else ()
        )
        results.append(
            P2Observation(
                case_id,
                P2TraceStatus(leg["status"]),
                tuple(relations),
                gaps,
                unresolved,
                path_count=len(leg["paths"]),
                exhaustive=leg["exhaustive"],
                provenance_valid=provenance_valid,
            )
        )
    return tuple(results)


def _expected_case(suite: P2BaselineSuite, case_id: str):
    return next(case for case in suite.cases if case.case_id == case_id)


def _timed(function: Callable[[], object]) -> tuple[object, float]:
    started = time.perf_counter_ns()
    value = function()
    finished = time.perf_counter_ns()
    return value, (finished - started) / 1_000_000
