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
    SymbolIndex,
)
from arkui_agent.retrieval import DefinitionDeclarationRetriever
from tests.fixtures.synthetic_cpp_repository import synthetic_cpp_repository


def configured_clangd() -> str:
    configured = os.environ.get("CLANGD_EXECUTABLE", "clangd")
    executable = shutil.which(configured)
    if executable is None:
        raise unittest.SkipTest(
            f"clangd retrieval integration unavailable: {configured!r} not found"
        )
    return executable


class DefinitionDeclarationRetrievalIntegrationTests(unittest.TestCase):
    def test_synthetic_clangd_facts_round_trip_through_index_and_retrieval(
        self,
    ) -> None:
        executable = configured_clangd()
        with (
            synthetic_cpp_repository() as repository,
            TemporaryDirectory(prefix="retrieval-index-") as temporary,
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

            with SymbolIndex(Path(temporary) / "symbols.sqlite3") as index:
                index.rebuild(symbols)
                retriever = DefinitionDeclarationRetriever(index)
                identity = retriever.resolve_unique(
                    retriever.candidates_by_qualified_name(
                        "fixture::Widget::value"
                    )
                )
                declaration = retriever.declaration(identity)
                definition = retriever.definition(identity)

            self.assertIsNotNone(declaration)
            self.assertIsNotNone(definition)
            assert declaration is not None and definition is not None
            self.assertEqual(
                declaration.file.path.as_posix(), "include/fixture/widget.h"
            )
            self.assertEqual(definition.file.path.as_posix(), "src/widget.cpp")


class ArkUIRetrievalSmokeTests(unittest.TestCase):
    def test_button_pattern_definition_and_declaration(self) -> None:
        repository_root = os.environ.get("ARKUI_REPO_ROOT")
        if not repository_root:
            self.skipTest("ARKUI_REPO_ROOT is not configured")
        executable = configured_clangd()
        workspace = RepositoryWorkspace(repository_root)
        header = RepositoryFile.from_path(
            "frameworks/core/components_ng/pattern/button/button_pattern.h"
        )
        source = RepositoryFile.from_path(
            "frameworks/core/components_ng/pattern/button/button_pattern.cpp"
        )
        header_path = workspace.resolve(header.path.as_posix())
        source_path = workspace.resolve(source.path.as_posix())
        if not header_path.is_file() or not source_path.is_file():
            self.fail("Configured ArkUI repository has no ButtonPattern sources")
        original_timestamps = (header_path.stat().st_mtime_ns, source_path.stat().st_mtime_ns)
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
            TemporaryDirectory(prefix="arkui-retrieval-smoke-") as temporary,
        ):
            provider.symbols_in_file(source)
            symbols = provider.symbols_in_file(header)
            with SymbolIndex(Path(temporary) / "symbols.sqlite3") as index:
                index.rebuild(symbols)
                retriever = DefinitionDeclarationRetriever(index)
                identity = retriever.resolve_unique(
                    retriever.candidates_by_qualified_name(
                        "OHOS::Ace::NG::ButtonPattern::GetFocusPattern"
                    )
                )
                declaration = retriever.declaration(identity)
                definition = retriever.definition(identity)

        self.assertIsNotNone(declaration)
        self.assertIsNotNone(definition)
        assert declaration is not None and definition is not None
        self.assertEqual(declaration.file, header)
        self.assertEqual(definition.file, source)
        self.assertEqual(
            (header_path.stat().st_mtime_ns, source_path.stat().st_mtime_ns),
            original_timestamps,
        )


if __name__ == "__main__":
    unittest.main()
