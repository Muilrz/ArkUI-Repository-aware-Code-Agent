from __future__ import annotations

import hashlib
import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from arkui_agent.evaluation.environment import read_repository_revision
from arkui_agent.graph import (
    GraphStore, NodeIdentity, RelationType, default_role_mapper, extract_framework_relations, project_index,
)
from arkui_agent.repository import ClangdSemanticProvider, RepositoryFile, RepositoryWorkspace, SymbolIndex
from arkui_agent.repository.index import SymbolSemanticFacts
from tests.fixtures.framework_repository import ROOT, queries, write_repository
from tests.integration.test_reference_call_retrieval import configured_clangd


def collect(workspace: RepositoryWorkspace, *, real: bool):
    selected = {}
    callees = {}
    query_files = queries()
    with ClangdSemanticProvider(
        workspace, executable=configured_clangd(), request_timeout=60,
        fallback_flags=("-std=c++17", f"-I{workspace.root}", f"-I{workspace.root / 'frameworks'}",
                        f"-I{workspace.root / 'interfaces/inner_api/ace'}",
                        f"-I{workspace.root / 'interfaces/inner_api/ace_kit/include'}"),
    ) as provider:
        # Open implementations before querying headers so P1 can retrieve the
        # definition range and the header's semantic parent without rewriting P1.
        if real:
            for slug in ("button", "text", "menu"):
                provider.symbols_in_file(RepositoryFile.from_path(f"{ROOT}/{slug}/{slug}_model_ng.cpp"))
            provider.symbols_in_file(RepositoryFile.from_path(f"{ROOT}/text/text_pattern.cpp"))
        for path, names in sorted(query_files.items()):
            symbols = provider.symbols_in_file(RepositoryFile.from_path(path))
            for name in names:
                matches = [s for s in symbols if s.qualified_name == name]
                if not matches:
                    raise AssertionError(f"P1 did not resolve {name} in {path}")
                for symbol in matches:
                    selected[symbol.identity] = symbol
        calls = {}
        for symbol in tuple(selected.values()):
            if symbol.qualified_name.endswith("::CreateLayoutProperty"):
                found = provider.callees(symbol.identity)
                calls[symbol.identity] = tuple(s.identity for s in found)
                callees.update((s.identity, s) for s in found)
        # Preserve the richer document records when a call endpoint already
        # has the same P1 identity. Never resolve overloads by name alone.
        symbols = {**callees, **selected}
        facts = tuple(SymbolSemanticFacts(s.identity, provider.references(s.identity),
                                          callees=calls.get(s.identity, ())) for s in symbols.values())
    return tuple(symbols.values()), facts


