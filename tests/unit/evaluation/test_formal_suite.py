from __future__ import annotations

import unittest
from collections import Counter
from pathlib import Path

from arkui_agent.evaluation import (
    RetrievalKind,
    load_benchmark_suite,
    load_p1_index_preparation,
)


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SUITE_PATH = PROJECT_ROOT / "benchmarks" / "p1" / "arkui-button-text-menu.json"
PREPARATION_PATH = (
    PROJECT_ROOT
    / "benchmarks"
    / "p1"
    / "arkui-button-text-menu.preparation.json"
)


class FormalP1SuiteContractTests(unittest.TestCase):
    def test_suite_is_revision_bound_and_covers_three_components_and_all_kinds(self) -> None:
        suite = load_benchmark_suite(SUITE_PATH)

        components = Counter(case.case_id.split("-", 1)[0] for case in suite.cases)
        kinds = Counter(case.kind for case in suite.cases)
        self.assertEqual(set(components), {"button", "text", "menu"})
        self.assertTrue(all(count > 1 for count in components.values()))
        self.assertEqual(set(kinds), set(RetrievalKind))
        self.assertEqual(len(suite.repository_revision), 40)
        self.assertTrue(
            all(case.annotation.rationale for case in suite.cases)
        )

    def test_preparation_manifest_uses_only_repository_relative_files(self) -> None:
        preparation = load_p1_index_preparation(PREPARATION_PATH)

        self.assertEqual(len(preparation.semantic_files), 6)
        self.assertEqual(len(preparation.test_files), 3)
        self.assertTrue(
            all(not file.path.is_absolute() for file in preparation.semantic_files)
        )
        self.assertTrue(
            all(not file.path.is_absolute() for file in preparation.test_files)
        )


if __name__ == "__main__":
    unittest.main()
