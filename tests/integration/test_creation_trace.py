from __future__ import annotations

import hashlib
import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from arkui_agent.evaluation.environment import read_repository_revision
from arkui_agent.graph import default_role_mapper, extract_framework_relations, project_index
from arkui_agent.graph.creation import CreationStage, CreationStatus, trace_component_creation
from arkui_agent.graph.model import NodeIdentity
from arkui_agent.repository import ClangdSemanticProvider, RepositoryFile, RepositoryWorkspace, SymbolIndex, SymbolKind
from arkui_agent.repository.index import SymbolSemanticFacts
from tests.fixtures.creation_cases import CASES, FRAME_HEADER, ROOT, write_creation_repository
from tests.integration.test_reference_call_retrieval import configured_clangd


def collect_creation(workspace, cases, *, real):
    selected = {}
    documents = {}
    seeds = {}
    models = {}
    with ClangdSemanticProvider(
        workspace, executable=configured_clangd(), request_timeout=60,
        fallback_flags=("-std=c++17", f"-I{workspace.root}", f"-I{workspace.root / 'frameworks'}",
                        f"-I{workspace.root / 'interfaces/inner_api/ace'}",
                        f"-I{workspace.root / 'interfaces/inner_api/ace_kit/include'}"),
    ) as provider:
        for case in cases:
            paths = [case.entry_file]
            if real:
                paths.insert(0, f"{ROOT}/{case.component}/{case.component}_model_ng.cpp")
            for path in paths:
                found = provider.symbols_in_file(RepositoryFile.from_path(path))
                documents.update((s.identity, s) for s in found)
                if path == case.entry_file:
                    matches = [s for s in found if s.display_name == case.entry_name and s.kind == SymbolKind.FUNCTION]
                    if len(matches) != 1:
                        raise AssertionError(f"P1 entry query not unique: {case.entry_name}")
                    seeds[case.component] = matches[0].identity
                    selected[matches[0].identity] = matches[0]
        for case in cases:
            for suffix in ("model_ng", "pattern"):
                path = f"{ROOT}/{case.component}/{case.component}_{suffix}.h"
                found = provider.symbols_in_file(RepositoryFile.from_path(path))
                documents.update((s.identity, s) for s in found)
                class_name = case.component.title() + ("ModelNG" if suffix == "model_ng" else "Pattern")
                names = {f"OHOS::Ace::NG::{class_name}"}
                if suffix == "model_ng":
                    names.add(f"OHOS::Ace::NG::{class_name}::CreateFrameNode")
                if case.component == "menu" and suffix == "pattern" and real:
                    names.add("OHOS::Ace::NG::InnerMenuPattern")
                for name in names:
                    matches = [s for s in found if s.qualified_name == name]
                    if len(matches) != 1:
                        raise AssertionError(f"P1 symbol query not unique: {name}")
                    symbol = matches[0]
                    selected[symbol.identity] = symbol
                    if name.endswith("ModelNG::CreateFrameNode"):
                        models[case.component] = symbol.identity
        found = provider.symbols_in_file(RepositoryFile.from_path(FRAME_HEADER))
        documents.update((s.identity, s) for s in found)
        for symbol in found:
            if symbol.qualified_name in {"OHOS::Ace::NG::FrameNode", "OHOS::Ace::NG::FrameNode::CreateFrameNode",
                                         "OHOS::Ace::NG::FrameNode::GetOrCreateFrameNode"}:
                selected[symbol.identity] = symbol
        endpoints = {}
        calls = {}
        callers = {}
        for identity in tuple(seeds.values()) + tuple(models.values()):
            outgoing = provider.callees(identity)
            # Entry references include function-pointer table initializers,
            # which are not supporting callers of this creation path. Query
            # incoming semantic calls only at the Model boundary we need.
            incoming = provider.callers(identity) if identity in models.values() else ()
            endpoints.update((s.identity, documents.get(s.identity, s)) for s in outgoing + incoming)
            calls[identity] = tuple(s.identity for s in outgoing)
            callers[identity] = tuple(s.identity for s in incoming)
        symbols = {**endpoints, **selected}
        facts = tuple(SymbolSemanticFacts(identity, references=provider.references(identity),
                      callers=callers.get(identity, ()), callees=calls.get(identity, ())) for identity in symbols)
    return tuple(symbols.values()), facts, seeds


