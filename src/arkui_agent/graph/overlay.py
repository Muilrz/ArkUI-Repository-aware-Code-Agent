"""Bounded static Show/Close paths; no runtime instance or lifecycle inference."""

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


class OverlayStatus(str, Enum):
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    AMBIGUOUS = "ambiguous"


class OverlayStage(str, Enum):
    ENTRY = "entry"
    SUPPORT = "support"
    MANAGER = "manager"
    OPERATION = "operation"
    MANAGED_NODE_TYPE = "managed_node_type"
    PATTERN = "pattern"
    ANIMATION = "animation"


class OverlayAnimation(str, Enum):
    PRESENT = "present"
    NOT_OBSERVED = "not_observed_in_supported_body"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True, slots=True)
class OverlayBounds:
    max_depth: int = 8
    max_paths: int = 32
    max_states: int = 1000

    def __post_init__(self) -> None:
        for name in ("max_depth", "max_paths", "max_states"):
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise ValueError(f"{name} must be a positive integer.")


@dataclass(frozen=True, slots=True)
class OverlayNode:
    node: GraphNode
    stage: OverlayStage
    evidence: tuple[RelationEvidence, ...]


@dataclass(frozen=True, slots=True)
class OverlayPath:
    nodes: tuple[OverlayNode, ...]
    calls: tuple[GraphEdge, ...]  # contiguous entry -> operation only
    binding: GraphEdge | None  # manager -> operation, not a CALL
    support: tuple[GraphEdge, ...]  # original directions, including tail CALLs
    candidates: tuple[OverlayNode, ...]
    source_evidence: tuple[RelationEvidence, ...]
    animation: OverlayAnimation
    gaps: tuple[str, ...]

    @property
    def status(self) -> OverlayStatus:
        return _status(self.gaps)


@dataclass(frozen=True, slots=True)
class OverlayLeg:
    operation: RelationType
    seeds: tuple[NodeIdentity, ...]
    paths: tuple[OverlayPath, ...]
    status: OverlayStatus
    exhaustive: bool
    gaps: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OverlayTrace:
    repository_key: str
    snapshot_key: str
    manager: NodeIdentity
    component: NodeIdentity
    show: OverlayLeg
    close: OverlayLeg
    status: OverlayStatus
    ruleset_identity: str = "p2.overlay.v1"
    association: str = "caller-selected Menu API family; same runtime node/manager instance is not established"


def _status(gaps: tuple[str, ...]) -> OverlayStatus:
    if any(g.startswith("ambiguous_") for g in gaps):
        return OverlayStatus.AMBIGUOUS
    return OverlayStatus.INCOMPLETE if gaps else OverlayStatus.COMPLETE


_FRAME_H = "frameworks/core/components_ng/base/frame_node.h"
_ANIMATION_H = "frameworks/core/components_ng/render/animation_utils.h"
_BODY = (r"\s*CHECK_NULL_VOID\(menu\);\s*auto\s+(?P<local>\w+)\s*=\s*menu->GetPattern<(?P<pattern>\w+)>\(\);"
         r"\s*CHECK_NULL_VOID\((?P=local)\);\s*(?P=local)->(?P<method>\w+)\(\);"
         r"\s*(?:AnimationUtils::(?P<animation>Animate)\(\s*\w+\s*,\s*\w+\s*\);\s*)?\}")


