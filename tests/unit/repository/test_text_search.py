from __future__ import annotations

import subprocess
import unittest
from dataclasses import FrozenInstanceError
from tempfile import TemporaryDirectory
from unittest.mock import patch

from arkui_agent.repository import (
    RepositoryFile,
    RepositoryPathError,
    RepositoryTextSearch,
    RepositoryWorkspace,
    SourceLocation,
    SourceRange,
    TextSearchBackendError,
    TextSearchMode,
    TextSearchQuery,
    TextSearchQueryError,
    TextSearchResult,
    TextSearchToolUnavailableError,
)


class TextSearchContractTests(unittest.TestCase):
    def test_query_defaults_are_explicit_and_immutable(self) -> None:
        query = TextSearchQuery("needle")

        self.assertEqual(query.mode, TextSearchMode.EXACT)
        self.assertTrue(query.case_sensitive)
        self.assertEqual(query.path_scope, ".")
        self.assertEqual(query.file_globs, ())
        self.assertIsNone(query.limit)
        with self.assertRaises(FrozenInstanceError):
            query.text = "changed"  # type: ignore[misc]

    def test_invalid_text_mode_filters_and_limit_are_rejected(self) -> None:
        invalid_queries = (
            {"text": ""},
            {"text": "two\nlines"},
            {"text": "x", "limit": 0},
            {"text": "x", "limit": -1},
        )
        for arguments in invalid_queries:
            with self.subTest(arguments=arguments):
                with self.assertRaises(TextSearchQueryError):
                    TextSearchQuery(**arguments)  # type: ignore[arg-type]

        with self.assertRaises(TypeError):
            TextSearchQuery("x", mode="regex")  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            TextSearchQuery("x", file_globs=["*.cpp"])  # type: ignore[arg-type]

    def test_scope_and_globs_reject_absolute_or_traversing_paths(self) -> None:
        for scope in ("../outside", "src/../outside", "/absolute", "C:/absolute"):
            with self.subTest(scope=scope):
                with self.assertRaises(RepositoryPathError):
                    TextSearchQuery("x", path_scope=scope)
        for pattern in ("../*.cpp", "src/../*.cpp", "/tmp/*.cpp", "C:/*.cpp"):
            with self.subTest(pattern=pattern):
                with self.assertRaises(RepositoryPathError):
                    TextSearchQuery("x", file_globs=(pattern,))

    def test_result_preserves_range_text_and_convenience_coordinates(self) -> None:
        file = RepositoryFile.from_path("src/example.cpp")
        result = TextSearchResult(
            SourceRange(
                SourceLocation(file, 4, 3),
                SourceLocation(file, 4, 9),
            ),
            "needle",
            "  needle();",
        )

        self.assertEqual(result.file, file)
        self.assertEqual((result.line, result.column), (4, 3))
        self.assertEqual(result.to_dict()["matched_text"], "needle")


class TextSearchErrorBoundaryTests(unittest.TestCase):
    def test_unavailable_rg_has_clear_tooling_error(self) -> None:
        with TemporaryDirectory(prefix="text-search-unavailable-") as temporary:
            workspace = RepositoryWorkspace(temporary)
            with patch(
                "arkui_agent.repository._ripgrep_text_search.shutil.which",
                return_value=None,
            ):
                with self.assertRaisesRegex(
                    TextSearchToolUnavailableError, "tool is unavailable"
                ):
                    RepositoryTextSearch(workspace)

    def test_backend_failure_is_not_reported_as_no_match(self) -> None:
        completed = subprocess.CompletedProcess(
            args=("rg",),
            returncode=2,
            stdout=b"",
            stderr=b"regex parse error",
        )
        with TemporaryDirectory(prefix="text-search-failure-") as temporary:
            workspace = RepositoryWorkspace(temporary)
            with (
                patch(
                    "arkui_agent.repository._ripgrep_text_search.shutil.which",
                    return_value="rg",
                ),
                patch(
                    "arkui_agent.repository._ripgrep_text_search.subprocess.run",
                    return_value=completed,
                ),
            ):
                search = RepositoryTextSearch(workspace)
                with self.assertRaisesRegex(TextSearchBackendError, "backend failed"):
                    search.search(TextSearchQuery("(", mode=TextSearchMode.REGEX))

    def test_nonexistent_scope_is_a_query_error(self) -> None:
        with TemporaryDirectory(prefix="text-search-scope-") as temporary:
            workspace = RepositoryWorkspace(temporary)
            with patch(
                "arkui_agent.repository._ripgrep_text_search.shutil.which",
                return_value="rg",
            ):
                search = RepositoryTextSearch(workspace)

            with self.assertRaisesRegex(TextSearchQueryError, "does not exist"):
                search.search(TextSearchQuery("x", path_scope="missing"))


if __name__ == "__main__":
    unittest.main()
