"""Prebuilt artifact validation and generation-pinned read sessions."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterator

from arkui_agent.graph.domain import DomainMap
from arkui_agent.graph.domain_storage import DomainStorageError, read_domain_map
from arkui_agent.graph.projection import GraphSnapshot
from arkui_agent.graph.storage import GraphStore, GraphStorageError
from arkui_agent.repository.index import SymbolIndex, SymbolIndexError
from arkui_agent.repository.workspace import RepositoryWorkspace

from .freshness import evaluate_freshness
from .model import (
    ArtifactKind, BindingReference, Coverage, Freshness, FreshnessResult, KnowledgeDiagnostic,
    KnowledgeManifest, KnowledgeSnapshot, ManifestError, QueryRequirement, Reason,
)
from .serialization import loads
from .source import FileStamp, GitSourceReader, SourceObservation, SourceReadError, hash_file


class SnapshotReadError(RuntimeError):
    def __init__(self, result: FreshnessResult) -> None:
        self.result = result
        super().__init__("; ".join(item.reason.value + ": " + item.detail for item in result.diagnostics))


@dataclass(frozen=True, slots=True)
class ArtifactObservation:
    index_path: Path | None
    graph: GraphSnapshot | None
    domain: DomainMap | None
    stamps: tuple[FileStamp, ...]
    diagnostics: tuple[KnowledgeDiagnostic, ...]


class PrebuiltArtifactReader:
    """Only public P1/P2 readers; never SQL queries, schema creation or rebuilding."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()

    def observe(self, snapshot: KnowledgeSnapshot) -> ArtifactObservation:
        stamps: list[FileStamp] = []
        issues: list[KnowledgeDiagnostic] = []
        paths: dict[ArtifactKind, Path] = {}
        graph = None
        domain = None
        for artifact in snapshot.artifacts.files:
            try:
                path = (self.root / artifact.path).resolve()
                if not path.is_relative_to(self.root):
                    raise OSError("Artifact path escapes the supplied root.")
                checksum, current_stamp = hash_file(path)
                if checksum != artifact.sha256:
                    issues.append(KnowledgeDiagnostic(Reason.ARTIFACT_MISMATCH, "Artifact SHA-256 mismatch.", artifact.kind))
                else:
                    paths[artifact.kind] = path
                    stamps.append(current_stamp)
            except (OSError, SourceReadError) as error:
                issues.append(KnowledgeDiagnostic(Reason.ARTIFACT_UNAVAILABLE, str(error), artifact.kind))
        if not issues:
            try:
                config = snapshot.configuration
                if (config.symbol_schema, config.graph_schema, config.domain_schema, config.projection_version) != (
                    3, 1, 1, "p1-index-v1"
                ):
                    raise ValueError("Unsupported prebuilt schema/projection versions.")
                with SymbolIndex.open_read_only(paths[ArtifactKind.SYMBOL]) as index:
                    indexed = {file.path.as_posix() for file in index.files()}
                    if not set(snapshot.scope.semantic_files + snapshot.scope.test_files).issubset(indexed):
                        raise ValueError("P1 file inventory does not cover declared semantic/test scope.")
                # Test artifacts must alias the same physical P1 database as symbols.
                if paths[ArtifactKind.TEST] != paths[ArtifactKind.SYMBOL]:
                    raise ValueError("P1 test and symbol files differ.")
                graph = GraphStore.read_file(paths[ArtifactKind.GRAPH],
                                             repository_key=snapshot.identity.repository,
                                             snapshot_key=snapshot.artifacts.graph.identity)
                domain = read_domain_map(paths[ArtifactKind.DOMAIN], repository_key=snapshot.identity.repository,
                                         snapshot_key=graph.snapshot_key, ruleset_identity=config.domain_ruleset)
                # Recheck after format readers, including races during open/decode.
                for artifact in snapshot.artifacts.files:
                    checksum, current_stamp = hash_file(paths[artifact.kind])
                    if checksum != artifact.sha256 or current_stamp not in stamps:
                        raise ValueError("Artifact changed during validation.")
            except (SymbolIndexError, GraphStorageError, DomainStorageError, ValueError, OSError, SourceReadError) as error:
                issues.append(KnowledgeDiagnostic(Reason.ARTIFACT_INVALID, str(error)))
        return ArtifactObservation(paths.get(ArtifactKind.SYMBOL), graph, domain, tuple(stamps), tuple(issues))


def _unavailable(reason: Reason, detail: str) -> FreshnessResult:
    return FreshnessResult(Freshness.UNKNOWN, Freshness.UNKNOWN, Coverage.UNKNOWN, None, None,
                           (KnowledgeDiagnostic(reason, detail),))


