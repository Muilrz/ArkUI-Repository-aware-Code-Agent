from __future__ import annotations

import unittest

from arkui_agent.repository import (
    RepositoryTextSearch,
    RepositoryWorkspace,
    TextSearchBackendError,
    TextSearchMode,
    TextSearchQuery,
)
from tests.fixtures.synthetic_cpp_repository import synthetic_cpp_repository


class RepositoryTextSearchIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository_context = synthetic_cpp_repository()
        self.repository = self.repository_context.__enter__()
        self.addCleanup(self.repository_context.__exit__, None, None, None)
        self.search = RepositoryTextSearch(
            RepositoryWorkspace(self.repository.root)
        )

    def test_exact_search_returns_traceable_match_text_and_range(self) -> None:
        results = self.search.search(
            TextSearchQuery("return 21;", path_scope="src/widget.cpp")
        )

        self.assertEqual(len(results), 1)
        result = results[0]
        self.assertEqual(result.file.path.as_posix(), "src/widget.cpp")
        self.assertEqual(result.matched_text, "return 21;")
        self.assertEqual(result.line_text.strip(), "return 21;")
        source_line = self.repository.source.read_text(encoding="utf-8").splitlines()[
            result.line - 1
        ]
        self.assertEqual(
            source_line[
                result.source_range.start.column - 1 : result.source_range.end.column
                - 1
            ],
            result.matched_text,
        )

    def test_regex_and_case_sensitivity_have_distinct_semantics(self) -> None:
        regex_results = self.search.search(
            TextSearchQuery(
                r"return\s+\d+;",
                mode=TextSearchMode.REGEX,
                path_scope="src",
            )
        )
        sensitive = self.search.search(
            TextSearchQuery("WIDGET", path_scope="include")
        )
        insensitive = self.search.search(
            TextSearchQuery(
                "WIDGET",
                case_sensitive=False,
                path_scope="include",
            )
        )

        self.assertEqual(tuple(item.matched_text for item in regex_results), ("return 21;",))
        self.assertEqual(sensitive, ())
        self.assertGreater(len(insensitive), 0)
        self.assertTrue(all(item.matched_text != "WIDGET" for item in insensitive))

    def test_path_scope_and_repository_relative_file_glob_compose(self) -> None:
        results = self.search.search(
            TextSearchQuery(
                "widget",
                case_sensitive=False,
                path_scope="tests",
                file_globs=("tests/*.cpp",),
            )
        )

        self.assertGreater(len(results), 0)
        self.assertTrue(
            all(item.file.path.as_posix() == "tests/widget_test.cpp" for item in results)
        )

    def test_limit_is_applied_to_global_deterministic_order(self) -> None:
        query = TextSearchQuery("Widget", case_sensitive=False)
        all_results = self.search.search(query)
        limited = self.search.search(
            TextSearchQuery("Widget", case_sensitive=False, limit=3)
        )

        self.assertGreater(len(all_results), 3)
        self.assertEqual(limited, all_results[:3])
        self.assertEqual(self.search.search(query), all_results)
        self.assertEqual(
            tuple(
                (
                    item.file.path.as_posix(),
                    item.line,
                    item.column,
                )
                for item in all_results
            ),
            tuple(
                sorted(
                    (
                        item.file.path.as_posix(),
                        item.line,
                        item.column,
                    )
                    for item in all_results
                )
            ),
        )

    def test_no_match_returns_empty_tuple(self) -> None:
        self.assertEqual(
            self.search.search(TextSearchQuery("definitely_not_in_repository")),
            (),
        )

    def test_utf8_byte_offsets_are_exposed_as_character_columns(self) -> None:
        unicode_source = self.repository.root / "src" / "unicode.cpp"
        line = 'const char* 名称 = "café needle";'
        unicode_source.write_text(line + "\n", encoding="utf-8")

        result = self.search.search(
            TextSearchQuery("needle", path_scope="src/unicode.cpp")
        )[0]

        self.assertEqual(result.column, line.index("needle") + 1)
        self.assertEqual(result.matched_text, "needle")

    def test_real_backend_regex_failure_is_explicit(self) -> None:
        with self.assertRaises(TextSearchBackendError):
            self.search.search(TextSearchQuery("(", mode=TextSearchMode.REGEX))


if __name__ == "__main__":
    unittest.main()
