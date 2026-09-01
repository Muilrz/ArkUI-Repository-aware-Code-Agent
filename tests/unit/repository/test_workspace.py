from __future__ import annotations

import os
import subprocess
import sys
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from arkui_agent.repository import (
    ARKUI_REPO_ROOT,
    RepositoryConfigurationError,
    RepositoryPathError,
    RepositoryRootError,
    RepositoryWorkspace,
)


class RepositoryWorkspaceTests(unittest.TestCase):
    def test_valid_directory_can_be_repository_root(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            workspace = RepositoryWorkspace(temporary_directory)

            self.assertEqual(workspace.root, Path(temporary_directory).resolve())

    def test_root_is_normalized_to_absolute_path(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            repository_root = Path(temporary_directory) / "repository"
            nested_directory = repository_root / "nested"
            nested_directory.mkdir(parents=True)

            workspace = RepositoryWorkspace(nested_directory / "..")

            self.assertTrue(workspace.root.is_absolute())
            self.assertEqual(workspace.root, repository_root.resolve())

    def test_nonexistent_root_is_rejected(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            missing_root = Path(temporary_directory) / "missing"

            with self.assertRaisesRegex(RepositoryRootError, "does not exist"):
                RepositoryWorkspace(missing_root)

    def test_file_cannot_be_repository_root(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            file_path = Path(temporary_directory) / "not-a-directory"
            file_path.write_text("content", encoding="utf-8")

            with self.assertRaisesRegex(RepositoryRootError, "not a directory"):
                RepositoryWorkspace(file_path)

    def test_workspace_can_be_created_from_environment(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            with patch.dict(
                os.environ, {ARKUI_REPO_ROOT: temporary_directory}, clear=True
            ):
                workspace = RepositoryWorkspace.from_environment()

            self.assertEqual(workspace.root, Path(temporary_directory).resolve())

    def test_missing_environment_variable_is_rejected(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(
                RepositoryConfigurationError, "is not set"
            ):
                RepositoryWorkspace.from_environment()

    def test_empty_environment_variable_is_rejected(self) -> None:
        for value in ("", "   "):
            with self.subTest(value=value):
                with patch.dict(os.environ, {ARKUI_REPO_ROOT: value}, clear=True):
                    with self.assertRaisesRegex(
                        RepositoryConfigurationError, "is empty"
                    ):
                        RepositoryWorkspace.from_environment()

    def test_normal_repository_relative_path_is_resolved(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            repository_root = Path(temporary_directory)
            source_file = repository_root / "src" / "example.cc"
            source_file.parent.mkdir()
            source_file.write_text("// fixture", encoding="utf-8")
            workspace = RepositoryWorkspace(repository_root)

            resolved = workspace.resolve(Path("src") / "example.cc")

            self.assertEqual(resolved, source_file.resolve())
            self.assertTrue(resolved.is_absolute())

    def test_parent_path_traversal_is_rejected(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            workspace = RepositoryWorkspace(temporary_directory)

            with self.assertRaisesRegex(RepositoryPathError, "escapes root"):
                workspace.resolve(Path("..") / "outside.cc")

    def test_absolute_path_is_rejected(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            workspace = RepositoryWorkspace(temporary_directory)

            with self.assertRaisesRegex(RepositoryPathError, "must be relative"):
                workspace.resolve(Path(temporary_directory) / "source.cc")

    def test_workspace_is_read_only_and_does_not_modify_repository(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            repository_root = Path(temporary_directory)
            source_file = repository_root / "source.cc"
            source_file.write_text("original", encoding="utf-8")
            entries_before = tuple(repository_root.iterdir())

            workspace = RepositoryWorkspace(repository_root)
            workspace.resolve("source.cc")

            self.assertTrue(workspace.read_only)
            with self.assertRaises(FrozenInstanceError):
                workspace.read_only = False  # type: ignore[misc]
            self.assertEqual(source_file.read_text(encoding="utf-8"), "original")
            self.assertEqual(tuple(repository_root.iterdir()), entries_before)

    def test_module_import_does_not_read_environment_configuration(self) -> None:
        environment = os.environ.copy()
        environment[ARKUI_REPO_ROOT] = ""

        completed = subprocess.run(
            [sys.executable, "-c", "import arkui_agent.repository.workspace"],
            check=False,
            capture_output=True,
            env=environment,
            text=True,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == "__main__":
    unittest.main()

