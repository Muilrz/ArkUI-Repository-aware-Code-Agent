from __future__ import annotations

import hashlib
import json
import os
import unittest
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory

from arkui_agent.evaluation.environment import read_repository_revision
from arkui_agent.graph import GraphStore, NodeIdentity, default_role_mapper, extract_framework_relations, project_index, trace_overlay
from arkui_agent.repository import ClangdSemanticProvider, RepositoryFile, RepositoryWorkspace, SymbolIdentity, SymbolIndex, SymbolKind
from arkui_agent.repository.index import SymbolSemanticFacts
from tests.fixtures.overlay_cases import (
    ANIMATION_H, ENTRY_CPP, FRAME_H, MANAGER_CPP, MANAGER_H, MENU_CPP, NS, PATTERN_H,
    REAL_ANIMATION, REAL_CHECKS, REAL_CLOSE, REAL_GAPS, REAL_SEED_DEFINITIONS, REAL_SHOW, REAL_STAGES,
    write_overlay_repository,
)
from tests.integration.test_reference_call_retrieval import configured_clangd


def collect_overlay(workspace, *, real):
    selected, documents = {}, {}
    with ClangdSemanticProvider(
        workspace, executable=configured_clangd(), request_timeout=60,
        fallback_flags=("-std=c++17", f"-I{workspace.root}", f"-I{workspace.root / 'frameworks'}",
                        f"-I{workspace.root / 'interfaces/inner_api/ace'}",
                        f"-I{workspace.root / 'interfaces/inner_api/ace_kit/include'}"),
    ) as provider:
        sources = (ENTRY_CPP, MENU_CPP, MANAGER_CPP) if real else ("overlay_entry.cpp", MANAGER_CPP)
        requested = set(REAL_SHOW + tuple(n for path in REAL_CLOSE for n in path)) if real else {
            NS + n for n in ("Open", "Close", "Dismiss", "Keyboard", "OverlayManager::ShowMenu", "OverlayManager::HideMenu",
                            "MenuPattern::OnModifyDone")}
        requested.update({NS + "OverlayManager", NS + "FrameNode", NS + "MenuPattern"})
        if not real:
            requested.add("OHOS::Ace::AnimationUtils::Animate")
        for path in sources + (MANAGER_H, FRAME_H, PATTERN_H) + (() if real else (ANIMATION_H,)):
            found = provider.symbols_in_file(RepositoryFile.from_path(path))
            documents.update((s.identity, s) for s in found)
            selected.update((s.identity, s) for s in found if s.qualified_name in requested)
        calls, callers, endpoints = {}, {}, {}
        for symbol in tuple(selected.values()):
            if symbol.kind not in {SymbolKind.METHOD, SymbolKind.FUNCTION}:
                continue
            if real:
                if symbol.qualified_name not in {NS + "OverlayManager::ShowMenu", NS + "OverlayManager::HideMenu"}:
                    continue
                # Incoming P1 calls provide the frozen entry -> operation
                # edges without collecting unrelated entry callee inventories.
                incoming = provider.callers(symbol.identity)
                callers[symbol.identity] = tuple(s.identity for s in incoming)
                endpoints.update((s.identity, documents.get(s.identity, s)) for s in incoming)
            else:
                outgoing = provider.callees(symbol.identity)
                calls[symbol.identity] = tuple(s.identity for s in outgoing)
                endpoints.update((s.identity, documents.get(s.identity, s)) for s in outgoing)
        symbols = {**endpoints, **selected}
        reference_ids = {s.identity for s in selected.values() if s.kind == SymbolKind.CLASS or not real}
        facts = tuple(SymbolSemanticFacts(s.identity,
                      references=provider.references(s.identity) if s.identity in reference_ids else (),
                      callers=callers.get(s.identity, ()), callees=calls.get(s.identity, ())) for s in symbols.values())
    return tuple(symbols.values()), facts


