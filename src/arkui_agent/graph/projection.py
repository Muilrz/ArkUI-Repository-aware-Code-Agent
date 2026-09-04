"""Project persisted P1 facts into P2-A records, without reading target sources."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from arkui_agent.graph.memory import MemoryGraph
from arkui_agent.graph.model import (
    EdgeIdentity, GraphEdge, GraphNode, NodeIdentity, NodeKind,
    RelationEvidence, RelationType, SourceAnchor,
)
from arkui_agent.repository.index import SymbolIndex
from arkui_agent.repository.model import SourceRange, SymbolIdentity, SymbolKind
from arkui_agent.retrieval.reference_call import ReferenceCallRetriever


@dataclass(frozen=True, slots=True)
class GraphSnapshot:
    """Canonical records plus caller-supplied repository/P1 snapshot scope.

    Scope keys must identify one repository and one immutable P1 index snapshot.
    They are not inferred from display names, timestamps or local target paths.
    """

    repository_key: str
    snapshot_key: str
    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]
    unavailable_relations: ClassVar[tuple[RelationType, ...]] = (
        RelationType.INHERIT, RelationType.OVERRIDE,
    )

    def __post_init__(self) -> None:
        if not self.repository_key.strip() or not self.snapshot_key.strip():
            raise ValueError("Graph snapshot requires repository and snapshot keys.")
        if not isinstance(self.nodes, tuple) or not isinstance(self.edges, tuple):
            raise TypeError("Graph snapshot records must be tuples.")
        query = MemoryGraph(self.nodes, self.edges)
        unique = {node.identity: node for node in self.nodes}
        nodes = tuple(unique[key] for key in sorted(unique))
        object.__setattr__(self, "nodes", nodes)
        object.__setattr__(self, "edges", tuple(
            edge for node in nodes for edge in query.outgoing_edges(node.identity)
        ))

    def query(self) -> MemoryGraph:
        return MemoryGraph(self.nodes, self.edges)


_SYMBOL_KINDS = {
    SymbolKind.FUNCTION: NodeKind.FUNCTION,
    SymbolKind.METHOD: NodeKind.METHOD,
    SymbolKind.CLASS: NodeKind.CLASS,
    SymbolKind.STRUCT: NodeKind.CLASS,
    SymbolKind.TEST_FIXTURE: NodeKind.TEST_FIXTURE,
    SymbolKind.TEST_CASE: NodeKind.TEST_CASE,
}


def project_index(
    index: SymbolIndex, *, repository_key: str, snapshot_key: str,
) -> GraphSnapshot:
    """Read a quiescent P1 index using only public identity-based interfaces.

    The caller must not rebuild the index concurrently. Failures propagate and
    no partial result is returned. INHERIT/OVERRIDE are unavailable in P1's
    current fact contract and are deliberately not inferred from parent/name.
    """

    files = index.files()
    symbols = {
        symbol.identity: symbol
        for file in files for symbol in index.symbols_in_file(file)
    }
    nodes = {
        NodeIdentity.for_file(file): GraphNode(
            NodeIdentity.for_file(file), NodeKind.FILE, file.path.as_posix(),
            (SourceAnchor(file=file),),
        ) for file in files
    }
    edges: list[GraphEdge] = []

    def add_edge(
        source: NodeIdentity, target: NodeIdentity, relation: RelationType,
        provenance: str, anchor: SourceAnchor, description: str,
    ) -> None:
        edges.append(GraphEdge(
            EdgeIdentity(source, target, relation),
            (RelationEvidence(provenance, anchor, description),),
        ))

    for symbol in symbols.values():
        identity = NodeIdentity.for_symbol(symbol.identity)
        anchors = tuple(
            SourceAnchor(symbol.identity, source_range=range_)
            for range_ in (symbol.declaration, symbol.definition) if range_ is not None
        )
        nodes[identity] = GraphNode(
            identity, _SYMBOL_KINDS.get(symbol.kind, NodeKind.SYMBOL),
            symbol.display_name, anchors,
        )
        for role, relation, range_ in (
            ("declaration", RelationType.DECLARE, symbol.declaration),
            ("definition", RelationType.DEFINE, symbol.definition),
        ):
            if range_ is not None:
                add_edge(NodeIdentity.for_file(range_.file), identity, relation,
                         f"p1.symbol.{role}", SourceAnchor(symbol.identity, source_range=range_),
                         f"P1 symbol {role} range")

    def add_test_node(
        identity: SymbolIdentity, kind: NodeKind, name: str,
        ranges: tuple[SourceRange, ...],
    ) -> None:
        key = NodeIdentity.for_symbol(identity)
        anchors = tuple(SourceAnchor(identity, source_range=range_) for range_ in ranges)
        previous = nodes.get(key)
        if previous is not None:
            anchors += previous.anchors
        # An exact P1 test identity enriches a semantic node, never a name match.
        nodes[key] = GraphNode(key, kind, name, anchors)

    for fixture in index.test_fixtures():
        add_test_node(fixture.identity, NodeKind.TEST_FIXTURE, fixture.display_name,
                      (fixture.source_range,))
        for case in index.test_cases_for_fixture(fixture.identity):
            ranges = (case.source_range,) if case.body_range is None else (
                case.source_range, case.body_range,
            )
            add_test_node(case.identity, NodeKind.TEST_CASE, case.display_name, ranges)
            add_edge(NodeIdentity.for_symbol(fixture.identity), NodeIdentity.for_symbol(case.identity),
                     RelationType.TEST, "p1.test_case.fixture_identity",
                     SourceAnchor(case.identity, source_range=case.source_range),
                     "fixture membership; not a tested-symbol or coverage assertion")
            for mapping in index.tested_symbol_mappings_for_case(case.identity):
                for reference in mapping.references:
                    add_edge(NodeIdentity.for_symbol(mapping.test_case_identity),
                             NodeIdentity.for_symbol(mapping.symbol_identity), RelationType.TEST,
                             "p1.tested_symbol_mapping.references",
                             SourceAnchor(mapping.symbol_identity, source_range=reference),
                             "direct symbol reference inside indexed test body; not coverage")

    retriever = ReferenceCallRetriever(index)
    for identity in sorted(symbols, key=lambda item: item.value):
        for reference in retriever.references(identity):
            add_edge(NodeIdentity.for_file(reference.source_range.file),
                     NodeIdentity.for_symbol(identity), RelationType.REFERENCE,
                     "p1.semantic_facts.references",
                     SourceAnchor(identity, source_range=reference.source_range),
                     "reference occurrence; enclosing caller identity is not supplied by P1")
        for fact, relations in (
            ("callers", retriever.callers(identity)),
            ("callees", retriever.callees(identity)),
        ):
            for relation in relations:
                for endpoint in (relation.caller_identity, relation.callee_identity):
                    key = NodeIdentity.for_symbol(endpoint)
                    if key not in nodes:
                        nodes[key] = GraphNode(key, NodeKind.SYMBOL, endpoint.value,
                                               (SourceAnchor(endpoint),))
                precision = "caller range unavailable"
                if relation.caller is not None:
                    precision = ("caller definition" if relation.caller.definition is not None
                                 else "caller declaration")
                add_edge(NodeIdentity.for_symbol(relation.caller_identity),
                         NodeIdentity.for_symbol(relation.callee_identity), RelationType.CALL,
                         f"p1.semantic_facts.{fact}",
                         SourceAnchor(relation.caller_identity, source_range=relation.source_range),
                         f"stored {fact} fact; {precision}; exact call site unavailable")

    return GraphSnapshot(repository_key, snapshot_key, tuple(nodes.values()), tuple(edges))
