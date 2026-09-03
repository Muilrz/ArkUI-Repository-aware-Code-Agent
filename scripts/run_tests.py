"""Run the project test suite with strict validation semantics."""

from __future__ import annotations

import argparse
import os
import sys
import unittest
import warnings
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import TextIO


EXTERNAL_REQUIREMENTS_ATTRIBUTE = "external_validation_requirements"
ARKUI_REPO_ROOT = "ARKUI_REPO_ROOT"


def iter_tests(suite: unittest.TestSuite) -> Iterable[unittest.TestCase]:
    """Flatten a discovered suite without relying on unittest internals."""

    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from iter_tests(item)
        else:
            yield item


def external_requirements(test: unittest.TestCase) -> tuple[str, ...]:
    """Return explicitly declared environment requirements for a test."""

    requirements = getattr(type(test), EXTERNAL_REQUIREMENTS_ATTRIBUTE, ())
    method_name = getattr(test, "_testMethodName", "")
    method = getattr(test, method_name, None)
    method_requirements = getattr(method, EXTERNAL_REQUIREMENTS_ATTRIBUTE, ())
    return tuple(dict.fromkeys((*requirements, *method_requirements)))


def select_tests(
    suite: unittest.TestSuite,
    environment: Mapping[str, str],
) -> tuple[unittest.TestSuite, tuple[tuple[str, tuple[str, ...]], ...]]:
    """Exclude only tests whose optional external requirements are absent."""

    selected = unittest.TestSuite()
    omitted: list[tuple[str, tuple[str, ...]]] = []
    for test in iter_tests(suite):
        missing = tuple(
            requirement
            for requirement in external_requirements(test)
            if not environment.get(requirement)
        )
        if missing:
            omitted.append((test.id(), missing))
        else:
            selected.addTest(test)
    return selected, tuple(omitted)


def strict_result_succeeded(
    result: unittest.TestResult,
    *,
    unraisable_resource_warnings: Sequence[object] = (),
) -> bool:
    """Reject incomplete or warning-tainted test runs."""

    return bool(
        result.testsRun
        and result.wasSuccessful()
        and not result.skipped
        and not result.expectedFailures
        and not unraisable_resource_warnings
    )


def run_suite(
    suite: unittest.TestSuite,
    *,
    stream: TextIO | None = None,
) -> tuple[unittest.TestResult, tuple[object, ...]]:
    """Run tests while turning ResourceWarning into a real failure."""

    unraisable_resource_warnings: list[object] = []
    previous_unraisable_hook = sys.unraisablehook

    def strict_unraisable_hook(unraisable: object) -> None:
        exception_type = getattr(unraisable, "exc_type", None)
        if exception_type is not None and issubclass(exception_type, ResourceWarning):
            unraisable_resource_warnings.append(unraisable)
            return
        previous_unraisable_hook(unraisable)

    sys.unraisablehook = strict_unraisable_hook
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", ResourceWarning)
            result = unittest.TextTestRunner(
                stream=stream,
                verbosity=2,
            ).run(suite)
    finally:
        sys.unraisablehook = previous_unraisable_hook

    return result, tuple(unraisable_resource_warnings)


def report_strict_failures(
    result: unittest.TestResult,
    unraisable_resource_warnings: Sequence[object],
    *,
    stream: TextIO,
) -> None:
    if result.testsRun == 0:
        print("VALIDATION FAILED: no tests were executed", file=stream)
    if result.skipped:
        print("VALIDATION FAILED: skipped tests are not accepted", file=stream)
        for test, reason in result.skipped:
            print(f"  SKIPPED {test.id()}: {reason}", file=stream)
    if result.expectedFailures:
        print("VALIDATION FAILED: expected failures are not accepted", file=stream)
        for test, _ in result.expectedFailures:
            print(f"  EXPECTED FAILURE {test.id()}", file=stream)
    if unraisable_resource_warnings:
        print("VALIDATION FAILED: unraisable ResourceWarning detected", file=stream)
        for warning in unraisable_resource_warnings:
            message = getattr(warning, "exc_value", warning)
            print(f"  RESOURCE WARNING: {message}", file=stream)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--require-arkui",
        action="store_true",
        help=(
            "require ARKUI_REPO_ROOT and execute real-ArkUI smoke tests; "
            "missing configuration is a validation failure"
        ),
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    project_root = Path(__file__).resolve().parents[1]
    source_root = project_root / "src"
    tests_root = project_root / "tests"

    sys.path.insert(0, str(source_root))
    existing_python_path = os.environ.get("PYTHONPATH")
    os.environ["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(source_root), existing_python_path) if part
    )

    discovered = unittest.defaultTestLoader.discover(
        start_dir=str(tests_root),
        pattern="test_*.py",
        top_level_dir=str(project_root),
    )
    if args.require_arkui and not os.environ.get(ARKUI_REPO_ROOT):
        print(
            "EXTERNAL REQUIREMENT MISSING: ARKUI_REPO_ROOT is required for "
            "real-ArkUI validation",
            file=sys.stderr,
        )
        return 2

    suite, omitted = select_tests(discovered, os.environ)
    if omitted:
        print(
            "Optional external validation not selected because its declared "
            "environment is absent:",
            file=sys.stderr,
        )
        for test_id, requirements in omitted:
            print(
                f"  NOT RUN {test_id}: requires {', '.join(requirements)}",
                file=sys.stderr,
            )
        print(
            "Use --require-arkui when the milestone requires real-ArkUI validation.",
            file=sys.stderr,
        )

    result, resource_warnings = run_suite(suite)
    report_strict_failures(result, resource_warnings, stream=sys.stderr)
    return 0 if strict_result_succeeded(
        result,
        unraisable_resource_warnings=resource_warnings,
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
