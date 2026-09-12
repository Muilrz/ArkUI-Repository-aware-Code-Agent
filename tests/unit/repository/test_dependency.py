from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from arkui_agent.repository import (
    CompilationDatabaseProvider,
    CompileContext,
    CompileContextInventory,
    ConfigurationInput,
    DependencyCoverageStatus,
    DependencyDiagnosticCode,
    DependencyImpactAnalyzer,
    DependencyMetadataSnapshot,
    DependencyRecord,
    ImpactStatus,
    MakeDepfileDependencyProvider,
    RepositoryChange,
    RepositoryChangeKind,
    RepositoryFile,
    RepositoryWorkspace,
    ReverseDependencyIndex,
    SemanticFileState,
    SemanticFingerprintInput,
    TranslationUnitIdentity,
    normalize_repository_changes,
)


def sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def context(source: str, *, flag: str = "-DONE", config_hash: str | None = None) -> CompileContext:
    configuration = () if config_hash is None else (
        ConfigurationInput(RepositoryFile.from_path(".clangd"), config_hash),
    )
    return CompileContext(RepositoryFile.from_path(source), "/repo",
                          ("clang++", flag, "-c", source), configuration)


def inventory(*contexts: CompileContext,
              coverage: DependencyCoverageStatus = DependencyCoverageStatus.COMPLETE) -> CompileContextInventory:
    return CompileContextInventory(tuple(sorted(contexts, key=lambda item: (
        item.source.path.as_posix(), item.identity.value,
    ))), coverage, (), "fixture-compile-v1")


def dependencies(*items: tuple[CompileContext, tuple[str, ...]],
                 coverage: DependencyCoverageStatus = DependencyCoverageStatus.COMPLETE) -> DependencyMetadataSnapshot:
    records = []
    for compile_context, paths in items:
        files = {compile_context.source, *(RepositoryFile.from_path(path) for path in paths)}
        records.append(DependencyRecord(
            TranslationUnitIdentity.from_context(compile_context),
            tuple(sorted(files, key=lambda item: item.path.as_posix())),
            "fixture-dependencies-v1",
        ))
    return DependencyMetadataSnapshot(tuple(sorted(records, key=lambda item: item.translation_unit.value)),
                                      coverage, (), "fixture-dependency-v1")


class ChangeAndIdentityTests(unittest.TestCase):
    def test_change_normalization_deduplicates_and_orders_without_losing_rename_sides(self) -> None:
        modify = RepositoryChange.from_paths("src/z.cpp", "src/z.cpp", RepositoryChangeKind.MODIFY)
        rename = RepositoryChange.from_paths("include/old.h", "include/new.h", RepositoryChangeKind.RENAME)

        self.assertEqual(normalize_repository_changes((modify, rename, modify)), (rename, modify))
        with self.assertRaisesRegex(ValueError, "conflicting paths"):
            normalize_repository_changes((
                modify,
                RepositoryChange.from_paths("src/z.cpp", None, RepositoryChangeKind.DELETE),
            ))

    def test_tu_and_compile_context_identity_cover_flags_and_relevant_configuration(self) -> None:
        first = context("src/a.cpp", config_hash=sha("config-a"))
        same = context("src/a.cpp", config_hash=sha("config-a"))
        changed_flag = context("src/a.cpp", flag="-DTWO", config_hash=sha("config-a"))
        changed_config = context("src/a.cpp", config_hash=sha("config-b"))

        self.assertEqual(first.identity, same.identity)
        self.assertEqual(TranslationUnitIdentity.from_context(first), TranslationUnitIdentity.from_context(same))
        self.assertNotEqual(first.identity, changed_flag.identity)
        self.assertNotEqual(first.identity, changed_config.identity)

    def test_one_source_can_have_multiple_exact_compile_context_tus(self) -> None:
        debug = context("src/a.cpp", flag="-DDEBUG")
        release = context("src/a.cpp", flag="-DNDEBUG")

        result = inventory(debug, release)

        self.assertEqual(len(result.translation_units), 2)
        self.assertNotEqual(*result.translation_units)

    def test_semantic_fingerprint_covers_dependency_producer_and_schema_inputs(self) -> None:
        tu = TranslationUnitIdentity.from_context(context("src/a.cpp"))
        states = tuple(sorted((
            SemanticFileState(RepositoryFile.from_path("src/a.cpp"), sha("source")),
            SemanticFileState(RepositoryFile.from_path("include/a.h"), sha("header")),
        ), key=lambda item: item.path.path.as_posix()))
        first = SemanticFingerprintInput(tu, states, "deps-v1", "clangd-v1", "schema-v1")
        changed = SemanticFingerprintInput(tu, states, "deps-v1", "clangd-v2", "schema-v1")

        self.assertEqual(first.sha256, first.sha256)
        self.assertNotEqual(first.sha256, changed.sha256)


