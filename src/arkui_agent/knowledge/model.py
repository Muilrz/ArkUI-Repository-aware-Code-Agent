"""Typed repository knowledge read contracts, independent of retrieval."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from types import UnionType
from typing import get_args, get_origin, get_type_hints

from arkui_agent.repository.model import RepositoryFile


class ManifestError(ValueError):
    """Malformed knowledge contract; never a usable empty snapshot."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ManifestError(message)


def _matches(value: object, annotation: object) -> bool:
    if get_origin(annotation) is UnionType:
        return any(_matches(value, choice) for choice in get_args(annotation))
    if get_origin(annotation) is tuple:
        return type(value) is tuple and all(_matches(item, get_args(annotation)[0]) for item in value)
    return type(value) is annotation


class Model:
    __slots__ = ()

    def __post_init__(self) -> None:
        for name, annotation in get_type_hints(type(self)).items():
            value = getattr(self, name)
            require(_matches(value, annotation), f"Invalid field type: {name}")
            if type(value) is str:
                require(bool(value.strip()), f"Empty field: {name}")
        self.validate()

    def validate(self) -> None:
        pass


def digest(value: str) -> None:
    require(re.fullmatch(r"[0-9a-f]{64}", value) is not None, "Expected lowercase SHA-256.")


def relative_path(value: str) -> None:
    try:
        RepositoryFile.from_path(value)
    except ValueError as error:
        raise ManifestError(str(error)) from error
    require(not any(ord(char) < 32 for char in value), "Control character in path.")


def timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ManifestError("Invalid ISO-8601 timestamp.") from error
    require(parsed.tzinfo is not None and parsed.utcoffset() is not None, "Timestamp needs timezone.")
    return parsed


class ScopeKind(str, Enum):
    SELECTED_FILES = "selected_files"
    FULL_REPOSITORY = "full_repository"


@dataclass(frozen=True, slots=True)
class BuildScope(Model):
    kind: ScopeKind
    semantic_files: tuple[str, ...]
    test_files: tuple[str, ...]
    text_files: tuple[str, ...]

    def validate(self) -> None:
        for paths in (self.semantic_files, self.test_files, self.text_files):
            require(paths == tuple(sorted(set(paths))), "Scope files must be sorted and unique.")
            for path in paths:
                relative_path(path)

    @property
    def files(self) -> tuple[str, ...]:
        return tuple(sorted(set(self.semantic_files + self.test_files + self.text_files)))

    def covers(self, requested: BuildScope) -> bool:
        if requested.kind is ScopeKind.FULL_REPOSITORY and self.kind is not ScopeKind.FULL_REPOSITORY:
            return False
        return all(set(wanted).issubset(actual) for wanted, actual in (
            (requested.semantic_files, self.semantic_files),
            (requested.test_files, self.test_files), (requested.text_files, self.text_files),
        ))


@dataclass(frozen=True, slots=True)
class FileHash(Model):
    path: str
    sha256: str

    def validate(self) -> None:
        relative_path(self.path)
        digest(self.sha256)


