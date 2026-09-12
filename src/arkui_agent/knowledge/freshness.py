"""Deterministic compatibility policy over explicit observations."""

from __future__ import annotations

from .model import (
    BuildStatus, Coverage, Freshness, FreshnessResult, KnowledgeDiagnostic, KnowledgeManifest,
    ProvenanceStatus, QueryRequirement, Reason, ScopeKind,
)
from .source import SourceObservation


def evaluate_freshness(manifest: KnowledgeManifest, requirement: QueryRequirement,
                       source: SourceObservation | None,
                       read_diagnostics: tuple[KnowledgeDiagnostic, ...] | None = None) -> FreshnessResult:
    # None means artifacts were not observed; an empty tuple means the adapter checked them.
    issues = list(read_diagnostics or ())
    snapshot = manifest.last_usable
    attempt = manifest.latest_attempt
    unknown = read_diagnostics is None or bool(read_diagnostics)
    stale = False
    coverage = Coverage.UNKNOWN

    def issue(reason: Reason, detail: str) -> None:
        issues.append(KnowledgeDiagnostic(reason, detail))

    if read_diagnostics is None:
        issue(Reason.ARTIFACT_UNAVAILABLE, "No artifact read validation was supplied.")

    if snapshot is None:
        unknown = True
        issue(Reason.NO_USABLE_SNAPSHOT, "No last usable generation is available.")
    else:
        identity = snapshot.identity
        coverage = Coverage.SUFFICIENT if snapshot.scope.covers(requirement.scope) else Coverage.INSUFFICIENT
        if coverage is Coverage.INSUFFICIENT:
            issue(Reason.SCOPE_INSUFFICIENT, "Declared per-channel scope does not cover this query.")
        if snapshot.build.provenance is not ProvenanceStatus.VERIFIED_BUILD:
            unknown = True
            issue(Reason.UNVERIFIED_PROVENANCE, "Legacy artifacts have no verified build provenance.")
        if identity.revision is None or requirement.revision is None or (source is not None and source.revision is None):
            unknown = True
            issue(Reason.UNKNOWN_REVISION, "Snapshot, query and source require explicit known commit IDs.")
        if identity.repository != requirement.repository or (source is not None and source.repository != identity.repository):
            unknown = True
            issue(Reason.REPOSITORY_MISMATCH, "Repository identities disagree.")
        if identity.revision != requirement.revision or (source is not None and source.revision != identity.revision):
            stale = True
            issue(Reason.REVISION_MISMATCH, "Source/snapshot/query revisions differ.")
        if source is None:
            unknown = True
            if not any(item.reason is Reason.SOURCE_UNAVAILABLE for item in issues):
                issue(Reason.SOURCE_UNAVAILABLE, "No reliable source observation.")
        else:
            if not {item.path for item in snapshot.source.files}.issubset(source.tracked_files):
                unknown = True
                issue(Reason.UNVERIFIED_PROVENANCE, "Source fingerprint includes files not tracked by the declared Git revision.")
            if source.dirty:
                stale = True
                issue(Reason.DIRTY_WORKSPACE, "Git reports tracked or untracked workspace changes.")
            if source.fingerprint != snapshot.source:
                stale = True
                issue(Reason.SOURCE_DRIFT, "Source bytes differ from the snapshot fingerprint.")
            if snapshot.scope.kind is ScopeKind.FULL_REPOSITORY and not set(source.tracked_files).issubset(
                item.path for item in snapshot.source.files
            ):
                unknown = True
                issue(Reason.UNVERIFIED_PROVENANCE, "Full-repository fingerprint omits tracked files.")
        if snapshot.build.source_sha256 != snapshot.source.sha256:
            unknown = True
            issue(Reason.UNVERIFIED_PROVENANCE, "Build provenance and source inventory digest disagree.")
        artifacts = snapshot.artifacts
        for artifact in (*artifacts.files, artifacts.text):
            if artifact.snapshot != identity:
                unknown = True
                issue(Reason.ARTIFACT_GENERATION_MISMATCH, "Artifact repository/revision/generation differs from snapshot.")
        if (artifacts.symbols.path, artifacts.symbols.sha256, artifacts.symbols.schema_version) != (
            artifacts.tests.path, artifacts.tests.sha256, artifacts.tests.schema_version
        ):
            unknown = True
            issue(Reason.ARTIFACT_MISMATCH, "P1 symbol and test knowledge must refer to the same sealed index.")
        if artifacts.text.source_sha256 != snapshot.source.sha256:
            unknown = True
            issue(Reason.ARTIFACT_MISMATCH, "Text knowledge must identify the same source fingerprint.")
        actual, expected = snapshot.configuration, requirement.configuration
        if any(getattr(actual, name) != getattr(expected, name) for name in (
            "configuration_sha256", "compiler_flags", "include_directories", "compile_database_sha256"
        )):
            stale = True
            issue(Reason.CONFIGURATION_MISMATCH, "Build configuration changed.")
        if actual.toolchain_sha256 != expected.toolchain_sha256:
            stale = True
            issue(Reason.TOOLCHAIN_MISMATCH, "Toolchain fingerprint changed.")
        version_fields = ("symbol_schema", "graph_schema", "domain_schema", "text_reader_version",
                          "test_rules_version", "projection_version", "domain_ruleset", "framework_rules_version",
                          "scanner_policy_version")
        if any(getattr(actual, name) != getattr(expected, name) for name in version_fields):
            stale = True
            issue(Reason.RULE_VERSION_MISMATCH, "Rule/schema/reader versions changed.")
        if (artifacts.symbols.schema_version != actual.symbol_schema
                or artifacts.tests.schema_version != actual.symbol_schema
                or artifacts.graph.schema_version != actual.graph_schema
                or artifacts.domain.schema_version != actual.domain_schema
                or artifacts.text.reader_version != actual.text_reader_version):
            unknown = True
            issue(Reason.ARTIFACT_MISMATCH, "Artifact versions disagree with the build configuration.")

    snapshot_state = Freshness.UNKNOWN if unknown else Freshness.STALE if stale else Freshness.FRESH
    state = snapshot_state
    if attempt is not None and attempt.status is BuildStatus.BUILDING:
        state = Freshness.BUILDING
        issue(Reason.LATEST_BUILDING, "Latest generation is still building; last usable remains separate.")
    elif attempt is not None and attempt.status in (BuildStatus.FAILED, BuildStatus.CANCELLED):
        state = Freshness.FAILED
        issue(Reason.LATEST_FAILED, attempt.failure or "Latest build failed.")
    return FreshnessResult(state, snapshot_state, coverage, None if snapshot is None else snapshot.identity,
                           attempt, tuple(issues))
