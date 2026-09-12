import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from arkui_agent.knowledge.progress import RefreshProgress


class RefreshProgressTests(unittest.TestCase):
    def test_atomic_bounded_throttled_large_scope_and_terminal_updates(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "progress.json"
            progress = RefreshProgress(path, "attempt-1", "generation-1")
            import os
            replace = os.replace
            replacements = []
            def checked_replace(source, destination):
                record = json.loads(Path(source).read_text())
                self.assertLess(Path(source).stat().st_size, 1500)
                if path.exists():
                    json.loads(path.read_text())
                replacements.append(record)
                replace(source, destination)
            with patch("arkui_agent.knowledge.progress.os.replace", side_effect=checked_replace), \
                 patch("arkui_agent.knowledge.progress.time.monotonic", return_value=100):
                progress.update("semantic_prepare", 2402, 14497, "x" * 100000)
                first = json.loads(path.read_text())
                self.assertEqual((first["current"], first["total"]), (2402, 14497))
                self.assertEqual(first["percent"], round(2402 / 14497 * 100, 2))
                self.assertEqual(first["status"], "running")
                for n in range(2403, 2500):
                    progress.update("semantic_prepare", n, 14497)
                self.assertEqual(len(replacements), 1)
                progress.update("semantic_collect", 0, 14497)
                progress.finish("cancelled")
            self.assertEqual(len(replacements), 3)
            self.assertEqual(json.loads(path.read_text())["status"], "cancelled")
            self.assertEqual(list(Path(root).glob(".progress-*")), [])

    def test_reporting_failure_is_nonfatal_and_preserves_previous_json(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "progress.json"
            progress = RefreshProgress(path, "attempt-1", "generation-1")
            progress.update("source_inventory")
            before = path.read_bytes()
            with patch("arkui_agent.knowledge.progress.os.replace", side_effect=OSError("read only")):
                progress.finish("failed")
            self.assertEqual(path.read_bytes(), before)
            self.assertIn("read only", progress.diagnostic)
            self.assertEqual(list(Path(root).glob(".progress-*")), [])
