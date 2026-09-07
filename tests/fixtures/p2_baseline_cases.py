"""Unified P2-I expectations composed from the existing frozen P2 fixtures.

No source expectation is copied from query output here. The suite references
the P1 formal benchmark plus P2-C--P2-H source-reviewed fixtures and keeps the
current capability gaps explicit.
"""

from __future__ import annotations

from pathlib import Path

from arkui_agent.evaluation import (
    P2Annotation,
    P2BaselineSuite,
    P2Capability,
    P2ExpectedCase,
    P2Relation,
    P2TraceStatus,
    RetrievalKind,
    load_benchmark_suite,
)
from tests.fixtures.arkui_role_cases import ROLE_CASES
from tests.fixtures.creation_cases import CASES as CREATION_CASES
from tests.fixtures.layout_cases import REAL_EXPECTED as LAYOUT_EXPECTED
from tests.fixtures.overlay_cases import (
    REAL_CLOSE,
    REAL_GAPS as OVERLAY_GAPS,
    REAL_SHOW,
)
from tests.fixtures.property_cases import (
    NATIVE_GAPS,
    REAL_CASES as PROPERTY_CASES,
    STACK_GAPS,
)


ARKUI_REVISION = "0096f5bd943ed1f7fa56883aed0e2379f13c2885"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
P1_SUITE_PATH = PROJECT_ROOT / "benchmarks" / "p1" / "arkui-button-text-menu.json"


def relation(
    path: str, ordinal: int, relation_type: str, source: str, target: str
) -> P2Relation:
    return P2Relation(path, ordinal, relation_type, source, target)


def build_p2_baseline_suite() -> P2BaselineSuite:
    cases = [
        _symbol_graph_case(),
        _component_graph_case(),
        _test_graph_case(),
        _framework_case(),
        *_creation_cases(),
        *_property_cases(),
        *_layout_cases(),
        *_overlay_cases(),
    ]
    return P2BaselineSuite(
        suite_id="arkui-p2-button-text-menu",
        repository="OpenHarmony/arkui_ace_engine",
        repository_revision=ARKUI_REVISION,
        cases=tuple(cases),
    )


def _symbol_label(identity: str, qualified_name: str) -> str:
    return f"symbol:{identity}|{qualified_name}"


def _symbol_graph_case() -> P2ExpectedCase:
    suite = load_benchmark_suite(P1_SUITE_PATH)
    expected: list[P2Relation] = []
    for case in suite.cases:
        if case.kind in {RetrievalKind.FIND_DECLARATION, RetrievalKind.FIND_DEFINITION}:
            assert case.expected.symbols is not None
            assert case.expected.files is not None
            relation_type = (
                "DECLARE"
                if case.kind is RetrievalKind.FIND_DECLARATION
                else "DEFINE"
            )
            for index, (file, symbol) in enumerate(
                zip(case.expected.files, case.expected.symbols, strict=True)
            ):
                expected.append(
                    relation(
                        case.case_id,
                        index,
                        relation_type,
                        f"file:{file}",
                        _symbol_label(symbol.identity, symbol.qualified_name),
                    )
                )
        if case.kind in {RetrievalKind.FIND_CALLERS, RetrievalKind.FIND_CALLEES}:
            assert case.expected.relations is not None
            for index, item in enumerate(case.expected.relations):
                expected.append(
                    relation(
                        case.case_id,
                        index,
                        "CALL",
                        _symbol_label(item.caller.identity, item.caller.qualified_name),
                        _symbol_label(item.callee.identity, item.callee.qualified_name),
                    )
                )
    return _graph_case(
        "symbol-graph",
        P2Capability.SYMBOL_GRAPH,
        tuple(expected),
        "benchmarks/p1/arkui-button-text-menu.json",
        "P1 revision-bound declaration, definition, and direct-call annotations are projected without changing identity.",
    )


def _test_graph_case() -> P2ExpectedCase:
    suite = load_benchmark_suite(P1_SUITE_PATH)
    expected: list[P2Relation] = []
    for case in suite.cases:
        if case.kind is not RetrievalKind.FIND_TESTS:
            continue
        assert case.expected.tests is not None
        assert hasattr(case.query, "symbol")
        target = case.query.symbol
        for index, test in enumerate(case.expected.tests):
            expected.append(
                relation(
                    case.case_id,
                    index,
                    "TEST",
                    f"test:{test.identity}|{test.display_name}|{test.file}",
                    _symbol_label(target.identity, target.qualified_name),
                )
            )
    return P2ExpectedCase(
        "test-graph",
        P2Capability.TEST_GRAPH,
        None,
        P2TraceStatus.INCOMPLETE,
        (),
        tuple(expected),
        ("missing_test_mapping",),
        annotation=P2Annotation(
            "benchmarks/p1/arkui-button-text-menu.json",
            "The P1 frozen TestCase identities are present, but its real baseline records all three direct symbol mappings as missing.",
        ),
    )