class PrebuiltSnapshotReader:
    def __init__(self, manifest_path: str | Path, *, artifact_root: str | Path, source: GitSourceReader) -> None:
        self.manifest_path = Path(manifest_path)
        self.artifacts = PrebuiltArtifactReader(artifact_root)
        self.source = source

    def _load(self) -> KnowledgeManifest:
        try:
            # Hash/stat around loading so a replaced manifest cannot be silently mixed.
            before = hash_file(self.manifest_path)
            value = loads(self.manifest_path.read_text(encoding="utf-8"))
            if not isinstance(value, KnowledgeManifest):
                raise ManifestError("Expected KnowledgeManifest root.")
            if before != hash_file(self.manifest_path):
                raise ManifestError("Manifest changed while reading.")
            return value
        except FileNotFoundError as error:
            raise SnapshotReadError(_unavailable(Reason.MANIFEST_MISSING, str(error))) from error
        except (OSError, UnicodeError, ManifestError, SourceReadError) as error:
            raise SnapshotReadError(_unavailable(Reason.MANIFEST_CORRUPT, str(error))) from error

    def _check(self, manifest: KnowledgeManifest, requirement: QueryRequirement) -> tuple[
        FreshnessResult, SourceObservation | None, ArtifactObservation | None
    ]:
        snapshot = manifest.last_usable
        if snapshot is None:
            return evaluate_freshness(manifest, requirement, None), None, None
        source = None
        issues: tuple[KnowledgeDiagnostic, ...] = ()
        try:
            source = self.source.observe(tuple(item.path for item in snapshot.source.files))
        except SourceReadError as error:
            issues = (KnowledgeDiagnostic(Reason.SOURCE_UNAVAILABLE, str(error)),)
        artifacts = self.artifacts.observe(snapshot)
        if source is not None:
            try:
                if source != self.source.observe(tuple(item.path for item in snapshot.source.files)):
                    issues += (KnowledgeDiagnostic(Reason.SOURCE_DRIFT, "Source changed while validating artifacts."),)
            except SourceReadError as error:
                issues += (KnowledgeDiagnostic(Reason.SOURCE_UNAVAILABLE, str(error)),)
        result = evaluate_freshness(manifest, requirement, source, issues + artifacts.diagnostics)
        return result, source, artifacts

    def inspect(self, requirement: QueryRequirement) -> FreshnessResult:
        try:
            manifest = self._load()
        except SnapshotReadError as error:
            return error.result
        return self._check(manifest, requirement)[0]

    def bind(self, requirement: QueryRequirement) -> SnapshotSession:
        manifest = self._load()
        result, source, artifacts = self._check(manifest, requirement)
        if not result.can_bind:
            raise SnapshotReadError(result)
        assert manifest.last_usable is not None and source is not None and artifacts is not None
        return SnapshotSession(self, manifest, requirement, BindingReference(manifest.last_usable, result), source, artifacts)


@dataclass(frozen=True, slots=True)
class BoundKnowledge:
    reference: BindingReference
    index: SymbolIndex
    graph: GraphSnapshot
    domain: DomainMap
    workspace: RepositoryWorkspace


class SnapshotSession:
    """Single-threaded guarded reads of one generation. No latest lookup after binding."""

    def __init__(self, reader: PrebuiltSnapshotReader, manifest: KnowledgeManifest, requirement: QueryRequirement,
                 reference: BindingReference, source: SourceObservation, artifacts: ArtifactObservation) -> None:
        self._reader = reader
        self._manifest = manifest
        self._requirement = requirement
        self._reference = reference
        self._source = source
        self._artifacts = artifacts
        self._closed = False

    @property
    def reference(self) -> BindingReference:
        return self._reference

    def close(self) -> None:
        self._closed = True

    def validate(self) -> FreshnessResult:
        if self._closed:
            raise SnapshotReadError(_unavailable(Reason.SESSION_CLOSED, "Session is closed or invalidated."))
        result, source, artifacts = self._reader._check(self._manifest, self._requirement)
        drift = (source != self._source or artifacts is None or artifacts.stamps != self._artifacts.stamps)
        if not result.can_bind or drift:
            self._closed = True
            result = replace(result, state=Freshness.UNKNOWN if drift else result.state,
                             snapshot_state=Freshness.UNKNOWN if drift else result.snapshot_state,
                             diagnostics=result.diagnostics + (KnowledgeDiagnostic(
                                 Reason.BINDING_DRIFT, "Pinned source/artifact observation changed; session invalidated."),))
            raise SnapshotReadError(result)
        return result

    @contextmanager
    def read(self) -> Iterator[BoundKnowledge]:
        self.validate()
        assert self._artifacts.index_path is not None and self._artifacts.graph is not None and self._artifacts.domain is not None
        try:
            index = SymbolIndex.open_read_only(self._artifacts.index_path)
        except SymbolIndexError as error:
            self._closed = True
            raise SnapshotReadError(replace(self.reference.freshness, state=Freshness.UNKNOWN,
                                           snapshot_state=Freshness.UNKNOWN,
                                           diagnostics=(KnowledgeDiagnostic(Reason.ARTIFACT_INVALID, str(error)),))) from error
        try:
            yield BoundKnowledge(self.reference, index, self._artifacts.graph, self._artifacts.domain,
                                 self._reader.source.workspace)
        finally:
            index.close()
            self.validate()

    def __enter__(self) -> SnapshotSession:
        self.validate()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
