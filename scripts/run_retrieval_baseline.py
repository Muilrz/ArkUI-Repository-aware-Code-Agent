"""Run a static P1 retrieval benchmark against an external repository/index."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src"
DEFAULT_OUTPUT = PROJECT_ROOT / "var" / "evaluation" / "p1-retrieval-baseline.json"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, required=True, help="static benchmark JSON")
    parser.add_argument(
        "--repository-root",
        type=Path,
        help="external read-only repository root; defaults to ARKUI_REPO_ROOT",
    )
    parser.add_argument(
        "--index", type=Path, required=True, help="existing generated P1 symbol index"
    )
    parser.add_argument(
        "--preparation",
        type=Path,
        help="optional real-P1 preparation manifest; rebuilds --index before running",
    )
    parser.add_argument(
        "--clangd",
        default=os.environ.get("CLANGD_EXECUTABLE", "clangd"),
        help="clangd executable used for preparation and version metadata",
    )
    parser.add_argument(
        "--request-timeout",
        type=float,
        default=60.0,
        help="semantic request timeout in seconds (default: 60)",
    )
    parser.add_argument(
        "--output", type=Path, default=DEFAULT_OUTPUT, help="generated JSON report"
    )
    parser.add_argument(
        "--recall-k",
        type=int,
        action="append",
        dest="recall_ks",
        help="rank cutoff; repeat for multiple cutoffs (default: 1, 5, 10)",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    sys.path.insert(0, str(SOURCE_ROOT))

    from arkui_agent.evaluation import (
        BaselineRunner,
        BenchmarkEnvironment,
        BenchmarkEnvironmentError,
        BenchmarkValidationError,
        P1RetrievalExecutor,
        load_benchmark_suite,
        load_p1_index_preparation,
        prepare_p1_index,
        read_repository_revision,
        read_tool_version,
        validate_repository_revision,
    )
    from arkui_agent.repository import (
        RepositoryWorkspace,
        RepositoryWorkspaceError,
        SemanticProviderError,
        SymbolIndex,
        SymbolIndexError,
        TestDiscoveryError,
    )

    repository_root = args.repository_root or os.environ.get("ARKUI_REPO_ROOT")
    if repository_root is None:
        print(
            "BASELINE SETUP FAILED: provide --repository-root or ARKUI_REPO_ROOT",
            file=sys.stderr,
        )
        return 2
    if args.preparation is None and not args.index.is_file():
        print(
            f"BASELINE SETUP FAILED: symbol index does not exist: {args.index}",
            file=sys.stderr,
        )
        return 2

    try:
        suite = load_benchmark_suite(args.cases)
        workspace = RepositoryWorkspace(repository_root)
        environment = None
        if args.preparation is not None:
            revision = read_repository_revision(workspace)
            validate_repository_revision(suite.repository_revision, revision)
            environment = BenchmarkEnvironment(
                revision,
                (
                    read_tool_version("clangd", args.clangd),
                    read_tool_version("ripgrep", "rg"),
                ),
            )
            preparation = load_p1_index_preparation(args.preparation)
            prepared = prepare_p1_index(
                workspace,
                suite,
                preparation,
                args.index,
                clangd_executable=args.clangd,
                request_timeout=args.request_timeout,
            )
            print(
                "P1 index prepared: "
                f"{prepared.scanned_file_count} files, "
                f"{prepared.indexed_symbol_count} symbols, "
                f"{prepared.test_case_count} test cases"
            )
        with SymbolIndex(args.index) as index:
            report = BaselineRunner(
                P1RetrievalExecutor(workspace, index),
                recall_ks=tuple(args.recall_ks or (1, 5, 10)),
            ).run(suite, environment=environment)
        report.write_json(args.output)
    except (
        BenchmarkEnvironmentError,
        BenchmarkValidationError,
        OSError,
        RepositoryWorkspaceError,
        SemanticProviderError,
        SymbolIndexError,
        TestDiscoveryError,
        ValueError,
    ) as exc:
        print(f"BASELINE SETUP FAILED: {exc}", file=sys.stderr)
        return 2

    print(
        f"Baseline complete: {report.summary.passed_count}/"
        f"{report.summary.case_count} cases passed; report: {args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