class _OverlayQuery:
    def __init__(self, index: SymbolIndex, graph: GraphSnapshot, domain: DomainMap,
                 workspace: RepositoryWorkspace, manager: NodeIdentity, component: NodeIdentity) -> None:
        if (graph.repository_key, graph.snapshot_key) != (domain.repository_key, domain.snapshot_key):
            raise ValueError("Overlay graph/domain scope mismatch.")
        generic = project_index(index, repository_key=graph.repository_key, snapshot_key=graph.snapshot_key)
        nodes = {n.identity: n for n in generic.nodes}
        if any(nodes.get(n.identity) != n for n in graph.nodes):
            raise ValueError("Overlay graph/P1 node mismatch.")
        originals = {e.identity: e for e in generic.edges}
        verified = {}
        for edge in graph.edges:
            original = originals.get(edge.identity)
            if original:
                if not set(original.evidence).issubset(edge.evidence):
                    raise ValueError("Overlay graph/P1 evidence mismatch.")
                verified[edge.identity] = original
        self.query = GraphSnapshot(graph.repository_key, graph.snapshot_key, graph.nodes, tuple(verified.values())).query()
        self.symbols = {n.identity: index.get(SymbolIdentity(n.identity.key)) for n in graph.nodes
                        if n.identity.namespace == "symbol"}
        self.roles = {m.identity: m for m in domain.mappings}
        self.manager, self.component = manager, component
        self.source = _SourceEvidence(workspace)
        self.valid_bindings: dict[EdgeIdentity, GraphEdge] = {}
        self.backing: dict[EdgeIdentity, tuple[GraphEdge, ...]] = {}
        supplied = {e.identity: e for e in graph.edges}
        extracted = extract_framework_relations(index, generic, domain, workspace)
        for edge in extracted.graph.edges:
            if edge.identity.source != manager or edge.identity.relation not in {RelationType.SHOW, RelationType.CLOSE}:
                continue
            actual = supplied.get(edge.identity)
            backing = tuple(e for e in generic.edges if any(
                p.description == f"supporting generic edge {e.identity.value}" for p in edge.evidence))
            if actual and set(edge.evidence).issubset(actual.evidence) and all(e.identity in verified for e in backing):
                self.valid_bindings[edge.identity] = edge
                self.backing[edge.identity] = backing

    def node(self, identity: NodeIdentity, stage: OverlayStage) -> OverlayNode:
        node = self.query.node(identity)
        assert node is not None
        evidence = tuple(RelationEvidence("p2.overlay.v1.anchor", a, "P1 source anchor") for a in node.anchors)
        symbol = self.symbols.get(identity)
        if symbol and symbol.parent_identity:
            evidence += (RelationEvidence("p1.symbol.parent_identity", SourceAnchor(symbol.identity,
                         source_range=symbol.declaration or symbol.definition),
                         f"semantic parent {NodeIdentity.for_symbol(symbol.parent_identity).value}"),)
        role = self.roles.get(identity)
        if role:
            evidence += role.evidence + tuple(p for c in role.candidates for p in c.evidence)
        return OverlayNode(node, stage, evidence)

    def role_gap(self, identity: NodeIdentity, kind: NodeKind) -> tuple[str, ...]:
        mapping = self.roles.get(identity)
        if mapping and mapping.status == MappingStatus.AMBIGUOUS:
            return ("ambiguous_role",)
        if mapping and mapping.resolved:
            if mapping.resolved.role != kind:
                return ("ambiguous_role_conflict",)
            expected_component = None if kind == NodeKind.OVERLAY_MANAGER else self.component
            if mapping.resolved.component == expected_component:
                return ()
            return ("ambiguous_component_role_conflict",)
        return ("unknown_role",)

    def refs(self, range_: SourceRange) -> tuple[GraphEdge, ...]:
        return tuple(e for e in self.query.outgoing_edges(NodeIdentity.for_file(range_.file),
                     relations=frozenset({RelationType.REFERENCE}))
                     if any(p.anchor.source_range == range_ for p in e.evidence))

    def proof(self, rule: str, range_: SourceRange, identity: SymbolIdentity) -> RelationEvidence:
        proof = self.source.proof(rule, range_, identity)
        return RelationEvidence("p2.overlay.v1." + rule, proof.anchor, proof.description)

    def path(self, ids: tuple[NodeIdentity, ...], calls: tuple[GraphEdge, ...], relation: RelationType,
             problems: tuple[str, ...] = ()) -> OverlayPath:
        nodes = [self.node(i, OverlayStage.ENTRY if j == 0 else OverlayStage.SUPPORT)
                 for j, i in enumerate(ids) if self.query.node(i)]
        support: list[GraphEdge] = []
        candidates: list[OverlayNode] = []
        proofs: list[RelationEvidence] = []
        gaps = list(problems)
        animation = OverlayAnimation.UNRESOLVED
        binding = None

        def finish() -> OverlayPath:
            edges = {e.identity: e for e in support}
            choices = {n.node.identity: n for n in candidates}
            return OverlayPath(tuple(nodes), calls, binding,
                               tuple(edges[k] for k in sorted(edges, key=lambda k: k.sort_key)),
                               tuple(choices[k] for k in sorted(choices)), tuple(proofs), animation, tuple(sorted(set(gaps))))

        if problems:
            if any("role" in gap for gap in problems) and self.query.node(self.manager):
                candidates.append(self.node(self.manager, OverlayStage.SUPPORT))
            return finish()
        operation = ids[-1]
        symbol = self.symbols[operation]
        assert symbol is not None
        nodes[-1:] = [self.node(self.manager, OverlayStage.MANAGER), self.node(operation, OverlayStage.OPERATION)]
        if not calls:
            gaps.append("missing_entry_call")
        key = EdgeIdentity(self.manager, operation, relation)
        binding = self.valid_bindings.get(key)
        if binding:
            support.extend(self.backing[key])
            # Preserve hashes of the binding sources within this query's read
            # snapshot as well as the extractor's source revalidation.
            for evidence in binding.evidence:
                if evidence.anchor.file:
                    self.source.read(evidence.anchor.file.path.as_posix())
        else:
            gaps.append("missing_operation_binding")
        definitions = self.query.incoming_edges(operation, relations=frozenset({RelationType.DEFINE}))
        support.extend(definitions)
        if symbol.definition is None or not definitions:
            gaps.append("missing_operation_definition")
            return finish()
        text, offset = self.source.window(symbol.definition.start)
        name = symbol.qualified_name.rsplit("::", 1)[-1]
        # This records the parameter TYPE, never invents a runtime FrameNode ID.
        parameter = (re.escape(name) + r"\([^(){};]*?RefPtr<(?P<node>FrameNode)>\s*&?\s*menu"
                     r"[^(){};]*\)\s*")
        signature = re.match(parameter + r"\{", text)
        if signature is None:
            gaps.append("unsupported_managed_parameter")
            return finish()
        proofs.append(self.proof("operation_signature", self.source.range(symbol.definition.file, offset,
                      offset + signature.end()), symbol.identity))
        refs = self.refs(self.source.range(symbol.definition.file, offset + signature.start("node"),
                                           offset + signature.end("node")))
        # A declaration parameter is evidence for this SAME opaque method
        # identity. Keep both locations and reject conflicting references.
        declarations = self.query.incoming_edges(operation, relations=frozenset({RelationType.DECLARE}))
        if symbol.declaration and symbol.declaration != symbol.definition and declarations:
            declaration, start = self.source.window(symbol.declaration.start)
            declared = re.match(parameter + ";", declaration)
            if declared:
                support.extend(declarations)
                proofs.append(self.proof("declared_operation_signature", self.source.range(symbol.declaration.file,
                              start, start + declared.end()), symbol.identity))
                refs += self.refs(self.source.range(symbol.declaration.file, start + declared.start("node"),
                                                    start + declared.end("node")))
        support.extend(refs)
        node_ids = sorted({e.identity.target for e in refs})
        if len(node_ids) != 1:
            gaps.append("ambiguous_managed_node_identity" if refs else "missing_managed_node_reference")
            candidates.extend(self.node(i, OverlayStage.SUPPORT) for i in node_ids)
        else:
            target = self.symbols.get(node_ids[0])
            anchor = None if target is None else target.definition or target.declaration
            if (target and target.kind == SymbolKind.CLASS and target.qualified_name == "OHOS::Ace::NG::FrameNode"
                    and anchor and anchor.file.path.as_posix() == _FRAME_H):
                nodes.append(self.node(node_ids[0], OverlayStage.MANAGED_NODE_TYPE))
            else:
                candidates.append(self.node(node_ids[0], OverlayStage.SUPPORT))
                gaps.append("ambiguous_managed_node_type" if target and anchor else "unverified_managed_node_type")
        # Complete tiny body only: no branch/lambda/member dispatch inference.
        body = re.match(_BODY, text[signature.end():])
        if body is None:
            gaps.append("unsupported_manager_body")
            return finish()
        base = offset + signature.end()
        proofs.append(self.proof("managed_body", self.source.range(symbol.definition.file, base, base + body.end()),
                                 symbol.identity))
        pattern_refs = self.refs(self.source.range(symbol.definition.file, base + body.start("pattern"),
                                                   base + body.end("pattern")))
        support.extend(pattern_refs)
        if len(pattern_refs) != 1:
            gaps.append("ambiguous_pattern_identity" if pattern_refs else "missing_pattern_reference")
            candidates.extend(self.node(e.identity.target, OverlayStage.SUPPORT) for e in pattern_refs)
        else:
            pattern = pattern_refs[0].identity.target
            role_gaps = self.role_gap(pattern, NodeKind.PATTERN)
            gaps.extend(role_gaps)
            if role_gaps:
                candidates.append(self.node(pattern, OverlayStage.SUPPORT))
            elif any(n.stage == OverlayStage.MANAGED_NODE_TYPE for n in nodes):
                nodes.append(self.node(pattern, OverlayStage.PATTERN))
                method_refs = self.refs(self.source.range(symbol.definition.file, base + body.start("method"),
                                                          base + body.end("method")))
                support.extend(method_refs)
                if len(method_refs) != 1:
                    gaps.append("ambiguous_pattern_operation" if method_refs else "missing_pattern_operation_reference")
                    candidates.extend(self.node(e.identity.target, OverlayStage.SUPPORT) for e in method_refs)
                else:
                    target = method_refs[0].identity.target
                    member = self.symbols.get(target)
                    edge = next((e for e in self.query.outgoing_edges(operation, relations=frozenset({RelationType.CALL}))
                                 if e.identity.target == target), None)
                    if not member or member.kind != SymbolKind.METHOD or member.parent_identity != SymbolIdentity(pattern.key):
                        gaps.append("ambiguous_pattern_operation_parent")
                        candidates.append(self.node(target, OverlayStage.SUPPORT))
                    elif edge is None:
                        gaps.append("missing_pattern_operation_call")
                    else:
                        support.append(edge)
        if body.group("animation") is None:
            animation = OverlayAnimation.NOT_OBSERVED
        else:
            refs = self.refs(self.source.range(symbol.definition.file, base + body.start("animation"),
                                               base + body.end("animation")))
            support.extend(refs)
            if len(refs) != 1:
                gaps.append("ambiguous_animation_identity" if refs else "missing_animation_reference")
                candidates.extend(self.node(e.identity.target, OverlayStage.SUPPORT) for e in refs)
            else:
                identity = refs[0].identity.target
                target = self.symbols.get(identity)
                anchor = None if target is None else target.declaration
                edge = next((e for e in self.query.outgoing_edges(operation, relations=frozenset({RelationType.CALL}))
                             if e.identity.target == identity), None)
                identity_matches = (target and target.kind == SymbolKind.METHOD
                                    and target.qualified_name == "OHOS::Ace::AnimationUtils::Animate"
                                    and anchor and anchor.file.path.as_posix() == _ANIMATION_H)
                if identity_matches and edge:
                    support.append(edge)
                    animation = OverlayAnimation.PRESENT
                    nodes.append(self.node(identity, OverlayStage.ANIMATION))
                else:
                    candidates.append(self.node(identity, OverlayStage.SUPPORT))
                    gaps.append("ambiguous_animation_target" if target and anchor and not identity_matches
                                else "unverified_animation_call")
        return finish()

    def leg(self, seeds: tuple[NodeIdentity, ...], relation: RelationType, bounds: OverlayBounds) -> OverlayLeg:
        name = "ShowMenu" if relation == RelationType.SHOW else "HideMenu"
        targets = {i for i, s in self.symbols.items() if s and s.kind == SymbolKind.METHOD
                   and s.parent_identity == SymbolIdentity(self.manager.key) and s.qualified_name.rsplit("::", 1)[-1] == name}
        gaps: set[str] = set()
        exhaustive = True
        paths: list[OverlayPath] = []
        role_gaps = self.role_gap(self.manager, NodeKind.OVERLAY_MANAGER)
        if self.query.node(self.manager) is None:
            role_gaps = ("missing_manager",)
        # Reverse reachability prunes unrelated call branches. Never insert an
        # index fact that is absent from the supplied partial graph.
        relevant = set(targets)
        pending = list(sorted(targets))
        while pending:
            current = pending.pop()
            for edge in self.query.incoming_edges(current, relations=frozenset({RelationType.CALL})):
                if edge.identity.source not in relevant:
                    relevant.add(edge.identity.source)
                    pending.append(edge.identity.source)
        stack: list[tuple[tuple[NodeIdentity, ...], tuple[GraphEdge, ...]]] = [((seed,), ()) for seed in reversed(seeds)]
        states = 0
        while stack:
            if states >= bounds.max_states or len(paths) >= bounds.max_paths:
                gaps.add("state_limit" if states >= bounds.max_states else "path_limit")
                exhaustive = False
                break
            ids, calls = stack.pop()
            states += 1
            current = ids[-1]
            problems = role_gaps
            if self.query.node(current) is None:
                problems += ("missing_seed",)
            if problems:
                paths.append(self.path(ids, calls, relation, problems))
                continue
            if current in targets:
                paths.append(self.path(ids, calls, relation))
                continue
            outgoing = tuple(e for e in self.query.outgoing_edges(current, relations=frozenset({RelationType.CALL}))
                             if e.identity.target in relevant)
            if not outgoing:
                paths.append(self.path(ids, calls, relation, ("missing_operation_call",)))
                continue
            if len(calls) >= bounds.max_depth:
                exhaustive = False
                gaps.add("depth_limit")
                paths.append(self.path(ids, calls, relation, ("depth_limit",)))
                continue
            for edge in reversed(outgoing):
                if edge.identity.target in ids:
                    exhaustive = False
                    gaps.add("cycle_cut")
                else:
                    stack.append((ids + (edge.identity.target,), calls + (edge,)))
        if not seeds:
            gaps.add("missing_seed")
        if len(paths) > 1:
            gaps.add("ambiguous_paths")
        gaps.update(g for p in paths for g in p.gaps)
        status = _status(tuple(gaps))
        return OverlayLeg(relation, seeds, tuple(paths), status, exhaustive, tuple(sorted(gaps)))


