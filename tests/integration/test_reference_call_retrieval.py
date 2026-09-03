from __future__ import annotations

import os
import shutil
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from arkui_agent.repository import (
    ClangdSemanticProvider,
    RepositoryFile,
    RepositoryWorkspace,
    Symbol,
    SymbolIndex,
    SymbolSemanticFacts,
)
from arkui_agent.retrieval import ReferenceCallRetriever
from tests.fixtures.synthetic_cpp_repository import synthetic_cpp_repository


def configured_clangd() -> str:
    configured = os.environ.get("CLANGD_EXECUTABLE", "clangd")
    executable = shutil.which(configured)
    if executable is None:
        raise unittest.SkipTest(
            f"clangd relation retrieval integration unavailable: {configured!r} not found"
        )
    return executable


def symbol_by_qualified_name(
    symbols: tuple[Symbol, ...], qualified_name: str
) -> Symbol:
    matches = [
        symbol for symbol in symbols if symbol.qualified_name == qualified_name
    ]
    if len(matches) != 1:
        raise AssertionError(
            f"Expected one semantic symbol {qualified_name!r}, found {len(matches)}"
        )
    return matches[0]


def indexed_symbols(
    primary: tuple[Symbol, ...], related: tuple[Symbol, ...]
) -> tuple[Symbol, ...]:
    """Keep one model record per proven identity without name reconciliation."""

    by_identity = {symbol.identity: symbol for symbol in primary}
    for symbol in related:
        by_identity.setdefault(symbol.identity, symbol)
    return tuple(by_identity.values())


class ReferenceCallRetrievalIntegrationTests(unittest.TestCase):
    def test_real_clangd_facts_round_trip_through_index(self) -> None:
        executable = configured_clangd()
        with (
            synthetic_cpp_repository() as repository,
            TemporaryDirectory(prefix="relation-retrieval-index-") as temporary,
        ):
            workspace = RepositoryWorkspace(repository.root)
            source = RepositoryFile.from_path("src/widget.cpp")
            header = RepositoryFile.from_path("include/fixture/widget.h")
            with ClangdSemanticProvider(
                workspace,
                executable=executable,
                fallback_flags=(
                    "-std=c++17",
                    f"-I{repository.root / 'include'}",
                ),
            ) as provider:
                provider.symbols_in_file(source)
                symbols = provider.symbols_in_file(header)
                value = symbol_by_qualified_name(
                    symbols, "fixture::Widget::value"
                )
                doubled_value = symbol_by_qualified_name(
                    symbols, "fixture::DerivedWidget::doubled_value"
                )
                references = provider.references(value.identity)
                callers = provider.callers(value.identity)
                callees = provider.callees(doubled_value.identity)

            facts = (
                SymbolSemanticFacts(
                    value.identity,
                    references=references,
                    callers=tuple(symbol.identity for symbol in callers),
                ),
                SymbolSemanticFacts(
                    doubled_value.identity,
                    callees=tuple(symbol.identity for symbol in callees),
                ),
            )
            all_symbols = indexed_symbols(symbols, (*callers, *callees))
            with SymbolIndex(Path(temporary) / "symbols.sqlite3") as index:
                index.rebuild(all_symbols, semantic_facts=facts)
                retriever = ReferenceCallRetriever(index)
                stored_references = retriever.references(value.identity)
                stored_callers = retriever.callers(value.identity)
                stored_callees = retriever.callees(doubled_value.identity)

            self.assertIn(
                "src/widget.cpp",
                {
                    result.source_range.file.path.as_posix()
                    for result in stored_references
                },
            )
            self.assertIn(
                "doubled_value",
                {
                    relation.caller.display_name
                    for relation in stored_callers
                    if relation.caller is not None
                },
            )
            self.assertIn(
                "value",
                {
                    relation.callee.display_name
                    for relation in stored_callees
                    if relation.callee is not None
                },
            )


class ArkUIReferenceCallSmokeTests(unittest.TestCase):
    external_validation_requirements = ("ARKUI_REPO_ROOT",)

    def test_button_pattern_on_modify_done_relations(self) -> None:
        repository_root = os.environ.get("ARKUI_REPO_ROOT")
        if not repository_root:
            self.skipTest("ARKUI_REPO_ROOT is not configured")
        executable = configured_clangd()
        workspace = RepositoryWorkspace(repository_root)
        source = RepositoryFile.from_path(
            "frameworks/core/components_ng/pattern/button/button_pattern.cpp"
        )
        header = RepositoryFile.from_path(
            "frameworks/core/components_ng/pattern/button/button_pattern.h"
        )
        source_path = workspace.resolve(source.path.as_posix())
        header_path = workspace.resolve(header.path.as_posix())
        if not source_path.is_file() or not header_path.is_file():
            self.fail("Configured ArkUI repository has no ButtonPattern sources")
        original_timestamps = (
            source_path.stat().st_mtime_ns,
            header_path.stat().st_mtime_ns,
        )
        fallback_flags = (
            "-std=c++17",
            f"-I{workspace.root}",
            f"-I{workspace.root / 'frameworks'}",
            f"-I{workspace.root / 'interfaces' / 'inner_api' / 'ace'}",
        )

        with (
            ClangdSemanticProvider(
                workspace,
                executable=executable,
                fallback_flags=fallback_flags,
                request_timeout=60,
            ) as provider,
            TemporaryDirectory(prefix="arkui-relation-smoke-") as temporary,
        ):
            source_symbols = provider.symbols_in_file(source)
            provider.symbols_in_file(header)
            target = symbol_by_qualified_name(
                source_symbols,
                "OHOS::Ace::NG::ButtonPattern::OnModifyDone",
            )
            references = provider.references(target.identity)
            callers = provider.callers(target.identity)
            callees = provider.callees(target.identity)
            facts = SymbolSemanticFacts(
                target.identity,
                references=references,
                callers=tuple(symbol.identity for symbol in callers),
                callees=tuple(symbol.identity for symbol in callees),
            )
            symbols = indexed_symbols(source_symbols, (*callers, *callees))
            with SymbolIndex(Path(temporary) / "symbols.sqlite3") as index:
                index.rebuild(symbols, semantic_facts=(facts,))
                retriever = ReferenceCallRetriever(index)
                stored_references = retriever.references(target.identity)
                stored_callers = retriever.callers(target.identity)
                stored_callees = retriever.callees(target.identity)

        self.assertIn(
            1654,
            {result.source_range.start.line for result in stored_references},
        )
        self.assertIn(
            "OHOS::Ace::NG::ButtonPattern::SetBuilderFunc",
            {
                relation.caller.qualified_name
                for relation in stored_callers
                if relation.caller is not None
            },
        )
        self.assertIn(
            "OHOS::Ace::NG::ButtonPattern::InitTouchEvent",
            {
                relation.callee.qualified_name
                for relation in stored_callees
                if relation.callee is not None
            },
        )
        self.assertTrue(
            all(
                relation.source_range is None
                or relation.source_range.file == source
                for relation in (*stored_callers, *stored_callees)
            )
        )
        self.assertEqual(
            (source_path.stat().st_mtime_ns, header_path.stat().st_mtime_ns),
            original_timestamps,
        )


if __name__ == "__main__":
    unittest.main()