def run_cases(test: unittest.TestCase, workspace: RepositoryWorkspace, *, real: bool):
    symbols, facts = collect(workspace, real=real)
    files = sorted({r.file.path.as_posix() for s in symbols for r in (s.declaration, s.definition) if r})
    hashes = {path: hashlib.sha256(workspace.resolve(path).read_bytes()).hexdigest() for path in files}
    with TemporaryDirectory(prefix="framework-index-") as temporary:
        with SymbolIndex(Path(temporary) / "p1.sqlite3") as index:
            index.rebuild(symbols, semantic_facts=facts)
            generic = project_index(index, repository_key="framework-smoke", snapshot_key="p1")
            domain = default_role_mapper().map(index, generic)
            result = extract_framework_relations(index, generic, domain, workspace)
            index.rebuild(reversed(symbols), semantic_facts=reversed(facts))
            rebuilt = project_index(index, repository_key="framework-smoke", snapshot_key="p1")
            test.assertEqual(result, extract_framework_relations(index, rebuilt, domain, workspace))
            store = GraphStore(Path(temporary), repository_key="framework-smoke", snapshot_key="p1")
            store.save(result.graph)
            original_bytes = store.path.read_bytes()
            store.save(extract_framework_relations(index, rebuilt, domain, workspace).graph)
            test.assertEqual(store.path.read_bytes(), original_bytes)
            test.assertEqual(store.load(), result.graph)
            store.delete()
    by_id = {NodeIdentity.for_symbol(s.identity): s.qualified_name for s in symbols}
    primitives = [e for e in result.graph.edges if e.identity.relation in {
        RelationType.CREATE, RelationType.UPDATE_PROPERTY, RelationType.MEASURE,
        RelationType.LAYOUT, RelationType.SHOW, RelationType.CLOSE,
    }]
    actual = {(by_id[e.identity.source], by_id[e.identity.target], e.identity.relation.value) for e in primitives}
    expected = set()
    for component in ("Button", "Text", "Menu"):
        prefix = f"OHOS::Ace::NG::{component}"
        expected.add((prefix + "Pattern::CreateLayoutProperty", prefix + "LayoutProperty", "CREATE"))
        expected.add((prefix + "ModelNG::SetFontWeight", prefix + "LayoutProperty", "UPDATE_PROPERTY"))
        method = "MeasureContent" if component == "Text" else "Measure"
        expected.add((prefix + "LayoutAlgorithm", prefix + "LayoutAlgorithm::" + method, "MEASURE"))
    expected.add(("OHOS::Ace::NG::MenuLayoutAlgorithm", "OHOS::Ace::NG::MenuLayoutAlgorithm::Layout", "LAYOUT"))
    for name, relation in (("ShowMenu", "SHOW"), ("HideMenu", "CLOSE")):
        expected.add(("OHOS::Ace::NG::OverlayManager", "OHOS::Ace::NG::OverlayManager::" + name, relation))
    test.assertEqual(actual, expected, [d for d in result.diagnostics if d.rule != "role"])
    test.assertEqual(len(primitives), len(expected), "Unexpected extra overload identities produced domain edges")
    for edge in primitives:
        test.assertTrue(any(e.provenance.startswith("p1.") for e in edge.evidence))
        test.assertTrue(any(e.provenance.endswith(".generic") for e in edge.evidence))
        test.assertTrue(any(e.provenance.startswith("arkui.role.") for e in edge.evidence))
        test.assertTrue(any("sha256=" in e.description for e in edge.evidence))
    test.assertFalse(any(e.identity.relation == RelationType.MOCK for e in result.graph.edges))
    for path, digest in hashes.items():
        test.assertEqual(hashlib.sha256(workspace.resolve(path).read_bytes()).hexdigest(), digest)
    return {"checks": sorted(actual), "domain_edges": len(primitives), "source_sha256": hashes,
            "diagnostics": [{"subject": d.subject.value, "rule": d.rule, "reason": d.reason}
                            for d in result.diagnostics],
            "provenance": [{"edge": e.identity.value, "evidence": [
                {"provenance": p.provenance, "description": p.description,
                 "anchor": p.anchor.sort_key} for p in e.evidence]} for e in primitives]}


class SyntheticFrameworkTests(unittest.TestCase):
    def test_real_provider_projection_and_extraction(self):
        with TemporaryDirectory(prefix="framework-cpp-") as temporary:
            write_repository(Path(temporary))
            run_cases(self, RepositoryWorkspace(temporary), real=False)


class RealFrameworkSmokeTests(unittest.TestCase):
    external_validation_requirements = ("ARKUI_REPO_ROOT",)

    def test_button_text_menu_framework_relations(self):
        if not os.environ.get("ARKUI_REPO_ROOT"):
            self.fail("P2-D requires real ARKUI_REPO_ROOT validation.")
        workspace = RepositoryWorkspace(os.environ["ARKUI_REPO_ROOT"])
        report = run_cases(self, workspace, real=True)
        report["repository_revision"] = read_repository_revision(workspace)
        path = Path(__file__).resolve().parents[2] / "var/validation/p2-d-framework-smoke.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
