from __future__ import annotations

import hashlib
import json
import os
import unittest
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory

from arkui_agent.evaluation.environment import read_repository_revision
from arkui_agent.graph import GraphStore, NodeIdentity, default_role_mapper, extract_framework_relations, project_index, trace_measure_layout
from arkui_agent.repository import ClangdSemanticProvider, RepositoryFile, RepositoryWorkspace, SymbolIdentity, SymbolIndex, SymbolKind
from arkui_agent.repository.index import SymbolSemanticFacts
from tests.fixtures.layout_cases import MENU_CANDIDATES, REAL_CHECKS, REAL_EXPECTED, ROOT, write_layout_repository
from tests.integration.test_reference_call_retrieval import configured_clangd


def collect_layout(workspace, *, real):
    selected, documents, seeds = {}, {}, {}
    with ClangdSemanticProvider(
        workspace, executable=configured_clangd(), request_timeout=60,
        fallback_flags=("-std=c++17", f"-I{workspace.root}", f"-I{workspace.root / 'frameworks'}",
                        f"-I{workspace.root / 'interfaces/inner_api/ace'}",
                        f"-I{workspace.root / 'interfaces/inner_api/ace_kit/include'}"),
    ) as provider:
        for name in ("Button", "Text", "Menu"):
            slug = name.lower()
            # Establish definition locations before header semantic parents.
            files = [f"{ROOT}/{slug}/{slug}_layout_algorithm.cpp"]
            if real:
                files.append(f"{ROOT}/{slug}/{slug}_pattern.cpp")
            for path in files:
                found = provider.symbols_in_file(RepositoryFile.from_path(path))
                documents.update((s.identity, s) for s in found)
            for suffix in ("pattern", "layout_algorithm", "layout_property"):
                path = f"{ROOT}/{slug}/{slug}_{suffix}.h"
                found = provider.symbols_in_file(RepositoryFile.from_path(path))
                documents.update((s.identity, s) for s in found)
                owner = "OHOS::Ace::NG::" + name + {"pattern": "Pattern", "layout_algorithm": "LayoutAlgorithm",
                                                    "layout_property": "LayoutProperty"}[suffix]
                for symbol in found:
                    if symbol.qualified_name == owner or (symbol.parent_identity and
                            symbol.qualified_name.startswith(owner + "::") and symbol.display_name in
                            {"CreateLayoutAlgorithm", "Measure", "MeasureContent", "Layout"}):
                        selected[symbol.identity] = symbol
                    if symbol.qualified_name == "OHOS::Ace::NG::" + name + "Pattern":
                        seeds[name] = symbol.identity
        if real:
            for filename, owner in (("multi_menu_layout_algorithm.h", "MultiMenuLayoutAlgorithm"),
                                    ("sub_menu_layout_algorithm.h", "SubMenuLayoutAlgorithm")):
                found = provider.symbols_in_file(RepositoryFile.from_path(f"{ROOT}/menu/{filename}"))
                matches = [s for s in found if s.qualified_name == "OHOS::Ace::NG::" + owner]
                if len(matches) != 1:
                    raise AssertionError(f"P1 did not resolve {owner}")
                selected[matches[0].identity] = matches[0]
        calls, endpoints = {}, {}
        for symbol in tuple(selected.values()):
            # The real smoke indexes the factory allocation CALL slice. Full
            # operation callee inventories open many unrelated documents and
            # exceed the current synchronous provider's close-notification
            # pipe capacity. Operation DEFINE/REFERENCE/parent facts remain
            # real; synthetic integration covers operation CALL preservation.
            if symbol.kind == SymbolKind.METHOD and (not real or symbol.display_name == "CreateLayoutAlgorithm"):
                found = provider.callees(symbol.identity)
                calls[symbol.identity] = tuple(s.identity for s in found)
                endpoints.update((s.identity, documents.get(s.identity, s)) for s in found)
        symbols = {**endpoints, **selected}
        # Only relevant class references are necessary for layout identity.
        facts = tuple(SymbolSemanticFacts(s.identity,
                      references=provider.references(s.identity) if s.identity in selected and s.kind == SymbolKind.CLASS else (),
                      callees=calls.get(s.identity, ())) for s in symbols.values())
    return tuple(symbols.values()), facts, seeds


