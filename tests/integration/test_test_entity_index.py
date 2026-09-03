from __future__ import annotations

import os
import shutil
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from arkui_agent.repository import (
    ClangdSemanticProvider,
    RepositoryFile,
    RepositoryTestDiscoverer,
    RepositoryWorkspace,
    SourceRange,
    Symbol,
    SymbolIndex,
    SymbolSemanticFacts,
)
from tests.fixtures.synthetic_cpp_repository import synthetic_cpp_repository


def text_at_range(source: str, source_range: SourceRange) -> str:
    if source_range.start.line != source_range.end.line:
        raise AssertionError("Test helper only supports single-line ranges")
    line = source.splitlines()[source_range.start.line - 1]
    return line[source_range.start.column - 1 : source_range.end.column - 1]


def configured_clangd() -> str:
    configured = os.environ.get("CLANGD_EXECUTABLE", "clangd")
    executable = shutil.which(configured)
    if executable is None:
        raise unittest.SkipTest(
            f"clangd test mapping integration unavailable: {configured!r} not found"
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


class TestEntityIndexIntegrationTests(unittest.TestCase):
    def test_synthetic_discovery_round_trips_through_index(self) -> None:
        with (
            synthetic_cpp_repository() as repository,
            TemporaryDirectory(prefix="test-entity-index-") as temporary,
        ):
            file = RepositoryFile.from_path("tests/widget_test.cpp")
            discovered = RepositoryTestDiscoverer(
                RepositoryWorkspace(repository.root)
            ).discover((file,))
            database = Path(temporary) / "test-entities.sqlite3"
            with SymbolIndex(database) as index:
                index.rebuild(
                    (),
                    test_fixtures=discovered.fixtures,
                    test_cases=discovered.cases,
                )

            with SymbolIndex(database) as reopened:
                fixtures = reopened.find_test_fixtures("WidgetTest")
                cases = reopened.test_cases_for_fixture(fixtures[0].identity)

        self.assertEqual(len(fixtures), 1)
        self.assertEqual(
            tuple(case.display_name for case in cases),
            ("ValueIsTwentyOne", "DerivedWidgetDoublesValue"),
        )
        self.assertTrue(all(case.source_range.file == file for case in cases))

    def test_clangd_reference_facts_build_direct_test_symbol_mapping(self) -> None:
        executable = configured_clangd()
        with (
            synthetic_cpp_repository() as repository,
            TemporaryDirectory(prefix="test-symbol-index-") as temporary,
        ):
            workspace = RepositoryWorkspace(repository.root)
            test_file = RepositoryFile.from_path("tests/widget_test.cpp")
            header = RepositoryFile.from_path("include/fixture/widget.h")
            discovered = RepositoryTestDiscoverer(workspace).discover((test_file,))
            with ClangdSemanticProvider(
                workspace,
                executable=executable,
                fallback_flags=(
                    "-std=c++17",
                    f"-I{repository.root / 'include'}",
                ),
            ) as provider:
                provider.symbols_in_file(test_file)
                symbols = provider.symbols_in_file(header)
                value = symbol_by_qualified_name(
                    symbols, "fixture::Widget::value"
                )
                doubled = symbol_by_qualified_name(
                    symbols, "fixture::DerivedWidget::doubled_value"
                )
                facts = (
                    SymbolSemanticFacts(
                        value.identity,
                        references=provider.references(value.identity),
                    ),
                    SymbolSemanticFacts(
                        doubled.identity,
                        references=provider.references(doubled.identity),
                    ),
                )

            database = Path(temporary) / "test-symbols.sqlite3"
            with SymbolIndex(database) as index:
                index.rebuild(
                    (value, doubled),
                    semantic_facts=facts,
                    test_fixtures=discovered.fixtures,
                    test_cases=discovered.cases,
                )
                value_cases = index.test_cases_for_symbol(value.identity)
                doubled_cases = index.test_cases_for_symbol(doubled.identity)

        self.assertEqual(
            tuple(case.display_name for case in value_cases),
            ("ValueIsTwentyOne",),
        )
        self.assertEqual(
            tuple(case.display_name for case in doubled_cases),
            (
                "DerivedWidgetDoublesValue",
                "DerivedWidgetDoublesValue",
            ),
        )
        self.assertTrue(all(case.body_range is not None for case in value_cases))


class ArkUITestEntitySmokeTests(unittest.TestCase):
    external_validation_requirements = ("ARKUI_REPO_ROOT",)

    def test_xcomponent_controller_fixture_and_cases(self) -> None:
        repository_root = os.environ.get("ARKUI_REPO_ROOT")
        if not repository_root:
            self.skipTest("ARKUI_REPO_ROOT is not configured")
        workspace = RepositoryWorkspace(repository_root)
        file = RepositoryFile.from_path(
            "test/unittest/interfaces/xcomponent_controller_test.cpp"
        )
        path = workspace.resolve(file.path.as_posix())
        if not path.is_file():
            self.fail("Configured ArkUI repository has no xcomponent controller test")
        original = path.read_bytes()

        discovered = RepositoryTestDiscoverer(workspace).discover((file,))
        with TemporaryDirectory(prefix="arkui-test-entity-smoke-") as temporary:
            with SymbolIndex(Path(temporary) / "test-entities.sqlite3") as index:
                index.rebuild(
                    (),
                    test_fixtures=discovered.fixtures,
                    test_cases=discovered.cases,
                )
                fixtures = index.find_test_fixtures("XComponentControllerTest")
                self.assertEqual(len(fixtures), 1)
                cases = index.test_cases_for_fixture(fixtures[0].identity)

        by_name = {case.display_name: case for case in cases}
        self.assertIn("XComponentControllerTest001", by_name)
        self.assertIn("XComponentControllerTest002", by_name)
        source = original.decode("utf-8")
        first = by_name["XComponentControllerTest001"]
        self.assertEqual(text_at_range(source, first.source_range), first.display_name)
        self.assertEqual(first.source_range.file, file)
        self.assertEqual(path.read_bytes(), original)

    def test_xcomponent_controller_symbol_maps_to_direct_test_case(self) -> None:
        repository_root = os.environ.get("ARKUI_REPO_ROOT")
        if not repository_root:
            self.skipTest("ARKUI_REPO_ROOT is not configured")
        executable = configured_clangd()
        workspace = RepositoryWorkspace(repository_root)
        test_file = RepositoryFile.from_path(
            "test/unittest/interfaces/xcomponent_controller_test.cpp"
        )
        header = RepositoryFile.from_path(
            "interfaces/inner_api/xcomponent_controller/xcomponent_controller.h"
        )
        test_path = workspace.resolve(test_file.path.as_posix())
        header_path = workspace.resolve(header.path.as_posix())
        if not test_path.is_file() or not header_path.is_file():
            self.fail("Configured ArkUI repository has no XComponentController sources")
        original_timestamps = (
            test_path.stat().st_mtime_ns,
            header_path.stat().st_mtime_ns,
        )
        discovered = RepositoryTestDiscoverer(workspace).discover((test_file,))
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
            TemporaryDirectory(prefix="arkui-test-symbol-smoke-") as temporary,
        ):
            provider.symbols_in_file(test_file)
            target = symbol_by_qualified_name(
                provider.symbols_in_file(header),
                "OHOS::Ace::XComponentController::"
                "GetXComponentControllerFromNapiValue",
            )
            facts = SymbolSemanticFacts(
                target.identity,
                references=provider.references(target.identity),
            )
            with SymbolIndex(Path(temporary) / "test-symbols.sqlite3") as index:
                index.rebuild(
                    (target,),
                    semantic_facts=(facts,),
                    test_fixtures=discovered.fixtures,
                    test_cases=discovered.cases,
                )
                mapped_cases = index.test_cases_for_symbol(target.identity)
                mappings = index.tested_symbol_mappings_for_symbol(
                    target.identity
                )

        self.assertIn(
            "XComponentControllerTest001",
            {case.display_name for case in mapped_cases},
        )
        self.assertTrue(mappings)
        self.assertTrue(
            all(
                reference.file == test_file
                for mapping in mappings
                for reference in mapping.references
            )
        )
        self.assertEqual(
            (test_path.stat().st_mtime_ns, header_path.stat().st_mtime_ns),
            original_timestamps,
        )


if __name__ == "__main__":
    unittest.main()
