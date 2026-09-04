"""Bounded component-creation query. Architectural order is not runtime order."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from arkui_agent.graph.domain import DomainMap, MappingStatus
from arkui_agent.graph.framework import _SourceEvidence
from arkui_agent.graph.model import GraphEdge, GraphNode, NodeIdentity, NodeKind, RelationEvidence, RelationType, SourceAnchor
from arkui_agent.graph.projection import GraphSnapshot, project_index
from arkui_agent.repository.index import SymbolIndex
from arkui_agent.repository.model import Symbol, SymbolIdentity, SymbolKind
from arkui_agent.repository.workspace import RepositoryWorkspace


class CreationStatus(str, Enum):
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    AMBIGUOUS = "ambiguous"


class CreationStage(str, Enum):
    ENTRY = "entry"
    BRIDGE = "bridge"
    SUPPORT = "support"
    MODEL = "model"
    FRAME_NODE = "frame_node"
    PATTERN = "pattern"


@dataclass(frozen=True, slots=True)
class CreationBounds:
    max_depth: int = 8
    max_paths: int = 32
    max_states: int = 1000

    def __post_init__(self) -> None:
        for name in ("max_depth", "max_paths", "max_states"):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} must be a positive integer.")


@dataclass(frozen=True, slots=True)
class CreationNode:
    node: GraphNode
    stage: CreationStage
    evidence: tuple[RelationEvidence, ...]


@dataclass(frozen=True, slots=True)
class PatternArgument:
    """A source-proven argument association, NOT a FrameNode -> Pattern CALL.

    The model/caller constructs Pattern before passing it to the FrameNode
    factory. Supporting edges retain their actual endpoints and precision.
    """

    caller: NodeIdentity
    frame_factory: NodeIdentity
    pattern: NodeIdentity
    supporting_relations: tuple[GraphEdge, ...]
    evidence: tuple[RelationEvidence, ...]


@dataclass(frozen=True, slots=True)
class CreationPath:
    nodes: tuple[CreationNode, ...]
    relations: tuple[GraphEdge, ...]  # contiguous, ordered direct CALL chain
    pattern_argument: PatternArgument | None
    pattern_candidates: tuple[NodeIdentity, ...]
    issues: tuple[str, ...]

    @property
    def status(self) -> CreationStatus:
        if any(issue in self.issues for issue in ("ambiguous_role", "ambiguous_reference", "ambiguous_allocation_call")):
            return CreationStatus.AMBIGUOUS
        return CreationStatus.INCOMPLETE if self.issues else CreationStatus.COMPLETE


@dataclass(frozen=True, slots=True)
class CreationTrace:
    repository_key: str
    snapshot_key: str
    seed: NodeIdentity
    component: NodeIdentity
    status: CreationStatus
    paths: tuple[CreationPath, ...]
    exhaustive: bool
    diagnostics: tuple[str, ...]
    ruleset_identity: str = "p2.creation.v1"


_FRAME_HEADER = "frameworks/core/components_ng/base/frame_node.h"
_FRAME_NAME = "OHOS::Ace::NG::FrameNode"
_FACTORY_FILE = "interfaces/inner_api/ace_kit/include/ui/base/referenced.h"


def trace_component_creation(
    index: SymbolIndex, graph: GraphSnapshot, domain: DomainMap, workspace: RepositoryWorkspace,
    *, seed: NodeIdentity, component: NodeIdentity, bounds: CreationBounds = CreationBounds(),
) -> CreationTrace:
    """Follow creation-relevant CALL paths, retaining all candidates in bounds.

    The explicit seed is the caller-selected entry identity, never a name query.
    P2-D operation bindings and property CREATE edges are not call-chain hops.
    Missing facts return partial paths; mismatched snapshots fail explicitly.
    """
    if (graph.repository_key, graph.snapshot_key) != (domain.repository_key, domain.snapshot_key):
        raise ValueError("Creation graph/domain scope mismatch.")
    generic = project_index(index, repository_key=graph.repository_key, snapshot_key=graph.snapshot_key)
    originals = {n.identity: n for n in generic.nodes}
    if any(originals.get(n.identity) != n for n in graph.nodes):
        raise ValueError("Creation query requires the matching P1 generic projection.")
    expected_edges = {e.identity: e for e in generic.edges}
    verified = []
    for edge in graph.edges:
        original = expected_edges.get(edge.identity)
        if original is not None:
            if not set(original.evidence).issubset(edge.evidence):
                raise ValueError("Creation graph/P1 evidence mismatch.")
            verified.append(original)
    # Only verified P1 CALL edges form paths, even if the supplied domain graph
    # contains additional CALL-like or operation-binding records.
    # A partial graph is valid: verify provided facts, never restore a missing
    # relation from the index and then claim a complete trace.
    query = GraphSnapshot(graph.repository_key, graph.snapshot_key, graph.nodes, tuple(verified)).query()
    symbols = {n.identity: index.get(SymbolIdentity(n.identity.key)) for n in graph.nodes
               if n.identity.namespace == "symbol"}
    source = _SourceEvidence(workspace)
    diagnostics: set[str] = set()
    roles = {m.identity: m for m in domain.mappings}

    def stage(identity: NodeIdentity) -> tuple[CreationStage, tuple[RelationEvidence, ...], tuple[str, ...]]:
        symbol = symbols.get(identity)
        node = query.node(identity)
        evidence = () if node is None else tuple(
            RelationEvidence("p2.creation.v1.anchor", a, "P1 graph source anchor") for a in node.anchors)
        if symbol is None or symbol.parent_identity is None:
            return CreationStage.SUPPORT, evidence, ()
        parent = NodeIdentity.for_symbol(symbol.parent_identity)
        owner = symbols.get(parent)
        evidence += (RelationEvidence("p1.symbol.parent_identity", SourceAnchor(symbol.identity,
                     source_range=symbol.declaration or symbol.definition),
                     f"semantic parent {parent.value}; domain ruleset {domain.ruleset_identity}"),)
        if owner is not None and symbol.kind == SymbolKind.METHOD:
            location = owner.definition or owner.declaration
            declaration = symbol.declaration
            if (owner.kind == SymbolKind.CLASS and owner.qualified_name == _FRAME_NAME and location is not None
                    and location.file.path.as_posix() == _FRAME_HEADER and declaration is not None
                    and declaration.file.path.as_posix() == _FRAME_HEADER and symbol.qualified_name in {
                        _FRAME_NAME + "::CreateFrameNode", _FRAME_NAME + "::GetOrCreateFrameNode"}):
                evidence += (RelationEvidence("p2.creation.v1.frame_factory", SourceAnchor(owner.identity,
                    source_range=location), "reviewed FrameNode class and factory declaration; trace-local stage"),)
                return CreationStage.FRAME_NODE, evidence, ()
        mapping = roles.get(parent)
        if mapping is not None and mapping.status == MappingStatus.AMBIGUOUS:
            return CreationStage.SUPPORT, evidence + mapping.evidence + tuple(
                e for c in mapping.candidates for e in c.evidence), ("ambiguous_role",)
        resolved = None if mapping is None else mapping.resolved
        if resolved is not None:
            evidence += resolved.evidence
            if resolved.component != component:
                return CreationStage.SUPPORT, evidence, ("different_component",)
            if resolved.role == NodeKind.MODEL:
                return CreationStage.MODEL, evidence, ()
            if resolved.role == NodeKind.BRIDGE:
                return CreationStage.BRIDGE, evidence, ()
        return CreationStage.SUPPORT, evidence, ()

    stages = {identity: stage(identity) for identity in symbols}
    targets = {identity for identity, (kind, _, issues) in stages.items()
               if kind in {CreationStage.MODEL, CreationStage.FRAME_NODE} or "ambiguous_role" in issues}
    # Reverse closure prunes unrelated callees; no ranking and no arbitrary
    # best-path choice. A Model with a missing FrameNode edge remains a target.
    relevant = set(targets)
    pending = list(sorted(targets))
    while pending:
        current = pending.pop()
        for edge in query.incoming_edges(current, relations=frozenset({RelationType.CALL})):
            if "different_component" in stages.get(edge.identity.source, (None, (), ()))[2]:
                continue
            if edge.identity.source not in relevant:
                relevant.add(edge.identity.source)
                pending.append(edge.identity.source)

    def argument(caller: NodeIdentity, frame: NodeIdentity):
        symbol = symbols.get(caller)
        if symbol is None or symbol.definition is None:
            return None, (), ("missing_definition",)
        if symbols[frame].qualified_name.endswith("::GetOrCreateFrameNode"):
            return None, (), ("unsupported_pattern_callback",)
        name = symbol.qualified_name.rsplit("::", 1)[-1]
        text, offset = source.window(symbol.definition.start)
        pattern = (re.escape(name) + r"\([^{};()]*\)\s*\{\s*auto\s+\w+\s*=\s*FrameNode::"
                   r"(?P<frame>CreateFrameNode)\(\s*[\w:]+\s*,\s*\w+\s*,\s*"
                   r"AceType::MakeRefPtr<(?P<pattern>\w+)>\(\)\s*\);")
        match = re.match(pattern, text)
        if match is None:
            return None, (), ("unsupported_pattern_argument",)
        file = symbol.definition.file

        def references(group: str) -> tuple[GraphEdge, ...]:
            range_ = source.range(file, offset + match.start(group), offset + match.end(group))
            return tuple(e for e in query.outgoing_edges(NodeIdentity.for_file(file),
                         relations=frozenset({RelationType.REFERENCE}))
                         if any(p.anchor.source_range == range_ for p in e.evidence))

        frame_refs, pattern_refs = references("frame"), references("pattern")
        if len(frame_refs) > 1 or len(pattern_refs) > 1:
            return None, tuple(sorted(e.identity.target for e in pattern_refs)), ("ambiguous_reference",)
        if len(frame_refs) != 1 or frame_refs[0].identity.target != frame or len(pattern_refs) != 1:
            return None, tuple(e.identity.target for e in pattern_refs), ("missing_argument_reference",)
        target = pattern_refs[0].identity.target
        factories = []
        for edge in query.outgoing_edges(caller, relations=frozenset({RelationType.CALL})):
            callee = symbols.get(edge.identity.target)
            if callee is None or callee.qualified_name != "OHOS::Ace::Referenced::MakeRefPtr":
                continue
            location = callee.definition or callee.declaration
            if location is not None and location.file.path.as_posix() == _FACTORY_FILE:
                factory_text, factory_offset = source.window(location.start)
                found = re.match(r"MakeRefPtr\(Args&&\.\.\. args\)\s*\{\s*return Claim<T, true>\(new T\("
                                 r"std::forward<Args>\(args\)\.\.\.\)\);\s*\}", factory_text)
                if found:
                    factories.append((edge, source.proof("creation.factory", source.range(location.file,
                        factory_offset, factory_offset + found.end()), callee.identity)))
        if len(factories) != 1:
            return None, (target,), ("ambiguous_allocation_call" if factories else "missing_allocation_call",)
        mapping = roles.get(target)
        source_evidence = (source.proof("creation.argument",
            source.range(file, offset, offset + match.end()), symbol.identity), factories[0][1])
        if mapping is None or mapping.resolved is None:
            evidence = source_evidence + (() if mapping is None else mapping.evidence + tuple(
                e for c in mapping.candidates for e in c.evidence))
            binding = PatternArgument(caller, frame, target, frame_refs + pattern_refs + (factories[0][0],), evidence)
            return binding, (target,), ("ambiguous_role" if mapping and mapping.status == MappingStatus.AMBIGUOUS else
                                        "unknown_pattern_role",)
        if mapping.resolved.role != NodeKind.PATTERN or mapping.resolved.component != component:
            return None, (target,), ("different_component_or_role",)
        evidence = mapping.resolved.evidence + source_evidence
        return (PatternArgument(caller, frame, target, frame_refs + pattern_refs + (factories[0][0],), evidence),
                (target,), ())

    paths: list[CreationPath] = []
    exhaustive = True
    states = 0
    # Per-path visited identities preserve diamonds and alternative supporting
    # call chains. Global visit-once BFS would silently erase that ambiguity.
    stack: list[tuple[tuple[NodeIdentity, ...], tuple[GraphEdge, ...]]] = [((seed,), ())]
    while stack:
        if states >= bounds.max_states or len(paths) >= bounds.max_paths:
            diagnostics.add("state_or_path_limit")
            exhaustive = False
            break
        identities, calls = stack.pop()
        states += 1
        nodes = []
        issues: list[str] = []
        for i, identity in enumerate(identities):
            node = query.node(identity)
            if node is None:
                issues.append("missing_node")
                continue
            kind, evidence, problems = stages.get(identity, (CreationStage.SUPPORT, (), ()))
            if i == 0 and kind == CreationStage.SUPPORT:
                kind = CreationStage.ENTRY
            if not any(a.source_range is not None for a in node.anchors):
                issues.append("missing_source_location")
            nodes.append(CreationNode(node, kind, evidence))
            issues.extend(problems)
        current = identities[-1]
        is_frame = bool(nodes and nodes[-1].stage == CreationStage.FRAME_NODE)
        association = None
        candidates: tuple[NodeIdentity, ...] = ()
        if is_frame:
            if nodes[0].stage in {CreationStage.MODEL, CreationStage.FRAME_NODE}:
                issues.append("missing_entry_stage")
            if not any(n.stage == CreationStage.MODEL for n in nodes):
                issues.append("missing_model_stage")
            if len(identities) < 2:
                issues.append("missing_entry_call")
            else:
                association, candidates, problems = argument(identities[-2], current)
                issues.extend(problems)
                if association is not None and not problems:
                    target_node = query.node(association.pattern)
                    assert target_node is not None
                    nodes.append(CreationNode(target_node, CreationStage.PATTERN, association.evidence))
        outgoing = tuple(e for e in query.outgoing_edges(current, relations=frozenset({RelationType.CALL}))
                         if e.identity.target in relevant)
        if not is_frame and not issues and len(calls) < bounds.max_depth and outgoing:
            for edge in reversed(outgoing):
                if edge.identity.target in identities:
                    diagnostics.add("cycle_cut")
                    exhaustive = False
                else:
                    stack.append((identities + (edge.identity.target,), calls + (edge,)))
            if any(e.identity.target not in identities for e in outgoing):
                continue
        if not is_frame:
            if len(calls) >= bounds.max_depth and outgoing:
                diagnostics.add("depth_limit")
                exhaustive = False
            issues.append("missing_creation_relation")
        if not any(n.stage == CreationStage.PATTERN for n in nodes):
            issues.append("missing_pattern_stage")
        paths.append(CreationPath(tuple(nodes), calls, association, candidates, tuple(sorted(set(issues)))))
    if component not in {c.node.identity for c in domain.components}:
        diagnostics.add("unknown_component")
        exhaustive = False
    if any(workspace.resolve(path).read_text(encoding="utf-8") != text for path, text in source.files.items()):
        raise ValueError("Source changed during creation query.")
    status = (CreationStatus.AMBIGUOUS if len(paths) > 1 or any(p.status == CreationStatus.AMBIGUOUS for p in paths)
              else CreationStatus.COMPLETE if exhaustive and paths and paths[0].status == CreationStatus.COMPLETE
              else CreationStatus.INCOMPLETE)
    return CreationTrace(graph.repository_key, graph.snapshot_key, seed, component, status, tuple(paths), exhaustive,
                         tuple(sorted(diagnostics)))