def trace_overlay(
    index: SymbolIndex, graph: GraphSnapshot, domain: DomainMap, workspace: RepositoryWorkspace,
    *, manager: NodeIdentity, component: NodeIdentity, show_seed: NodeIdentity,
    close_seeds: tuple[NodeIdentity, ...], bounds: OverlayBounds = OverlayBounds(),
) -> OverlayTrace:
    """Pair explicitly selected Menu Show/Close entry candidates, not instances.

    Each leg independently enumerates real CALL paths to the selected manager's
    P2-D operation boundary. Binding and optional source-proven associations
    stay distinct. No automatic overlay/entry discovery or lifecycle analysis.
    """
    if not isinstance(close_seeds, tuple):
        raise TypeError("close_seeds must be a tuple of explicit NodeIdentity values.")
    context = _OverlayQuery(index, graph, domain, workspace, manager, component)
    show = context.leg((show_seed,), RelationType.SHOW, bounds)
    close = context.leg(tuple(sorted(set(close_seeds))), RelationType.CLOSE, bounds)
    if any(workspace.resolve(p).read_text(encoding="utf-8") != text for p, text in context.source.files.items()):
        raise ValueError("Source changed during overlay trace; rebuild the snapshot.")
    status = _status(show.gaps + close.gaps)
    return OverlayTrace(graph.repository_key, graph.snapshot_key, manager, component, show, close, status)
