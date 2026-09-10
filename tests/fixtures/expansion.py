"""P3 synthetic overlay facts over original P2 fixture source, sealed through B.

This is test preparation, not a production refresh adapter or real ArkUI gold.
"""

import hashlib
import json
import re
from dataclasses import replace
from pathlib import Path

from arkui_agent.graph import default_role_mapper, extract_framework_relations, project_index
from arkui_agent.graph.storage import GraphStore
from arkui_agent.knowledge import ArtifactKind, BuildScope, QueryRequirement, ScopeKind, TextKnowledge
from arkui_agent.repository import RepositoryFile, SourceLocation, SourceRange, Symbol, SymbolIdentity, SymbolIndex, SymbolKind
from arkui_agent.repository.index import SymbolSemanticFacts
from tests.fixtures.knowledge_snapshot import PrebuiltFixture
from tests.fixtures.overlay_cases import FRAME_H, MANAGER_CPP, MANAGER_H, NS, PATTERN_H, write_overlay_repository


class OverlayExpansionFixture(PrebuiltFixture):
    def __init__(self, root: Path, *, cycle: bool = False, partial: bool = False):
        super().__init__(root)
        write_overlay_repository(self.repo, multiple_close=True)
        if cycle:
            with (self.repo / "overlay_entry.cpp").open("a", encoding="utf-8") as stream:
                stream.write("\nnamespace OHOS::Ace::NG { void Recursive() { Recursive(); } }\n")
        self.git("add", ".")
        self.git("commit", "-m", "P3 synthetic overlay expansion source")
        symbols = []

        def sid(name):
            return SymbolIdentity(NS + name)

        def token(path, name):
            text = (self.repo / path).read_text(encoding="utf-8")
            match = re.search(r"\b" + re.escape(name) + r"\b", text)
            assert match is not None
            file = RepositoryFile.from_path(path)
            start = SourceLocation(file, text.count("\n", 0, match.start()) + 1,
                                   match.start() - text.rfind("\n", 0, match.start()))
            return SourceRange(start, replace(start, column=start.column + len(name)))

        for name, path in (("OverlayManager", MANAGER_H), ("FrameNode", FRAME_H), ("MenuPattern", PATTERN_H)):
            location = token(path, name)
            symbols.append(Symbol(sid(name), SymbolKind.CLASS, name, NS + name, location, location))
        for method in ("ShowMenu", "HideMenu"):
            symbols.append(Symbol(sid("OverlayManager::" + method), SymbolKind.METHOD, method,
                NS + "OverlayManager::" + method, token(MANAGER_H, method), token(MANAGER_CPP, method), sid("OverlayManager")))
        for name in ("Open", "Close", "Dismiss", "Keyboard") + (("Recursive",) if cycle else ()):
            location = token("overlay_entry.cpp", name)
            symbols.append(Symbol(sid(name), SymbolKind.FUNCTION, name, NS + name, location, location))
        # Missing manager body/reference facts are intentional; entry CALLs are real.
        calls = (("Open", ("OverlayManager::ShowMenu",)),
                 ("Close", ("Dismiss", "Keyboard")),
                 ("Dismiss", ("OverlayManager::HideMenu",)),
                 ("Keyboard", ("OverlayManager::HideMenu",)))
        if cycle:
            calls += (("Recursive", ("Recursive",)),)
        facts = tuple(SymbolSemanticFacts(sid(source), callees=tuple(sid(t) for t in targets)) for source, targets in calls)
        manifest = self.prebuild("expansion")
        snapshot = manifest.last_usable
        paths = tuple(sorted(self.git("ls-files").splitlines()))
        observation = self.source.observe(paths)
        identity = replace(snapshot.identity, revision=observation.revision)
        with SymbolIndex(self.artifacts / snapshot.artifacts.symbols.path) as index:
            index.rebuild(symbols, semantic_facts=facts, files=tuple(RepositoryFile.from_path(p) for p in paths))
            graph = project_index(index, repository_key=identity.repository, snapshot_key=snapshot.artifacts.graph.identity)
            domain = default_role_mapper().map(index, graph)
            graph = extract_framework_relations(index, graph, domain, self.source.workspace).graph
        if partial:
            graph = replace(graph, edges=tuple(e for e in graph.edges if not (
                e.identity.source.key == NS + "Close" and e.identity.target.key == NS + "Keyboard")))
        GraphStore(self.artifacts, repository_key=graph.repository_key, snapshot_key=graph.snapshot_key).save(graph)
        (self.artifacts / snapshot.artifacts.domain.path).write_text(json.dumps(domain.to_dict(), sort_keys=True), encoding="utf-8")

        def seal(reference):
            digest = hashlib.sha256((self.artifacts / reference.path).read_bytes()).hexdigest()
            return replace(reference, snapshot=identity, sha256=digest,
                           identity=reference.identity if reference.kind is ArtifactKind.GRAPH else "sha256:" + digest)

        artifacts = replace(snapshot.artifacts, **{name: seal(getattr(snapshot.artifacts, name))
                            for name in ("symbols", "tests", "graph", "domain")},
                            text=TextKnowledge("sha256:" + observation.fingerprint.sha256, identity,
                                               observation.fingerprint.sha256, "rg-source-v1"))
        scope = BuildScope(ScopeKind.SELECTED_FILES, tuple(p for p in paths if p.endswith((".h", ".cpp"))), (), paths)
        snapshot = replace(snapshot, identity=identity, scope=scope, source=observation.fingerprint,
                           artifacts=artifacts, configuration=replace(snapshot.configuration, domain_ruleset=domain.ruleset_identity),
                           build=replace(snapshot.build, source_sha256=observation.fingerprint.sha256))
        self.manifest = replace(manifest, last_usable=snapshot, latest_attempt=replace(manifest.latest_attempt, target=identity))
        self.write(self.manifest)
        self.requirement = QueryRequirement(identity.repository, identity.revision, scope, snapshot.configuration)
