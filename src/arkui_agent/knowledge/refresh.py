"""Single-run P1/P2 rebuild and atomic KnowledgeManifest publication."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import uuid
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Callable, Protocol

from arkui_agent.graph import (
    GraphSnapshot, GraphStorageError, GraphStore, default_role_mapper,
    extract_framework_relations, project_index,
)
from arkui_agent.graph.domain import DomainMap
from arkui_agent.graph.framework import RULESET as FRAMEWORK_RULESET
from arkui_agent.repository import (
    ARKUI_FIXTURE_TEST_MACROS, ClangdSemanticProvider, RepositoryFile,
    RepositoryFileType, RepositoryScanner, RepositoryTestDiscoverer,
    RepositoryWorkspace, SemanticProvider, SemanticProviderError, Symbol,
    SymbolIndex, SymbolIndexError, SymbolObservation, SymbolSemanticFacts, TestDiscoveryError,
    canonicalize_symbol_groups, classify_repository_path,
)

from .model import (
    ArtifactKind, ArtifactReference, BuildAttempt, BuildConfiguration, BuildScope,
    BuildStatus, KnowledgeArtifacts, KnowledgeManifest, KnowledgeSnapshot,
    ManifestError, ProvenanceStatus, QueryRequirement, ScopeKind, SnapshotBuild,
    SnapshotIdentity, TextKnowledge, SourceFingerprint,
)
from .reader import PrebuiltArtifactReader, PrebuiltSnapshotReader
from .serialization import dumps, loads
from .source import GitSourceReader, SourceObservation, SourceReadError, hash_file
from .progress import RefreshProgress
from arkui_agent.repository.interrupts import defer_keyboard_interrupt


class RefreshStatus(str, Enum):
    PUBLISHED = "published"
    NO_OP = "no_op"
    FAILED = "failed"
    CANCELLED = "cancelled"
    CONFLICT = "conflict"


class CoverageChannel(str, Enum):
    SEMANTIC = "semantic"
    TEST = "test"
    TEXT = "text"


class CoverageStatus(str, Enum):
    PROCESSED = "processed"
    FAILED = "failed"
    EXCLUDED = "excluded"


class CoverageReason(str, Enum):
    UNSUPPORTED_BY_POLICY = "unsupported_by_policy"


@dataclass(frozen=True, slots=True)
class FileCoverage:
    path: str
    channel: CoverageChannel
    status: CoverageStatus
    detail: str


@dataclass(frozen=True, slots=True)
class PolicyExclusion:
    path: str
    channel: CoverageChannel | None  # None: scanner-excluded non-C/C++ path, text remains available
    detail: str
    status: CoverageStatus = CoverageStatus.EXCLUDED
    reason: CoverageReason = CoverageReason.UNSUPPORTED_BY_POLICY


@dataclass(frozen=True, slots=True)
class RefreshCoverage:
    scope: BuildScope | None
    tracked_files: tuple[str, ...]
    files: tuple[FileCoverage, ...]
    diagnostics: tuple[str, ...] = ()
    exclusions: tuple[PolicyExclusion, ...] = ()

    def summary(self) -> dict[str, object]:
        """Bounded stdout view; never materialize the full report to trim it."""
        return {
            "tracked_files": len(self.tracked_files),
            "scope": self.scope.kind.value if self.scope else None,
            "semantic_files": len(self.scope.semantic_files) if self.scope else 0,
            "test_files": len(self.scope.test_files) if self.scope else 0,
            "text_files": len(self.scope.text_files) if self.scope else 0,
            "processed": {c.value: sum(f.channel is c and f.status is CoverageStatus.PROCESSED
                                       for f in self.files) for c in CoverageChannel},
            "failed_files": sum(f.status is CoverageStatus.FAILED for f in self.files),
            "excluded_files": len(self.exclusions),
            "excluded_by_channel": {c.value: sum(f.channel is c for f in self.exclusions)
                                    for c in CoverageChannel},
            "excluded_other_files": sum(f.channel is None for f in self.exclusions),
            "exclusion_sample": [{"path": _bounded(f.path, 300), "reason": f.reason.value,
                                  "detail": _bounded(f.detail, 300)} for f in self.exclusions[:3]],
            "diagnostic_count": len(self.diagnostics),
            "diagnostic_sample": [_bounded(d, 500) for d in self.diagnostics[:3]],
        }

    def to_dict(self) -> dict[str, object]:
        """Report scope separately from source inventory and build outcomes."""
        return {
            "tracked_files": len(self.tracked_files),
            "semantic_files": len(self.scope.semantic_files) if self.scope else 0,
            "test_files": len(self.scope.test_files) if self.scope else 0,
            "text_files": len(self.scope.text_files) if self.scope else 0,
            "scope": None if self.scope is None else asdict(self.scope),
            "processed": {channel.value: sum(f.channel is channel and f.status is CoverageStatus.PROCESSED
                                              for f in self.files) for channel in CoverageChannel},
            "excluded_files": len({f.path for f in self.exclusions}),
            "excluded_other_files": sum(f.channel is None for f in self.exclusions),
            "excluded_by_channel": {channel.value: sum(f.channel is channel for f in self.exclusions)
                                    for channel in CoverageChannel},
            "exclusions": [asdict(f) for f in self.exclusions],
            "diagnostics": self.diagnostics,
            "failures": [asdict(f) for f in self.files if f.status is CoverageStatus.FAILED],
        }


@dataclass(frozen=True, slots=True)
class RefreshRequest:
    scope: BuildScope
    reason: str
    force: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.scope, BuildScope):
            raise TypeError("scope must be BuildScope.")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("Refresh reason must not be empty.")
        if type(self.force) is not bool:
            raise TypeError("force must be bool.")


@dataclass(frozen=True, slots=True)
class RefreshResult:
    status: RefreshStatus
    snapshot: KnowledgeSnapshot | None
    attempt: BuildAttempt | None
    coverage: RefreshCoverage
    diagnostics: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BuildContext:
    identity: SnapshotIdentity
    scope: BuildScope
    source: SourceObservation
    generation_directory: Path
    progress: Callable[[str, int, int, str | None], None] = lambda phase, current=0, total=0, file=None: None


@dataclass(frozen=True, slots=True)
class BuildOutput:
    index_path: Path
    graph_path: Path
    domain_path: Path
    graph: GraphSnapshot
    domain: DomainMap
    coverage: RefreshCoverage


class RefreshBuilder(Protocol):
    def configuration(self, workspace: RepositoryWorkspace) -> BuildConfiguration: ...

    def build(self, workspace: RepositoryWorkspace, context: BuildContext) -> BuildOutput: ...


ProviderFactory = Callable[[RepositoryWorkspace, BuildConfiguration], SemanticProvider]


@dataclass(frozen=True, slots=True)
class ProductionBuildInputs:
    """Inputs that materially affect P1/P2 bytes and therefore no-op safety."""

    clangd_executable: str = "clangd"
    compiler_executable: str | None = None
    compile_database: str | None = None
    configuration_files: tuple[str, ...] = ()
    compiler_flags: tuple[str, ...] = ()
    include_directories: tuple[str, ...] = ()
    request_timeout: float = 60.0
    text_reader_version: str = "rg-source-v1"
    scanner_policy_version: str = "p1-scanner-v1"

    def resolve(self, workspace: RepositoryWorkspace) -> BuildConfiguration:
        mapper = default_role_mapper()
        tool_records = [_tool_record(self.clangd_executable)]
        compile_sha = None
        if self.compile_database is not None:
            compile_path = workspace.resolve(self.compile_database)
            compile_sha = hash_file(compile_path)[0]
        configuration_files = tuple(sorted(set(self.configuration_files + (
            (".clangd",) if workspace.resolve(".clangd").is_file() else ()
        ))))
        configuration_hashes = tuple(
            (path, hash_file(workspace.resolve(path))[0]) for path in configuration_files
        )
        test_rules = "arkui-test-macros-v1:" + _json_sha(tuple(ARKUI_FIXTURE_TEST_MACROS))
        toolchain_sha = _json_sha(tool_records)
        payload = {
            "scope_derivation": "scanner-policy-supported-v2",
            "scanner_excluded_directories": sorted(RepositoryScanner(workspace).excluded_directories),
            "semantic_normalization": "p1-clangd-symbol-id-v4",
            "semantic_document_lifecycle": "fixed-scope-two-pass-v1",
            "max_open_documents": ClangdSemanticProvider.MAX_OPEN_DOCUMENTS,
            # Caller-supplied provenance only: this driver is never executed by
            # refresh. Its local availability is not a semantic dependency.
            "compiler_hint": self.compiler_executable,
            "toolchain_sha256": toolchain_sha,
            "compile_database_sha256": compile_sha,
            "compile_database_path": self.compile_database,
            "configuration_files": configuration_hashes,
            "compiler_flags": self.compiler_flags,
            "include_directories": self.include_directories,
            "symbol_schema": 3,
            "graph_schema": 1,
            "domain_schema": 1,
            "text_reader_version": self.text_reader_version,
            "test_rules_version": test_rules,
            "projection_version": "p1-index-v1",
            "domain_ruleset": mapper.ruleset_identity,
            "framework_rules_version": FRAMEWORK_RULESET,
            "scanner_policy_version": self.scanner_policy_version,
        }
        return BuildConfiguration(
            _json_sha(payload), toolchain_sha, 3, 1, 1,
            self.text_reader_version, test_rules, "p1-index-v1",
            mapper.ruleset_identity, FRAMEWORK_RULESET,
            self.compiler_flags, self.include_directories, compile_sha,
            self.scanner_policy_version,
        )


class P1P2RefreshBuilder:
    """Production adapter composed only from public P1/P2 build capabilities."""

    def __init__(self, inputs: ProductionBuildInputs = ProductionBuildInputs(), *,
                 provider_factory: ProviderFactory | None = None) -> None:
        self.inputs = inputs
        self._provider_factory = provider_factory

    def configuration(self, workspace: RepositoryWorkspace) -> BuildConfiguration:
        return self.inputs.resolve(workspace)

    def _provider(self, workspace: RepositoryWorkspace,
                  configuration: BuildConfiguration) -> SemanticProvider:
        if self._provider_factory is not None:
            return self._provider_factory(workspace, configuration)
        compile_directory = None
        if self.inputs.compile_database is not None:
            compile_directory = workspace.resolve(self.inputs.compile_database).parent
        fallback = configuration.compiler_flags + tuple(
            "-I" + str(workspace.resolve(directory))
            for directory in configuration.include_directories
        )
        return ClangdSemanticProvider(
            workspace, executable=self.inputs.clangd_executable,
            compilation_database_directory=compile_directory,
            fallback_flags=fallback, request_timeout=self.inputs.request_timeout,
        )

    def build(self, workspace: RepositoryWorkspace, context: BuildContext) -> BuildOutput:
        configuration = self.configuration(workspace)
        context.generation_directory.mkdir(parents=True, exist_ok=False)
        semantic_files = tuple(RepositoryFile.from_path(path) for path in sorted(set(
            context.scope.semantic_files + context.scope.test_files
        )))
        test_files = tuple(RepositoryFile.from_path(path) for path in context.scope.test_files)
        coverage: list[FileCoverage] = []
        context.progress("test_discovery", 0, len(test_files), None)
        discovered = RepositoryTestDiscoverer(workspace).discover(test_files)
        context.progress("test_discovery", len(test_files), len(test_files), None)
        coverage.extend(FileCoverage(file.path.as_posix(), CoverageChannel.TEST,
                                     CoverageStatus.PROCESSED, "P1 test discovery completed.")
                        for file in test_files)

        symbols: dict[object, Symbol] = {}
        facts: list[SymbolSemanticFacts] = []
        try:
            with self._provider(workspace, configuration) as provider:
                observer = getattr(provider, "set_progress_observer", None)
                if callable(observer):
                    observer(context.progress)
                context.progress("semantic_collect", 0, len(semantic_files), None)
                observations_method = getattr(provider, "symbol_observations_in_files", None)
                if callable(observations_method):
                    observations = list(observations_method(semantic_files))
                    context.progress("canonicalize", 0, 1, None)
                    groups = canonicalize_symbol_groups(observations)
                    collected = tuple(group.symbol for group in groups)
                else:
                    observations = []
                    for current, file in enumerate(semantic_files, 1):
                        observations.extend(SymbolObservation(symbol) for symbol in provider.symbols_in_file(file))
                        context.progress("semantic_collect", current, len(semantic_files), file.path.as_posix())
                    context.progress("canonicalize", 0, 1, None)
                    collected = tuple(group.symbol for group in canonicalize_symbol_groups(observations))
                context.progress("canonicalize", 1, 1, None)
                for symbol in collected:
                    symbols[symbol.identity] = symbol
                for file in semantic_files:
                    coverage.append(FileCoverage(file.path.as_posix(), CoverageChannel.SEMANTIC,
                                                 CoverageStatus.PROCESSED,
                                                 "Semantic provider completed; an empty symbol set is explicit."))
                context.progress("semantic_relations", 0, len(collected), None)
                for current, symbol in enumerate(collected, 1):
                    references = provider.references(symbol.identity)
                    callers = provider.callers(symbol.identity)
                    callees = provider.callees(symbol.identity)
                    for related in (*callers, *callees):
                        observations.append(SymbolObservation(related))
                    facts.append(SymbolSemanticFacts(
                        symbol.identity, references=references,
                        callers=tuple(item.identity for item in callers),
                        callees=tuple(item.identity for item in callees),
                    ))
                    context.progress("semantic_relations", current, len(collected), None)
                audit = getattr(provider, "symbol_observations", None)
                if callable(audit):
                    observations.extend(audit())
                # Retain original endpoint evidence, not just enriched scalars.
                # Write before canonicalization so genuine conflicts are auditable.
                evidence: dict[str, list[SymbolObservation]] = {}
                for observation in sorted(set(observations), key=repr):
                    evidence.setdefault(observation.symbol.identity.value, []).append(observation)
                _atomic_text(context.generation_directory / "semantic-observations.json", json.dumps([
                    {"identity": identity, "observations": [
                        {"symbol": observation.symbol.to_dict(),
                         "site": None if observation.site is None else observation.site.to_dict(),
                         "parent_kind": None if observation.parent_kind is None else observation.parent_kind.value,
                         "provenance": observation.provenance}
                        for observation in evidence[identity]]}
                    for identity in sorted(evidence)
                ], sort_keys=True))
                context.progress("canonicalize", 0, 1, None)
                groups = canonicalize_symbol_groups(observations)
                symbols = {group.symbol.identity: group.symbol for group in groups}
                context.progress("canonicalize", 1, 1, None)
        except SemanticProviderError as error:
            raise SemanticProviderError(
                f"stage=semantic; declared_count={len(semantic_files)}; "
                f"sample={[f.path.as_posix() for f in semantic_files[:3]]}; {error}"
            ) from error

        index_path = context.generation_directory / "symbol-index.sqlite3"
        indexed_files = tuple(RepositoryFile.from_path(path) for path in sorted(set(
            context.scope.semantic_files + context.scope.test_files
        )))
        with SymbolIndex(index_path) as index:
            context.progress("symbol_index", 0, 1, None)
            index.rebuild(symbols.values(), files=indexed_files, semantic_facts=facts,
                          test_fixtures=discovered.fixtures, test_cases=discovered.cases)
            context.progress("symbol_index", 1, 1, None)
            context.progress("graph_build", 0, 3, None)
            generic = project_index(index, repository_key=context.identity.repository,
                                    snapshot_key=context.identity.generation)
            context.progress("graph_build", 1, 3, None)
            domain = default_role_mapper().map(index, generic)
            context.progress("graph_build", 2, 3, None)
            extraction = extract_framework_relations(index, generic, domain, workspace)
            graph = extraction.graph
            context.progress("graph_build", 3, 3, None)
        context.progress("artifact_persistence", 0, 1, None)
        # GraphStore already isolates repository/snapshot keys under two content
        # digests. Root it at the knowledge directory to avoid exceeding legacy
        # Windows path limits by nesting those digests below the UUID directory.
        knowledge_root = context.generation_directory.parents[1]
        store = GraphStore(knowledge_root, repository_key=context.identity.repository,
                           snapshot_key=context.identity.generation)
        store.save(graph)
        domain_path = context.generation_directory / "domain.json"
        _atomic_text(domain_path, json.dumps(domain.to_dict(), ensure_ascii=True,
                                             sort_keys=True, separators=(",", ":")) + "\n")
        context.progress("artifact_persistence", 1, 1, None)
        coverage.extend(FileCoverage(path, CoverageChannel.TEXT, CoverageStatus.PROCESSED,
                                     "Revision-bound source text is available through the P1 workspace reader.")
                        for path in context.scope.text_files)
        diagnostics = tuple(sorted({
            "framework:" + item.subject.value + ":" + item.rule + ":" + item.reason
            for item in extraction.diagnostics
        }))
        return BuildOutput(index_path, store.path, domain_path, graph, domain,
                           RefreshCoverage(context.scope, context.source.tracked_files,
                                           tuple(sorted(coverage, key=lambda item: (item.path, item.channel.value))),
                                           diagnostics))


class ManifestPublisher:
    def publish(self, path: Path, manifest: KnowledgeManifest) -> None:
        _atomic_text(path, dumps(manifest))


class WriterConflictError(RuntimeError):
    pass


class _WriterLease:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._owned = False

    def __enter__(self) -> _WriterLease:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as error:
            raise WriterConflictError(f"Refresh writer already owns {self.path}.") from error
        self._owned = True
        try:
            try:
                os.write(descriptor, (str(os.getpid()) + "\n").encode("ascii"))
            finally:
                os.close(descriptor)
        except BaseException:
            self.__exit__()
            raise
        return self

    def __exit__(self, *exc: object) -> None:
        if self._owned:
            self.path.unlink(missing_ok=True)
            self._owned = False


class KnowledgeRefreshService:
    """The shared one-shot entry point for manual and future scheduler callers."""

    def __init__(self, source_root: str | Path, knowledge_root: str | Path, *,
                 repository: str, builder: RefreshBuilder | None = None,
                 publisher: ManifestPublisher | None = None,
                 producer: str = "arkui-agent-p3-f-v1") -> None:
        self.source = GitSourceReader(source_root, repository=repository)
        self.root = Path(knowledge_root).expanduser().resolve()
        if self.root == self.source.workspace.root or self.root.is_relative_to(self.source.workspace.root):
            raise ValueError("Knowledge root must be outside the read-only target repository.")
        self.manifest_path = self.root / "manifest.json"
        self.repository = repository
        self.builder = builder or P1P2RefreshBuilder()
        self.publisher = publisher or ManifestPublisher()
        self.producer = producer

    def refresh(self, request: RefreshRequest) -> RefreshResult:
        if not isinstance(request, RefreshRequest):
            raise TypeError("refresh requires RefreshRequest.")
        empty = RefreshCoverage(None, (), ())
        try:
            lease = _WriterLease(self.root / ".refresh.lock")
            with defer_keyboard_interrupt():
                lease.__enter__()
        except KeyboardInterrupt:
            with defer_keyboard_interrupt(reraise=False):
                lease.__exit__()
            return RefreshResult(RefreshStatus.CANCELLED, None, None, empty, ("Build cancelled by user before attempt start",))
        except (OSError, WriterConflictError) as error:
            return RefreshResult(RefreshStatus.CONFLICT, None, None, empty, (str(error),))
        try:
            try:
                return self._refresh_locked(request)
            except (ManifestError, OSError, SourceReadError, UnicodeError) as error:
                return RefreshResult(RefreshStatus.FAILED, None, None, empty, (str(error),))
        finally:
            with defer_keyboard_interrupt(reraise=False):
                lease.__exit__(None, None, None)

    def _refresh_locked(self, request: RefreshRequest) -> RefreshResult:
        manifest = self._load_manifest()
        initial = SourceObservation(self.repository, None, False, SourceFingerprint(()), (), ())
        identity = SnapshotIdentity("snapshot-" + uuid.uuid4().hex,
                                    "generation-" + uuid.uuid4().hex,
                                    self.repository, None)
        started = _now()
        attempt = BuildAttempt("attempt-" + uuid.uuid4().hex, identity, BuildStatus.BUILDING,
                               request.reason, started, None, None)
        exclusions: tuple[PolicyExclusion, ...] = ()
        progress = RefreshProgress(self.root / "progress.json", attempt.attempt_id, identity.generation)
        def finish(result: RefreshResult) -> RefreshResult:
            status = "succeeded" if result.status is RefreshStatus.PUBLISHED else result.status.value
            progress.finish(status)
            if progress.diagnostic:
                return replace(result, diagnostics=result.diagnostics + (progress.diagnostic,))
            return result
        try:
            progress.update("source_inventory")
            initial = self.source.observe(())
            identity = replace(identity, revision=initial.revision)
            attempt = replace(attempt, target=identity)
            if initial.revision is None:
                raise SourceReadError("Git HEAD has no commit.")
            if initial.dirty:
                raise SourceReadError("Target repository is dirty; refresh never modifies or snapshots it.")
            exclusions = self._policy_exclusions(initial)
            scope, inventory, scope_diagnostics = self._resolve_scope(request.scope, initial, exclusions)
            progress.update("source_inventory", 0, len(inventory))
            observed = self.source.observe(inventory, progress=progress.update)
            if observed.revision != initial.revision or observed.dirty:
                raise SourceReadError("Git revision/status drifted before the build started.")
            configuration = self.builder.configuration(self.source.workspace)
            requirement = QueryRequirement(self.repository, observed.revision, scope, configuration)
            if not request.force and manifest.last_usable is not None:
                reader = PrebuiltSnapshotReader(self.manifest_path, artifact_root=self.root, source=self.source)
                freshness = reader.inspect(requirement)
                if freshness.can_bind:
                    coverage = RefreshCoverage(scope, observed.tracked_files, (), scope_diagnostics, exclusions)
                    progress.attempt_id = manifest.latest_attempt.attempt_id
                    progress.generation = manifest.last_usable.identity.generation
                    return finish(RefreshResult(RefreshStatus.NO_OP, manifest.last_usable,
                                         manifest.latest_attempt, coverage, ("Compatible fresh generation already exists.",)))
            self.publisher.publish(self.manifest_path, KnowledgeManifest(manifest.last_usable, attempt))
            output = self.builder.build(self.source.workspace, BuildContext(
                identity, scope, observed, self.root / "generations" / identity.generation, progress.update
            ))
            coverage = RefreshCoverage(output.coverage.scope, output.coverage.tracked_files,
                                       output.coverage.files,
                                       tuple(sorted(set(scope_diagnostics + output.coverage.diagnostics))), exclusions)
            _atomic_json(self.root / "generations" / identity.generation / "coverage.json",
                         coverage.to_dict())
            snapshot = self._snapshot(identity, attempt, scope, observed, configuration, output)
            progress.update("artifact_validation", 0, 1)
            artifact_issues = PrebuiltArtifactReader(self.root).observe(snapshot).diagnostics
            if artifact_issues:
                raise ValueError("Built artifacts failed public validation: " + "; ".join(
                    item.reason.value + ":" + item.detail for item in artifact_issues
                ))
            progress.update("artifact_validation", 1, 1)
            progress.update("source_inventory", 0, len(inventory))
            before_publication = self.source.observe(inventory, progress=progress.update)
            if before_publication != observed:
                raise SourceReadError(
                    "Git revision, dirty state, tracked inventory, or source fingerprint drifted during rebuild."
                )
            if self.builder.configuration(self.source.workspace) != configuration:
                raise SourceReadError("Build configuration/toolchain/rules changed during rebuild.")
            finished = _now()
            snapshot = KnowledgeSnapshot(
                snapshot.identity, snapshot.scope, snapshot.source, snapshot.configuration,
                snapshot.artifacts, SnapshotBuild(attempt.attempt_id, BuildStatus.SUCCEEDED,
                                                  finished, self.producer,
                                                  ProvenanceStatus.VERIFIED_BUILD,
                                                  observed.fingerprint.sha256),
            )
            succeeded = BuildAttempt(attempt.attempt_id, identity, BuildStatus.SUCCEEDED,
                                     request.reason, started, finished, None)
            progress.update("publish", 0, 1)
            self.publisher.publish(self.manifest_path, KnowledgeManifest(snapshot, succeeded))
            progress.update("publish", 1, 1)
            return finish(RefreshResult(RefreshStatus.PUBLISHED, snapshot, succeeded, coverage, ()))
        except KeyboardInterrupt as cancellation:
            with defer_keyboard_interrupt(reraise=False):
                # os.replace is the publication commit point. A signal delivered
                # immediately after it must not roll back an already usable build.
                try:
                    committed = self._load_manifest()
                except (ManifestError, OSError) as error:
                    cancellation.add_note("Unable to inspect publication during cancellation: " + str(error)[:300])
                    committed = manifest
                if (committed.latest_attempt is not None
                        and committed.latest_attempt.attempt_id == attempt.attempt_id
                        and committed.latest_attempt.status is BuildStatus.SUCCEEDED):
                    progress.update("publish", 1, 1)
                    return finish(RefreshResult(RefreshStatus.PUBLISHED, committed.last_usable,
                                  committed.latest_attempt, coverage, ("Cancellation arrived after publication.",)))
                detail = "Build cancelled by user"
                notes = getattr(cancellation, "__notes__", ())
                if notes:
                    detail += "; cleanup: " + "; ".join(str(note)[:300] for note in notes[:3])
                return finish(self._record_failure(manifest, attempt, detail,
                              locals().get("output"), locals().get("scope"), initial, exclusions,
                              cancelled=True))
        except (GraphStorageError, ManifestError, OSError, SemanticProviderError, SourceReadError,
                SymbolIndexError, TestDiscoveryError, ValueError) as error:
            with defer_keyboard_interrupt(reraise=False):
                return finish(self._record_failure(manifest, attempt, str(error),
                                        locals().get("output", None),
                                        locals().get("scope", None), initial, exclusions))

    def _load_manifest(self) -> KnowledgeManifest:
        try:
            value = loads(self.manifest_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return KnowledgeManifest(None, None)
        if not isinstance(value, KnowledgeManifest):
            raise ManifestError("Knowledge root manifest is not a KnowledgeManifest.")
        return value

    def _policy_exclusions(self, initial: SourceObservation) -> tuple[PolicyExclusion, ...]:
        scanner = RepositoryScanner(self.source.workspace)
        exclusions = []
        for path in sorted(initial.tracked_files):
            file = RepositoryFile.from_path(path)
            directory = scanner.excluded_directory(file)
            if directory is None:
                continue
            kind = classify_repository_path(file.path)
            channel = None
            if kind is RepositoryFileType.TEST:
                channel = CoverageChannel.TEST
            elif kind in (RepositoryFileType.SOURCE, RepositoryFileType.HEADER):
                channel = CoverageChannel.SEMANTIC
            exclusions.append(PolicyExclusion(path, channel,
                                              f"RepositoryScanner excluded directory: {directory}"))
        return tuple(exclusions)

    def _resolve_scope(self, requested: BuildScope, initial: SourceObservation,
                       exclusions: tuple[PolicyExclusion, ...]) -> tuple[
        BuildScope, tuple[str, ...], tuple[str, ...]
    ]:
        tracked = set(initial.tracked_files)
        scanner = RepositoryScanner(self.source.workspace)
        excluded_paths = {item.path for item in exclusions}
        if requested.kind is ScopeKind.SELECTED_FILES:
            wanted = set(requested.files)
            if not wanted.issubset(tracked):
                raise ValueError("Selected scope contains paths not tracked by the current Git revision: "
                                 + ", ".join(sorted(wanted - tracked)))
            if wanted & excluded_paths:
                raise ValueError("Selected scope requests unsupported-by-policy paths: "
                                 + ", ".join(sorted(wanted & excluded_paths)))
            scanned = {item.path.as_posix() for item in scanner.scan(include_patterns=tuple(sorted(wanted)))}
            if scanned != wanted:
                raise ValueError("Scanner could not cover selected files: " + ", ".join(sorted(wanted - scanned)))
            diagnostics = (
                "Selected knowledge scope remains channel-limited; its source fingerprint conservatively covers "
                "the complete Git tracked inventory for semantic/framework build dependencies.",
            )
            return requested, tuple(sorted(tracked)), diagnostics
        classified = {
            path: classify_repository_path(RepositoryFile.from_path(path).path)
            for path in tracked - excluded_paths
        }
        semantic_types = {RepositoryFileType.SOURCE, RepositoryFileType.HEADER, RepositoryFileType.TEST}
        supported = {path for path, kind in classified.items() if kind in semantic_types}
        expected = tracked - excluded_paths
        scanned = {item.path.as_posix() for item in scanner.scan()} & tracked
        if scanned != expected:
            missing = tuple(sorted(expected - scanned))
            unexpected = tuple(sorted(scanned - expected))
            raise ValueError("Full-repository scanner coverage mismatch; missing=" + repr(missing)
                             + ", unexpected=" + repr(unexpected))
        tests = tuple(sorted(path for path in supported if classified[path] is RepositoryFileType.TEST))
        semantic = tuple(sorted(supported - set(tests)))
        scope = BuildScope(ScopeKind.FULL_REPOSITORY, semantic, tests, tuple(sorted(tracked)))
        diagnostics = (f"Full scope: tracked={len(tracked)}, supported semantic={len(semantic)}, "
                       f"test={len(tests)}, text={len(tracked)}, scanner-excluded-by-policy={len(excluded_paths)}. "
                       "All tracked paths remain source fingerprint inputs, including exclusions.",)
        return scope, tuple(sorted(tracked)), diagnostics

    def _snapshot(self, identity: SnapshotIdentity, attempt: BuildAttempt, scope: BuildScope,
                  source: SourceObservation, configuration: BuildConfiguration,
                  output: BuildOutput) -> KnowledgeSnapshot:
        def artifact(kind: ArtifactKind, path: Path, version: int) -> ArtifactReference:
            checksum = hash_file(path)[0]
            relative = path.resolve().relative_to(self.root).as_posix()
            key = output.graph.snapshot_key if kind is ArtifactKind.GRAPH else "sha256:" + checksum
            return ArtifactReference(kind, key, identity, relative, checksum, version)

        artifacts = KnowledgeArtifacts(
            artifact(ArtifactKind.SYMBOL, output.index_path, configuration.symbol_schema),
            artifact(ArtifactKind.TEST, output.index_path, configuration.symbol_schema),
            artifact(ArtifactKind.GRAPH, output.graph_path, configuration.graph_schema),
            artifact(ArtifactKind.DOMAIN, output.domain_path, configuration.domain_schema),
            TextKnowledge("sha256:" + source.fingerprint.sha256, identity,
                          source.fingerprint.sha256, configuration.text_reader_version),
        )
        return KnowledgeSnapshot(
            identity, scope, source.fingerprint, configuration, artifacts,
            SnapshotBuild(attempt.attempt_id, BuildStatus.SUCCEEDED, attempt.started_at,
                          self.producer, ProvenanceStatus.VERIFIED_BUILD,
                          source.fingerprint.sha256),
        )

    def _prebuild_failure(self, manifest: KnowledgeManifest, request: RefreshRequest,
                          source: SourceObservation, failure: str) -> RefreshResult:
        identity = SnapshotIdentity("snapshot-" + uuid.uuid4().hex,
                                    "generation-" + uuid.uuid4().hex,
                                    self.repository, source.revision)
        started = _now()
        building = BuildAttempt("attempt-" + uuid.uuid4().hex, identity, BuildStatus.BUILDING,
                                request.reason, started, None, None)
        return self._record_failure(manifest, building, failure, None, None, source)

    def _record_failure(self, manifest: KnowledgeManifest, attempt: BuildAttempt, failure: str,
                        output: BuildOutput | None, scope: BuildScope | None,
                        source: SourceObservation, exclusions: tuple[PolicyExclusion, ...] = (), *,
                        cancelled: bool = False) -> RefreshResult:
        finished = _now()
        report_directory = self.root / "generations" / attempt.target.generation
        full_failure = failure
        failure = _bounded(failure, 4096)
        failure += f"; report=generations/{attempt.target.generation}/coverage.json"
        failed = BuildAttempt(attempt.attempt_id, attempt.target,
                              BuildStatus.CANCELLED if cancelled else BuildStatus.FAILED,
                              attempt.reason, attempt.started_at, finished,
                              failure or "Refresh failed without diagnostic text.")
        diagnostics = [failed.failure]
        try:
            self.publisher.publish(self.manifest_path, KnowledgeManifest(manifest.last_usable, failed))
        except (ManifestError, OSError, ValueError) as publication_error:
            diagnostics.append("Unable to publish failed latest_attempt: " + str(publication_error))
        if output is not None:
            coverage = RefreshCoverage(output.coverage.scope, output.coverage.tracked_files,
                                       output.coverage.files, output.coverage.diagnostics, exclusions)
        else:
            failed_files: list[FileCoverage] = []
            if scope is not None:
                for channel, paths in ((CoverageChannel.SEMANTIC, scope.semantic_files),
                                       (CoverageChannel.TEST, scope.test_files),
                                       (CoverageChannel.TEXT, scope.text_files)):
                    failed_files.extend(FileCoverage(
                        path, channel, CoverageStatus.FAILED,
                        "Generation did not complete; per-file coverage is not claimed. See failure.json.",
                    ) for path in paths)
            coverage = RefreshCoverage(scope, source.tracked_files,
                                       tuple(sorted(failed_files, key=lambda item: (item.path, item.channel.value))),
                                       (failure,), exclusions)
        try:
            _atomic_json(report_directory / "failure.json", {"failure": full_failure})
            _atomic_json(report_directory / "orphan.json", {
                "attempt_id": attempt.attempt_id, "generation": attempt.target.generation,
                "status": failed.status.value, "usable": False,
                "reason": "Unpublished generation; never read or reused by refresh; no automatic GC.",
            })
            _atomic_json(report_directory / "coverage.json", coverage.to_dict())
        except (OSError, ValueError) as report_error:
            diagnostics.append("Unable to write failure report: " + _bounded(str(report_error), 500))
        return RefreshResult(RefreshStatus.CANCELLED if cancelled else RefreshStatus.FAILED, manifest.last_usable, failed,
                             coverage, tuple(diagnostics))


def _bounded(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    half = (limit - 40) // 2
    return value[:half] + " ... [truncated; see report] ... " + value[-half:]


def _atomic_json(path: Path, value: object) -> None:
    """Stream full audit output without a second repository-sized JSON string."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                prefix=".report-", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_sha(value: object) -> str:
    data = json.dumps(value, ensure_ascii=True, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _tool_record(executable: str) -> dict[str, str]:
    path = shutil.which(executable)
    if path is None:
        raise ValueError(f"Build tool is unavailable: {executable!r}")
    resolved = Path(path).resolve()
    try:
        result = subprocess.run((str(resolved), "--version"), capture_output=True,
                                timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValueError(f"Unable to inspect build tool: {executable!r}") from error
    if result.returncode != 0:
        raise ValueError(f"Build tool --version failed: {executable!r}")
    return {"requested": executable, "path": str(resolved),
            "binary_sha256": hash_file(resolved)[0],
            "version_sha256": hashlib.sha256(result.stdout + result.stderr).hexdigest()}


def _atomic_text(path: Path, text: str) -> None:
    temporary: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                                dir=path.parent, suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