def _component_graph_case() -> P2ExpectedCase:
    expected = tuple(
        relation(
            "role-mapping",
            index,
            "ROLE:" + role,
            "shared" if component is None else "component:" + component,
            "OHOS::Ace::NG::" + name,
        )
        for index, (component, name, role, _) in enumerate(ROLE_CASES)
    )
    return _graph_case(
        "component-graph",
        P2Capability.COMPONENT_GRAPH,
        expected,
        "tests/fixtures/arkui_role_cases.py",
        "Button, Text, Menu, and shared OverlayManager roles were reviewed against authoritative headers.",
    )


def _framework_case() -> P2ExpectedCase:
    values: list[tuple[str, str, str]] = []
    for component in ("Button", "Text", "Menu"):
        prefix = "OHOS::Ace::NG::" + component
        values.extend(
            (
                (
                    prefix + "Pattern::CreateLayoutProperty",
                    prefix + "LayoutProperty",
                    "CREATE",
                ),
                (
                    prefix + "ModelNG::SetFontWeight",
                    prefix + "LayoutProperty",
                    "UPDATE_PROPERTY",
                ),
                (
                    prefix + "LayoutAlgorithm",
                    prefix
                    + "LayoutAlgorithm::"
                    + ("MeasureContent" if component == "Text" else "Measure"),
                    "MEASURE",
                ),
            )
        )
    values.extend(
        (
            (
                "OHOS::Ace::NG::MenuLayoutAlgorithm",
                "OHOS::Ace::NG::MenuLayoutAlgorithm::Layout",
                "LAYOUT",
            ),
            (
                "OHOS::Ace::NG::OverlayManager",
                "OHOS::Ace::NG::OverlayManager::ShowMenu",
                "SHOW",
            ),
            (
                "OHOS::Ace::NG::OverlayManager",
                "OHOS::Ace::NG::OverlayManager::HideMenu",
                "CLOSE",
            ),
        )
    )
    expected = tuple(
        relation("framework", index, kind, source, target)
        for index, (source, target, kind) in enumerate(sorted(values))
    )
    return _graph_case(
        "framework-relations",
        P2Capability.FRAMEWORK_RELATIONS,
        expected,
        "tests/integration/test_framework_relations.py",
        "The P2-D real fixture fixes the exact CREATE/UPDATE_PROPERTY/MEASURE/LAYOUT/SHOW/CLOSE relation set.",
    )


def _creation_cases() -> tuple[P2ExpectedCase, ...]:
    results = []
    for case in CREATION_CASES:
        title = case.component.title()
        path = case.component
        entry = case.entry_namespace + "::" + case.entry_name
        model = f"OHOS::Ace::NG::{title}ModelNG::CreateFrameNode"
        frame = f"OHOS::Ace::NG::FrameNode::{case.frame_method}"
        pattern = f"OHOS::Ace::NG::{case.pattern}"
        present = (
            relation(path, 0, "CALL", entry, model),
            relation(path, 1, "CALL", model, frame),
        )
        pattern_relation = relation(path, 2, "PATTERN_ARGUMENT", frame, pattern)
        complete = case.expected_status == "complete"
        results.append(
            P2ExpectedCase(
                f"creation-{case.component}",
                P2Capability.CREATION_TRACE,
                case.component,
                P2TraceStatus(case.expected_status),
                present + ((pattern_relation,) if complete else ()),
                () if complete else (pattern_relation,),
                case.expected_gaps,
                path_count=1,
                annotation=P2Annotation(
                    "tests/fixtures/creation_cases.py",
                    "Entry, Model, FrameNode, and Pattern source fragments were frozen before trace execution.",
                ),
            )
        )
    return tuple(results)


def _property_cases() -> tuple[P2ExpectedCase, ...]:
    results = []
    for case in PROPERTY_CASES:
        component = case.component.lower()
        model = f"OHOS::Ace::NG::{case.component}ModelNG::SetFontWeight"
        prop = f"OHOS::Ace::NG::{case.component}LayoutProperty"
        entry = f"OHOS::Ace::NG::{case.entry}"
        native_call = relation(component + "-native", 0, "CALL", entry, model)
        binding = relation(
            component + "-stack", 0, "UPDATE_PROPERTY", model, prop
        )
        writer = relation(
            component + "-stack",
            1,
            "PROPERTY_WRITER",
            prop,
            prop + "::<FontWeight state>",
        )
        results.extend(
            (
                P2ExpectedCase(
                    f"property-{component}-native",
                    P2Capability.PROPERTY_UPDATE_TRACE,
                    component,
                    P2TraceStatus.INCOMPLETE,
                    (native_call,),
                    (relation(component + "-native", 1, "UPDATE_PROPERTY", model, prop),),
                    NATIVE_GAPS,
                    annotation=P2Annotation(
                        "tests/fixtures/property_cases.py",
                        "The native overload CALL is real; ACE_UPDATE_NODE_* remains outside the P2-D binding template.",
                    ),
                ),
                P2ExpectedCase(
                    f"property-{component}-stack",
                    P2Capability.PROPERTY_UPDATE_TRACE,
                    component,
                    P2TraceStatus.INCOMPLETE,
                    (binding,),
                    (
                        relation(component + "-stack", 2, "CALL", entry, model),
                        writer,
                    ),
                    STACK_GAPS,
                    annotation=P2Annotation(
                        "tests/fixtures/property_cases.py",
                        "The stack overload has the frozen UPDATE_PROPERTY binding but no entry CALL or explicit-field writer.",
                    ),
                ),
            )
        )
    return tuple(results)


