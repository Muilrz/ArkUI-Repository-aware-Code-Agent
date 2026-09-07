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

__all__ = [
    "ArtifactKind", "ArtifactReference", "BindingReference", "BuildAttempt", "BuildConfiguration", "BuildScope",
    "BuildStatus", "Coverage", "FileHash", "Freshness", "FreshnessResult", "KnowledgeArtifacts", "KnowledgeDiagnostic",
    "KnowledgeManifest", "KnowledgeSnapshot", "ManifestError", "ProvenanceStatus", "QueryRequirement", "Reason",
    "ScopeKind", "SnapshotBuild", "SnapshotIdentity", "SourceFingerprint", "TextKnowledge", "evaluate_freshness",
    "BoundKnowledge", "PrebuiltArtifactReader", "PrebuiltSnapshotReader", "SnapshotReadError", "SnapshotSession",
    "dumps", "loads", "GitSourceReader", "SourceReadError",
]
