"""Run the unified P2 real-ArkUI graph and trace baseline."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src"
DEFAULT_OUTPUT = PROJECT_ROOT / "var" / "evaluation" / "p2-arkui-baseline.json"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repository-root",
        type=Path,
        help="external read-only ArkUI root; defaults to ARKUI_REPO_ROOT",
    )
    parser.add_argument(
        "--clangd",
        default=os.environ.get("CLANGD_EXECUTABLE", "clangd"),
        help="clangd executable used by the real validation adapters",
    )
    parser.add_argument(
        "--output", type=Path, default=DEFAULT_OUTPUT, help="generated JSON report"
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    sys.path.insert(0, str(PROJECT_ROOT))
    sys.path.insert(0, str(SOURCE_ROOT))

    from arkui_agent.evaluation import (
        BenchmarkEnvironment,
        BenchmarkEnvironmentError,
        P2BaselineValidationError,
        evaluate_p2_baseline,
        read_repository_revision,
        read_tool_version,
        validate_repository_revision,
    )
    from arkui_agent.repository import (
        RepositoryWorkspace,
        RepositoryWorkspaceError,
        SemanticProviderError,
        SymbolIndexError,
        TestDiscoveryError,
    )
    from tests.fixtures.p2_baseline_cases import build_p2_baseline_suite
    from tests.integration.p2_baseline_support import run_real_p2_baseline

    repository_root = args.repository_root or os.environ.get("ARKUI_REPO_ROOT")
    if repository_root is None:
        print(
            "P2 BASELINE SETUP FAILED: provide --repository-root or ARKUI_REPO_ROOT",
            file=sys.stderr,
        )
        return 2
    os.environ["CLANGD_EXECUTABLE"] = os.fspath(args.clangd)

    try:
        suite = build_p2_baseline_suite()
        workspace = RepositoryWorkspace(repository_root)
        revision = read_repository_revision(workspace)
        # Revision validation deliberately happens before source checks,
        # provider startup, index construction, or any graph query.
        validate_repository_revision(suite.repository_revision, revision)
        environment = BenchmarkEnvironment(
            revision,
            (
                read_tool_version("clangd", args.clangd),
                read_tool_version("ripgrep", "rg"),
            ),
        )
        observations, stage_latencies = run_real_p2_baseline(workspace, suite)
        report = evaluate_p2_baseline(
            suite,
            observations,
            stage_latencies=stage_latencies,
            environment=environment,
        )
        report.write_json(args.output)
    except (
        AssertionError,
        BenchmarkEnvironmentError,
        OSError,
        P2BaselineValidationError,
        RepositoryWorkspaceError,
        SemanticProviderError,
        SymbolIndexError,
        TestDiscoveryError,
        ValueError,
    ) as exc:
        print(f"P2 BASELINE FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    summary = report.summary
    print(
        "P2 baseline complete: "
        f"{summary.conforming_case_count}/{summary.case_count} cases conform; "
        f"relation coverage={summary.relation_coverage:.4f}; "
        f"Call Chain Accuracy={summary.call_chain_accuracy:.4f}; "
        f"report: {args.output}"
    )
    return 0 if summary.regression_failure_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
