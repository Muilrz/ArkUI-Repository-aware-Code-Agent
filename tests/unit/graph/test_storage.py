from __future__ import annotations

import json
import subprocess
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from arkui_agent.graph import GraphSnapshot, GraphStorageError, GraphStore, NodeIdentity, TraversalBounds
from arkui_agent.repository import SymbolIndex, SymbolIndexClosedError
from tests.unit.graph.test_query import edge, node


class GraphStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = TemporaryDirectory(prefix="graph-storage-unit-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.store = GraphStore(self.root, repository_key="repo", snapshot_key="snapshot")
        self.snapshot = GraphSnapshot("repo", "snapshot", (node("b"), node("a")), (edge("a", "b"),))

    def test_round_trip_and_deterministic_bytes_preserve_query_semantics(self) -> None:
        self.store.save(self.snapshot)
        original = self.store.path.read_bytes()
        loaded = self.store.load()
        self.assertEqual(loaded, self.snapshot)
        identity = node("a").identity
        self.assertEqual(loaded.query().traverse(identity, bounds=TraversalBounds(2)),
                         self.snapshot.query().traverse(identity, bounds=TraversalBounds(2)))
        reversed_ = replace(self.snapshot, nodes=tuple(reversed(self.snapshot.nodes)), edges=self.snapshot.edges * 2)
        self.store.save(reversed_)
        self.assertEqual(self.store.path.read_bytes(), original)

    def test_repository_and_snapshot_scope_are_isolated(self) -> None:
        stores = (
            GraphStore(self.root, repository_key="other", snapshot_key="snapshot"),
            GraphStore(self.root, repository_key="repo", snapshot_key="other"),
            GraphStore(self.root, repository_key="../../escape", snapshot_key="../other"),
        )
        self.store.save(self.snapshot)
        for other in stores:
            with self.subTest(path=other.path):
                self.assertNotEqual(self.store.path, other.path)
                self.assertTrue(other.path.is_relative_to(self.root))
                with self.assertRaises(GraphStorageError):
                    other.save(self.snapshot)
                other.path.parent.mkdir(parents=True, exist_ok=True)
                other.path.write_bytes(self.store.path.read_bytes())
                with self.assertRaisesRegex(GraphStorageError, "scope mismatch"):
                    other.load()

    def test_delete_rebuild_replaces_stale_records_and_preserves_loaded_query(self) -> None:
        self.store.save(self.snapshot)
        old_query = self.store.load().query()
        self.store.delete()
        self.store.delete()
        with self.assertRaises(GraphStorageError):
            self.store.load()
        with SymbolIndex(self.root / "index.sqlite3") as index:
            index.rebuild(())
            rebuilt = self.store.rebuild(index)
        self.assertEqual(self.store.load(), rebuilt)
        self.assertEqual(rebuilt.nodes, ())
        self.assertIsNotNone(old_query.node(NodeIdentity("symbol", "a")))

    def test_failed_projection_preserves_last_complete_snapshot(self) -> None:
        self.store.save(self.snapshot)
        original = self.store.path.read_bytes()
        with SymbolIndex(self.root / "index.sqlite3") as index:
            pass
        with self.assertRaises(SymbolIndexClosedError):
            self.store.rebuild(index)
        self.assertEqual(self.store.path.read_bytes(), original)

    def test_actual_write_failure_has_explicit_error_and_cleans_temporary_file(self) -> None:
        self.store.path.mkdir(parents=True)
        with self.assertRaises(GraphStorageError):
            self.store.save(self.snapshot)
        self.assertEqual(list(self.store.path.parent.glob("*.tmp")), [])

    def test_invalid_missing_corrupt_schema_and_records_are_not_empty_graphs(self) -> None:
        with self.assertRaises(GraphStorageError):
            self.store.load()
        self.store.save(self.snapshot)
        valid = json.loads(self.store.path.read_text(encoding="utf-8"))
        for payload in ([], {}, {**valid, "schema_version": 2}, {**valid, "schema_version": True},
                        {**valid, "nodes": {}}, {**valid, "edges": [None]},
                        {**valid, "nodes": []}):
            with self.subTest(payload=payload):
                self.store.path.write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaises(GraphStorageError):
                    self.store.load()
        self.store.path.write_text("{", encoding="utf-8")
        with self.assertRaises(GraphStorageError):
            self.store.load()

    def test_generated_filename_and_runtime_data_are_ignored(self) -> None:
        root = Path(__file__).resolve().parents[3]
        result = subprocess.run(
            ["git", "check-ignore", "--", "var/graph/code-graph.json", "scratch/code-graph.json"], cwd=root,
            text=True, capture_output=True, check=True,
        )
        self.assertEqual(result.stdout.splitlines(), ["var/graph/code-graph.json", "scratch/code-graph.json"])

    def test_invalid_scope_and_conflicting_snapshot_records_fail(self) -> None:
        with self.assertRaises(ValueError):
            GraphStore(self.root, repository_key="", snapshot_key="snapshot")
        with self.assertRaises(ValueError):
            replace(self.snapshot, snapshot_key=" ")
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            replace(self.snapshot, nodes=(node("a"), replace(node("a"), display_name="different")))
