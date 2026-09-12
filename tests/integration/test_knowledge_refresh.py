from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Event
from typing import Self
from unittest.mock import patch

from arkui_agent.context import parse_task
from arkui_agent.context.materialization import materialize_context
from arkui_agent.graph import GraphSnapshot, default_role_mapper
from arkui_agent.knowledge import (
    BuildConfiguration, BuildScope, BuildStatus, GitSourceReader,
    KnowledgeRefreshService, ManifestPublisher, P1P2RefreshBuilder,
    PrebuiltSnapshotReader, QueryRequirement, RefreshRequest, RefreshStatus,
    ScopeKind, loads,
    ProductionBuildInputs, CoverageReason, CoverageStatus, Freshness,
)
from arkui_agent.repository import (
    RepositoryFile, RepositoryScanner, SemanticProviderClosedError, SourceLocation, SourceRange,
    Symbol, SymbolIdentity, SymbolKind, SymbolObservation,
)
from arkui_agent.retrieval.candidates import (
    CandidateQuery, Channel, EvidenceSide, NameSelector, QueryOrigin,
    RetrievalRequest,
)
from arkui_agent.retrieval.expansion import GraphExpander
from arkui_agent.retrieval.service import CandidateRetriever


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _configuration(label: str = "v1", *, tool: str = "tool-v1",
                   rules: str | None = None) -> BuildConfiguration:
    mapper = default_role_mapper()
    return BuildConfiguration(
        _sha("configuration-" + label), _sha(tool), 3, 1, 1,
        "rg-source-v1", "test-rules-" + label, "p1-index-v1",
        mapper.ruleset_identity if rules is None else rules,
        "arkui.framework.v1", ("-std=c++17",), (".",), None,
        "p1-scanner-v1",
    )


class FixtureProvider:
    def __init__(self, symbol: Symbol) -> None:
        self.symbol = symbol
        self.closed = False

    def symbols_in_file(self, file: RepositoryFile) -> tuple[Symbol, ...]:
        self._open()
        return (self.symbol,) if file.path.as_posix() == "src/widget.cpp" else ()

    def declaration(self, identity: SymbolIdentity) -> SourceRange | None:
        self._open()
        return self.symbol.declaration if identity == self.symbol.identity else None

    def definition(self, identity: SymbolIdentity) -> SourceRange | None:
        self._open()
        return self.symbol.definition if identity == self.symbol.identity else None

    def references(self, identity: SymbolIdentity) -> tuple[SourceRange, ...]:
        self._open()
        return ()

    def callers(self, identity: SymbolIdentity) -> tuple[Symbol, ...]:
        self._open()
        return ()

    def callees(self, identity: SymbolIdentity) -> tuple[Symbol, ...]:
        self._open()
        return ()

    def close(self) -> None:
        self.closed = True

    def __enter__(self) -> Self:
        self._open()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _open(self) -> None:
        if self.closed:
            raise SemanticProviderClosedError("closed")


class StaticBuilder(P1P2RefreshBuilder):
    def __init__(self, configuration: BuildConfiguration, symbol: Symbol) -> None:
        super().__init__(provider_factory=lambda workspace, config: FixtureProvider(symbol))
        self.value = configuration

    def configuration(self, workspace) -> BuildConfiguration:
        return self.value


class FailingBuilder(StaticBuilder):
    def build(self, workspace, context):
        raise ValueError("injected semantic build failure for src/widget.cpp")


class DriftBuilder(StaticBuilder):
    def build(self, workspace, context):
        output = super().build(workspace, context)
        workspace.resolve("src/widget.cpp").write_text("int widget() { return 2; }\n", encoding="utf-8")
        return output


class RevisionDriftBuilder(StaticBuilder):
    def build(self, workspace, context):
        output = super().build(workspace, context)
        workspace.resolve("README.md").write_text("next revision\n", encoding="utf-8")
        subprocess.run(("git", "-C", str(workspace.root), "add", "README.md"),
                       capture_output=True, check=True, timeout=30)
        subprocess.run(("git", "-C", str(workspace.root), "commit", "-m", "drift"),
                       capture_output=True, check=True, timeout=30)
        return output


