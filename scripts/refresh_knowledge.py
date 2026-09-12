"""Thin manual/smoke CLI for the shared P3-F one-shot refresh service."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))

from arkui_agent.knowledge import (  # noqa: E402
    BuildScope, KnowledgeRefreshService, P1P2RefreshBuilder,
    ProductionBuildInputs, RefreshRequest, RefreshStatus, ScopeKind,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--knowledge-root", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--scope", choices=("selected", "full"), required=True)
    parser.add_argument("--semantic-file", action="append", default=[])
    parser.add_argument("--test-file", action="append", default=[])
    parser.add_argument("--text-file", action="append", default=[])
    parser.add_argument("--clangd", default="clangd")
    parser.add_argument("--compiler", help="Optional compiler provenance hint; never executed or required locally")
    parser.add_argument("--compile-database")
    parser.add_argument("--configuration-file", action="append", default=[])
    parser.add_argument("--compiler-flag", action="append", default=[])
    parser.add_argument("--include-directory", action="append", default=[])
    parser.add_argument("--request-timeout", type=float, default=60.0)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    if args.scope == "full" and any((args.semantic_file, args.test_file, args.text_file)):
        parser.error("Full scope is derived from Git tracked inventory; do not pass selected file lists.")
    kind = ScopeKind.FULL_REPOSITORY if args.scope == "full" else ScopeKind.SELECTED_FILES
    scope = BuildScope(kind, tuple(sorted(set(args.semantic_file))),
                       tuple(sorted(set(args.test_file))), tuple(sorted(set(args.text_file))))
    inputs = ProductionBuildInputs(
        clangd_executable=args.clangd, compiler_executable=args.compiler,
        compile_database=args.compile_database,
        configuration_files=tuple(args.configuration_file),
        compiler_flags=tuple(args.compiler_flag),
        include_directories=tuple(args.include_directory),
        request_timeout=args.request_timeout,
    )
    service = KnowledgeRefreshService(
        args.repository_root, args.knowledge_root, repository=args.repository,
        builder=P1P2RefreshBuilder(inputs),
    )
    result = service.refresh(RefreshRequest(scope, args.reason, args.force))
    payload = result_payload(result, service.manifest_path)
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if result.status in (RefreshStatus.PUBLISHED, RefreshStatus.NO_OP) else (
        130 if result.status is RefreshStatus.CANCELLED else 2 if result.status is RefreshStatus.CONFLICT else 1
    )


def result_payload(result, manifest_path: Path) -> dict[str, object]:
    """Bounded command output; full per-file reports stay in the generation."""
    return {
        "status": result.status.value,
        "snapshot": None if result.snapshot is None else {
            "snapshot_id": result.snapshot.identity.snapshot_id,
            "generation": result.snapshot.identity.generation,
            "repository": result.snapshot.identity.repository,
            "revision": result.snapshot.identity.revision,
            "scope": result.snapshot.scope.kind.value,
        },
        "attempt": None if result.attempt is None else {
            "attempt_id": result.attempt.attempt_id,
            "generation": result.attempt.target.generation,
            "status": result.attempt.status.value,
            "failure": result.attempt.failure,
        },
        "coverage": result.coverage.summary(),
        "coverage_report": None if result.attempt is None else str(
            manifest_path.parent / "generations" / result.attempt.target.generation / "coverage.json"),
        "diagnostics": [d[:4096] for d in result.diagnostics[:3]],
        "manifest": str(manifest_path),
    }


if __name__ == "__main__":
    raise SystemExit(main())