class ProviderAdapterTests(unittest.TestCase):
    def test_compilation_database_adapter_normalizes_tus_and_configuration_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "src").mkdir()
            (root / "src" / "a.cpp").write_text("int a;\n", encoding="utf-8")
            (root / ".clangd").write_text("CompileFlags: {}\n", encoding="utf-8")
            expected_configuration_hash = hashlib.sha256((root / ".clangd").read_bytes()).hexdigest()
            (root / "compile_commands.json").write_text(json.dumps([{
                "directory": str(root),
                "file": "src/a.cpp",
                "arguments": ["clang++", "-Iinclude", "-c", "src/a.cpp"],
            }]), encoding="utf-8")

            result = CompilationDatabaseProvider(
                configuration_files=(".clangd",),
            ).load(RepositoryWorkspace(root))

        self.assertEqual(result.coverage, DependencyCoverageStatus.COMPLETE)
        self.assertEqual([item.source.path.as_posix() for item in result.contexts], ["src/a.cpp"])
        self.assertEqual(result.contexts[0].configuration_inputs[0].sha256,
                         expected_configuration_hash)

    def test_malformed_compilation_database_returns_unknown_diagnostic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "compile_commands.json").write_text("{}", encoding="utf-8")
            result = CompilationDatabaseProvider().load(RepositoryWorkspace(root))

        self.assertEqual(result.coverage, DependencyCoverageStatus.UNKNOWN)
        self.assertEqual(result.diagnostics[0].code, DependencyDiagnosticCode.MALFORMED_METADATA)
        self.assertTrue(result.diagnostics[0].requires_full_rebuild)

    def test_missing_compilation_database_has_distinct_fallback_diagnostic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = CompilationDatabaseProvider().load(RepositoryWorkspace(directory))

        self.assertEqual(result.coverage, DependencyCoverageStatus.UNKNOWN)
        self.assertEqual(result.diagnostics[0].code,
                         DependencyDiagnosticCode.MISSING_COMPILE_METADATA)
        self.assertTrue(result.diagnostics[0].requires_full_rebuild)

    def test_compilation_database_may_be_explicit_external_build_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as metadata:
            root = Path(directory)
            (root / "src").mkdir()
            (root / "src" / "a.cpp").write_text("int a;\n", encoding="utf-8")
            database = Path(metadata) / "compile_commands.json"
            database.write_text(json.dumps([{
                "directory": str(root), "file": "src/a.cpp",
                "arguments": ["clang++", "-c", "src/a.cpp"],
            }]), encoding="utf-8")

            result = CompilationDatabaseProvider(database).load(RepositoryWorkspace(root))

        self.assertEqual(result.coverage, DependencyCoverageStatus.COMPLETE)
        self.assertEqual(result.contexts[0].source, RepositoryFile.from_path("src/a.cpp"))

    def test_make_depfile_adapter_supplies_flat_direct_and_transitive_reverse_lookup(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as metadata:
            root = Path(directory)
            for relative in ("src/a.cpp", "src/b.cpp", "include/direct.h", "include/transitive.h"):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("// fixture\n", encoding="utf-8")
            (Path(metadata) / "a.d").write_text(
                "a.o: src/a.cpp include/direct.h \\\n include/transitive.h\n", encoding="utf-8",
            )
            (Path(metadata) / "b.d").write_text("b.o: src/b.cpp include/direct.h\n", encoding="utf-8")
            contexts = inventory(
                CompileContext(RepositoryFile.from_path("src/a.cpp"), str(root),
                               ("clang++", "-c", "src/a.cpp")),
                CompileContext(RepositoryFile.from_path("src/b.cpp"), str(root),
                               ("clang++", "-c", "src/b.cpp")),
            )
            result = MakeDepfileDependencyProvider(metadata, {
                "src/a.cpp": "a.d", "src/b.cpp": "b.d",
            }).load(RepositoryWorkspace(root), contexts)

        reverse = ReverseDependencyIndex(result)
        self.assertEqual(result.coverage, DependencyCoverageStatus.COMPLETE)
        self.assertEqual(len(reverse.translation_units_for(RepositoryFile.from_path("include/direct.h"))), 2)
        self.assertEqual(len(reverse.translation_units_for(RepositoryFile.from_path("include/transitive.h"))), 1)

    def test_missing_depfile_is_partial_and_requests_safe_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as metadata:
            root = Path(directory)
            (root / "src").mkdir()
            (root / "src" / "a.cpp").write_text("int a;\n", encoding="utf-8")
            compile_contexts = inventory(CompileContext(
                RepositoryFile.from_path("src/a.cpp"), str(root), ("clang++", "-c", "src/a.cpp"),
            ))
            result = MakeDepfileDependencyProvider(metadata, {}).load(
                RepositoryWorkspace(root), compile_contexts,
            )

        self.assertEqual(result.coverage, DependencyCoverageStatus.PARTIAL)
        self.assertEqual(result.diagnostics[0].code,
                         DependencyDiagnosticCode.MISSING_DEPENDENCY_METADATA)
        self.assertTrue(result.diagnostics[0].requires_full_rebuild)


class DependencyImpactTests(unittest.TestCase):
    def setUp(self) -> None:
        self.a = context("src/a.cpp")
        self.b = context("src/b.cpp")
        self.contexts = inventory(self.a, self.b)
        self.metadata = dependencies(
            (self.a, ("include/direct.h", "include/transitive.h")),
            (self.b, ("include/direct.h",)),
        )
        self.analyzer = DependencyImpactAnalyzer()

    def analyze(self, *changes: RepositoryChange):
        return self.analyzer.analyze(changes, previous_contexts=self.contexts,
                                     current_contexts=self.contexts,
                                     previous_dependencies=self.metadata,
                                     current_dependencies=self.metadata)

    def test_cpp_change_invalidates_its_own_tu_only(self) -> None:
        result = self.analyze(RepositoryChange.from_paths(
            "src/a.cpp", "src/a.cpp", RepositoryChangeKind.MODIFY,
        ))

        self.assertEqual(result.status, ImpactStatus.SAFE_INCREMENTAL)
        self.assertEqual(result.affected_translation_units,
                         (TranslationUnitIdentity.from_context(self.a),))

    def test_header_change_invalidates_every_direct_and_transitive_dependent_tu(self) -> None:
        direct = self.analyze(RepositoryChange.from_paths(
            "include/direct.h", "include/direct.h", RepositoryChangeKind.MODIFY,
        ))
        transitive = self.analyze(RepositoryChange.from_paths(
            "include/transitive.h", "include/transitive.h", RepositoryChangeKind.MODIFY,
        ))

        self.assertEqual(len(direct.affected_translation_units), 2)
        self.assertEqual(transitive.affected_translation_units,
                         (TranslationUnitIdentity.from_context(self.a),))

    def test_compile_configuration_change_invalidates_only_contexts_that_reference_it(self) -> None:
        before_a = context("src/a.cpp", config_hash=sha("old"))
        after_a = context("src/a.cpp", config_hash=sha("new"))
        unchanged_b = context("src/b.cpp")
        previous = inventory(before_a, unchanged_b)
        current = inventory(after_a, unchanged_b)
        result = self.analyzer.analyze((RepositoryChange.from_paths(
            ".clangd", ".clangd", RepositoryChangeKind.MODIFY,
        ),), previous_contexts=previous, current_contexts=current,
            previous_dependencies=dependencies((before_a, ()), (unchanged_b, ())),
            current_dependencies=dependencies((after_a, ()), (unchanged_b, ())))

        self.assertEqual(result.status, ImpactStatus.SAFE_INCREMENTAL)
        self.assertEqual(set(result.affected_translation_units), {
            TranslationUnitIdentity.from_context(before_a),
            TranslationUnitIdentity.from_context(after_a),
        })

    def test_rename_uses_both_revision_sides_and_deleted_tu_identity_is_retained(self) -> None:
        renamed = self.analyze(RepositoryChange.from_paths(
            "include/direct.h", "include/renamed.h", RepositoryChangeKind.RENAME,
        ))
        deleted = self.analyze(RepositoryChange.from_paths(
            "src/a.cpp", None, RepositoryChangeKind.DELETE,
        ))

        self.assertEqual(len(renamed.affected_translation_units), 2)
        self.assertIn(TranslationUnitIdentity.from_context(self.a), deleted.affected_translation_units)

    def test_incomplete_dependency_coverage_never_claims_safe_header_impact(self) -> None:
        partial = dependencies((self.a, ("include/direct.h",)),
                               coverage=DependencyCoverageStatus.PARTIAL)
        result = self.analyzer.analyze((RepositoryChange.from_paths(
            "include/direct.h", "include/direct.h", RepositoryChangeKind.MODIFY,
        ),), previous_contexts=self.contexts, current_contexts=self.contexts,
            previous_dependencies=partial, current_dependencies=partial)

        self.assertEqual(result.status, ImpactStatus.FULL_REBUILD_REQUIRED)
        self.assertTrue(result.requires_full_rebuild)
        self.assertIn(DependencyDiagnosticCode.UNKNOWN_HEADER_IMPACT,
                      {item.code for item in result.diagnostics})

    def test_provider_complete_claim_is_rejected_when_a_tu_record_is_missing(self) -> None:
        incomplete = dependencies((self.a, ("include/direct.h",)))
        result = self.analyzer.analyze((RepositoryChange.from_paths(
            "include/direct.h", "include/direct.h", RepositoryChangeKind.MODIFY,
        ),), previous_contexts=self.contexts, current_contexts=self.contexts,
            previous_dependencies=incomplete, current_dependencies=incomplete)

        self.assertEqual(result.status, ImpactStatus.FULL_REBUILD_REQUIRED)
        self.assertTrue(any("coverage mismatch" in item.message for item in result.diagnostics))


if __name__ == "__main__":
    unittest.main()