@dataclass(frozen=True, slots=True)
class SourceFingerprint(Model):
    files: tuple[FileHash, ...]

    def validate(self) -> None:
        names = tuple(item.path for item in self.files)
        require(names == tuple(sorted(set(names))), "Source inventory must be sorted and unique.")

    @property
    def sha256(self) -> str:
        content = json.dumps([(item.path, item.sha256) for item in self.files],
                             ensure_ascii=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(content).hexdigest()


@dataclass(frozen=True, slots=True)
class SnapshotIdentity(Model):
    snapshot_id: str
    generation: str
    repository: str
    revision: str | None

    def validate(self) -> None:
        require(self.revision is None or re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", self.revision) is not None,
                "Revision must be a full Git commit ID or explicit null.")


@dataclass(frozen=True, slots=True)
class BuildConfiguration(Model):
    configuration_sha256: str
    toolchain_sha256: str
    symbol_schema: int
    graph_schema: int
    domain_schema: int
    text_reader_version: str
    test_rules_version: str
    projection_version: str
    domain_ruleset: str
    framework_rules_version: str
    compiler_flags: tuple[str, ...] = ()
    include_directories: tuple[str, ...] = ()
    compile_database_sha256: str | None = None
    scanner_policy_version: str = "p1-scanner-v1"

    def validate(self) -> None:
        digest(self.configuration_sha256)
        digest(self.toolchain_sha256)
        require(min(self.symbol_schema, self.graph_schema, self.domain_schema) > 0, "Invalid schema version.")
        require(all(flag.strip() for flag in self.compiler_flags), "Empty compiler flag.")
        for directory in self.include_directories:
            if directory != ".":
                relative_path(directory)
        if self.compile_database_sha256 is not None:
            digest(self.compile_database_sha256)


class ArtifactKind(str, Enum):
    SYMBOL = "symbol"
    TEST = "test"
    GRAPH = "graph"
    DOMAIN = "domain"


@dataclass(frozen=True, slots=True)
class ArtifactReference(Model):
    kind: ArtifactKind
    identity: str
    snapshot: SnapshotIdentity
    path: str
    sha256: str
    schema_version: int

    def validate(self) -> None:
        relative_path(self.path)
        digest(self.sha256)
        require(self.schema_version > 0, "Invalid artifact schema version.")
        if self.kind is not ArtifactKind.GRAPH:
            require(self.identity == "sha256:" + self.sha256,
                    "P1/domain artifact identity must be its content digest; legacy files have no embedded identity.")


@dataclass(frozen=True, slots=True)
class TextKnowledge(Model):
    identity: str
    snapshot: SnapshotIdentity
    source_sha256: str
    reader_version: str

    def validate(self) -> None:
        digest(self.source_sha256)
        require(self.identity == "sha256:" + self.source_sha256, "Text identity must name the source inventory digest.")


@dataclass(frozen=True, slots=True)
class KnowledgeArtifacts(Model):
    symbols: ArtifactReference
    tests: ArtifactReference
    graph: ArtifactReference
    domain: ArtifactReference
    text: TextKnowledge

    def validate(self) -> None:
        require(tuple(item.kind for item in self.files) == tuple(ArtifactKind), "Wrong artifact role.")

    @property
    def files(self) -> tuple[ArtifactReference, ...]:
        return self.symbols, self.tests, self.graph, self.domain


class BuildStatus(str, Enum):
    SUCCEEDED = "succeeded"
    BUILDING = "building"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ProvenanceStatus(str, Enum):
    VERIFIED_BUILD = "verified_build"
    UNVERIFIED = "unverified"


@dataclass(frozen=True, slots=True)
class SnapshotBuild(Model):
    attempt_id: str
    status: BuildStatus
    built_at: str
    producer: str
    provenance: ProvenanceStatus
    source_sha256: str

    def validate(self) -> None:
        timestamp(self.built_at)
        digest(self.source_sha256)


@dataclass(frozen=True, slots=True)
class KnowledgeSnapshot(Model):
    identity: SnapshotIdentity
    scope: BuildScope
    source: SourceFingerprint
    configuration: BuildConfiguration
    artifacts: KnowledgeArtifacts
    build: SnapshotBuild

    def validate(self) -> None:
        require(set(self.scope.files).issubset(item.path for item in self.source.files),
                "Source fingerprint must cover every declared scope file.")


@dataclass(frozen=True, slots=True)
class BuildAttempt(Model):
    attempt_id: str
    target: SnapshotIdentity
    status: BuildStatus
    reason: str
    started_at: str
    finished_at: str | None
    failure: str | None

    def validate(self) -> None:
        start = timestamp(self.started_at)
        if self.status is BuildStatus.BUILDING:
            require(self.finished_at is None and self.failure is None, "Building attempt cannot be finished.")
        else:
            require(self.finished_at is not None and timestamp(self.finished_at) >= start, "Invalid finish time.")
            require((self.failure is not None) == (self.status in (BuildStatus.FAILED, BuildStatus.CANCELLED)), "Invalid failure metadata.")


@dataclass(frozen=True, slots=True)
class KnowledgeManifest(Model):
    last_usable: KnowledgeSnapshot | None
    latest_attempt: BuildAttempt | None

    def validate(self) -> None:
        if self.last_usable is not None:
            require(self.last_usable.build.status is BuildStatus.SUCCEEDED, "Unsuccessful build cannot be last usable.")
        if self.last_usable is not None and self.latest_attempt is not None:
            snapshot, attempt = self.last_usable, self.latest_attempt
            require(snapshot.identity.repository == attempt.target.repository, "Attempt repository mismatch.")
            if attempt.status is BuildStatus.SUCCEEDED:
                require(attempt.target == snapshot.identity and attempt.attempt_id == snapshot.build.attempt_id,
                        "Successful latest attempt must identify last usable generation.")
                require(timestamp(attempt.started_at) <= timestamp(snapshot.build.built_at)
                        <= timestamp(attempt.finished_at), "Build time must belong to its successful attempt.")
            else:
                require(attempt.target.generation != snapshot.identity.generation,
                        "New attempts must not overwrite last usable generation.")
        if self.latest_attempt is not None and self.latest_attempt.status is BuildStatus.SUCCEEDED:
            require(self.last_usable is not None, "Successful publication needs last usable snapshot.")


class Freshness(str, Enum):
    FRESH = "fresh"
    STALE = "stale"
    BUILDING = "building"
    FAILED = "failed"
    UNKNOWN = "unknown"


class Coverage(str, Enum):
    SUFFICIENT = "sufficient"
    INSUFFICIENT = "insufficient"
    UNKNOWN = "unknown"


class Reason(str, Enum):
    MANIFEST_MISSING = "manifest_missing"
    MANIFEST_CORRUPT = "manifest_corrupt"
    NO_USABLE_SNAPSHOT = "no_usable_snapshot"
    UNVERIFIED_PROVENANCE = "unverified_provenance"
    UNKNOWN_REVISION = "unknown_revision"
    REPOSITORY_MISMATCH = "repository_mismatch"
    REVISION_MISMATCH = "revision_mismatch"
    DIRTY_WORKSPACE = "dirty_workspace"
    SOURCE_DRIFT = "source_drift"
    SOURCE_UNAVAILABLE = "source_unavailable"
    ARTIFACT_GENERATION_MISMATCH = "artifact_generation_mismatch"
    ARTIFACT_MISMATCH = "artifact_mismatch"
    ARTIFACT_UNAVAILABLE = "artifact_unavailable"
    ARTIFACT_INVALID = "artifact_invalid"
    CONFIGURATION_MISMATCH = "configuration_mismatch"
    TOOLCHAIN_MISMATCH = "toolchain_mismatch"
    RULE_VERSION_MISMATCH = "rule_version_mismatch"
    SCOPE_INSUFFICIENT = "scope_insufficient"
    LATEST_BUILDING = "latest_building"
    LATEST_FAILED = "latest_failed"
    SESSION_CLOSED = "session_closed"
    BINDING_DRIFT = "binding_drift"


@dataclass(frozen=True, slots=True)
class KnowledgeDiagnostic(Model):
    reason: Reason
    detail: str
    artifact: ArtifactKind | None = None


@dataclass(frozen=True, slots=True)
class QueryRequirement(Model):
    repository: str
    revision: str | None
    scope: BuildScope
    configuration: BuildConfiguration

    def validate(self) -> None:
        if self.revision is not None:
            require(re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", self.revision) is not None,
                    "Query revision must be a full commit ID or null.")


@dataclass(frozen=True, slots=True)
class FreshnessResult(Model):
    state: Freshness
    snapshot_state: Freshness
    coverage: Coverage
    snapshot: SnapshotIdentity | None
    latest_attempt: BuildAttempt | None
    diagnostics: tuple[KnowledgeDiagnostic, ...]

    def validate(self) -> None:
        require(self.snapshot_state in (Freshness.FRESH, Freshness.STALE, Freshness.UNKNOWN),
                "snapshot_state describes last usable compatibility, not latest attempt.")
        if self.state is Freshness.FRESH:
            require(self.snapshot is not None and self.snapshot.revision is not None
                    and self.snapshot_state is Freshness.FRESH,
                    "Fresh requires a revision-bound compatible snapshot.")
            require(all(item.reason is Reason.SCOPE_INSUFFICIENT for item in self.diagnostics),
                    "Fresh cannot carry compatibility failures.")

    @property
    def can_bind(self) -> bool:
        return self.state is Freshness.FRESH and self.coverage is Coverage.SUFFICIENT


@dataclass(frozen=True, slots=True)
class BindingReference(Model):
    snapshot: KnowledgeSnapshot
    freshness: FreshnessResult

    def validate(self) -> None:
        require(self.freshness.can_bind and self.snapshot.identity == self.freshness.snapshot,
                "Binding requires a compatible, sufficiently scoped snapshot.")


MODEL_TYPES = {cls.__name__: cls for cls in (
    BuildScope, FileHash, SourceFingerprint, SnapshotIdentity, BuildConfiguration,
    ArtifactReference, TextKnowledge, KnowledgeArtifacts, SnapshotBuild, KnowledgeSnapshot,
    BuildAttempt, KnowledgeManifest, KnowledgeDiagnostic, QueryRequirement, FreshnessResult, BindingReference,
)}