def run_layout_cases(test, workspace, *, real):
    checks = []
    if real:
        for file, line, expected in REAL_CHECKS:
            actual = workspace.resolve(f"{ROOT}/{file}").read_text(encoding="utf-8").splitlines()[line - 1].strip()
            test.assertIn(expected, actual, (file, line, actual))
            checks.append({"file": f"{ROOT}/{file}", "line": line, "expected": expected, "source": actual})
        for slug in ("button", "text"):
            header = workspace.resolve(f"{ROOT}/{slug}/{slug}_layout_algorithm.h").read_text(encoding="utf-8")
            test.assertNotIn("void Layout(", header)
    # Expectations above are independent of graph output and checked first.
    symbols, facts, seeds = collect_layout(workspace, real=real)
    files = {r.file.path.as_posix() for s in symbols for r in (s.declaration, s.definition) if r}
    files.update(c["file"] for c in checks)
    hashes = {p: hashlib.sha256(workspace.resolve(p).read_bytes()).hexdigest() for p in sorted(files)}
    results = []
    with TemporaryDirectory(prefix="layout-index-") as temporary:
        with SymbolIndex(Path(temporary) / "p1.sqlite3") as index:
            index.rebuild(symbols, semantic_facts=facts)
            generic = project_index(index, repository_key="layout-smoke", snapshot_key="p1")
            domain = default_role_mapper().map(index, generic)
            graph = extract_framework_relations(index, generic, domain, workspace).graph
            store = GraphStore(Path(temporary), repository_key=graph.repository_key, snapshot_key=graph.snapshot_key)
            store.save(graph)
            for name, identity in seeds.items():
                args = dict(seed=NodeIdentity.for_symbol(identity), component=NodeIdentity("arkui.component", name.lower()))
                trace = trace_measure_layout(index, graph, domain, workspace, **args)
                expected = REAL_EXPECTED[name] if real else (
                    "complete", ("pattern", "factory", "algorithm", "measure", "layout", "layout_property"), ())
                test.assertEqual((trace.status.value, tuple(s.stage.value for s in trace.stages), trace.gaps), expected)
                # Check identities against the source-reviewed names, not only
                # stage labels. Names here assert results; query uses P1 IDs.
                expected_names = [name + "Pattern", name + "Pattern::CreateLayoutAlgorithm"]
                if name == "Button" or not real:
                    expected_names += [name + "LayoutAlgorithm", name + "LayoutAlgorithm::Measure"]
                    if not real:
                        expected_names += [name + "LayoutAlgorithm::Layout"]
                    expected_names += [name + "LayoutProperty"]
                test.assertEqual([index.get(SymbolIdentity(s.candidates[0].node.identity.key)).qualified_name
                                  for s in trace.stages], ["OHOS::Ace::NG::" + n for n in expected_names])
                test.assertTrue(trace.exhaustive, trace.gaps)
                if name == "Button" or not real:
                    test.assertEqual(len(trace.dependencies), 1 if real else 2)
                    test.assertEqual([e.identity.relation.value for e in trace.bindings],
                                     ["CREATE", "MEASURE"] if real else ["CREATE", "MEASURE", "LAYOUT"])
                    test.assertTrue(all(d.property_class == trace.stages[-1].candidates[0].node.identity
                                        for d in trace.dependencies))
                    if not real:
                        test.assertTrue(all(any(e.identity.source == d.operation for e in trace.calls)
                                            for d in trace.dependencies))
                if real and name == "Menu":
                    test.assertEqual(tuple(sorted(c.node.display_name.rsplit("::", 1)[-1] for c in trace.candidates)), MENU_CANDIDATES)
                    test.assertFalse(trace.bindings)
                test.assertTrue(all(n.evidence for stage in trace.stages for n in stage.candidates))
                index.rebuild(reversed(symbols), semantic_facts=reversed(facts))
                test.assertEqual(trace_measure_layout(index, store.load(), domain, workspace, **args), trace)
                results.append({"component": name, "expected": expected, "trace": asdict(trace)})
    for file, digest in hashes.items():
        test.assertEqual(hashlib.sha256(workspace.resolve(file).read_bytes()).hexdigest(), digest)
    return {"frozen_source_checks": checks, "traces": results, "source_sha256": hashes}


class SyntheticLayoutTests(unittest.TestCase):
    def test_clangd_layout_pipeline(self):
        with TemporaryDirectory(prefix="layout-cpp-") as temporary:
            write_layout_repository(Path(temporary))
            run_layout_cases(self, RepositoryWorkspace(temporary), real=False)


class RealLayoutSmokeTests(unittest.TestCase):
    external_validation_requirements = ("ARKUI_REPO_ROOT",)

    def test_frozen_button_text_menu_layout(self):
        if not os.environ.get("ARKUI_REPO_ROOT"):
            self.fail("P2-G requires real ARKUI_REPO_ROOT validation.")
        workspace = RepositoryWorkspace(os.environ["ARKUI_REPO_ROOT"])
        report = run_layout_cases(self, workspace, real=True)
        report["repository_revision"] = read_repository_revision(workspace)
        path = Path(__file__).resolve().parents[2] / "var/validation/p2-g-layout-smoke.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
