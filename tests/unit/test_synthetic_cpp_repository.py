from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from arkui_agent.repository import ARKUI_REPO_ROOT, RepositoryWorkspace
from tests.fixtures import synthetic_cpp_repository


class SyntheticCppRepositoryTests(unittest.TestCase):
    def test_fixture_creates_expected_repository_layout(self) -> None:
        with synthetic_cpp_repository() as repository:
            self.assertTrue(repository.root.is_absolute())
            self.assertEqual(
                repository.relative_files,
                (
                    Path("include/fixture/widget.h"),
                    Path("src/widget.cpp"),
                    Path("tests/widget_test.cpp"),
                ),
            )
            for path in (
                repository.header,
                repository.source,
                repository.test_source,
            ):
                self.assertTrue(path.is_file())
                self.assertTrue(path.is_relative_to(repository.root))

    def test_fixture_contains_minimal_cpp_language_shapes(self) -> None:
        with synthetic_cpp_repository() as repository:
            header = repository.header.read_text(encoding="utf-8")
            source = repository.source.read_text(encoding="utf-8")
            test_source = repository.test_source.read_text(encoding="utf-8")

            self.assertIn("namespace fixture", header)
            self.assertIn("class Widget", header)
            self.assertIn("int value() const;", header)
            self.assertIn("class DerivedWidget : public Widget", header)
            self.assertIn("int Widget::value() const", source)
            self.assertIn("return value() * 2;", source)
            self.assertIn("#define FIXTURE_TEST(name)", test_source)
            self.assertIn("FIXTURE_TEST(derived_widget_doubles_value)", test_source)

    def test_fixture_instances_are_isolated(self) -> None:
        with synthetic_cpp_repository() as first:
            marker = first.root / "only-in-first.txt"
            marker.write_text("isolated", encoding="utf-8")

            with synthetic_cpp_repository() as second:
                self.assertNotEqual(first.root, second.root)
                self.assertFalse((second.root / marker.name).exists())

    def test_fixture_is_removed_after_context_exit(self) -> None:
        with synthetic_cpp_repository() as repository:
            repository_root = repository.root
            self.assertTrue(repository_root.exists())

        self.assertFalse(repository_root.exists())

    def test_fixture_does_not_read_or_modify_configured_target(self) -> None:
        with TemporaryDirectory() as target_directory:
            target_root = Path(target_directory)
            marker = target_root / "target-marker.txt"
            marker.write_text("unchanged", encoding="utf-8")
            entries_before = tuple(target_root.iterdir())

            with patch.dict(
                os.environ, {ARKUI_REPO_ROOT: target_directory}, clear=True
            ):
                with synthetic_cpp_repository() as repository:
                    self.assertNotEqual(repository.root, target_root.resolve())

            self.assertEqual(marker.read_text(encoding="utf-8"), "unchanged")
            self.assertEqual(tuple(target_root.iterdir()), entries_before)

    def test_fixture_can_be_opened_by_repository_workspace(self) -> None:
        with synthetic_cpp_repository() as repository:
            workspace = RepositoryWorkspace(repository.root)

            self.assertEqual(workspace.root, repository.root)
            self.assertEqual(
                workspace.resolve("src/widget.cpp"), repository.source
            )


if __name__ == "__main__":
    unittest.main()

