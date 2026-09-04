from __future__ import annotations

import hashlib
import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from arkui_agent.evaluation.environment import read_repository_revision, read_tool_version
from arkui_agent.graph import MappingStatus, NodeIdentity, default_role_mapper, project_index
from arkui_agent.repository import (
    ClangdSemanticProvider, RepositoryFile, RepositoryWorkspace, SymbolIndex, SymbolKind,
)
from tests.fixtures.arkui_role_cases import NEGATIVE_CASES, ROLE_CASES
from tests.integration.test_reference_call_retrieval import configured_clangd


def run_role_cases(test: unittest.TestCase, workspace: RepositoryWorkspace) -> dict[str, object]:
    """Real P1 provider -> index -> P2 projection -> domain metadata.

    The selected names are retrieval queries. Expected roles/associations never
    enter index construction or role mapping.
    """
    queries = {(name, path) for _, name, _, path in ROLE_CASES} | set(NEGATIVE_CASES)
    files = sorted({path for _, path in queries})
    originals = {path: hashlib.sha256(workspace.resolve(path).read_bytes()).hexdigest() for path in files}
    symbols = []
    with ClangdSemanticProvider(
        workspace, executable=configured_clangd(), request_timeout=60,
        fallback_flags=("-std=c++17", f"-I{workspace.root}", f"-I{workspace.root / 'frameworks'}",
                        f"-I{workspace.root / 'interfaces/inner_api/ace'}",
                        f"-I{workspace.root / 'interfaces/inner_api/ace_kit/include'}"),
    ) as provider:
        for path in files:
            found = provider.symbols_in_file(RepositoryFile.from_path(path))
            for name, _ in sorted(query for query in queries if query[1] == path):
                matches = {s.identity: s for s in found
                           if s.kind == SymbolKind.CLASS and s.qualified_name == f"OHOS::Ace::NG::{name}"}
                test.assertEqual(len(matches), 1, f"P1 class query {name} in {path}")
                symbols.extend(matches.values())
    with TemporaryDirectory(prefix="role-index-") as temporary:
        database = Path(temporary) / "p1.sqlite3"
        with SymbolIndex(database) as index:
            index.rebuild(symbols)
        with SymbolIndex(database) as index:
            snapshot_key = hashlib.sha256(json.dumps(
                [s.to_dict() for s in sorted(symbols, key=lambda s: s.identity.value)],
                sort_keys=True, separators=(",", ":"),
            ).encode("utf-8")).hexdigest()
            graph = project_index(index, repository_key="arkui-role-smoke", snapshot_key=snapshot_key)
            result = default_role_mapper().map(index, graph)
            test.assertEqual(default_role_mapper().map(index, graph), result)
            original_nodes, original_edges = graph.nodes, graph.edges
            repeated = default_role_mapper().map(index, graph)
            test.assertEqual((graph.nodes, graph.edges), (original_nodes, original_edges))
            test.assertEqual(repeated.to_dict(), result.to_dict())
    by_name = {s.qualified_name: s for s in symbols}
    checks = []
    for component, name, role, path in ROLE_CASES:
        symbol = by_name[f"OHOS::Ace::NG::{name}"]
        decision = result.lookup(NodeIdentity.for_symbol(symbol.identity))
        test.assertEqual(decision.status, MappingStatus.RECOGNIZED, f"{name}: {decision.reason}")
        test.assertEqual(decision.resolved.role.value, role, name)
        actual_component = None if decision.resolved.component is None else decision.resolved.component.key
        test.assertEqual(actual_component, component, name)
        test.assertTrue(decision.resolved.evidence)
        test.assertTrue(all(e.anchor.file.path.as_posix() == path for e in decision.resolved.evidence))
        checks.append({"symbol": name, "identity": symbol.identity.value, "expected_role": role,
                       "actual_role": decision.resolved.role.value, "component": actual_component, "passed": True})
    for name, _ in NEGATIVE_CASES:
        decision = result.lookup(NodeIdentity.for_symbol(by_name[f"OHOS::Ace::NG::{name}"].identity))
        test.assertEqual(decision.status, MappingStatus.UNKNOWN, name)
        checks.append({"symbol": name, "status": decision.status.value, "passed": True})
    test.assertEqual({c.node.identity.key for c in result.components}, {"button", "text", "menu"})
    for component, expected_count in (("button", 5), ("text", 5), ("menu", 6)):
        test.assertEqual(len(result.members(NodeIdentity("arkui.component", component))), expected_count)
    for path, original in originals.items():
        test.assertEqual(hashlib.sha256(workspace.resolve(path).read_bytes()).hexdigest(), original)
    return {"checks": checks, "source_sha256": originals, "domain": result.to_dict()}


class SyntheticArkUIRoleTests(unittest.TestCase):
    def test_synthetic_repository_covers_roles_components_and_negative_cases(self) -> None:
        with TemporaryDirectory(prefix="synthetic-arkui-roles-") as temporary:
            root = Path(temporary)
            contents: dict[str, list[str]] = {}
            for name, path in sorted({(name, path) for _, name, _, path in ROLE_CASES} | set(NEGATIVE_CASES)):
                contents.setdefault(path, []).append(f"class {name} {{}};")
            for path, classes in contents.items():
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("namespace OHOS::Ace::NG {\n" + "\n".join(classes) + "\n}\n", encoding="utf-8")
            run_role_cases(self, RepositoryWorkspace(root))


class RealArkUIRoleSmokeTests(unittest.TestCase):
    # General test discovery follows the repository's external-environment policy.
    # P2-C MUST also execute this class explicitly; absent config is an error here.
    external_validation_requirements = ("ARKUI_REPO_ROOT",)

    def test_button_text_menu_and_shared_overlay_roles(self) -> None:
        root = os.environ.get("ARKUI_REPO_ROOT")
        if not root:
            self.fail("P2-C requires ARKUI_REPO_ROOT; real smoke cannot be skipped.")
        workspace = RepositoryWorkspace(root)
        report = run_role_cases(self, workspace)
        report["repository_revision"] = read_repository_revision(workspace)
        report["clangd"] = read_tool_version("clangd", configured_clangd()).to_dict()
        output = Path(__file__).resolve().parents[2] / "var/validation/p2-c-role-smoke.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
