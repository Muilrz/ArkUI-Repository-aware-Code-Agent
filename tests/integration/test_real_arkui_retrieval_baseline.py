from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from arkui_agent.evaluation import (
    BaselineRunner,
    BenchmarkEnvironment,
    FailureCategory,
    P1RetrievalExecutor,
    load_benchmark_suite,
    load_p1_index_preparation,
    prepare_p1_index,
    read_repository_revision,
    read_tool_version,
)
from arkui_agent.repository import RepositoryWorkspace, SymbolIndex


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class RealArkUIRetrievalBaselineTests(unittest.TestCase):
    external_validation_requirements = ("ARKUI_REPO_ROOT",)

    def test_pinned_button_text_menu_suite_runs_through_real_p1_chain(self) -> None:
        workspace = RepositoryWorkspace(os.environ["ARKUI_REPO_ROOT"])
        suite = load_benchmark_suite(
            PROJECT_ROOT / "benchmarks" / "p1" / "arkui-button-text-menu.json"
        )
        preparation = load_p1_index_preparation(
            PROJECT_ROOT
            / "benchmarks"
            / "p1"
            / "arkui-button-text-menu.preparation.json"
        )
        revision = read_repository_revision(workspace)
        environment = BenchmarkEnvironment(
            revision,
            (
                read_tool_version("clangd", os.environ.get("CLANGD_EXECUTABLE", "clangd")),
                read_tool_version("ripgrep", "rg"),
            ),
        )

        with TemporaryDirectory(prefix="real-arkui-p1-baseline-") as temporary:
            index_path = Path(temporary) / "symbol-index.sqlite3"
            prepare_p1_index(
                workspace,
                suite,
                preparation,
                index_path,
                clangd_executable=os.environ.get("CLANGD_EXECUTABLE", "clangd"),
            )
            with SymbolIndex(index_path) as index:
                report = BaselineRunner(P1RetrievalExecutor(workspace, index)).run(
                    suite, environment=environment
                )

        self.assertEqual(report.summary.case_count, 16)
        self.assertEqual(report.environment, environment)
        self.assertGreater(report.summary.passed_count, 0)
        self.assertEqual(
            {result.case.kind for result in report.results},
            {case.kind for case in suite.cases},
        )
        self.assertTrue(
            all(
                failure.category
                not in {
                    FailureCategory.BACKEND_FAILURE,
                    FailureCategory.BACKEND_UNAVAILABLE,
                    FailureCategory.INDEX_FAILURE,
                    FailureCategory.QUERY_REJECTED,
                    FailureCategory.UNEXPECTED_ERROR,
                }
                for result in report.results
                for failure in result.failures
            )
        )


if __name__ == "__main__":
    unittest.main()
