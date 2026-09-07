from __future__ import annotations

import json
import unittest
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

from arkui_agent.knowledge import (
    ArtifactKind, ArtifactReference, BindingReference, BuildAttempt, BuildConfiguration, BuildScope,
    BuildStatus, Coverage, FileHash, Freshness, KnowledgeArtifacts, KnowledgeManifest, KnowledgeSnapshot,
    ManifestError, ProvenanceStatus, QueryRequirement, Reason, ScopeKind, SnapshotBuild,
    SnapshotIdentity, SourceFingerprint, TextKnowledge, dumps, evaluate_freshness, loads,
)
from arkui_agent.knowledge.source import SourceObservation


class ManifestContractTests(unittest.TestCase):
    def setUp(self) -> None:
        identity = SnapshotIdentity("snapshot", "g1", "repo", "a" * 40)
        source = SourceFingerprint((FileHash("a.cpp", "b" * 64),))
        scope = BuildScope(ScopeKind.SELECTED_FILES, ("a.cpp",), (), ("a.cpp",))
        config = BuildConfiguration("c" * 64, "d" * 64, 3, 1, 1, "text-v1", "tests-v1",
                                    "p1-index-v1", "domain-v1", "framework-v1")
        artifacts = KnowledgeArtifacts(*(
            ArtifactReference(kind, kind.value if kind is ArtifactKind.GRAPH else "sha256:" + "e" * 64, identity,
                              "index.db" if kind in (ArtifactKind.SYMBOL, ArtifactKind.TEST) else kind.value + ".json",
                              "e" * 64, 3 if kind in (ArtifactKind.SYMBOL, ArtifactKind.TEST) else 1)
            for kind in ArtifactKind
        ), TextKnowledge("sha256:" + source.sha256, identity, source.sha256, "text-v1"))
        time = "2026-09-08T00:00:00+00:00"
        self.snapshot = KnowledgeSnapshot(identity, scope, source, config, artifacts,
                                         SnapshotBuild("build1", BuildStatus.SUCCEEDED, time, "verified-producer",
                                                       ProvenanceStatus.VERIFIED_BUILD, source.sha256))
        self.manifest = KnowledgeManifest(self.snapshot, BuildAttempt("build1", identity, BuildStatus.SUCCEEDED,
                                                                     "manual", time, time, None))
        self.requirement = QueryRequirement("repo", identity.revision, scope, config)
        self.source = SourceObservation("repo", identity.revision, False, source, (), ("a.cpp",))

    def result(self, manifest=None, requirement=None, source=None):
        return evaluate_freshness(manifest or self.manifest, requirement or self.requirement,
                                  source or self.source, ())

    def test_manifest_result_and_binding_canonical_round_trip(self) -> None:
        result = self.result()
        self.assertEqual(result.state, Freshness.FRESH)
        self.assertTrue(result.can_bind)
        for value in (self.manifest, self.requirement, result, BindingReference(self.snapshot, result)):
            self.assertEqual(loads(dumps(value)), value)
            self.assertEqual(dumps(loads(dumps(value))), dumps(value))
        with self.assertRaises(FrozenInstanceError):
            self.snapshot.identity = None

    def test_unobserved_artifacts_or_legacy_provenance_cannot_be_fresh(self) -> None:
        self.assertEqual(evaluate_freshness(self.manifest, self.requirement, self.source).state, Freshness.UNKNOWN)
        snapshot = replace(self.snapshot, build=replace(self.snapshot.build, provenance=ProvenanceStatus.UNVERIFIED))
        result = self.result(replace(self.manifest, last_usable=snapshot))
        self.assertEqual(result.state, Freshness.UNKNOWN)
        self.assertIn(Reason.UNVERIFIED_PROVENANCE, [d.reason for d in result.diagnostics])

    def test_scope_is_independent_from_freshness_and_channel_specific(self) -> None:
        for scope in (replace(self.snapshot.scope, kind=ScopeKind.FULL_REPOSITORY),
                      replace(self.snapshot.scope, test_files=("a.cpp",))):
            result = self.result(requirement=replace(self.requirement, scope=scope))
            self.assertEqual(result.state, Freshness.FRESH)
            self.assertEqual(result.coverage, Coverage.INSUFFICIENT)
            self.assertFalse(result.can_bind)
            self.assertEqual([d.reason for d in result.diagnostics], [Reason.SCOPE_INSUFFICIENT])

    def test_unknown_revision_and_repository_mismatch_never_fresh(self) -> None:
        for requirement in (replace(self.requirement, revision=None), replace(self.requirement, repository="other")):
            result = self.result(requirement=requirement)
            self.assertEqual(result.state, Freshness.UNKNOWN)
            self.assertEqual(loads(dumps(result)), result)
        self.assertEqual(self.result(source=replace(self.source, revision=None)).state, Freshness.UNKNOWN)

    def test_config_toolchain_and_rule_changes_are_stale(self) -> None:
        for field, value, reason in (
            ("configuration_sha256", "f" * 64, Reason.CONFIGURATION_MISMATCH),
            ("toolchain_sha256", "f" * 64, Reason.TOOLCHAIN_MISMATCH),
            ("test_rules_version", "v2", Reason.RULE_VERSION_MISMATCH),
            ("framework_rules_version", "v2", Reason.RULE_VERSION_MISMATCH),
            ("symbol_schema", 4, Reason.RULE_VERSION_MISMATCH),
            ("compiler_flags", ("-std=c++20",), Reason.CONFIGURATION_MISMATCH),
        ):
            requirement = replace(self.requirement, configuration=replace(self.snapshot.configuration, **{field: value}))
            result = self.result(requirement=requirement)
            self.assertEqual(result.state, Freshness.STALE)
            self.assertIn(reason, [d.reason for d in result.diagnostics])

    def test_building_and_failed_keep_last_usable_separate(self) -> None:
        for status, freshness in ((BuildStatus.BUILDING, Freshness.BUILDING), (BuildStatus.FAILED, Freshness.FAILED)):
            attempt = BuildAttempt("build2", replace(self.snapshot.identity, generation="g2"), status, "manual",
                                   "2026-09-08T01:00:00+00:00",
                                   None if status is BuildStatus.BUILDING else "2026-09-08T01:01:00+00:00",
                                   None if status is BuildStatus.BUILDING else "tool failure")
            manifest = replace(self.manifest, latest_attempt=attempt)
            result = self.result(manifest)
            self.assertEqual(result.state, freshness)
            self.assertEqual(result.snapshot_state, Freshness.FRESH)
            self.assertEqual(result.snapshot, self.snapshot.identity)
            self.assertFalse(result.can_bind)
            self.assertEqual(loads(dumps(result)), result)
            empty = self.result(KnowledgeManifest(None, attempt))
            self.assertEqual(empty.state, freshness)
            self.assertIsNone(empty.snapshot)

    def test_mixed_generation_revision_and_text_source_digest_are_unknown(self) -> None:
        for identity in (replace(self.snapshot.identity, generation="g2"),
                         replace(self.snapshot.identity, revision="f" * 40)):
            artifacts = replace(self.snapshot.artifacts, graph=replace(self.snapshot.artifacts.graph, snapshot=identity))
            result = self.result(replace(self.manifest, last_usable=replace(self.snapshot, artifacts=artifacts)))
            self.assertEqual(result.state, Freshness.UNKNOWN)
            self.assertIn(Reason.ARTIFACT_GENERATION_MISMATCH, [d.reason for d in result.diagnostics])
        artifacts = replace(self.snapshot.artifacts, text=replace(self.snapshot.artifacts.text,
                                                                 identity="sha256:" + "0" * 64, source_sha256="0" * 64))
        self.assertEqual(self.result(replace(self.manifest, last_usable=replace(self.snapshot, artifacts=artifacts))).state,
                         Freshness.UNKNOWN)

    def test_invalid_publication_types_paths_versions_and_json_are_rejected(self) -> None:
        with self.assertRaises(ManifestError):
            replace(self.manifest, last_usable=replace(self.snapshot, build=replace(self.snapshot.build, status=BuildStatus.FAILED)))
        with self.assertRaises(ManifestError):
            replace(self.snapshot.identity, revision="HEAD")
        with self.assertRaises(ManifestError):
            replace(self.snapshot.build, built_at="2026-09-08T01:00:00")
        for path in ("../a", "/a", "C:/a", "a\\b"):
            with self.assertRaises(ManifestError):
                replace(self.snapshot.artifacts.graph, path=path)
        for mutate in (
            lambda value: value.update(schema_version=True),
            lambda value: value.update(schema_version=2),
            lambda value: value["record"].update(extra=1),
            lambda value: value["record"].pop("last_usable"),
            lambda value: value["record"]["last_usable"]["build"].update(provenance="magic"),
        ):
            value = json.loads(dumps(self.manifest))
            mutate(value)
            with self.assertRaises(ManifestError):
                loads(json.dumps(value))
        with self.assertRaises(ManifestError):
            loads('{"schema_version":1,"schema_version":1}')

    def test_existing_p2_preparation_is_expressible_as_selected_scope(self) -> None:
        from arkui_agent.evaluation.preparation import load_p1_index_preparation

        root = Path(__file__).resolve().parents[3]
        preparation = load_p1_index_preparation(root / "benchmarks/p1/arkui-button-text-menu.preparation.json")
        semantic = tuple(sorted(file.path.as_posix() for file in preparation.semantic_files))
        tests = tuple(sorted(file.path.as_posix() for file in preparation.test_files))
        scope = BuildScope(ScopeKind.SELECTED_FILES, semantic, tests, tuple(sorted(set(semantic + tests))))
        configuration = replace(self.snapshot.configuration, compiler_flags=("-std=c++17",),
                                include_directories=preparation.fallback_include_directories)
        self.assertEqual(scope.semantic_files, semantic)
        self.assertEqual(scope.test_files, tests)
        self.assertFalse(scope.covers(replace(scope, kind=ScopeKind.FULL_REPOSITORY)))
        self.assertEqual(loads(dumps(configuration)), configuration)


if __name__ == "__main__":
    unittest.main()
