from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from arkui_agent.repository import (
    RepositoryFile,
    RepositoryTestDiscoverer,
    RepositoryWorkspace,
    SourceRange,
    SymbolIndex,
)
from tests.fixtures.synthetic_cpp_repository import synthetic_cpp_repository


def text_at_range(source: str, source_range: SourceRange) -> str:
    if source_range.start.line != source_range.end.line:
        raise AssertionError("Test helper only supports single-line ranges")
    line = source.splitlines()[source_range.start.line - 1]
    return line[source_range.start.column - 1 : source_range.end.column - 1]


class TestEntityIndexIntegrationTests(unittest.TestCase):
    def test_synthetic_discovery_round_trips_through_index(self) -> None:
        with (
            synthetic_cpp_repository() as repository,
            TemporaryDirectory(prefix="test-entity-index-") as temporary,
        ):
            file = RepositoryFile.from_path("tests/widget_test.cpp")
            discovered = RepositoryTestDiscoverer(
                RepositoryWorkspace(repository.root)
            ).discover((file,))
            database = Path(temporary) / "test-entities.sqlite3"
            with SymbolIndex(database) as index:
                index.rebuild(
                    (),
                    test_fixtures=discovered.fixtures,
                    test_cases=discovered.cases,
                )

            with SymbolIndex(database) as reopened:
                fixtures = reopened.find_test_fixtures("WidgetTest")
                cases = reopened.test_cases_for_fixture(fixtures[0].identity)

        self.assertEqual(len(fixtures), 1)
        self.assertEqual(
            tuple(case.display_name for case in cases),
            ("ValueIsTwentyOne", "DerivedWidgetDoublesValue"),
        )
        self.assertTrue(all(case.source_range.file == file for case in cases))


class ArkUITestEntitySmokeTests(unittest.TestCase):
    def test_xcomponent_controller_fixture_and_cases(self) -> None:
        repository_root = os.environ.get("ARKUI_REPO_ROOT")
        if not repository_root:
            self.skipTest("ARKUI_REPO_ROOT is not configured")
        workspace = RepositoryWorkspace(repository_root)
        file = RepositoryFile.from_path(
            "test/unittest/interfaces/xcomponent_controller_test.cpp"
        )
        path = workspace.resolve(file.path.as_posix())
        if not path.is_file():
            self.fail("Configured ArkUI repository has no xcomponent controller test")
        original = path.read_bytes()

        discovered = RepositoryTestDiscoverer(workspace).discover((file,))
        with TemporaryDirectory(prefix="arkui-test-entity-smoke-") as temporary:
            with SymbolIndex(Path(temporary) / "test-entities.sqlite3") as index:
                index.rebuild(
                    (),
                    test_fixtures=discovered.fixtures,
                    test_cases=discovered.cases,
                )
                fixtures = index.find_test_fixtures("XComponentControllerTest")
                self.assertEqual(len(fixtures), 1)
                cases = index.test_cases_for_fixture(fixtures[0].identity)

        by_name = {case.display_name: case for case in cases}
        self.assertIn("XComponentControllerTest001", by_name)
        self.assertIn("XComponentControllerTest002", by_name)
        source = original.decode("utf-8")
        first = by_name["XComponentControllerTest001"]
        self.assertEqual(text_at_range(source, first.source_range), first.display_name)
        self.assertEqual(first.source_range.file, file)
        self.assertEqual(path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
