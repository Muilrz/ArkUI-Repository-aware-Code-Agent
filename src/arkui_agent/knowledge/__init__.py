"""Shared knowledge manifest, freshness and prebuilt read binding (P3-B)."""

from .model import (
    ArtifactKind, ArtifactReference, BindingReference, BuildAttempt, BuildConfiguration, BuildScope,
    BuildStatus, Coverage, FileHash, Freshness, FreshnessResult, KnowledgeArtifacts, KnowledgeDiagnostic,
    KnowledgeManifest, KnowledgeSnapshot, ManifestError, ProvenanceStatus, QueryRequirement, Reason,
    ScopeKind, SnapshotBuild, SnapshotIdentity, SourceFingerprint, TextKnowledge,
)
from .freshness import evaluate_freshness
from .reader import BoundKnowledge, PrebuiltArtifactReader, PrebuiltSnapshotReader, SnapshotReadError, SnapshotSession
from .serialization import dumps, loads
from .source import GitSourceReader, SourceReadError
from .refresh import (
    BuildContext, BuildOutput, CoverageChannel, CoverageReason, CoverageStatus, FileCoverage, PolicyExclusion,
    KnowledgeRefreshService, ManifestPublisher, P1P2RefreshBuilder,
    ProductionBuildInputs, RefreshCoverage, RefreshRequest, RefreshResult,
    RefreshBuilder, RefreshStatus, WriterConflictError,
)

__all__ = [
    "ArtifactKind", "ArtifactReference", "BindingReference", "BuildAttempt", "BuildConfiguration", "BuildScope",
    "BuildStatus", "Coverage", "FileHash", "Freshness", "FreshnessResult", "KnowledgeArtifacts", "KnowledgeDiagnostic",
    "KnowledgeManifest", "KnowledgeSnapshot", "ManifestError", "ProvenanceStatus", "QueryRequirement", "Reason",
    "ScopeKind", "SnapshotBuild", "SnapshotIdentity", "SourceFingerprint", "TextKnowledge", "evaluate_freshness",
    "BoundKnowledge", "PrebuiltArtifactReader", "PrebuiltSnapshotReader", "SnapshotReadError", "SnapshotSession",
    "dumps", "loads", "GitSourceReader", "SourceReadError",
    "BuildContext", "BuildOutput", "CoverageChannel", "CoverageReason", "CoverageStatus", "FileCoverage", "PolicyExclusion",
    "KnowledgeRefreshService", "ManifestPublisher", "P1P2RefreshBuilder",
    "ProductionBuildInputs", "RefreshBuilder", "RefreshCoverage", "RefreshRequest", "RefreshResult",
    "RefreshStatus", "WriterConflictError",
]
