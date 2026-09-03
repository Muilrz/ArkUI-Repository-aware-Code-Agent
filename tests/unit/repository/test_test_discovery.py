from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from arkui_agent.repository import (
    RepositoryFile,
    RepositoryTestDiscoverer,
    RepositoryWorkspace,
    SourceRange,
    TestDiscoveryError,
    TestMacroRecognizer,
)
from tests.fixtures.synthetic_cpp_repository import synthetic_cpp_repository


def text_at_range(source: str, source_range: SourceRange) -> str:
    start = source_range.start
    end = source_range.end
    if start.line != end.line:
        raise AssertionError("Test helper only supports single-line ranges")
    line = source.splitlines()[start.line - 1]
    return line[start.column - 1 : end.column - 1]


class TestMacroRecognizerTests(unittest.TestCase):
    def test_discovers_multiple_fixtures_and_cases_from_explicit_macros(self) -> None:
        with synthetic_cpp_repository() as repository:
            file = RepositoryFile.from_path("tests/widget_test.cpp")
            source = repository.test_source.read_text(encoding="utf-8")

            discovered = TestMacroRecognizer().recognize(file, source)

        self.assertEqual(
            tuple(fixture.display_name for fixture in discovered.fixtures),
            ("WidgetTest", "AlternateWidgetTest"),
        )
        self.assertEqual(
            tuple(case.display_name for case in discovered.cases),
            (
                "ValueIsTwentyOne",
                "DerivedWidgetDoublesValue",
                "DerivedWidgetDoublesValue",
            ),
        )
        widget = discovered.fixtures[0]
        alternate = discovered.fixtures[1]
        self.assertEqual(
            tuple(
                case.fixture_identity
                for case in discovered.cases
                if case.display_name == "DerivedWidgetDoublesValue"
            ),
            (widget.identity, alternate.identity),
        )

    def test_ranges_point_to_exact_fixture_and_case_tokens(self) -> None:
        source = "HWTEST_F(WidgetTest, ValueIsTwentyOne, TestSize.Level1)\n"
        file = RepositoryFile.from_path("tests/widget_test.cpp")

        discovered = TestMacroRecognizer().recognize(file, source)

        self.assertEqual(
            text_at_range(source, discovered.fixtures[0].source_range),
            "WidgetTest",
        )
        self.assertEqual(
            text_at_range(source, discovered.cases[0].source_range),
            "ValueIsTwentyOne",
        )
        self.assertEqual(discovered.cases[0].source_range.file, file)

    def test_only_configured_fixture_style_macros_are_recognized(self) -> None:
        source = """\
TEST(PlainSuite, PlainCase)
CUSTOM_TEST(WidgetTest, CustomCase)
TEST_P(WidgetTest, ParameterizedCase)
"""
        discovered = TestMacroRecognizer().recognize(
            RepositoryFile.from_path("tests/macros.cpp"), source
        )

        self.assertEqual(
            tuple(case.display_name for case in discovered.cases),
            ("ParameterizedCase",),
        )

    def test_same_name_fixture_declarations_in_one_file_remain_distinct(self) -> None:
        source = """\
namespace first {
class SharedFixture {};
HWTEST_F(SharedFixture, SharedCase, TestSize.Level1)
}
namespace second {
class SharedFixture {};
HWTEST_F(SharedFixture, SharedCase, TestSize.Level1)
}
"""

        discovered = TestMacroRecognizer().recognize(
            RepositoryFile.from_path("tests/shared.cpp"), source
        )

        self.assertEqual(len(discovered.fixtures), 2)
        self.assertEqual(len(discovered.cases), 2)
        self.assertNotEqual(
            discovered.fixtures[0].identity,
            discovered.fixtures[1].identity,
        )
        self.assertEqual(
            tuple(case.fixture_identity for case in discovered.cases),
            tuple(fixture.identity for fixture in discovered.fixtures),
        )

    def test_invalid_macro_configuration_is_rejected(self) -> None:
        for macro_names in ((), ("NOT-A-MACRO",)):
            with self.subTest(macro_names=macro_names):
                with self.assertRaises(ValueError):
                    TestMacroRecognizer(macro_names)


class RepositoryTestDiscovererTests(unittest.TestCase):
    def test_temporary_repository_discovery_is_read_only_and_deterministic(self) -> None:
        with synthetic_cpp_repository() as repository:
            file = RepositoryFile.from_path("tests/widget_test.cpp")
            before = repository.test_source.read_bytes()
            discoverer = RepositoryTestDiscoverer(
                RepositoryWorkspace(repository.root)
            )

            first = discoverer.discover((file, file))
            second = discoverer.discover((file,))

            self.assertEqual(first, second)
            self.assertEqual(repository.test_source.read_bytes(), before)

    def test_same_fixture_name_in_different_files_has_distinct_identity(self) -> None:
        with TemporaryDirectory(prefix="same-test-name-") as temporary:
            root = Path(temporary)
            first_path = root / "tests" / "first.cpp"
            second_path = root / "tests" / "second.cpp"
            first_path.parent.mkdir(parents=True)
            source = "HWTEST_F(SharedFixture, SharedCase, TestSize.Level1)\n"
            first_path.write_text(source, encoding="utf-8")
            second_path.write_text(source, encoding="utf-8")
            files = (
                RepositoryFile.from_path("tests/second.cpp"),
                RepositoryFile.from_path("tests/first.cpp"),
            )

            discovered = RepositoryTestDiscoverer(
                RepositoryWorkspace(root)
            ).discover(files)

        self.assertEqual(len(discovered.fixtures), 2)
        self.assertEqual(len(discovered.cases), 2)
        self.assertNotEqual(
            discovered.fixtures[0].identity,
            discovered.fixtures[1].identity,
        )
        self.assertNotEqual(discovered.cases[0].identity, discovered.cases[1].identity)
        self.assertEqual(
            tuple(item.source_range.file.path.as_posix() for item in discovered.cases),
            ("tests/first.cpp", "tests/second.cpp"),
        )

    def test_missing_explicit_source_fails_clearly(self) -> None:
        with TemporaryDirectory(prefix="missing-test-source-") as temporary:
            discoverer = RepositoryTestDiscoverer(
                RepositoryWorkspace(temporary)
            )

            with self.assertRaisesRegex(TestDiscoveryError, "missing.cpp"):
                discoverer.discover(
                    (RepositoryFile.from_path("tests/missing.cpp"),)
                )


if __name__ == "__main__":
    unittest.main()
