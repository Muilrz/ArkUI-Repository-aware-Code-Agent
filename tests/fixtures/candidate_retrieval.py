"""Hand-authored synthetic C1 facts over matching C++ source, not ArkUI gold."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

from arkui_agent.graph.domain import ArkUIRoleMapper, ComponentSpec, RoleRule
from arkui_agent.graph.model import NodeKind
from arkui_agent.graph.projection import project_index
from arkui_agent.graph.storage import GraphStore
from arkui_agent.knowledge import ArtifactKind, QueryRequirement
from arkui_agent.repository.index import SymbolIndex, SymbolSemanticFacts
from arkui_agent.repository.model import RepositoryFile, SourceLocation, SourceRange, Symbol, SymbolIdentity, SymbolKind, TestCase, TestFixture
from tests.fixtures.knowledge_snapshot import PrebuiltFixture


SOURCE = """namespace demo {
class Widget {};
int External();
int Set(int value) { return value; }
int Set(double value) { return (int)value; }
int Caller() { External(); return Set(1); }
}
"""
TEST_SOURCE = """class WidgetTest {}; namespace demo { int Set(int); }
void CaseOne() { demo::Set(1); }
"""
EXPECTED_SET_IDENTITIES = ("set:double", "set:int")


class CandidateFixture(PrebuiltFixture):
    def __init__(self, root: Path) -> None:
        super().__init__(root)
        (self.repo / "src/widget.cpp").write_text(SOURCE, encoding="utf-8", newline="\n")
        (self.repo / "tests/widget_test.cpp").write_text(TEST_SOURCE, encoding="utf-8", newline="\n")
        self.git("add", ".")
        self.git("commit", "-m", "C1 candidate source")
        base = self.prebuild("c1")
        snapshot = base.last_usable
        source = RepositoryFile.from_path("src/widget.cpp")
        tests = RepositoryFile.from_path("tests/widget_test.cpp")

        def whole(file: RepositoryFile, line: int, text: str) -> SourceRange:
            return SourceRange(SourceLocation(file, line, 1), SourceLocation(file, line, len(text.splitlines()[line - 1]) + 1))

        symbols = tuple(Symbol(SymbolIdentity(identity), kind, name, "demo::" + name,
                               declaration=whole(source, line, SOURCE), definition=whole(source, line, SOURCE))
                        for identity, name, line, kind in (
                            ("widget", "Widget", 2, SymbolKind.CLASS),
                            ("set:int", "Set", 4, SymbolKind.FUNCTION),
                            ("set:double", "Set", 5, SymbolKind.FUNCTION),
                            ("caller", "Caller", 6, SymbolKind.FUNCTION),
                        ))

        def token(file: RepositoryFile, line: int, text: str, word: str) -> SourceRange:
            column = text.splitlines()[line - 1].index(word) + 1
            return SourceRange(SourceLocation(file, line, column), SourceLocation(file, line, column + len(word)))

        test_fixture = TestFixture(SymbolIdentity("fixture:WidgetTest"), "WidgetTest", token(tests, 1, TEST_SOURCE, "WidgetTest"))
        test_case = TestCase(SymbolIdentity("test:CaseOne"), "CaseOne", test_fixture.identity,
                             token(tests, 2, TEST_SOURCE, "CaseOne"), whole(tests, 2, TEST_SOURCE))
        facts = (
            SymbolSemanticFacts(SymbolIdentity("set:int"), (token(source, 6, SOURCE, "Set"), token(tests, 2, TEST_SOURCE, "Set")),
                                callers=(SymbolIdentity("caller"),)),
            SymbolSemanticFacts(SymbolIdentity("caller"), callees=(SymbolIdentity("set:int"), SymbolIdentity("external"))),
        )
        index_path = self.artifacts / snapshot.artifacts.symbols.path
        with SymbolIndex(index_path) as index:
            index.rebuild(symbols, files=(source, tests), semantic_facts=facts,
                          test_fixtures=(test_fixture,), test_cases=(test_case,))
            graph = project_index(index, repository_key=snapshot.identity.repository,
                                  snapshot_key=snapshot.artifacts.graph.identity)
            domain = ArkUIRoleMapper((ComponentSpec("widget", "Widget"),),
                                     (RoleRule("widget", NodeKind.PATTERN, "demo::Widget", source, "widget"),)).map(index, graph)
        GraphStore(self.artifacts, repository_key=graph.repository_key, snapshot_key=graph.snapshot_key).save(graph)
        (self.artifacts / snapshot.artifacts.domain.path).write_text(json.dumps(domain.to_dict(), sort_keys=True), encoding="utf-8")

        def reseal(reference):
            checksum = hashlib.sha256((self.artifacts / reference.path).read_bytes()).hexdigest()
            return replace(reference, sha256=checksum,
                           identity=reference.identity if reference.kind is ArtifactKind.GRAPH else "sha256:" + checksum)

        artifacts = replace(snapshot.artifacts, **{name: reseal(getattr(snapshot.artifacts, name))
                                                   for name in ("symbols", "tests", "graph", "domain")})
        snapshot = replace(snapshot, artifacts=artifacts,
                           configuration=replace(snapshot.configuration, domain_ruleset=domain.ruleset_identity))
        self.manifest = replace(base, last_usable=snapshot)
        self.write(self.manifest)
        self.requirement = QueryRequirement(snapshot.identity.repository, snapshot.identity.revision,
                                             snapshot.scope, snapshot.configuration)
