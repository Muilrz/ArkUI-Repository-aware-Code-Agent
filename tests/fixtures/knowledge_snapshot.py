"""Synthetic prebuilt P1/P2 artifacts; never used as production refresh logic."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from arkui_agent.graph.domain import ArkUIRoleMapper
from arkui_agent.graph.projection import project_index
from arkui_agent.graph.storage import GraphStore
from arkui_agent.knowledge import (
    ArtifactKind, ArtifactReference, BuildAttempt, BuildConfiguration, BuildScope, BuildStatus,
    GitSourceReader, KnowledgeArtifacts, KnowledgeManifest, KnowledgeSnapshot, PrebuiltSnapshotReader,
    ProvenanceStatus, QueryRequirement, ScopeKind, SnapshotBuild, SnapshotIdentity, TextKnowledge, dumps,
)
from arkui_agent.repository.index import SymbolIndex
from arkui_agent.repository.model import RepositoryFile, SourceLocation, SourceRange, Symbol, SymbolIdentity, SymbolKind


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class PrebuiltFixture:
    def __init__(self, root: Path) -> None:
        self.repo = root / "source"
        self.repo.mkdir()
        self.artifacts = root / "knowledge"
        self.artifacts.mkdir()
        self.manifest_path = self.artifacts / "manifest.json"
        self.git("init")
        self.git("config", "user.email", "fixture@example.invalid")
        self.git("config", "user.name", "Fixture")
        self.git("config", "core.autocrlf", "false")
        for name, content in (("src/widget.cpp", "int widget() { return 1; }\n"),
                              ("tests/widget_test.cpp", "int smoke() { return 0; }\n"),
                              ("README.md", "synthetic source\n")):
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8", newline="\n")
        self.git("add", ".")
        self.git("commit", "-m", "synthetic source")
        self.source = GitSourceReader(self.repo, repository="test/repository")
        self.scope = BuildScope(ScopeKind.SELECTED_FILES, ("src/widget.cpp",), ("tests/widget_test.cpp",),
                                ("src/widget.cpp", "tests/widget_test.cpp"))
        self.manifest = self.prebuild("g1")
        self.write(self.manifest)
        snapshot = self.manifest.last_usable
        self.requirement = QueryRequirement("test/repository", snapshot.identity.revision, self.scope, snapshot.configuration)
        self.reader = PrebuiltSnapshotReader(self.manifest_path, artifact_root=self.artifacts, source=self.source)

    def git(self, *arguments: str) -> str:
        result = subprocess.run(("git", "-C", str(self.repo), *arguments), capture_output=True,
                                text=True, encoding="utf-8", check=True, timeout=30)
        return result.stdout.strip()

    def write(self, manifest: KnowledgeManifest) -> None:
        self.manifest_path.write_text(dumps(manifest), encoding="utf-8")

    def prebuild(self, generation: str) -> KnowledgeManifest:
        observation = self.source.observe(("README.md", "src/widget.cpp", "tests/widget_test.cpp"))
        identity = SnapshotIdentity("snapshot-" + generation, generation, "test/repository", observation.revision)
        index_path = self.artifacts / generation / "symbols.sqlite3"
        file = RepositoryFile.from_path("src/widget.cpp")
        symbol = Symbol(SymbolIdentity("widget"), SymbolKind.FUNCTION, "widget", "widget",
                        definition=SourceRange(SourceLocation(file, 1, 1), SourceLocation(file, 1, 27)))
        with SymbolIndex(index_path) as index:
            index.rebuild((symbol,), files=(file, RepositoryFile.from_path("tests/widget_test.cpp")))
            graph = project_index(index, repository_key=identity.repository, snapshot_key="graph-" + generation)
            domain = ArkUIRoleMapper((), ()).map(index, graph)
        store = GraphStore(self.artifacts, repository_key=identity.repository, snapshot_key=graph.snapshot_key)
        store.save(graph)
        domain_path = self.artifacts / generation / "domain.json"
        domain_path.write_text(json.dumps(domain.to_dict(), sort_keys=True), encoding="utf-8")

        def artifact(kind: ArtifactKind, path: Path, key: str, version: int) -> ArtifactReference:
            checksum = hashlib.sha256(path.read_bytes()).hexdigest()
            return ArtifactReference(kind, key if kind is ArtifactKind.GRAPH else "sha256:" + checksum,
                                     identity, path.relative_to(self.artifacts).as_posix(), checksum, version)

        configuration = BuildConfiguration(sha("config"), sha("toolchain"), 3, 1, 1, "rg-source-v1", "test-rules-v1",
                                            "p1-index-v1", domain.ruleset_identity, "framework-v1")
        artifacts = KnowledgeArtifacts(
            artifact(ArtifactKind.SYMBOL, index_path, "p1-" + generation, 3),
            artifact(ArtifactKind.TEST, index_path, "p1-" + generation, 3),
            artifact(ArtifactKind.GRAPH, store.path, graph.snapshot_key, 1),
            artifact(ArtifactKind.DOMAIN, domain_path, "domain-" + generation, 1),
            TextKnowledge("sha256:" + observation.fingerprint.sha256, identity, observation.fingerprint.sha256, "rg-source-v1"),
        )
        time = "2026-09-08T00:00:00+00:00"
        snapshot = KnowledgeSnapshot(identity, self.scope, observation.fingerprint, configuration, artifacts,
                                     SnapshotBuild("build-" + generation, BuildStatus.SUCCEEDED, time,
                                                   "synthetic-fixture-v1", ProvenanceStatus.VERIFIED_BUILD,
                                                   observation.fingerprint.sha256))
        return KnowledgeManifest(snapshot, BuildAttempt("build-" + generation, identity, BuildStatus.SUCCEEDED,
                                                        "fixture preparation", time, time, None))