def run_overlay_case(test, workspace, *, real, animation=False, multiple_close=False):
    checks = []
    if real:
        # Check independently frozen source facts before collecting/querying.
        for file, line, fragment in REAL_CHECKS:
            actual = workspace.resolve(file).read_text(encoding="utf-8").splitlines()[line - 1].strip()
            test.assertIn(fragment, actual, (file, line, actual))
            checks.append({"file": file, "line": line, "expected_fragment": fragment, "source": actual})
    symbols, facts = collect_overlay(workspace, real=real)

    def identity(name):
        anchor = REAL_SEED_DEFINITIONS.get(name) if real else None
        matches = [s.identity for s in symbols if s.qualified_name == name and
                   (anchor is None or s.definition and
                    (s.definition.file.path.as_posix(), s.definition.start.line) == anchor)]
        test.assertEqual(len(matches), 1, name)
        return NodeIdentity.for_symbol(matches[0])

    args = dict(manager=identity(NS + "OverlayManager"), component=NodeIdentity("arkui.component", "menu"),
                show_seed=identity(REAL_SHOW[0] if real else NS + "Open"),
                close_seeds=tuple(identity(p[0]) for p in REAL_CLOSE) if real else (identity(NS + "Close"),))
    files = {r.file.path.as_posix() for s in symbols for r in (s.declaration, s.definition) if r}
    files.update(c["file"] for c in checks)
    hashes = {p: hashlib.sha256(workspace.resolve(p).read_bytes()).hexdigest() for p in sorted(files)}
    with TemporaryDirectory(prefix="overlay-index-") as temporary:
        with SymbolIndex(Path(temporary) / "index.sqlite3") as index:
            index.rebuild(symbols, semantic_facts=facts)
            generic = project_index(index, repository_key="overlay-smoke", snapshot_key="p1")
            domain = default_role_mapper().map(index, generic)
            graph = extract_framework_relations(index, generic, domain, workspace).graph
            store = GraphStore(Path(temporary), repository_key=graph.repository_key, snapshot_key=graph.snapshot_key)
            store.save(graph)
            trace = trace_overlay(index, graph, domain, workspace, **args)
            test.assertEqual(trace.status.value, "ambiguous" if real or multiple_close else "complete")
            test.assertEqual(trace.show.status.value, "incomplete" if real else "complete")
            test.assertEqual(trace.close.status.value, "ambiguous" if real or multiple_close else "complete")
            test.assertTrue(trace.show.exhaustive and trace.close.exhaustive)
            test.assertEqual(len(trace.show.paths), 1)
            test.assertEqual(len(trace.close.paths), 2 if real or multiple_close else 1)
            for leg in (trace.show, trace.close):
                for path in leg.paths:
                    test.assertEqual(path.binding.identity.relation, leg.operation)
                    test.assertEqual(path.gaps, REAL_GAPS if real else ())
                    test.assertEqual(path.animation.value, REAL_ANIMATION if real else
                                     "present" if animation else "not_observed_in_supported_body")
                    test.assertTrue(all(n.evidence for n in path.nodes))
                    test.assertTrue(all(e.evidence for e in path.calls + path.support))
                    test.assertTrue(all("sha256=" in p.description for p in path.source_evidence))
                    if real:
                        test.assertEqual(tuple(n.stage.value for n in path.nodes), REAL_STAGES)
                        names = tuple(index.get(SymbolIdentity(i.key)).qualified_name for i in
                                      (path.calls[0].identity.source,) + tuple(e.identity.target for e in path.calls))
                        test.assertIn(names, (REAL_SHOW,) if leg is trace.show else REAL_CLOSE)
                    else:
                        test.assertIn("pattern", [n.stage.value for n in path.nodes])
                        test.assertEqual("animation" in [n.stage.value for n in path.nodes], animation)
            index.rebuild(reversed(symbols), semantic_facts=reversed(facts))
            test.assertEqual(trace_overlay(index, store.load(), domain, workspace, **args), trace)
    for file, digest in hashes.items():
        test.assertEqual(hashlib.sha256(workspace.resolve(file).read_bytes()).hexdigest(), digest)
    return {"frozen_source_checks": checks, "source_sha256": hashes, "trace": asdict(trace),
            "downstream_source_observations": {
                "animated_close": "MenuManager::HideMenu -> PopMenuAnimation; AnimationUtils::Animate exists downstream",
                "without_animation_close": "MenuManager::HideAllMenusWithoutAnimation removes managed children",
                "trace_boundary": "Neither observation crosses unresolved modifier dispatch; animation remains unresolved",
            } if real else {}}


class SyntheticOverlayTests(unittest.TestCase):
    def test_show_close_without_animation(self):
        with TemporaryDirectory(prefix="overlay-cpp-") as temporary:
            write_overlay_repository(Path(temporary))
            run_overlay_case(self, RepositoryWorkspace(temporary), real=False)

    def test_animation_and_multiple_close_paths(self):
        with TemporaryDirectory(prefix="overlay-cpp-") as temporary:
            write_overlay_repository(Path(temporary), animation=True, multiple_close=True)
            run_overlay_case(self, RepositoryWorkspace(temporary), real=False, animation=True, multiple_close=True)


class RealOverlaySmokeTests(unittest.TestCase):
    external_validation_requirements = ("ARKUI_REPO_ROOT",)

    def test_frozen_menu_show_and_two_close_entries(self):
        if not os.environ.get("ARKUI_REPO_ROOT"):
            self.fail("P2-H requires real ARKUI_REPO_ROOT validation.")
        workspace = RepositoryWorkspace(os.environ["ARKUI_REPO_ROOT"])
        report = run_overlay_case(self, workspace, real=True)
        report["repository_revision"] = read_repository_revision(workspace)
        path = Path(__file__).resolve().parents[2] / "var/validation/p2-h-overlay-smoke.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
