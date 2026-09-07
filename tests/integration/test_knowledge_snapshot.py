from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from arkui_agent.knowledge import (
    BuildAttempt, BuildStatus, Coverage, Freshness, Reason, ScopeKind, SnapshotReadError, dumps, loads,
)
from arkui_agent.repository.index import SymbolIndex, SymbolIndexError
from tests.fixtures.knowledge_snapshot import PrebuiltFixture, sha


class KnowledgeSnapshotReadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.fixture = PrebuiltFixture(Path(self.temporary.name))

    def test_fresh_prebuilt_binding_reads_public_p1_p2_without_writes(self) -> None:
        f = self.fixture
        before = {p: p.read_bytes() for p in f.artifacts.rglob("*") if p.is_file()}
        with f.reader.bind(f.requirement) as session:
            self.assertEqual(session.reference.freshness.state, Freshness.FRESH)
            self.assertEqual(loads(dumps(session.reference)), session.reference)
            with session.read() as view:
                self.assertEqual(view.reference.snapshot.identity.generation, "g1")
                self.assertEqual(view.index.find_by_name("widget")[0].identity.value, "widget")
                self.assertEqual(view.graph.snapshot_key, "graph-g1")
                self.assertEqual(view.domain.repository_key, "test/repository")
                self.assertTrue(view.domain.mappings)
                with self.assertRaises(SymbolIndexError):
                    view.index.rebuild(())
            self.assertEqual(session.validate().state, Freshness.FRESH)
        with self.assertRaises(SnapshotReadError):
            session.validate()
        self.assertEqual(before, {p: p.read_bytes() for p in f.artifacts.rglob("*") if p.is_file()})

    def test_revision_transition_is_stale_and_no_automatic_rebuild(self) -> None:
        f = self.fixture
        (f.repo / "README.md").write_text("next revision\n", encoding="utf-8")
        f.git("add", ".")
        f.git("commit", "-m", "next")
        result = f.reader.inspect(replace(f.requirement, revision=f.git("rev-parse", "HEAD")))
        self.assertEqual(result.state, Freshness.STALE)
        self.assertIn(Reason.REVISION_MISMATCH, [d.reason for d in result.diagnostics])
        self.assertEqual(f.manifest_path.read_text(encoding="utf-8"), dumps(f.manifest))

    def test_dirty_tracked_and_untracked_files_block_binding(self) -> None:
        f = self.fixture
        for path in (f.repo / "README.md", f.repo / "untracked.txt"):
            path.write_text("dirty\n", encoding="utf-8")
            result = f.reader.inspect(f.requirement)
            self.assertEqual(result.state, Freshness.STALE)
            self.assertIn(Reason.DIRTY_WORKSPACE, [d.reason for d in result.diagnostics])
            with self.assertRaises(SnapshotReadError):
                f.reader.bind(f.requirement)
            if path.name == "README.md":
                f.git("restore", "README.md")
            else:
                path.unlink()

    def test_source_fingerprint_detects_drift_hidden_from_git_status(self) -> None:
        f = self.fixture
        f.git("update-index", "--assume-unchanged", "src/widget.cpp")
        (f.repo / "src/widget.cpp").write_text("int widget() { return 9; }\n", encoding="utf-8")
        self.assertEqual(f.git("status", "--porcelain"), "")
        result = f.reader.inspect(f.requirement)
        self.assertEqual(result.state, Freshness.STALE)
        self.assertIn(Reason.SOURCE_DRIFT, [d.reason for d in result.diagnostics])

    def test_unknown_revision_is_not_inferred_from_current_head(self) -> None:
        f = self.fixture
        result = f.reader.inspect(replace(f.requirement, revision=None))
        self.assertEqual(result.state, Freshness.UNKNOWN)
        self.assertIn(Reason.UNKNOWN_REVISION, [d.reason for d in result.diagnostics])
        f.git("checkout", "--orphan", "unborn")
        result = f.reader.inspect(f.requirement)
        self.assertEqual(result.state, Freshness.UNKNOWN)
        self.assertIn(Reason.UNKNOWN_REVISION, [d.reason for d in result.diagnostics])

    def test_old_index_new_graph_has_explicit_generation_failure(self) -> None:
        f = self.fixture
        new = f.prebuild("g2")
        old = f.manifest.last_usable
        mixed = replace(old, artifacts=replace(old.artifacts, graph=new.last_usable.artifacts.graph))
        f.write(replace(f.manifest, last_usable=mixed))
        result = f.reader.inspect(f.requirement)
        self.assertEqual(result.state, Freshness.UNKNOWN)
        self.assertIn(Reason.ARTIFACT_GENERATION_MISMATCH, [d.reason for d in result.diagnostics])
        with self.assertRaises(SnapshotReadError):
            f.reader.bind(f.requirement)

    def test_artifact_hash_mismatch_missing_and_corruption_do_not_create_empty_data(self) -> None:
        f = self.fixture
        ref = f.manifest.last_usable.artifacts.symbols
        path = f.artifacts / ref.path
        original = path.read_bytes()
        path.write_bytes(b"not a database")
        result = f.reader.inspect(f.requirement)
        self.assertIn(Reason.ARTIFACT_MISMATCH, [d.reason for d in result.diagnostics])
        self.assertEqual(result.state, Freshness.UNKNOWN)
        snapshot = f.manifest.last_usable
        checksum = hashlib.sha256(path.read_bytes()).hexdigest()
        artifacts = replace(snapshot.artifacts, symbols=replace(ref, identity="sha256:" + checksum, sha256=checksum),
                            tests=replace(snapshot.artifacts.tests, identity="sha256:" + checksum, sha256=checksum))
        f.write(replace(f.manifest, last_usable=replace(snapshot, artifacts=artifacts)))
        self.assertIn(Reason.ARTIFACT_INVALID, [d.reason for d in f.reader.inspect(f.requirement).diagnostics])
        path.write_bytes(original)
        f.write(f.manifest)
        path.unlink()
        self.assertEqual(f.reader.inspect(f.requirement).state, Freshness.UNKNOWN)
        self.assertFalse(path.exists())
        with self.assertRaises(SymbolIndexError):
            SymbolIndex.open_read_only(path)
        self.assertFalse(path.exists())

    def test_graph_and_domain_embedded_identity_checked_even_with_matching_hash(self) -> None:
        f = self.fixture
        snapshot = f.manifest.last_usable
        for field, key in (("graph", "snapshot_key"), ("domain", "ruleset_identity")):
            ref = getattr(snapshot.artifacts, field)
            path = f.artifacts / ref.path
            original = path.read_bytes()
            payload = json.loads(original)
            payload[key] = "wrong"
            path.write_text(json.dumps(payload), encoding="utf-8")
            checksum = hashlib.sha256(path.read_bytes()).hexdigest()
            artifacts = replace(snapshot.artifacts, **{field: replace(ref, sha256=checksum,
                                identity=ref.identity if field == "graph" else "sha256:" + checksum)})
            f.write(replace(f.manifest, last_usable=replace(snapshot, artifacts=artifacts)))
            result = f.reader.inspect(f.requirement)
            self.assertEqual(result.state, Freshness.UNKNOWN)
            self.assertIn(Reason.ARTIFACT_INVALID, [d.reason for d in result.diagnostics])
            path.write_bytes(original)

    def test_missing_and_corrupt_manifest_are_unknown(self) -> None:
        f = self.fixture
        f.manifest_path.unlink()
        result = f.reader.inspect(f.requirement)
        self.assertEqual(result.state, Freshness.UNKNOWN)
        self.assertEqual(result.diagnostics[0].reason, Reason.MANIFEST_MISSING)
        self.assertFalse(f.manifest_path.exists())
        for text in ("{", "{}", dumps(f.requirement)):
            f.manifest_path.write_text(text, encoding="utf-8")
            result = f.reader.inspect(f.requirement)
            self.assertEqual(result.state, Freshness.UNKNOWN)
            self.assertEqual(result.diagnostics[0].reason, Reason.MANIFEST_CORRUPT)
            self.assertEqual(loads(dumps(result)), result)

    def test_selected_scope_can_be_fresh_but_insufficient_for_full_query(self) -> None:
        f = self.fixture
        requirement = replace(f.requirement, scope=replace(f.scope, kind=ScopeKind.FULL_REPOSITORY))
        result = f.reader.inspect(requirement)
        self.assertEqual(result.state, Freshness.FRESH)
        self.assertEqual(result.coverage, Coverage.INSUFFICIENT)
        self.assertFalse(result.can_bind)
        with self.assertRaises(SnapshotReadError):
            f.reader.bind(requirement)

    def test_full_scope_requires_inventory_and_config_tool_rule_changes_are_stale(self) -> None:
        f = self.fixture
        snapshot = replace(f.manifest.last_usable, scope=replace(f.scope, kind=ScopeKind.FULL_REPOSITORY))
        f.write(replace(f.manifest, last_usable=snapshot))
        self.assertEqual(f.reader.inspect(replace(f.requirement, scope=snapshot.scope)).state, Freshness.FRESH)
        for field, value in (("configuration_sha256", sha("other")), ("toolchain_sha256", sha("other")),
                             ("framework_rules_version", "v2")):
            requirement = replace(f.requirement, configuration=replace(f.requirement.configuration, **{field: value}))
            self.assertEqual(f.reader.inspect(requirement).state, Freshness.STALE)

    def test_latest_failure_and_building_do_not_destroy_last_usable(self) -> None:
        f = self.fixture
        for status, expected in ((BuildStatus.BUILDING, Freshness.BUILDING), (BuildStatus.FAILED, Freshness.FAILED)):
            attempt = BuildAttempt("build2", replace(f.manifest.last_usable.identity, generation="g2"), status, "manual",
                                   "2026-09-08T01:00:00+00:00",
                                   None if status is BuildStatus.BUILDING else "2026-09-08T01:01:00+00:00",
                                   None if status is BuildStatus.BUILDING else "compiler unavailable")
            f.write(replace(f.manifest, latest_attempt=attempt))
            result = f.reader.inspect(f.requirement)
            self.assertEqual(result.state, expected)
            self.assertEqual(result.snapshot_state, Freshness.FRESH)
            self.assertEqual(result.snapshot.generation, "g1")
            self.assertEqual(loads(dumps(result)), result)
            with self.assertRaises(SnapshotReadError):
                f.reader.bind(f.requirement)

    def test_artifact_mutation_during_read_invalidates_session(self) -> None:
        f = self.fixture
        session = f.reader.bind(f.requirement)
        with self.assertRaises(SnapshotReadError):
            with session.read():
                path = f.artifacts / f.manifest.last_usable.artifacts.graph.path
                path.write_bytes(path.read_bytes() + b" ")
        with self.assertRaises(SnapshotReadError):
            session.validate()

    def test_source_mutation_during_read_invalidates_session(self) -> None:
        f = self.fixture
        session = f.reader.bind(f.requirement)
        with self.assertRaises(SnapshotReadError):
            with session.read():
                (f.repo / "src/widget.cpp").write_text("changed\n", encoding="utf-8")

    def test_same_bytes_replacement_is_detected_by_file_stamp(self) -> None:
        f = self.fixture
        session = f.reader.bind(f.requirement)
        path = f.artifacts / f.manifest.last_usable.artifacts.graph.path
        replacement = path.with_suffix(".replacement")
        replacement.write_bytes(path.read_bytes())
        replacement.replace(path)
        with self.assertRaises(SnapshotReadError) as failure:
            session.validate()
        self.assertIn(Reason.BINDING_DRIFT, [d.reason for d in failure.exception.result.diagnostics])

    def test_manifest_pointer_change_does_not_rebind_existing_session(self) -> None:
        f = self.fixture
        session = f.reader.bind(f.requirement)
        new = f.prebuild("g2")
        f.write(new)
        with session.read() as view:
            self.assertEqual(view.reference.snapshot.identity.generation, "g1")
            self.assertEqual(view.graph.snapshot_key, "graph-g1")
        with f.reader.bind(f.requirement) as next_session:
            self.assertEqual(next_session.reference.snapshot.identity.generation, "g2")

    def test_live_sqlite_sidecars_are_rejected(self) -> None:
        f = self.fixture
        path = f.artifacts / f.manifest.last_usable.artifacts.symbols.path
        Path(str(path) + "-wal").write_bytes(b"pending")
        result = f.reader.inspect(f.requirement)
        self.assertEqual(result.state, Freshness.UNKNOWN)
        self.assertIn(Reason.ARTIFACT_INVALID, [d.reason for d in result.diagnostics])


if __name__ == "__main__":
    unittest.main()
