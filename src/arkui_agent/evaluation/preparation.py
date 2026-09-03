"""Thin real-P1 index preparation used by reproducible evaluation runs."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from arkui_agent.evaluation.model import (
    BenchmarkSuite,
    BenchmarkValidationError,
    IdentityQueryInput,
    RetrievalKind,
)
from arkui_agent.repository import (
    ClangdSemanticProvider,
    RepositoryFile,
    RepositoryScanner,
    RepositoryTestDiscoverer,
    RepositoryWorkspace,
    Symbol,
    SymbolIndex,
    SymbolSemanticFacts,
)


@dataclass(frozen=True, slots=True)
class P1IndexPreparation:
    semantic_files: tuple[RepositoryFile, ...]
    test_files: tuple[RepositoryFile, ...]
    fallback_include_directories: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class P1PreparationResult:
    scanned_file_count: int
    indexed_symbol_count: int
    semantic_fact_count: int
    test_fixture_count: int
    test_case_count: int


def load_p1_index_preparation(path: str | Path) -> P1IndexPreparation:
    source = Path(path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BenchmarkValidationError(
            f"Cannot load P1 preparation manifest {source}: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise BenchmarkValidationError("P1 preparation manifest must be an object.")
    allowed = {
        "semantic_files",
        "test_files",
        "fallback_include_directories",
    }
    unknown = sorted(set(payload).difference(allowed))
    if unknown:
        raise BenchmarkValidationError(
            f"Unknown P1 preparation fields: {', '.join(unknown)}."
        )
    return P1IndexPreparation(
        semantic_files=_repository_files(payload.get("semantic_files"), "semantic_files"),
        test_files=_repository_files(payload.get("test_files"), "test_files"),
        fallback_include_directories=_relative_directories(
            payload.get("fallback_include_directories")
        ),
    )


def prepare_p1_index(
    workspace: RepositoryWorkspace,
    suite: BenchmarkSuite,
    preparation: P1IndexPreparation,
    index_path: str | os.PathLike[str],
    *,
    clangd_executable: str | os.PathLike[str] = "clangd",
    request_timeout: float = 60.0,
) -> P1PreparationResult:
    """Build evaluation data through scanner/provider/index/test-discovery APIs.

    Query targets come only from the case query contract. Expected annotations
    are never read or inserted into the index.
    """

    requested_files = (*preparation.semantic_files, *preparation.test_files)
    scanned_files = RepositoryScanner(workspace).scan(
        include_patterns=tuple(file.path.as_posix() for file in requested_files)
    )
    expected_paths = {file.path.as_posix() for file in requested_files}
    scanned_paths = {file.path.as_posix() for file in scanned_files}
    if scanned_paths != expected_paths:
        missing = sorted(expected_paths.difference(scanned_paths))
        unexpected = sorted(scanned_paths.difference(expected_paths))
        detail = []
        if missing:
            detail.append(f"missing: {', '.join(missing)}")
        if unexpected:
            detail.append(f"unexpected: {', '.join(unexpected)}")
        raise BenchmarkValidationError(
            "Preparation scan did not resolve the exact manifest file set ("
            + "; ".join(detail)
            + ")."
        )

    discovered_tests = RepositoryTestDiscoverer(workspace).discover(
        preparation.test_files
    )
    fallback_flags = (
        "-std=c++17",
        *(
            f"-I{workspace.resolve(directory)}"
            for directory in preparation.fallback_include_directories
        ),
    )
    required_queries = tuple(
        case.query
        for case in suite.cases
        if isinstance(case.query, IdentityQueryInput)
    )
    symbols: dict[object, Symbol] = {}
    facts: list[SymbolSemanticFacts] = []

    with ClangdSemanticProvider(
        workspace,
        executable=clangd_executable,
        fallback_flags=fallback_flags,
        request_timeout=request_timeout,
    ) as provider:
        # Opening selected tests before reference queries lets the real semantic
        # backend observe them; their symbols are not injected as expectations.
        for file in preparation.test_files:
            provider.symbols_in_file(file)
        for file in preparation.semantic_files:
            for symbol in provider.symbols_in_file(file):
                symbols.setdefault(symbol.identity, symbol)

        query_by_identity = {query.symbol.identity: query for query in required_queries}
        for identity_value, query in query_by_identity.items():
            target = next(
                (
                    symbol
                    for symbol in symbols.values()
                    if symbol.identity.value == identity_value
                    and symbol.qualified_name == query.symbol.qualified_name
                ),
                None,
            )
            if target is None:
                raise BenchmarkValidationError(
                    "Preparation could not resolve identity query target "
                    f"{identity_value!r} ({query.symbol.qualified_name})."
                )
            kinds = {
                candidate.kind
                for candidate in required_queries
                if candidate.symbol.identity == identity_value
            }
            references = (
                provider.references(target.identity)
                if kinds & {RetrievalKind.FIND_REFERENCES, RetrievalKind.FIND_TESTS}
                else ()
            )
            callers = (
                provider.callers(target.identity)
                if RetrievalKind.FIND_CALLERS in kinds
                else ()
            )
            callees = (
                provider.callees(target.identity)
                if RetrievalKind.FIND_CALLEES in kinds
                else ()
            )
            for related in (*callers, *callees):
                symbols.setdefault(related.identity, related)
            facts.append(
                SymbolSemanticFacts(
                    target.identity,
                    references=references,
                    callers=tuple(symbol.identity for symbol in callers),
                    callees=tuple(symbol.identity for symbol in callees),
                )
            )

    destination = Path(index_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with SymbolIndex(destination) as index:
        index.rebuild(
            symbols.values(),
            files=scanned_files,
            semantic_facts=facts,
            test_fixtures=discovered_tests.fixtures,
            test_cases=discovered_tests.cases,
        )
    return P1PreparationResult(
        scanned_file_count=len(scanned_files),
        indexed_symbol_count=len(symbols),
        semantic_fact_count=len(facts),
        test_fixture_count=len(discovered_tests.fixtures),
        test_case_count=len(discovered_tests.cases),
    )


def _repository_files(value: object, label: str) -> tuple[RepositoryFile, ...]:
    if not isinstance(value, list) or not value:
        raise BenchmarkValidationError(f"{label} must be a non-empty array.")
    try:
        files = tuple(RepositoryFile.from_path(item) for item in value)
    except (TypeError, ValueError) as exc:
        raise BenchmarkValidationError(f"Invalid {label}: {exc}") from exc
    if len(set(files)) != len(files):
        raise BenchmarkValidationError(f"{label} must not contain duplicates.")
    return files


def _relative_directories(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise BenchmarkValidationError(
            "fallback_include_directories must be a non-empty array."
        )
    directories: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item:
            raise BenchmarkValidationError(
                "fallback include directories must be non-empty strings."
            )
        # RepositoryFile supplies the same canonical/root-bound validation;
        # dot is the only directory form it intentionally rejects.
        if item != ".":
            try:
                RepositoryFile.from_path(item)
            except (TypeError, ValueError) as exc:
                raise BenchmarkValidationError(
                    f"Invalid fallback include directory {item!r}: {exc}"
                ) from exc
        directories.append(item)
    if len(set(directories)) != len(directories):
        raise BenchmarkValidationError(
            "fallback_include_directories must not contain duplicates."
        )
    return tuple(directories)