def run_creation_cases(test, workspace, cases, *, real):
    # Assertions are independent source-reviewed expectations, never filled
    # from graph output. A changed fixture/repository must be reviewed again.
    for case in cases:
        for path, line, expected in case.source_evidence:
            test.assertEqual(workspace.resolve(path).read_text(encoding="utf-8").splitlines()[line - 1].strip(), expected)
    symbols, facts, seeds = collect_creation(workspace, cases, real=real)
    names = {NodeIdentity.for_symbol(s.identity): s.qualified_name for s in symbols}
    files = {r.file.path.as_posix() for s in symbols for r in (s.declaration, s.definition) if r}
    hashes = {path: hashlib.sha256(workspace.resolve(path).read_bytes()).hexdigest() for path in sorted(files)}
    checks = []
    with TemporaryDirectory(prefix="creation-index-") as temporary:
        with SymbolIndex(Path(temporary) / "p1.sqlite3") as index:
            index.rebuild(symbols, semantic_facts=facts)
            generic = project_index(index, repository_key="creation-smoke", snapshot_key="p1")
            domain = default_role_mapper().map(index, generic)
            framework = extract_framework_relations(index, generic, domain, workspace).graph
            for case in cases:
                args = dict(seed=NodeIdentity.for_symbol(seeds[case.component]),
                            component=NodeIdentity("arkui.component", case.component))
                trace = trace_component_creation(index, framework, domain, workspace, **args)
                test.assertEqual(trace.status.value, case.expected_status, (case.component, trace))
                test.assertTrue(trace.exhaustive)
                test.assertEqual(len(trace.paths), 1)
                path = trace.paths[0]
                test.assertEqual(path.issues, case.expected_gaps)
                expected_names = [case.entry_namespace + "::" + case.entry_name,
                                  f"OHOS::Ace::NG::{case.component.title()}ModelNG::CreateFrameNode",
                                  f"OHOS::Ace::NG::FrameNode::{case.frame_method}"]
                if case.expected_status == "complete":
                    expected_names.append(f"OHOS::Ace::NG::{case.pattern}")
                    test.assertIsNotNone(path.pattern_argument)
                    test.assertEqual(path.nodes[-1].stage, CreationStage.PATTERN)
                else:
                    test.assertIn("unsupported_pattern_callback", path.issues)
                    test.assertIsNone(path.pattern_argument)
                    inner = next(s for s in symbols if s.qualified_name == "OHOS::Ace::NG::InnerMenuPattern")
                    test.assertIsNone(domain.lookup(NodeIdentity.for_symbol(inner.identity)).resolved)
                test.assertEqual([names[n.node.identity] for n in path.nodes], expected_names)
                test.assertEqual(len(path.relations), 2)
                for i, edge in enumerate(path.relations):
                    test.assertEqual(edge.identity.source, path.nodes[i].node.identity)
                    test.assertEqual(edge.identity.target, path.nodes[i + 1].node.identity)
                    test.assertTrue(all(e.provenance.startswith("p1.") for e in edge.evidence))
                test.assertTrue(all(n.evidence and any(a.source_range for a in n.node.anchors) for n in path.nodes))
                index.rebuild(reversed(symbols), semantic_facts=reversed(facts))
                rebuilt = project_index(index, repository_key="creation-smoke", snapshot_key="p1")
                test.assertEqual(trace, trace_component_creation(index, rebuilt, domain, workspace, **args))
                checks.append({"component": case.component, "expected_status": case.expected_status,
                    "status": trace.status.value, "expected_architecture": expected_names[:3] + [f"OHOS::Ace::NG::{case.pattern}"],
                    "actual_nodes": [names[n.node.identity] for n in path.nodes], "issues": path.issues,
                    "pattern_candidates": [item.value for item in path.pattern_candidates],
                    "node_evidence": [{"identity": n.node.identity.value, "stage": n.stage.value,
                                       "evidence": [e.sort_key for e in n.evidence]} for n in path.nodes],
                    "calls": [{"edge": e.identity.value, "evidence": [p.sort_key for p in e.evidence]} for e in path.relations],
                    "argument_evidence": [] if path.pattern_argument is None else [p.sort_key for p in path.pattern_argument.evidence],
                    "argument_relations": [] if path.pattern_argument is None else [
                        {"edge": e.identity.value, "evidence": [p.sort_key for p in e.evidence]}
                        for e in path.pattern_argument.supporting_relations],
                    "source_review": case.source_evidence})
    for path, digest in hashes.items():
        test.assertEqual(hashlib.sha256(workspace.resolve(path).read_bytes()).hexdigest(), digest)
    return {"checks": checks, "source_sha256": hashes}


class SyntheticCreationTests(unittest.TestCase):
    def test_complete_creation_via_real_p1_provider(self):
        with TemporaryDirectory(prefix="creation-cpp-") as temporary:
            cases = write_creation_repository(Path(temporary))
            run_creation_cases(self, RepositoryWorkspace(temporary), cases, real=False)


class RealCreationTests(unittest.TestCase):
    external_validation_requirements = ("ARKUI_REPO_ROOT",)

    def test_source_reviewed_button_text_menu_paths(self):
        if not os.environ.get("ARKUI_REPO_ROOT"):
            self.fail("P2-E requires real ArkUI creation trace validation.")
        workspace = RepositoryWorkspace(os.environ["ARKUI_REPO_ROOT"])
        report = run_creation_cases(self, workspace, CASES, real=True)
        report["repository_revision"] = read_repository_revision(workspace)
        output = Path(__file__).resolve().parents[2] / "var/validation/p2-e-creation-smoke.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