def _layout_cases() -> tuple[P2ExpectedCase, ...]:
    results = []
    for component, (status, stages, gaps) in LAYOUT_EXPECTED.items():
        title = component
        slug = title.lower()
        pattern = f"OHOS::Ace::NG::{title}Pattern"
        factory = pattern + "::CreateLayoutAlgorithm"
        present = [relation(slug, 0, "MEMBER", pattern, factory)]
        missing: list[P2Relation] = []
        if "algorithm" in stages:
            algorithm = f"OHOS::Ace::NG::{title}LayoutAlgorithm"
            measure = algorithm + "::" + ("MeasureContent" if title == "Text" else "Measure")
            prop = f"OHOS::Ace::NG::{title}LayoutProperty"
            present.extend(
                (
                    relation(slug, 1, "CREATE", factory, algorithm),
                    relation(slug, 2, "MEASURE", algorithm, measure),
                    relation(slug, 3, "LAYOUT_PROPERTY", measure, prop),
                )
            )
            missing.append(
                relation(slug, 4, "LAYOUT", algorithm, algorithm + "::Layout")
            )
        else:
            missing.append(
                relation(
                    slug,
                    1,
                    "CREATE",
                    factory,
                    (
                        "OHOS::Ace::NG::TextLayoutAlgorithm"
                        if title == "Text"
                        else "OHOS::Ace::NG::<ambiguous Menu LayoutAlgorithm>"
                    ),
                )
            )
        results.append(
            P2ExpectedCase(
                f"layout-{slug}",
                P2Capability.MEASURE_LAYOUT_TRACE,
                slug,
                P2TraceStatus(status),
                tuple(present),
                tuple(missing),
                gaps,
                annotation=P2Annotation(
                    "tests/fixtures/layout_cases.py",
                    "Factory, operation, candidate, and LayoutProperty source anchors are frozen in REAL_CHECKS/REAL_EXPECTED.",
                ),
            )
        )
    return tuple(results)


def _overlay_cases() -> tuple[P2ExpectedCase, ...]:
    show = _overlay_case(
        "overlay-show-menu",
        P2Capability.OVERLAY_SHOW_TRACE,
        P2TraceStatus.INCOMPLETE,
        (REAL_SHOW,),
        "SHOW",
    )
    close = _overlay_case(
        "overlay-close-menu",
        P2Capability.OVERLAY_CLOSE_TRACE,
        P2TraceStatus.AMBIGUOUS,
        REAL_CLOSE,
        "CLOSE",
    )
    return show, close


def _overlay_case(
    case_id: str,
    capability: P2Capability,
    status: P2TraceStatus,
    paths: tuple[tuple[str, str], ...],
    binding_type: str,
) -> P2ExpectedCase:
    present: list[P2Relation] = []
    missing: list[P2Relation] = []
    for path_index, (entry, operation) in enumerate(paths):
        path = f"{binding_type.lower()}-{path_index}"
        present.extend(
            (
                relation(path, 0, "CALL", entry, operation),
                relation(
                    path,
                    1,
                    binding_type,
                    "OHOS::Ace::NG::OverlayManager",
                    operation,
                ),
                relation(
                    path,
                    2,
                    "MANAGED_NODE_TYPE",
                    operation,
                    "OHOS::Ace::NG::FrameNode",
                ),
            )
        )
        missing.append(
            relation(
                path,
                3,
                "MANAGER_DISPATCH",
                operation,
                "OHOS::Ace::NG::<menu pattern/animation tail>",
            )
        )
    return P2ExpectedCase(
        case_id,
        capability,
        "menu",
        status,
        tuple(present),
        tuple(missing),
        OVERLAY_GAPS,
        ("animation",),
        path_count=len(paths),
        annotation=P2Annotation(
            "tests/fixtures/overlay_cases.py",
            "Show and both Close entries are source-frozen; modifier dispatch is unsupported and animation remains unresolved.",
        ),
    )


def _graph_case(
    case_id: str,
    capability: P2Capability,
    relations: tuple[P2Relation, ...],
    source_fixture: str,
    rationale: str,
) -> P2ExpectedCase:
    return P2ExpectedCase(
        case_id,
        capability,
        None,
        P2TraceStatus.COMPLETE,
        relations,
        annotation=P2Annotation(source_fixture, rationale),
    )
