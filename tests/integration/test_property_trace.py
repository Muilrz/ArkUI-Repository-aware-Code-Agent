from __future__ import annotations

import hashlib
import json
import os
import unittest
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory

from arkui_agent.evaluation.environment import read_repository_revision
from arkui_agent.graph import (
    GraphStore, NodeIdentity, PropertyStatus, default_role_mapper, extract_framework_relations,
    project_index, trace_property_update,
)
from arkui_agent.repository import ClangdSemanticProvider, RepositoryFile, RepositoryWorkspace, SymbolIndex, SymbolKind
from arkui_agent.repository.index import SymbolSemanticFacts
from tests.fixtures.property_cases import (
    MACROS, NATIVE_EXPECTED, NATIVE_GAPS, REAL_CASES, ROOT, STACK_EXPECTED, STACK_GAPS, write_property_repository,
)
from tests.integration.test_reference_call_retrieval import configured_clangd


def collect_property(workspace, *, real):
    selected, documents, seeds, setters, stack_setters = {}, {}, {}, {}, {}
    with ClangdSemanticProvider(
        workspace, executable=configured_clangd(), request_timeout=60,
        fallback_flags=("-std=c++17", f"-I{workspace.root}", f"-I{workspace.root / 'frameworks'}",
                        f"-I{workspace.root / 'interfaces/inner_api/ace'}",
                        f"-I{workspace.root / 'interfaces/inner_api/ace_kit/include'}"),
    ) as provider:
        for case in REAL_CASES:
            slug = case.component.lower()
            entry_file = case.entry_file if real else f"{ROOT}/{slug}/property_entry.cpp"
            files = [entry_file]
            if real:
                files = [f"{ROOT}/{slug}/{slug}_model_ng.cpp", case.consumer_file] + files
            for file in files:
                found = provider.symbols_in_file(RepositoryFile.from_path(file))
                documents.update((s.identity, s) for s in found)
                if file == entry_file:
                    name = case.entry if real else "Apply" + case.component + "Weight"
                    matches = [s for s in found if s.display_name == name and s.kind == SymbolKind.FUNCTION]
                    if len(matches) != 1:
                        raise AssertionError(f"Non-unique P1 entry: {name}")
                    selected[matches[0].identity] = matches[0]
                    seeds[slug] = matches[0].identity
                    if not real:
                        selected.update((s.identity, s) for s in found if s.display_name == "Consume" + case.component + "Weight")
            kind = "Paint" if not real and slug == "menu" else "Layout"
            for suffix, owner in (("model_ng", case.component + "ModelNG"),
                                  (kind.lower() + "_property", case.component + kind + "Property")):
                file = f"{ROOT}/{slug}/{slug}_{suffix}.h"
                found = provider.symbols_in_file(RepositoryFile.from_path(file))
                documents.update((s.identity, s) for s in found)
                for symbol in found:
                    qualified = "OHOS::Ace::NG::" + owner
                    if (symbol.qualified_name == qualified or
                            symbol.qualified_name.startswith(qualified + "::") and
                            (not real or "FontWeight" in symbol.display_name or symbol.display_name == "InspectorGetTextFont")):
                        selected[symbol.identity] = symbol
                    if symbol.qualified_name == qualified + "::SetFontWeight":
                        if real:
                            if symbol.definition and symbol.definition.start.line == case.native_line:
                                setters[slug] = symbol.identity
                            if symbol.definition and symbol.definition.start.line == case.stack_line:
                                stack_setters[slug] = symbol.identity
                        elif symbol.definition and symbol.definition.start.line == 7:
                            setters[slug] = symbol.identity
        if set(setters) != {"button", "text", "menu"} or real and len(stack_setters) != 3:
            raise AssertionError(f"P1 did not resolve exact setter definition anchors: {setters}, {stack_setters}")
        endpoints, calls, callers = {}, {}, {}
        identities = tuple(seeds.values()) + tuple(setters.values()) + tuple(stack_setters.values())
        if not real:
            identities += tuple(s.identity for s in selected.values() if s.display_name.startswith("Consume"))
        for identity in identities:
            outgoing = provider.callees(identity)
            incoming = provider.callers(identity) if identity in setters.values() else ()
            endpoints.update((s.identity, documents.get(s.identity, s)) for s in outgoing + incoming)
            calls[identity] = tuple(s.identity for s in outgoing)
            callers[identity] = tuple(s.identity for s in incoming)
        symbols = {**endpoints, **selected}
        facts = tuple(SymbolSemanticFacts(identity, references=provider.references(identity),
                      callers=callers.get(identity, ()), callees=calls.get(identity, ())) for identity in symbols)
    return tuple(symbols.values()), facts, seeds, setters, stack_setters


