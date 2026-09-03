from __future__ import annotations

import unittest

from arkui_agent.evaluation import (
    BenchmarkValidationError,
    RetrievalKind,
    benchmark_suite_from_dict,
)


def case(case_id: str, query: dict[str, object]) -> dict[str, object]:
    return {
        "id": case_id,
        "query": query,
        "expected": {"files": []},
        "annotation": {
            "annotator": "reviewer",
            "rationale": "Expected result was checked manually.",
        },
    }


class BenchmarkModelTests(unittest.TestCase):
    def test_schema_loads_every_supported_query_kind(self) -> None:
        symbol = {
            "identity": "opaque:widget-value",
            "qualified_name": "fixture::Widget::value",
        }
        payload = {
            "schema_version": 1,
            "suite_id": "controlled",
            "repository": "synthetic-cpp",
            "repository_revision": "fixture-v1",
            "cases": [
                case("text", {"kind": "text_search", "text": "value"}),
                case(
                    "symbol",
                    {
                        "kind": "search_symbol",
                        "name": "fixture::Widget::value",
                        "match": "qualified_name",
                    },
                ),
                *[
                    case(kind, {"kind": kind, "symbol": symbol})
                    for kind in (
                        "find_declaration",
                        "find_definition",
                        "find_references",
                        "find_callers",
                        "find_callees",
                        "find_tests",
                    )
                ],
            ],
        }

        suite = benchmark_suite_from_dict(payload)

        self.assertEqual(
            tuple(item.kind for item in suite.cases), tuple(RetrievalKind)
        )
        serialized = suite.to_dict()
        self.assertEqual(serialized["suite_id"], payload["suite_id"])
        self.assertEqual(len(serialized["cases"]), 8)
        self.assertEqual(
            serialized["cases"][0]["query"]["mode"], "exact"  # type: ignore[index]
        )

    def test_expected_empty_is_distinct_from_unannotated_dimension(self) -> None:
        payload = {
            "schema_version": 1,
            "suite_id": "negative-case",
            "repository": "synthetic-cpp",
            "repository_revision": "fixture-v1",
            "cases": [case("no-callers", {"kind": "text_search", "text": "x"})],
        }

        suite = benchmark_suite_from_dict(payload)

        expected = suite.cases[0].expected
        self.assertEqual(expected.files, ())
        self.assertIsNone(expected.symbols)

    def test_symbols_require_both_identity_and_qualified_name(self) -> None:
        payload = {
            "schema_version": 1,
            "suite_id": "invalid",
            "repository": "synthetic-cpp",
            "repository_revision": "fixture-v1",
            "cases": [
                {
                    **case("bad", {"kind": "text_search", "text": "x"}),
                    "expected": {"symbols": [{"identity": "opaque:value"}]},
                }
            ],
        }

        with self.assertRaisesRegex(BenchmarkValidationError, "qualified_name"):
            benchmark_suite_from_dict(payload)

    def test_unknown_fields_and_duplicate_case_ids_are_rejected(self) -> None:
        base = {
            "schema_version": 1,
            "suite_id": "invalid",
            "repository": "synthetic-cpp",
            "repository_revision": "fixture-v1",
        }
        duplicate = case("same", {"kind": "text_search", "text": "x"})
        with self.assertRaisesRegex(BenchmarkValidationError, "case ids"):
            benchmark_suite_from_dict({**base, "cases": [duplicate, duplicate]})

        invalid_query = case(
            "unknown", {"kind": "text_search", "text": "x", "command": "rg"}
        )
        with self.assertRaisesRegex(BenchmarkValidationError, "command"):
            benchmark_suite_from_dict({**base, "cases": [invalid_query]})


if __name__ == "__main__":
    unittest.main()
