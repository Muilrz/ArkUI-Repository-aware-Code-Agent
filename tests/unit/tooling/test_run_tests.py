from __future__ import annotations

import io
import os
import unittest
import warnings
from unittest.mock import patch

from scripts.run_tests import run_suite, select_tests, strict_result_succeeded


def passing_test() -> unittest.TestCase:
    class PassingTest(unittest.TestCase):
        def test_passes(self) -> None:
            self.assertTrue(True)

    return PassingTest("test_passes")


def skipping_test() -> unittest.TestCase:
    class SkippingTest(unittest.TestCase):
        def test_skips(self) -> None:
            self.skipTest("required tool is absent")

    return SkippingTest("test_skips")


def resource_warning_test() -> unittest.TestCase:
    class ResourceWarningTest(unittest.TestCase):
        def test_warns(self) -> None:
            warnings.warn("unclosed test resource", ResourceWarning)

    return ResourceWarningTest("test_warns")


def external_test() -> unittest.TestCase:
    class ExternalTest(unittest.TestCase):
        external_validation_requirements = ("ARKUI_REPO_ROOT",)

        def test_external(self) -> None:
            self.assertTrue(True)

    return ExternalTest("test_external")


class StrictTestRunnerTests(unittest.TestCase):
    def test_passing_nonempty_suite_succeeds(self) -> None:
        result, resource_warnings = run_suite(
            unittest.TestSuite((passing_test(),)),
            stream=io.StringIO(),
        )

        self.assertTrue(
            strict_result_succeeded(
                result,
                unraisable_resource_warnings=resource_warnings,
            )
        )

    def test_skip_is_a_validation_failure(self) -> None:
        result, resource_warnings = run_suite(
            unittest.TestSuite((skipping_test(),)),
            stream=io.StringIO(),
        )

        self.assertFalse(
            strict_result_succeeded(
                result,
                unraisable_resource_warnings=resource_warnings,
            )
        )
        self.assertEqual(len(result.skipped), 1)

    def test_resource_warning_is_a_validation_failure(self) -> None:
        result, resource_warnings = run_suite(
            unittest.TestSuite((resource_warning_test(),)),
            stream=io.StringIO(),
        )

        self.assertFalse(
            strict_result_succeeded(
                result,
                unraisable_resource_warnings=resource_warnings,
            )
        )
        self.assertEqual(len(result.errors), 1)

    def test_optional_external_test_is_not_selected_without_environment(self) -> None:
        passing = passing_test()
        external = external_test()
        suite = unittest.TestSuite((passing, external))
        with patch.dict(os.environ, {}, clear=True):
            selected, omitted = select_tests(suite, os.environ)

        self.assertEqual(
            tuple(test.id() for test in selected),
            (passing.id(),),
        )
        self.assertEqual(
            omitted,
            ((external.id(), ("ARKUI_REPO_ROOT",)),),
        )


if __name__ == "__main__":
    unittest.main()