def frozen_source_checks(test, workspace):
    checks = []
    for case in REAL_CASES:
        slug = case.component.lower()
        model = f"{ROOT}/{slug}/{slug}_model_ng.cpp"
        prop = f"{ROOT}/{slug}/{slug}_layout_property.h"
        for file, line, expected in (
            (case.entry_file, case.entry_line, "void " + case.entry + "("),
            (case.entry_file, case.call_line, case.component + "ModelNG::SetFontWeight(frameNode,"),
            (model, case.native_line, case.component + "ModelNG::SetFontWeight(FrameNode* frameNode,"),
            (model, case.native_line + 2, "ACE_UPDATE_NODE_LAYOUT_PROPERTY(" + case.component + "LayoutProperty, FontWeight,"),
            (model, case.stack_line + 2, "ACE_UPDATE_LAYOUT_PROPERTY(" + case.component + "LayoutProperty, FontWeight,"),
            (prop, case.property_line, "FontWeight,"),
            (case.consumer_file, case.consumer_line, "GetFontWeight().value()"),
        ):
            actual = workspace.resolve(file).read_text(encoding="utf-8").splitlines()[line - 1].strip()
            test.assertIn(expected, actual, (file, line, actual))
            checks.append({"file": file, "line": line, "expected_fragment": expected, "source": actual})
    return checks


def run_property_cases(test, workspace, *, real):
    # Freeze/check source before collecting P1 facts and before any trace query.
    checks = frozen_source_checks(test, workspace) if real else []
    symbols, facts, seeds, setters, stack_setters = collect_property(workspace, real=real)
    files = {r.file.path.as_posix() for s in symbols for r in (s.declaration, s.definition) if r}
    files.update(c["file"] for c in checks)
    files.add(MACROS)
    hashes = {p: hashlib.sha256(workspace.resolve(p).read_bytes()).hexdigest() for p in sorted(files)}
    traces = []
    with TemporaryDirectory(prefix="property-index-") as temporary:
        with SymbolIndex(Path(temporary) / "index.sqlite3") as index:
            index.rebuild(symbols, semantic_facts=facts)
            generic = project_index(index, repository_key="property-smoke", snapshot_key="p1")
            domain = default_role_mapper().map(index, generic)
            graph = extract_framework_relations(index, generic, domain, workspace).graph
            store = GraphStore(Path(temporary), repository_key=graph.repository_key, snapshot_key=graph.snapshot_key)
            store.save(graph)
            test.assertEqual(store.load(), graph)
            for case in REAL_CASES:
                slug = case.component.lower()
                modes = ("native", "stack") if real else ("synthetic",)
                for mode in modes:
                    setter = stack_setters[slug] if mode == "stack" else setters[slug]
                    args = dict(seed=NodeIdentity.for_symbol(setter if mode == "stack" else seeds[slug]),
                                setter=NodeIdentity.for_symbol(setter), component=NodeIdentity("arkui.component", slug))
                    trace = trace_property_update(index, graph, domain, workspace, **args)
                    test.assertEqual(trace.status, PropertyStatus.INCOMPLETE if real else PropertyStatus.COMPLETE, trace)
                    test.assertTrue(trace.exhaustive)
                    test.assertEqual(len(trace.paths), 1)
                    path = trace.paths[0]
                    expected = STACK_EXPECTED if mode == "stack" else NATIVE_EXPECTED
                    if real:
                        test.assertEqual(tuple(n.stage.value for n in path.nodes), expected)
                        test.assertEqual(path.gaps, STACK_GAPS if mode == "stack" else NATIVE_GAPS)
                        test.assertNotEqual(setters[slug], stack_setters[slug])
                    else:
                        kind = "paint_property" if slug == "menu" else "layout_property"
                        test.assertEqual(tuple(n.stage.value for n in path.nodes),
                                         ("entry", "model", kind, "writer", "state", "reader", "consumer"))
                    if path.binding:
                        test.assertEqual(path.binding.token, "FontWeight")
                        test.assertTrue(any(e.provenance.startswith("p1.") for e in path.binding.relation.evidence))
                    test.assertTrue(all(n.evidence for n in path.nodes))
                    # Rebuild/reload preserve identity, evidence and candidate ordering.
                    index.rebuild(reversed(symbols), semantic_facts=reversed(facts))
                    test.assertEqual(trace_property_update(index, store.load(), domain, workspace, **args), trace)
                    traces.append({"component": slug, "mode": mode, "trace": asdict(trace)})
    for file, digest in hashes.items():
        test.assertEqual(hashlib.sha256(workspace.resolve(file).read_bytes()).hexdigest(), digest)
    return {"property": "FontWeight", "frozen_source_checks": checks, "traces": traces, "source_sha256": hashes}


class SyntheticPropertyTests(unittest.TestCase):
    def test_real_provider_property_update_and_read_paths(self):
        with TemporaryDirectory(prefix="property-cpp-") as temporary:
            write_property_repository(Path(temporary))
            run_property_cases(self, RepositoryWorkspace(temporary), real=False)


class RealPropertySmokeTests(unittest.TestCase):
    external_validation_requirements = ("ARKUI_REPO_ROOT",)

    def test_button_text_menu_frozen_property_paths(self):
        if not os.environ.get("ARKUI_REPO_ROOT"):
            self.fail("P2-F requires real ARKUI_REPO_ROOT validation.")
        workspace = RepositoryWorkspace(os.environ["ARKUI_REPO_ROOT"])
        report = run_property_cases(self, workspace, real=True)
        report["repository_revision"] = read_repository_revision(workspace)
        path = Path(__file__).resolve().parents[2] / "var/validation/p2-f-property-smoke.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