class BlockingBuilder(StaticBuilder):
    def __init__(self, configuration: BuildConfiguration, symbol: Symbol,
                 entered: Event, release: Event) -> None:
        super().__init__(configuration, symbol)
        self.entered = entered
        self.release = release

    def build(self, workspace, context):
        self.entered.set()
        if not self.release.wait(timeout=5):
            raise ValueError("writer conflict test release timed out")
        return super().build(workspace, context)


class FailSuccessfulPublication(ManifestPublisher):
    def __init__(self) -> None:
        self.failed = False

    def publish(self, path, manifest) -> None:
        if (not self.failed and manifest.latest_attempt is not None
                and manifest.latest_attempt.status is BuildStatus.SUCCEEDED):
            self.failed = True
            raise OSError("injected final manifest publication failure")
        super().publish(path, manifest)


class KnowledgeRefreshIntegrationTests(unittest.TestCase):
    def test_cancelled_build_preserves_old_session_releases_lock_and_restarts(self):
        service = self.service()
        first = service.refresh(RefreshRequest(self.scope, "first"))
        self.assertEqual(first.status, RefreshStatus.PUBLISHED, first.diagnostics)
        reader = PrebuiltSnapshotReader(service.manifest_path, artifact_root=self.knowledge,
                                        source=service.source)
        with reader.bind(self.requirement(first.snapshot)) as session:
            bound = session.reference
            def cancel(workspace, context):
                context.generation_directory.mkdir()
                (context.generation_directory / "partial.txt").write_text("not usable")
                context.progress("semantic_prepare", 1, 14497, "src/widget.cpp")
                raise KeyboardInterrupt
            with patch.object(service.builder, "build", side_effect=cancel):
                result = service.refresh(RefreshRequest(self.scope, "cancel", True))
            self.assertEqual(result.status, RefreshStatus.CANCELLED)
            self.assertEqual(session.reference, bound)
            with session.read() as knowledge:
                self.assertEqual(knowledge.graph.snapshot_key, first.snapshot.identity.generation)
            self.assertEqual(result.snapshot, first.snapshot)
            manifest = loads(service.manifest_path.read_text())
            self.assertEqual(manifest.latest_attempt.status, BuildStatus.CANCELLED)
            self.assertIsNotNone(manifest.latest_attempt.finished_at)
            self.assertIn("Build cancelled by user", manifest.latest_attempt.failure)
            self.assertEqual(manifest.last_usable, first.snapshot)
            self.assertFalse((self.knowledge / ".refresh.lock").exists())
            self.assertFalse(reader.inspect(self.requirement(first.snapshot)).can_bind)
            orphan = self.knowledge / "generations" / result.attempt.target.generation
            self.assertFalse(json.loads((orphan / "orphan.json").read_text())["usable"])
            progress = json.loads((self.knowledge / "progress.json").read_text())
            self.assertEqual((progress["status"], progress["phase"], progress["current"], progress["total"]),
                             ("cancelled", "semantic_prepare", 1, 14497))
            restarted = service.refresh(RefreshRequest(self.scope, "restart"))
            self.assertEqual(restarted.status, RefreshStatus.PUBLISHED, restarted.diagnostics)
            self.assertNotEqual(restarted.snapshot.identity.generation, result.attempt.target.generation)

    def test_cancellation_before_initial_source_observation_finishes(self):
        service = self.service()
        with patch.object(service.source, "observe", side_effect=KeyboardInterrupt):
            result = service.refresh(RefreshRequest(self.scope, "cancel early"))
        self.assertEqual(result.status, RefreshStatus.CANCELLED)
        self.assertEqual(loads(service.manifest_path.read_text()).latest_attempt.status, BuildStatus.CANCELLED)
        self.assertFalse((self.knowledge / ".refresh.lock").exists())

    def test_progress_success_failure_and_io_failure_do_not_change_build_semantics(self):
        from arkui_agent.knowledge.progress import RefreshProgress
        events = []
        original_update = RefreshProgress.update
        def observed_update(progress, phase, *args, **kwargs):
            events.append((phase, kwargs.get("status", "running")))
            return original_update(progress, phase, *args, **kwargs)
        service = self.service()
        with patch.object(RefreshProgress, "update", observed_update):
            result = service.refresh(RefreshRequest(self.scope, "success"))
        self.assertTrue({"source_inventory", "test_discovery", "semantic_collect", "canonicalize",
                         "symbol_index", "graph_build", "artifact_validation", "publish"}.issubset(
                             {phase for phase, status in events if status == "running"}))
        self.assertEqual(events[-1], ("publish", "succeeded"))
        record = json.loads((self.knowledge / "progress.json").read_text())
        self.assertEqual((record["status"], record["phase"], record["percent"]), ("succeeded", "publish", 100))
        self.assertEqual(record["attempt_id"], result.attempt.attempt_id)
        failed = self.service(FailingBuilder(self.config, self.symbol)).refresh(RefreshRequest(self.scope, "failure", True))
        self.assertEqual(failed.status, RefreshStatus.FAILED)
        self.assertEqual(json.loads((self.knowledge / "progress.json").read_text())["status"], "failed")
        # Patch only progress serialization, never artifact/manifest persistence.
        with patch("arkui_agent.knowledge.progress.NamedTemporaryFile", side_effect=OSError("telemetry unavailable")):
            result = service.refresh(RefreshRequest(self.scope, "telemetry failure", True))
        self.assertEqual(result.status, RefreshStatus.PUBLISHED, result.diagnostics)
        self.assertTrue(any("Progress reporting unavailable" in d for d in result.diagnostics))

    def test_provider_cleanup_failure_cannot_replace_cancellation(self):
        from arkui_agent.repository import ClangdSemanticProvider
        class CancellingProvider(FixtureProvider):
            cleanup_diagnostics = ()
            __exit__ = ClangdSemanticProvider.__exit__
            def symbols_in_file(inner, file):
                raise KeyboardInterrupt
            def close(inner):
                inner.closed = True
                raise OSError("cleanup problem")
        provider = CancellingProvider(self.symbol)
        builder = StaticBuilder(self.config, self.symbol)
        builder._provider_factory = lambda workspace, configuration: provider
        result = self.service(builder).refresh(RefreshRequest(self.scope, "cancel in semantic"))
        self.assertEqual(result.status, RefreshStatus.CANCELLED)
        self.assertTrue(provider.closed)
        self.assertIn("Build cancelled by user", result.attempt.failure)
        self.assertIn("cleanup problem", result.attempt.failure)

    def test_cancel_delivered_after_atomic_publication_does_not_rollback(self):
        class CancelAfterPublish(ManifestPublisher):
            def publish(inner, path, manifest):
                super().publish(path, manifest)
                if manifest.latest_attempt.status is BuildStatus.SUCCEEDED:
                    raise KeyboardInterrupt
        service = self.service(publisher=CancelAfterPublish())
        result = service.refresh(RefreshRequest(self.scope, "publication boundary"))
        self.assertEqual(result.status, RefreshStatus.PUBLISHED)
        self.assertEqual(loads(service.manifest_path.read_text()).last_usable, result.snapshot)
        self.assertFalse((self.knowledge / ".refresh.lock").exists())

    def test_large_failure_is_bounded_in_manifest_and_cli_but_report_is_complete(self):
        from scripts.refresh_knowledge import result_payload
        from arkui_agent.knowledge import KnowledgeManifest

        service = self.service()
        first = self.service(FailingBuilder(_configuration(), self.symbol)).refresh(
            RefreshRequest(self.scope, "failure sizing"))
        paths = tuple(f"src/file-{i:05d}.cpp" for i in range(10000))
        scope = BuildScope(ScopeKind.FULL_REPOSITORY, paths, (), paths)
        detail = "stage=semantic; " + "large backend diagnostic " * 50000 + "; exit_code=71"
        result = service._record_failure(KnowledgeManifest(None, first.attempt), first.attempt,
                                         detail, None, scope, service.source.observe(()))
        self.assertLess(len(result.attempt.failure), 4300)
        self.assertIn("exit_code=71", result.attempt.failure)
        self.assertLess(service.manifest_path.stat().st_size, 7000)
        directory = self.knowledge / "generations" / result.attempt.target.generation
        self.assertEqual(json.loads((directory / "failure.json").read_text())["failure"], detail)
        coverage = json.loads((directory / "coverage.json").read_text())
        self.assertEqual(len(coverage["failures"]), 20000)
        self.assertLess(max(len(f["detail"]) for f in coverage["failures"]), 150)
        with patch.object(type(result.coverage), "to_dict", side_effect=AssertionError("full report on stdout")):
            payload = result_payload(result, service.manifest_path)
        encoded = json.dumps(payload)
        self.assertLess(len(encoded), 15000)
        self.assertEqual(payload["coverage"]["semantic_files"], 10000)

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.repo = root / "source"
        self.repo.mkdir()
        self.knowledge = root / "knowledge"
        self.git("init")
        self.git("config", "user.email", "fixture@example.invalid")
        self.git("config", "user.name", "Fixture")
        self.git("config", "core.autocrlf", "false")
        self.write("src/widget.cpp", "int widget() { return 1; }\n")
        self.write("tests/widget_test.cpp", "int smoke() { return 0; }\n")
        self.write("README.md", "fixture\n")
        self.git("add", ".")
        self.git("commit", "-m", "fixture")
        file = RepositoryFile.from_path("src/widget.cpp")
        self.symbol = Symbol(
            SymbolIdentity("widget-v1"), SymbolKind.FUNCTION, "widget", "widget",
            definition=SourceRange(SourceLocation(file, 1, 1), SourceLocation(file, 1, 27)),
        )
        self.scope = BuildScope(
            ScopeKind.SELECTED_FILES, ("src/widget.cpp",), ("tests/widget_test.cpp",),
            ("src/widget.cpp", "tests/widget_test.cpp"),
        )
        self.config = _configuration()

    def write(self, relative: str, text: str) -> None:
        path = self.repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")

    def git(self, *arguments: str) -> str:
        return subprocess.run(("git", "-C", str(self.repo), *arguments), capture_output=True,
                              text=True, encoding="utf-8", check=True, timeout=30).stdout.strip()

    def service(self, builder=None, publisher=None) -> KnowledgeRefreshService:
        return KnowledgeRefreshService(
            self.repo, self.knowledge, repository="test/repository",
            builder=builder or StaticBuilder(self.config, self.symbol), publisher=publisher,
        )

    def requirement(self, snapshot) -> QueryRequirement:
        return QueryRequirement("test/repository", snapshot.identity.revision,
                                snapshot.scope, snapshot.configuration)

    def test_first_refresh_is_fresh_binds_and_feeds_c1_through_e(self) -> None:
        result = self.service().refresh(RefreshRequest(self.scope, "initial manual build"))
        self.assertEqual(result.status, RefreshStatus.PUBLISHED, result.diagnostics)
        reader = PrebuiltSnapshotReader(self.knowledge / "manifest.json", artifact_root=self.knowledge,
                                        source=GitSourceReader(self.repo, repository="test/repository"))
        with reader.bind(self.requirement(result.snapshot)) as session:
            task = parse_task("inspect widget", repository="test/repository",
                              target_revision=result.snapshot.identity.revision,
                              source_id="refresh-consumer").value
            query = CandidateQuery(Channel.SYMBOL, NameSelector("widget"),
                                   (QueryOrigin(task.provenance, "refresh product"),))
            direct = CandidateRetriever().retrieve(
                RetrievalRequest(task, EvidenceSide.TARGET, (query,)), session
            )
            self.assertTrue(direct.candidates)
            expansion = GraphExpander().expand(direct, session)
            materialized = materialize_context(expansion, target=session)
            self.assertEqual(materialized.upstream, expansion)
            self.assertEqual(materialized.bindings[0].snapshot.identity, result.snapshot.identity)

    def test_missing_unused_compiler_does_not_prevent_publication_or_noop(self) -> None:
        inputs = ProductionBuildInputs(clangd_executable=sys.executable,
                                       compiler_executable="missing-unused-compiler")
        builder = P1P2RefreshBuilder(inputs, provider_factory=lambda workspace, config: FixtureProvider(self.symbol))
        service = self.service(builder)
        result = service.refresh(RefreshRequest(self.scope, "optional compiler"))
        self.assertEqual(result.status, RefreshStatus.PUBLISHED, result.diagnostics)
        noop = service.refresh(RefreshRequest(self.scope, "optional compiler unchanged"))
        self.assertEqual(noop.status, RefreshStatus.NO_OP, noop.diagnostics)

    def test_related_partial_observations_use_public_merge_and_retain_provenance(self) -> None:
        complete = replace(self.symbol, declaration=self.symbol.definition)

        class PartialProvider(FixtureProvider):
            def symbol_observations_in_files(self, files):
                return (SymbolObservation(complete, complete.declaration),)

            def callers(self, identity):
                return (replace(complete, declaration=None),)

        builder = P1P2RefreshBuilder(
            ProductionBuildInputs(clangd_executable=sys.executable),
            provider_factory=lambda workspace, config: PartialProvider(complete),
        )
        result = self.service(builder).refresh(RefreshRequest(self.scope, "partial related evidence"))
        self.assertEqual(result.status, RefreshStatus.PUBLISHED, result.diagnostics)
        evidence = json.loads((self.knowledge / "generations" / result.snapshot.identity.generation
                               / "semantic-observations.json").read_text(encoding="utf-8"))
        self.assertEqual(len(evidence), 1)
        self.assertEqual(len(evidence[0]["observations"]), 2)
        self.assertEqual(sum(item["site"] is None for item in evidence[0]["observations"]), 1)

    def test_compatible_refresh_noops_and_force_uses_new_generation(self) -> None:
        service = self.service()
        first = service.refresh(RefreshRequest(self.scope, "initial"))
        self.assertEqual(first.status, RefreshStatus.PUBLISHED, first.diagnostics)
        noop = service.refresh(RefreshRequest(self.scope, "scheduled check"))
        forced = service.refresh(RefreshRequest(self.scope, "manual force", force=True))
        self.assertEqual(noop.status, RefreshStatus.NO_OP)
        self.assertEqual(noop.snapshot.identity, first.snapshot.identity)
        self.assertEqual(forced.status, RefreshStatus.PUBLISHED)
        self.assertNotEqual(forced.snapshot.identity.generation, first.snapshot.identity.generation)

    def test_build_failure_keeps_old_snapshot_and_failed_latest_attempt(self) -> None:
        first = self.service().refresh(RefreshRequest(self.scope, "initial"))
        self.assertEqual(first.status, RefreshStatus.PUBLISHED, first.diagnostics)
        failed = self.service(FailingBuilder(self.config, self.symbol)).refresh(
            RefreshRequest(self.scope, "failing rebuild", force=True)
        )
        manifest = loads((self.knowledge / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(failed.status, RefreshStatus.FAILED)
        self.assertEqual(manifest.last_usable.identity, first.snapshot.identity)
        self.assertEqual(manifest.latest_attempt.status, BuildStatus.FAILED)
        rebuilt = self.service().refresh(RefreshRequest(self.scope, "retry after failed latest"))
        self.assertEqual(rebuilt.status, RefreshStatus.PUBLISHED)
        self.assertNotEqual(rebuilt.snapshot.identity.generation, first.snapshot.identity.generation)

    def test_source_drift_fails_without_publishing_generation(self) -> None:
        first = self.service().refresh(RefreshRequest(self.scope, "initial"))
        self.assertEqual(first.status, RefreshStatus.PUBLISHED, first.diagnostics)
        failed = self.service(DriftBuilder(self.config, self.symbol)).refresh(
            RefreshRequest(self.scope, "drift", force=True)
        )
        manifest = loads((self.knowledge / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(failed.status, RefreshStatus.FAILED)
        self.assertEqual(manifest.last_usable.identity, first.snapshot.identity)
        self.assertIn("drift", manifest.latest_attempt.failure.lower())

    def test_revision_drift_fails_without_publishing_generation(self) -> None:
        first = self.service().refresh(RefreshRequest(self.scope, "initial"))
        self.assertEqual(first.status, RefreshStatus.PUBLISHED, first.diagnostics)
        failed = self.service(RevisionDriftBuilder(self.config, self.symbol)).refresh(
            RefreshRequest(self.scope, "revision drift", force=True)
        )
        manifest = loads((self.knowledge / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(failed.status, RefreshStatus.FAILED)
        self.assertEqual(manifest.last_usable.identity, first.snapshot.identity)
        self.assertIn("drift", manifest.latest_attempt.failure.lower())

    def test_old_session_remains_generation_pinned_after_force_publication(self) -> None:
        service = self.service()
        first = service.refresh(RefreshRequest(self.scope, "initial"))
        self.assertEqual(first.status, RefreshStatus.PUBLISHED, first.diagnostics)
        reader = PrebuiltSnapshotReader(self.knowledge / "manifest.json", artifact_root=self.knowledge,
                                        source=GitSourceReader(self.repo, repository="test/repository"))
        old = reader.bind(self.requirement(first.snapshot))
        second = service.refresh(RefreshRequest(self.scope, "force", force=True))
        with old.read() as view:
            self.assertEqual(view.reference.snapshot.identity.generation,
                             first.snapshot.identity.generation)
        with reader.bind(self.requirement(second.snapshot)) as new:
            self.assertEqual(new.reference.snapshot.identity.generation,
                             second.snapshot.identity.generation)
        old.close()

    def test_second_live_writer_conflicts_without_wait_or_manifest_damage(self) -> None:
        entered, release = Event(), Event()
        first_service = self.service(BlockingBuilder(self.config, self.symbol, entered, release))
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(first_service.refresh, RefreshRequest(self.scope, "first writer"))
            self.assertTrue(entered.wait(timeout=5))
            try:
                conflict = self.service().refresh(RefreshRequest(self.scope, "second writer"))
                self.assertEqual(conflict.status, RefreshStatus.CONFLICT)
                building = loads((self.knowledge / "manifest.json").read_text(encoding="utf-8"))
                self.assertEqual(building.latest_attempt.status, BuildStatus.BUILDING)
            finally:
                release.set()
            published = future.result(timeout=5)
        self.assertEqual(published.status, RefreshStatus.PUBLISHED)
        final = loads((self.knowledge / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(final.latest_attempt.status, BuildStatus.SUCCEEDED)

    def test_config_rule_and_toolchain_changes_each_prevent_noop(self) -> None:
        previous = self.service().refresh(RefreshRequest(self.scope, "initial"))
        self.assertEqual(previous.status, RefreshStatus.PUBLISHED, previous.diagnostics)
        for name, configuration in (
            ("config", _configuration("v2")),
            ("tool", _configuration("v2", tool="tool-v2")),
            ("rule", replace(_configuration("v2", tool="tool-v2"),
                             framework_rules_version="arkui.framework.v2")),
        ):
            result = self.service(StaticBuilder(configuration, self.symbol)).refresh(
                RefreshRequest(self.scope, name)
            )
            self.assertEqual(result.status, RefreshStatus.PUBLISHED)
            self.assertNotEqual(result.snapshot.identity.generation,
                                previous.snapshot.identity.generation)
            previous = result

    def test_selected_snapshot_never_claims_full_and_full_uses_tracked_inventory(self) -> None:
        selected = self.service().refresh(RefreshRequest(self.scope, "selected"))
        self.assertEqual(selected.status, RefreshStatus.PUBLISHED, selected.diagnostics)
        full_request = BuildScope(ScopeKind.FULL_REPOSITORY, (), (), ())
        full = self.service().refresh(RefreshRequest(full_request, "full"))
        self.assertEqual(selected.snapshot.scope.kind, ScopeKind.SELECTED_FILES)
        self.assertEqual(full.status, RefreshStatus.PUBLISHED)
        self.assertEqual(full.snapshot.scope.kind, ScopeKind.FULL_REPOSITORY)
        self.assertEqual({item.path for item in full.snapshot.source.files},
                         {"README.md", "src/widget.cpp", "tests/widget_test.cpp"})
        self.assertEqual(full.snapshot.scope.semantic_files, ("src/widget.cpp",))
        self.assertEqual(full.snapshot.scope.test_files, ("tests/widget_test.cpp",))
        self.assertEqual(full.snapshot.scope.text_files,
                         ("README.md", "src/widget.cpp", "tests/widget_test.cpp"))

    def test_full_scope_scanner_omission_is_explicit_failure(self) -> None:
        full_request = BuildScope(ScopeKind.FULL_REPOSITORY, (), (), ())
        actual_scan = RepositoryScanner.scan
        def omit_supported(scanner, **kwargs):
            return tuple(file for file in actual_scan(scanner, **kwargs)
                         if file.path.as_posix() != "src/widget.cpp")
        with patch.object(RepositoryScanner, "scan", omit_supported):
            failed = self.service().refresh(RefreshRequest(full_request, "full coverage"))
        manifest = loads((self.knowledge / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(failed.status, RefreshStatus.FAILED)
        self.assertIsNone(manifest.last_usable)
        self.assertEqual(manifest.latest_attempt.status, BuildStatus.FAILED)
        self.assertIn("src/widget.cpp", manifest.latest_attempt.failure)
        self.assertEqual(failed.coverage.exclusions, ())

    def test_full_policy_exclusions_are_reported_but_remain_fingerprint_inputs(self) -> None:
        excluded = ("generated/hidden.cpp", "nested/Generated/hidden.h",
                    "tests/generated/hidden_test.cpp", "generated/notes.txt")
        for path in excluded:
            self.write(path, "// generated content\n")
        self.git("add", ".")
        self.git("commit", "-m", "tracked generated source")
        service = self.service()
        scope = BuildScope(ScopeKind.FULL_REPOSITORY, (), (), ())
        result = service.refresh(RefreshRequest(scope, "full supported coverage"))
        self.assertEqual(result.status, RefreshStatus.PUBLISHED, result.diagnostics)
        self.assertEqual(result.snapshot.scope.semantic_files, ("src/widget.cpp",))
        self.assertEqual(result.snapshot.scope.test_files, ("tests/widget_test.cpp",))
        self.assertEqual(result.snapshot.scope.text_files,
                         tuple(sorted((*excluded, "README.md", "src/widget.cpp", "tests/widget_test.cpp"))))
        self.assertTrue(set(excluded).issubset({f.path for f in result.snapshot.source.files}))
        self.assertFalse(set(excluded) & set(result.snapshot.scope.semantic_files + result.snapshot.scope.test_files))
        self.assertFalse(set(excluded) & {f.path for f in result.coverage.files if f.channel.value != "text"})
        self.assertEqual({f.path for f in result.coverage.exclusions}, set(excluded))
        for item in result.coverage.exclusions:
            self.assertEqual(item.status, CoverageStatus.EXCLUDED)
            self.assertEqual(item.reason, CoverageReason.UNSUPPORTED_BY_POLICY)
            self.assertIn("generated", item.detail.lower())
        report = result.coverage.to_dict()
        self.assertEqual(report["tracked_files"], 7)
        self.assertEqual(report["excluded_files"], 4)
        self.assertEqual(report["excluded_other_files"], 1)
        self.assertEqual(report["excluded_by_channel"], {"semantic": 2, "test": 1, "text": 0})
        self.assertEqual(report["text_files"], 7)
        self.assertEqual(report["semantic_files"], 1)
        persisted = json.loads((self.knowledge / "generations" / result.snapshot.identity.generation
                                / "coverage.json").read_text(encoding="utf-8"))
        self.assertEqual(persisted, json.loads(json.dumps(report)))
        noop = service.refresh(RefreshRequest(scope, "same full policy"))
        self.assertEqual(noop.status, RefreshStatus.NO_OP)
        self.assertEqual(noop.coverage.exclusions, result.coverage.exclusions)
        self.assertEqual(noop.coverage.to_dict()["semantic_files"], 1)
        reader = PrebuiltSnapshotReader(self.knowledge / "manifest.json", artifact_root=self.knowledge,
                                        source=GitSourceReader(self.repo, repository="test/repository"))
        excluded_query = QueryRequirement("test/repository", result.snapshot.identity.revision,
                                          BuildScope(ScopeKind.SELECTED_FILES, (excluded[0],), (), ()),
                                          result.snapshot.configuration)
        self.assertFalse(reader.inspect(excluded_query).can_bind)
        self.write(excluded[0], "// changed generated dependency\n")
        self.assertEqual(reader.inspect(self.requirement(result.snapshot)).state, Freshness.STALE)
        failed = service.refresh(RefreshRequest(scope, "changed excluded source"))
        self.assertEqual(failed.status, RefreshStatus.FAILED)
        self.assertEqual(failed.snapshot.identity, result.snapshot.identity)
        self.git("add", ".")
        self.git("commit", "-m", "changed generated dependency")
        rebuilt = service.refresh(RefreshRequest(scope, "committed excluded change"))
        self.assertEqual(rebuilt.status, RefreshStatus.PUBLISHED, rebuilt.diagnostics)
        self.assertNotEqual(rebuilt.snapshot.source.sha256, result.snapshot.source.sha256)
        self.assertNotEqual(rebuilt.snapshot.identity.generation, result.snapshot.identity.generation)

    def test_selected_generated_paths_are_rejected_with_typed_exclusion(self) -> None:
        path = "generated/hidden.cpp"
        self.write(path, "int hidden;\n")
        self.git("add", ".")
        self.git("commit", "-m", "tracked excluded")
        for semantic, text in (((path,), ()), ((), (path,))):
            scope = BuildScope(ScopeKind.SELECTED_FILES, semantic, (), text)
            result = self.service().refresh(RefreshRequest(scope, "selected excluded"))
            self.assertEqual(result.status, RefreshStatus.FAILED)
            self.assertIsNone(result.snapshot)
            self.assertIn("unsupported-by-policy", result.diagnostics[0])
            self.assertEqual({f.path for f in result.coverage.exclusions}, {path})

    def test_policy_exclusion_does_not_excuse_unrelated_scanner_omission(self) -> None:
        self.write("generated/hidden.cpp", "int hidden;\n")
        self.git("add", ".")
        self.git("commit", "-m", "generated and supported")
        actual_scan = RepositoryScanner.scan
        def omit_supported(scanner, **kwargs):
            return tuple(f for f in actual_scan(scanner, **kwargs) if f.path.as_posix() != "src/widget.cpp")
        with patch.object(RepositoryScanner, "scan", omit_supported):
            result = self.service().refresh(RefreshRequest(BuildScope(ScopeKind.FULL_REPOSITORY, (), (), ()), "omission"))
        self.assertEqual(result.status, RefreshStatus.FAILED)
        self.assertIn("src/widget.cpp", result.diagnostics[0])
        self.assertNotIn("generated/hidden.cpp", result.diagnostics[0])
        self.assertEqual({f.path for f in result.coverage.exclusions}, {"generated/hidden.cpp"})

    def test_final_publication_failure_preserves_old_generation_and_records_failure(self) -> None:
        first = self.service().refresh(RefreshRequest(self.scope, "initial"))
        self.assertEqual(first.status, RefreshStatus.PUBLISHED, first.diagnostics)
        failed = self.service(publisher=FailSuccessfulPublication()).refresh(
            RefreshRequest(self.scope, "publish failure", force=True)
        )
        manifest = loads((self.knowledge / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(failed.status, RefreshStatus.FAILED)
        self.assertEqual(manifest.last_usable.identity, first.snapshot.identity)
        self.assertEqual(manifest.latest_attempt.status, BuildStatus.FAILED)
        self.assertIn("publication", manifest.latest_attempt.failure)


if __name__ == "__main__":
    unittest.main()
