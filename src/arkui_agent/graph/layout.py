"""Evidence-preserving layout architecture trace, never a runtime call chain."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from arkui_agent.graph.domain import DomainMap, MappingStatus
from arkui_agent.graph.framework import _SourceEvidence, extract_framework_relations
from arkui_agent.graph.model import EdgeIdentity, GraphEdge, GraphNode, NodeIdentity, NodeKind, RelationEvidence, RelationType, SourceAnchor
from arkui_agent.graph.projection import GraphSnapshot, project_index
from arkui_agent.repository.index import SymbolIndex
from arkui_agent.repository.model import SourceRange, SymbolIdentity, SymbolKind
from arkui_agent.repository.workspace import RepositoryWorkspace


class LayoutStatus(str, Enum):
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    AMBIGUOUS = "ambiguous"


class LayoutStage(str, Enum):
    PATTERN = "pattern"
    FACTORY = "factory"
    ALGORITHM = "algorithm"
    MEASURE = "measure"
    LAYOUT = "layout"
    LAYOUT_PROPERTY = "layout_property"


@dataclass(frozen=True, slots=True)
class LayoutBounds:
    max_candidates: int = 32
    max_calls: int = 100

    def __post_init__(self) -> None:
        for field in ("max_candidates", "max_calls"):
            if type(getattr(self, field)) is not int or getattr(self, field) < 1:
                raise ValueError(f"{field} must be a positive integer.")


@dataclass(frozen=True, slots=True)
class LayoutNode:
    node: GraphNode
    evidence: tuple[RelationEvidence, ...]


@dataclass(frozen=True, slots=True)
class LayoutStageResult:
    stage: LayoutStage
    candidates: tuple[LayoutNode, ...]


@dataclass(frozen=True, slots=True)
class LayoutDependency:
    """A source-scoped type reference from an implementation; NOT a CALL."""

    operation: NodeIdentity
    property_class: NodeIdentity
    reference: GraphEdge  # original file -> class REFERENCE
    evidence: tuple[RelationEvidence, ...]


@dataclass(frozen=True, slots=True)
class LayoutTrace:
    repository_key: str
    snapshot_key: str
    seed: NodeIdentity
    component: NodeIdentity
    stages: tuple[LayoutStageResult, ...]
    bindings: tuple[GraphEdge, ...]  # CREATE, MEASURE, LAYOUT; original endpoints
    support: tuple[GraphEdge, ...]  # P1 DECLARE/DEFINE/REFERENCE, original endpoints
    calls: tuple[GraphEdge, ...]  # one-hop actual CALLs, not stage-to-stage links
    dependencies: tuple[LayoutDependency, ...]
    candidates: tuple[LayoutNode, ...]  # unresolved identities and role evidence
    source_evidence: tuple[RelationEvidence, ...]
    gaps: tuple[str, ...]
    exhaustive: bool
    status: LayoutStatus
    ruleset_identity: str = "p2.layout.v1"


# These patterns inspect only anchored, bounded source idioms. Identity always
# comes from P1. Conditional allocations expose candidates, never CREATE edges.
_RETURN = r"return\s+(?:AceType::)?MakeRefPtr<\w+>\([^(){};]*\);"
_FACTORY = (r"CreateLayoutAlgorithm\([^(){};]*\)(?:\s+override)?\s*\{\s*(?:"
            + _RETURN + r"|switch\s*\(\w+\)\s*\{\s*(?:(?:case\s+[\w:]+:|default:|"
            + _RETURN + r")\s*)+\})\s*\}")
# Reviewed straight-line preamble statements. Never cross a branch, closing
# brace, comment, literal or preprocessor directive to find a nearby reference.
_PREAMBLE = (r"(?:auto\s+\w+\s*=\s*\w+->(?:GetHostNode\(\)|GetPattern<\w+>\(\));"
             r"|CHECK_NULL_(?:VOID\(\w+\)|RETURN\(\w+,\s*std::nullopt\));"
             r"|ACE_UINODE_TRACE\(\w+\);|MenuDumpInfo\s+\w+;)")
_PROPERTY = (r"auto\s+\w+\s*=\s*(?:AceType::)?DynamicCast<(?P<property>\w+)>"
             r"\(layoutWrapper->GetLayoutProperty\(\)\);")


def trace_measure_layout(
    index: SymbolIndex, graph: GraphSnapshot, domain: DomainMap, workspace: RepositoryWorkspace,
    *, seed: NodeIdentity, component: NodeIdentity, bounds: LayoutBounds = LayoutBounds(),
) -> LayoutTrace:
    """Trace an explicit Pattern identity through existing P2-D primitives.

    Stages are architectural order; Measure and Layout are separate sibling
    operations. No virtual dispatch/inheritance, recursive CALL expansion,
    same-instance property claim, or conditional factory resolution is implied.
    A partial graph remains partial even when the index contains more facts.
    """
    if (graph.repository_key, graph.snapshot_key) != (domain.repository_key, domain.snapshot_key):
        raise ValueError("Layout graph/domain scope mismatch.")
    generic = project_index(index, repository_key=graph.repository_key, snapshot_key=graph.snapshot_key)
    originals = {n.identity: n for n in generic.nodes}
    if any(originals.get(n.identity) != n for n in graph.nodes):
        raise ValueError("Layout graph/P1 node mismatch.")
    original_edges = {e.identity: e for e in generic.edges}
    verified = {}
    for edge in graph.edges:
        original = original_edges.get(edge.identity)
        if original:
            if not set(original.evidence).issubset(edge.evidence):
                raise ValueError("Layout graph/P1 evidence mismatch.")
            verified[edge.identity] = original
    query = GraphSnapshot(graph.repository_key, graph.snapshot_key, graph.nodes, tuple(verified.values())).query()
    symbols = {n.identity: index.get(SymbolIdentity(n.identity.key)) for n in graph.nodes
               if n.identity.namespace == "symbol"}
    roles = {m.identity: m for m in domain.mappings}
    source = _SourceEvidence(workspace)
    stages: list[LayoutStageResult] = []
    bindings: list[GraphEdge] = []
    support: dict[EdgeIdentity, GraphEdge] = {}
    calls: dict[EdgeIdentity, GraphEdge] = {}
    dependencies: list[LayoutDependency] = []
    candidates: dict[NodeIdentity, LayoutNode] = {}
    source_evidence: list[RelationEvidence] = []
    gaps: set[str] = set()
    exhaustive = True

    def node(identity: NodeIdentity) -> LayoutNode:
        value = query.node(identity)
        assert value is not None
        evidence = tuple(RelationEvidence("p2.layout.v1.anchor", a, "P1 source anchor") for a in value.anchors)
        symbol = symbols.get(identity)
        if symbol and symbol.parent_identity:
            evidence += (RelationEvidence("p1.symbol.parent_identity", SourceAnchor(symbol.identity,
                         source_range=symbol.declaration or symbol.definition),
                         f"semantic parent {NodeIdentity.for_symbol(symbol.parent_identity).value}"),)
        mapping = roles.get(identity)
        if mapping:
            evidence += mapping.evidence + tuple(e for c in mapping.candidates for e in c.evidence)
        return LayoutNode(value, evidence)

    def limited(identities: tuple[NodeIdentity, ...], label: str) -> tuple[NodeIdentity, ...]:
        nonlocal exhaustive
        ordered = tuple(sorted(set(identities)))
        if len(ordered) > bounds.max_candidates:
            exhaustive = False
            gaps.add(label + "_candidate_limit")
        return ordered[:bounds.max_candidates]

    def role_ok(identity: NodeIdentity, kind: NodeKind, label: str) -> bool:
        mapping = roles.get(identity)
        if mapping and mapping.status == MappingStatus.AMBIGUOUS:
            gaps.add("ambiguous_" + label + "_role")
        elif mapping and mapping.resolved and mapping.resolved.role != kind:
            gaps.add("ambiguous_" + label + "_role_conflict")
        elif not mapping or not mapping.resolved or mapping.resolved.component != component:
            gaps.add("unknown_or_cross_component_" + label)
        else:
            return True
        candidates[identity] = node(identity)
        return False

    def facts(identity: NodeIdentity, relation: RelationType) -> tuple[GraphEdge, ...]:
        return query.incoming_edges(identity, relations=frozenset({relation}))

    def remember(edges: tuple[GraphEdge, ...]) -> None:
        support.update((e.identity, e) for e in edges)

    def stage(kind: LayoutStage, ids: tuple[NodeIdentity, ...]) -> None:
        if ids:
            stages.append(LayoutStageResult(kind, tuple(node(i) for i in ids)))

    def direct_calls(identity: NodeIdentity) -> None:
        nonlocal exhaustive
        for edge in query.outgoing_edges(identity, relations=frozenset({RelationType.CALL})):
            if edge.identity not in calls and len(calls) >= bounds.max_calls:
                exhaustive = False
                gaps.add("support_call_limit")
                break
            calls[edge.identity] = edge

    def references(range_: SourceRange) -> tuple[GraphEdge, ...]:
        return tuple(e for e in query.outgoing_edges(NodeIdentity.for_file(range_.file),
                     relations=frozenset({RelationType.REFERENCE}))
                     if any(p.anchor.source_range == range_ for p in e.evidence))

    def proof(rule: str, range_: SourceRange, identity: SymbolIdentity) -> RelationEvidence:
        evidence = source.proof(rule, range_, identity)
        return RelationEvidence("p2.layout.v1." + rule, evidence.anchor, evidence.description)

    # Recheck P2-D meaning and source. Do not adopt edges absent from input or
    # whose required generic support was removed from a partial snapshot.
    extracted = extract_framework_relations(index, generic, domain, workspace)
    provided = {e.identity: e for e in graph.edges}
    valid_bindings: dict[EdgeIdentity, GraphEdge] = {}
    for edge in extracted.graph.edges:
        if edge.identity.relation not in {RelationType.CREATE, RelationType.MEASURE, RelationType.LAYOUT}:
            continue
        supplied = provided.get(edge.identity)
        backing = tuple(e for e in generic.edges if any(
            p.description == f"supporting generic edge {e.identity.value}" for p in edge.evidence))
        if supplied and set(edge.evidence).issubset(supplied.evidence) and all(e.identity in verified for e in backing):
            valid_bindings[edge.identity] = edge

    def accept_binding(start: NodeIdentity, end: NodeIdentity, relation: RelationType) -> bool:
        found = next((e for e in valid_bindings.values() if
                      (e.identity.source, e.identity.target, e.identity.relation) == (start, end, relation)), None)
        if found is None:
            return False
        bindings.append(found)
        remember(tuple(e for e in verified.values() if any(
            p.description == f"supporting generic edge {e.identity.value}" for p in found.evidence)
            and e.identity.relation != RelationType.CALL))
        return True

    def finish() -> LayoutTrace:
        candidate_ids = limited(tuple(candidates), "unresolved")
        if any(workspace.resolve(p).read_text(encoding="utf-8") != text for p, text in source.files.items()):
            raise ValueError("Source changed during layout trace; rebuild the snapshot.")
        status = (LayoutStatus.AMBIGUOUS if any(g.startswith("ambiguous_") for g in gaps) else
                  LayoutStatus.INCOMPLETE if gaps or not exhaustive else LayoutStatus.COMPLETE)
        return LayoutTrace(graph.repository_key, graph.snapshot_key, seed, component, tuple(stages), tuple(bindings),
                           tuple(support[k] for k in sorted(support, key=lambda k: k.sort_key)),
                           tuple(calls[k] for k in sorted(calls, key=lambda k: k.sort_key)),
                           tuple(dependencies), tuple(candidates[k] for k in candidate_ids), tuple(source_evidence),
                           tuple(sorted(gaps)), exhaustive, status)

    if query.node(seed) is None:
        gaps.add("missing_seed")
        return finish()
    if not role_ok(seed, NodeKind.PATTERN, "pattern"):
        return finish()
    stage(LayoutStage.PATTERN, (seed,))
    factories = tuple(i for i, s in symbols.items() if s and s.kind == SymbolKind.METHOD
                      and s.parent_identity == SymbolIdentity(seed.key)
                      and s.qualified_name.rsplit("::", 1)[-1] == "CreateLayoutAlgorithm")
    if len(factories) != 1:
        gaps.add("ambiguous_factory_identity" if factories else "missing_factory")
    factories = limited(factories, "factory")
    stage(LayoutStage.FACTORY, factories)
    for identity in factories:
        remember(facts(identity, RelationType.DECLARE) + facts(identity, RelationType.DEFINE))
        direct_calls(identity)
    if len(factories) != 1 or "ambiguous_factory_identity" in gaps:
        return finish()
    factory = factories[0]
    symbol = symbols[factory]
    assert symbol is not None
    if symbol.definition is None or not facts(factory, RelationType.DEFINE):
        gaps.add("missing_factory_definition")
        return finish()
    text, offset = source.window(symbol.definition.start)
    match = re.match(_FACTORY, text)
    if not match:
        gaps.add("unsupported_factory_body")
        return finish()
    source_evidence.append(proof("factory_candidates", source.range(
        symbol.definition.file, offset, offset + match.end()), symbol.identity))
    targets = set()
    for occurrence in re.finditer(r"MakeRefPtr<(?P<target>\w+)>", match.group()):
        range_ = source.range(symbol.definition.file, offset + occurrence.start("target"),
                              offset + occurrence.end("target"))
        refs = references(range_)
        remember(refs)
        if not refs:
            gaps.add("missing_algorithm_reference")
        targets.update(e.identity.target for e in refs)
    if len(targets) > 1:
        gaps.add("ambiguous_algorithm_identity")
    selected = limited(tuple(targets), "algorithm")
    for identity in selected:
        candidates[identity] = node(identity)
    if len(targets) != 1:
        gaps.add("missing_create_binding")
        return finish()
    algorithm = selected[0]
    if not role_ok(algorithm, NodeKind.LAYOUT_ALGORITHM, "algorithm"):
        return finish()
    if not accept_binding(factory, algorithm, RelationType.CREATE):
        gaps.add("missing_create_binding")
        return finish()
    stage(LayoutStage.ALGORITHM, (algorithm,))
    candidates.pop(algorithm, None)
    operations: list[NodeIdentity] = []
    for relation, kind, names in ((RelationType.MEASURE, LayoutStage.MEASURE, {"Measure", "MeasureContent"}),
                                  (RelationType.LAYOUT, LayoutStage.LAYOUT, {"Layout"})):
        members = tuple(i for i, s in symbols.items() if s and s.kind == SymbolKind.METHOD
                        and s.parent_identity == SymbolIdentity(algorithm.key)
                        and s.qualified_name.rsplit("::", 1)[-1] in names)
        if len(members) > 1:
            gaps.add("ambiguous_" + kind.value + "_identity")
        members = limited(members, kind.value)
        implemented = []
        for identity in members:
            candidates[identity] = node(identity)
            if not accept_binding(algorithm, identity, relation):
                gaps.add("missing_" + kind.value + "_binding")
                continue
            method = symbols[identity]
            assert method is not None
            definitions = facts(identity, RelationType.DEFINE)
            if method.definition is None or not definitions:
                gaps.add("missing_" + kind.value + "_implementation")
                continue
            # Confirm the definition anchor starts a body, not a declaration or
            # another overload. P1 establishes identity; text corroborates it.
            body, body_offset = source.window(method.definition.start)
            name = method.qualified_name.rsplit("::", 1)[-1]
            implementation = re.match(re.escape(name) + r"\([^(){};]*\)\s*\{", body)
            if not implementation:
                gaps.add("unsupported_" + kind.value + "_implementation")
                continue
            source_evidence.append(proof("implementation", source.range(
                method.definition.file, body_offset, body_offset + implementation.end()), method.identity))
            implemented.append(identity)
            candidates.pop(identity, None)
            remember(definitions)
            direct_calls(identity)
        if not members:
            gaps.add("missing_" + kind.value + "_binding")
        stage(kind, tuple(implemented))
        operations.extend(implemented)
    properties = set()
    for identity in operations:
        method = symbols[identity]
        assert method is not None and method.definition is not None
        body, start = source.window(method.definition.start)
        name = method.qualified_name.rsplit("::", 1)[-1]
        match = re.match(re.escape(name) + r"\([^(){};]*\)\s*\{\s*(?:" + _PREAMBLE + r"\s*)*" + _PROPERTY, body)
        if not match:
            gaps.add("unsupported_property_preamble:" + identity.value)
            continue
        range_ = source.range(method.definition.file, start + match.start("property"), start + match.end("property"))
        refs = references(range_)
        remember(refs)
        if len(refs) != 1:
            gaps.add("ambiguous_property_identity" if refs else "missing_property_reference")
            for ref in refs:
                candidates[ref.identity.target] = node(ref.identity.target)
            continue
        target = refs[0].identity.target
        if not role_ok(target, NodeKind.LAYOUT_PROPERTY, "property"):
            continue
        evidence = proof("property_preamble", source.range(method.definition.file, start, start + match.end()),
                         method.identity)
        dependencies.append(LayoutDependency(identity, target, refs[0], (evidence,) + node(target).evidence))
        properties.add(target)
    if not properties:
        gaps.add("missing_layout_property_dependency")
    if len(properties) > 1:
        gaps.add("ambiguous_property_identity")
    stage(LayoutStage.LAYOUT_PROPERTY, limited(tuple(properties), "property"))
    return finish()
