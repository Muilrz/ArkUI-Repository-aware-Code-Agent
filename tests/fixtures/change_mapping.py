"""Two clean checkouts of connected commits, with synthetic P1 prebuilt extents."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from arkui_agent.graph import ArkUIRoleMapper, GraphStore, project_index
from arkui_agent.knowledge import (
    ArtifactKind, ArtifactReference, BuildAttempt, BuildConfiguration, BuildScope, BuildStatus,
    GitSourceReader, KnowledgeArtifacts, KnowledgeManifest, KnowledgeSnapshot, PrebuiltSnapshotReader,
    ProvenanceStatus, QueryRequirement, ScopeKind, SnapshotBuild, SnapshotIdentity, TextKnowledge, dumps,
)
from arkui_agent.repository import RepositoryFile, SourceLocation, SourceRange, Symbol, SymbolIdentity, SymbolIndex, SymbolKind


REPOSITORY = "synthetic/c2"
BASE_TEXT = "int f() {\n  int x = 1;\n  return x;\n}\n\nint g() {\n  return 2;\n}\n"
HEAD_TEXT = "// moved\n" + BASE_TEXT.replace("x = 1", "x = 3")


def git(repo, *args):
    return subprocess.run(("git", "-C", str(repo), *args), capture_output=True, text=True,
                          encoding="utf-8", check=True, timeout=30).stdout.strip()


def symbol(identity, path, start, end, *, declaration=None):
    file = RepositoryFile.from_path(path)
    extent = SourceRange(SourceLocation(file, *start), SourceLocation(file, *end))
    return Symbol(SymbolIdentity(identity), SymbolKind.FUNCTION, identity.split(":")[0], identity.split(":")[0],
                  declaration=declaration, definition=extent)


class DualRevisionFixture:
    def __init__(self, root: Path):
        self.root = root
        self.base = root / "base"
        self.base.mkdir()
        git(self.base, "init")
        git(self.base, "config", "user.name", "C2 fixture")
        git(self.base, "config", "user.email", "fixture@example.invalid")
        git(self.base, "config", "core.autocrlf", "false")
        for name, content in (("code.cpp", BASE_TEXT), ("old.cpp", BASE_TEXT),
                              ("gone.cpp", BASE_TEXT), ("macro.h", "#define VALUE 1\n"), ("script.py", "x = 1\n")):
            (self.base / name).write_text(content, encoding="utf-8", newline="\n")
        git(self.base, "add", ".")
        git(self.base, "commit", "-m", "base fixture")
        self.base_revision = git(self.base, "rev-parse", "HEAD")
        self.head = root / "head"
        git(self.base, "clone", "--no-hardlinks", str(self.base), str(self.head))
        git(self.head, "config", "user.name", "C2 fixture")
        git(self.head, "config", "user.email", "fixture@example.invalid")
        git(self.head, "config", "core.autocrlf", "false")
        (self.head / "code.cpp").write_text(HEAD_TEXT, encoding="utf-8", newline="\n")
        (self.head / "old.cpp").rename(self.head / "new.cpp")
        (self.head / "gone.cpp").unlink()
        (self.head / "added.cpp").write_text(BASE_TEXT, encoding="utf-8", newline="\n")
        git(self.head, "add", "-A")
        git(self.head, "commit", "-m", "move rename add delete fixture")
        self.head_revision = git(self.head, "rev-parse", "HEAD")
        self.records = {
            "base": (symbol("f:base", "code.cpp", (1, 1), (4, 2)), symbol("g:base", "code.cpp", (6, 1), (8, 2)),
                     symbol("renamed", "old.cpp", (1, 1), (4, 2)), symbol("deleted", "gone.cpp", (1, 1), (4, 2))),
            "head": (symbol("f:head", "code.cpp", (2, 1), (5, 2)), symbol("g:head", "code.cpp", (7, 1), (9, 2)),
                     symbol("renamed", "new.cpp", (1, 1), (4, 2)), symbol("added", "added.cpp", (1, 1), (4, 2))),
        }

    def bind(self, side, *, records=None, excluded=()):
        repo = getattr(self, side)
        root = self.root / (side + "-artifacts")
        root.mkdir()
        files = tuple(sorted(p.name for p in repo.iterdir() if p.is_file()))
        source = GitSourceReader(repo, repository=REPOSITORY)
        observation = source.observe(files)
        identity = SnapshotIdentity(side, side + "-generation", REPOSITORY, observation.revision)
        scope = BuildScope(ScopeKind.SELECTED_FILES, tuple(p for p in files if p not in excluded), (), files)
        path = root / "symbols.sqlite3"
        with SymbolIndex(path) as index:
            index.rebuild(self.records[side] if records is None else records, files=tuple(RepositoryFile.from_path(p) for p in files))
            graph = project_index(index, repository_key=REPOSITORY, snapshot_key="graph-" + side)
            domain = ArkUIRoleMapper((), ()).map(index, graph)
        store = GraphStore(root, repository_key=REPOSITORY, snapshot_key=graph.snapshot_key)
        store.save(graph)
        domain_path = root / "domain.json"
        domain_path.write_text(json.dumps(domain.to_dict()), encoding="utf-8")

        def ref(kind, file, version):
            sha = hashlib.sha256(file.read_bytes()).hexdigest()
            return ArtifactReference(kind, graph.snapshot_key if kind is ArtifactKind.GRAPH else "sha256:" + sha,
                                     identity, file.relative_to(root).as_posix(), sha, version)

        artifacts = KnowledgeArtifacts(ref(ArtifactKind.SYMBOL, path, 3), ref(ArtifactKind.TEST, path, 3),
                                      ref(ArtifactKind.GRAPH, store.path, 1), ref(ArtifactKind.DOMAIN, domain_path, 1),
                                      TextKnowledge("sha256:" + observation.fingerprint.sha256, identity, observation.fingerprint.sha256, "rg-source-v1"))
        config = BuildConfiguration("a" * 64, "b" * 64, 3, 1, 1, "rg-source-v1", "test-v1", "p1-index-v1", domain.ruleset_identity, "none-v1")
        timestamp = "2026-09-09T00:00:00+00:00"
        build = SnapshotBuild(side, BuildStatus.SUCCEEDED, timestamp, "synthetic-c2-v1", ProvenanceStatus.VERIFIED_BUILD, observation.fingerprint.sha256)
        manifest = KnowledgeManifest(KnowledgeSnapshot(identity, scope, observation.fingerprint, config, artifacts, build),
                                     BuildAttempt(side, identity, BuildStatus.SUCCEEDED, "fixture", timestamp, timestamp, None))
        manifest_path = root / "manifest.json"
        manifest_path.write_text(dumps(manifest), encoding="utf-8")
        return PrebuiltSnapshotReader(manifest_path, artifact_root=root, source=source).bind(QueryRequirement(REPOSITORY, observation.revision, scope, config))
