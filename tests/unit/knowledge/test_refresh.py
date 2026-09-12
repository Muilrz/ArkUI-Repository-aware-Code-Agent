from __future__ import annotations

import tempfile
import unittest
import sys
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from arkui_agent.knowledge import (
    BuildScope, KnowledgeRefreshService, RefreshRequest, RefreshStatus, ScopeKind,
    ProductionBuildInputs,
)
from arkui_agent.repository import RepositoryWorkspace


class RefreshContractTests(unittest.TestCase):
    def test_interrupt_during_lease_setup_releases_lock_before_attempt(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "source"
            source.mkdir()
            knowledge = Path(root) / "knowledge"
            service = KnowledgeRefreshService(source, knowledge, repository="repo")
            with patch("arkui_agent.knowledge.refresh.os.write", side_effect=KeyboardInterrupt):
                result = service.refresh(RefreshRequest(BuildScope(ScopeKind.SELECTED_FILES, (), (), ()), "cancel"))
            self.assertEqual(result.status, RefreshStatus.CANCELLED)
            self.assertIsNone(result.attempt)
            self.assertFalse((knowledge / ".refresh.lock").exists())

    def test_unused_compiler_is_optional_provenance_not_an_executable_dependency(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = RepositoryWorkspace(temporary)
            # Actual executable inspection boundary; Python supplies --version
            # without starting a semantic build in this configuration unit test.
            inputs = ProductionBuildInputs(clangd_executable=sys.executable)
            baseline = inputs.resolve(workspace)
            hinted = replace(inputs, compiler_executable="nonexistent-cross-compiler-for-provenance").resolve(workspace)
            self.assertEqual(baseline.toolchain_sha256, hinted.toolchain_sha256)
            self.assertNotEqual(baseline.configuration_sha256, hinted.configuration_sha256)
            invalid = Path(temporary) / "invalid-driver.exe"
            invalid.write_bytes(b"not executable")
            self.assertEqual(baseline.toolchain_sha256, replace(inputs, compiler_executable=str(invalid)).resolve(workspace).toolchain_sha256)
            self.assertNotEqual(baseline.configuration_sha256, replace(inputs, compiler_flags=("-DMODE=2",)).resolve(workspace).configuration_sha256)
            with self.assertRaises(ValueError):
                replace(inputs, clangd_executable="nonexistent-required-clangd").resolve(workspace)

    def test_request_requires_explicit_reason_and_boolean_force(self) -> None:
        scope = BuildScope(ScopeKind.SELECTED_FILES, (), (), ())
        with self.assertRaises(ValueError):
            RefreshRequest(scope, "")
        with self.assertRaises(TypeError):
            RefreshRequest(scope, "manual", force=1)

    def test_existing_writer_is_an_immediate_conflict_without_manifest_write(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            knowledge = root / "knowledge"
            knowledge.mkdir()
            lock = knowledge / ".refresh.lock"
            lock.write_text("another writer\n", encoding="utf-8")
            result = KnowledgeRefreshService(source, knowledge, repository="test/repository").refresh(
                RefreshRequest(BuildScope(ScopeKind.SELECTED_FILES, (), (), ()), "manual")
            )
            self.assertEqual(result.status, RefreshStatus.CONFLICT)
            self.assertFalse((knowledge / "manifest.json").exists())
            self.assertEqual(lock.read_text(encoding="utf-8"), "another writer\n")


if __name__ == "__main__":
    unittest.main()
