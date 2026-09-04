"""Property-specific static update/read paths over existing P1/P2 identities."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from arkui_agent.graph.domain import DomainMap, MappingStatus
from arkui_agent.graph.framework import _SourceEvidence, extract_framework_relations
from arkui_agent.graph.model import GraphEdge, GraphNode, NodeIdentity, NodeKind, RelationEvidence, RelationType, SourceAnchor
from arkui_agent.graph.projection import GraphSnapshot, project_index
from arkui_agent.repository.index import SymbolIndex
from arkui_agent.repository.model import SymbolIdentity, SymbolKind
from arkui_agent.repository.workspace import RepositoryWorkspace


class PropertyStatus(str, Enum):
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    AMBIGUOUS = "ambiguous"


class PropertyStage(str, Enum):
    ENTRY = "entry"
    BRIDGE = "bridge"
    SUPPORT = "support"
    MODEL = "model"
    LAYOUT_PROPERTY = "layout_property"
    PAINT_PROPERTY = "paint_property"
    WRITER = "writer"
    STATE = "state"
    READER = "reader"
    CONSUMER = "consumer"


@dataclass(frozen=True, slots=True)
class PropertyBounds:
    max_depth: int = 8
    max_paths: int = 32
    max_states: int = 1000

    def __post_init__(self) -> None:
        for name in ("max_depth", "max_paths", "max_states"):
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise ValueError(f"{name} must be a positive integer.")


@dataclass(frozen=True, slots=True)
class PropertyNode:
    node: GraphNode
    stage: PropertyStage
    evidence: tuple[RelationEvidence, ...]


@dataclass(frozen=True, slots=True)
class PropertyBinding:
    """Token is source syntax, NOT a synthesized symbol identity."""

    token: str
    property_class: NodeIdentity
    role: NodeKind
    relation: GraphEdge
    evidence: tuple[RelationEvidence, ...]


@dataclass(frozen=True, slots=True)
class PropertyPath:
    nodes: tuple[PropertyNode, ...]  # architectural update/read order
    calls: tuple[GraphEdge, ...]  # contiguous entry -> selected setter only
    binding: PropertyBinding | None
    support: tuple[GraphEdge, ...]  # actual directions, never fictional flow edges
    candidates: tuple[NodeIdentity, ...]
    gaps: tuple[str, ...]
    candidate_evidence: tuple[RelationEvidence, ...] = ()

    @property
    def status(self) -> PropertyStatus:
        if any(g.startswith("ambiguous_") for g in self.gaps):
            return PropertyStatus.AMBIGUOUS
        return PropertyStatus.INCOMPLETE if self.gaps else PropertyStatus.COMPLETE


@dataclass(frozen=True, slots=True)
class PropertyTrace:
    repository_key: str
    snapshot_key: str
    seed: NodeIdentity
    setter: NodeIdentity
    component: NodeIdentity
    status: PropertyStatus
    paths: tuple[PropertyPath, ...]
    exhaustive: bool
    diagnostics: tuple[str, ...]
    ruleset_identity: str = "p2.property.v1"


def trace_property_update(
    index: SymbolIndex, graph: GraphSnapshot, domain: DomainMap, workspace: RepositoryWorkspace,
    *, seed: NodeIdentity, setter: NodeIdentity, component: NodeIdentity,
    bounds: PropertyBounds = PropertyBounds(),
) -> PropertyTrace:
    """Query one explicit setter identity; no dispatch, overload or alias guessing.

    Complete means a static update/read chain within the supplied snapshot,
    not proof of runtime object identity, execution order or rendering effects.
    Macro-generated member identities and complex bodies remain unsupported.
    """
    if (graph.repository_key, graph.snapshot_key) != (domain.repository_key, domain.snapshot_key):
        raise ValueError("Property graph/domain scope mismatch.")
    generic = project_index(index, repository_key=graph.repository_key, snapshot_key=graph.snapshot_key)
    original_nodes = {n.identity: n for n in generic.nodes}
    if any(original_nodes.get(n.identity) != n for n in graph.nodes):
        raise ValueError("Property graph/P1 node mismatch.")
    originals = {e.identity: e for e in generic.edges}
    verified = []
    for edge in graph.edges:
        original = originals.get(edge.identity)
        if original is not None:
            if not set(original.evidence).issubset(edge.evidence):
                raise ValueError("Property graph/P1 evidence mismatch.")
            verified.append(original)
    query = GraphSnapshot(graph.repository_key, graph.snapshot_key, graph.nodes, tuple(verified)).query()
    source = _SourceEvidence(workspace)
    symbols = {n.identity: index.get(SymbolIdentity(n.identity.key)) for n in graph.nodes
               if n.identity.namespace == "symbol"}
    roles = {m.identity: m for m in domain.mappings}
    diagnostics: set[str] = set()
    exhaustive = True

    def node(identity: NodeIdentity, stage: PropertyStage) -> PropertyNode:
        value = query.node(identity)
        assert value is not None
        proofs = tuple(RelationEvidence("p2.property.v1.anchor", a, "P1 source anchor") for a in value.anchors)
        symbol = symbols.get(identity)
        if symbol and symbol.parent_identity:
            proofs += (RelationEvidence("p1.symbol.parent_identity", SourceAnchor(symbol.identity,
                       source_range=symbol.declaration or symbol.definition),
                       f"semantic parent {NodeIdentity.for_symbol(symbol.parent_identity).value}"),)
        owner = roles.get(NodeIdentity.for_symbol(symbol.parent_identity)) if symbol and symbol.parent_identity else None
        mapping = roles.get(identity) or owner
        if mapping:
            proofs += mapping.evidence + tuple(e for c in mapping.candidates for e in c.evidence)
        if stage in {PropertyStage.SUPPORT, PropertyStage.ENTRY} and owner and owner.resolved:
            if owner.resolved.role == NodeKind.BRIDGE and owner.resolved.component == component:
                stage = PropertyStage.BRIDGE
        return PropertyNode(value, stage, proofs)

    def match_body(identity: NodeIdentity, body: str, parameters: str = r"[^(){};\"'#]*"):
        symbol = symbols.get(identity)
        if symbol is None or symbol.definition is None:
            return None
        text, offset = source.window(symbol.definition.start)
        name = symbol.qualified_name.rsplit("::", 1)[-1]
        match = re.match(re.escape(name) + r"\(" + parameters + r"\)\s*(?:const\s*)?\{\s*" + body + r"\s*\}", text)
        return (symbol, match, offset) if match else None

    def refs(found, group: str) -> tuple[GraphEdge, ...]:
        symbol, match, offset = found
        range_ = source.range(symbol.definition.file, offset + match.start(group), offset + match.end(group))
        return tuple(e for e in query.outgoing_edges(NodeIdentity.for_file(range_.file),
                     relations=frozenset({RelationType.REFERENCE}))
                     if any(p.anchor.source_range == range_ for p in e.evidence))

    def proof(found, rule: str) -> RelationEvidence:
        symbol, match, offset = found
        return source.proof("property." + rule, source.range(symbol.definition.file, offset, offset + match.end()),
                            symbol.identity)

    # Source revalidation uses P2-D itself. A supplied domain edge must still
    # have its original meaning; missing edges/support are never backfilled.
    for edge in graph.edges:
        if edge.identity.source == setter and edge.identity.relation == RelationType.UPDATE_PROPERTY:
            for evidence in edge.evidence:
                if evidence.anchor.file:
                    source.read(evidence.anchor.file.path.as_posix())
    extracted = extract_framework_relations(index, generic, domain, workspace)
    updates = {e.identity: e for e in extracted.graph.edges if e.identity.relation == RelationType.UPDATE_PROPERTY}
    provided = {e.identity: e for e in graph.edges}
    binding = None
    binding_gaps: list[str] = []
    candidates: tuple[NodeIdentity, ...] = ()
    candidate_evidence: tuple[RelationEvidence, ...] = ()
    found = match_body(setter, r"ACE_UPDATE_(?P<kind>LAYOUT|PAINT)_PROPERTY\(\s*(?P<target>\w+)\s*,"
                              r"\s*(?P<token>\w+)\s*,\s*\w+\s*\);")
    selected = symbols.get(setter)
    owner = roles.get(NodeIdentity.for_symbol(selected.parent_identity)) if selected and selected.parent_identity else None
    if owner and owner.status == MappingStatus.AMBIGUOUS:
        binding_gaps.append("ambiguous_model_role")
    elif not owner or not owner.resolved or owner.resolved.role != NodeKind.MODEL or owner.resolved.component != component:
        binding_gaps.append("unknown_or_cross_component_model")
    if found:
        references = refs(found, "target")
        candidates = tuple(sorted(e.identity.target for e in references))
        candidate_evidence = (proof(found, "token"),) + tuple(p for e in references for p in e.evidence)
        candidate_evidence += tuple(p for identity in candidates for p in node(identity, PropertyStage.SUPPORT).evidence)
        if len(references) > 1:
            binding_gaps.append("ambiguous_property_identity")
        elif not references:
            binding_gaps.append("missing_property_reference")
        else:
            target = references[0].identity.target
            mapping = roles.get(target)
            expected = NodeKind.LAYOUT_PROPERTY if found[1].group("kind") == "LAYOUT" else NodeKind.PAINT_PROPERTY
            if mapping and mapping.status == MappingStatus.AMBIGUOUS:
                binding_gaps.append("ambiguous_property_role")
            elif mapping and mapping.resolved and mapping.resolved.role != expected:
                binding_gaps.append("ambiguous_property_role_conflict")
            elif not mapping or not mapping.resolved or mapping.resolved.component != component:
                binding_gaps.append("unknown_or_cross_component_property")
            elif not binding_gaps:
                for edge in updates.values():
                    if edge.identity.source != setter or edge.identity.target != target:
                        continue
                    supplied = provided.get(edge.identity)
                    backing = tuple(e for e in verified if e.identity.target == setter and
                                    e.identity.relation == RelationType.DEFINE)
                    if supplied and set(edge.evidence).issubset(supplied.evidence) and backing:
                        binding = PropertyBinding(found[1].group("token"), target, expected, edge,
                                                  (proof(found, "token"),) + mapping.resolved.evidence)
    if binding is None and not binding_gaps:
        binding_gaps.append("missing_update_binding")

    # Explicit, complete tiny write/read bodies are the supported state rule.
    # Names only corroborate the already CALL-resolved writer of the macro;
    # the shared FIELD identity, not Get/Set spelling, connects reads to writes.
    tails: list[tuple[tuple[PropertyNode, ...], tuple[GraphEdge, ...], tuple[str, ...]]] = []
    if binding:
        property_stage = PropertyStage.LAYOUT_PROPERTY if binding.role == NodeKind.LAYOUT_PROPERTY else PropertyStage.PAINT_PROPERTY
        base = (node(binding.property_class, property_stage),)
        writers = []
        for call in query.outgoing_edges(setter, relations=frozenset({RelationType.CALL})):
            writer = symbols.get(call.identity.target)
            if (writer and writer.kind == SymbolKind.METHOD and writer.parent_identity and
                    NodeIdentity.for_symbol(writer.parent_identity) == binding.property_class and
                    writer.qualified_name.rsplit("::", 1)[-1] == "Update" + binding.token):
                writers.append(call)
        if not writers:
            tails.append((base, (), ("missing_property_writer",)))
        for call in writers:
            writer_id = call.identity.target
            write = match_body(writer_id, r"(?P<field>\w+)\s*=\s*(?P=parameter)\s*;",
                               r"[\w:&*<> ]+\s+(?P<parameter>\w+)")
            field_refs = () if write is None else refs(write, "field")
            prefix = base + (node(writer_id, PropertyStage.WRITER),)
            if write:
                prefix = prefix[:-1] + (PropertyNode(prefix[-1].node, PropertyStage.WRITER,
                           prefix[-1].evidence + (proof(write, "write"),)),)
            if len(field_refs) != 1:
                tails.append((prefix, (call,) + field_refs, ("ambiguous_state_identity" if field_refs else "unsupported_property_write",)))
                candidates += tuple(e.identity.target for e in field_refs)
                candidate_evidence += tuple(p for e in field_refs for p in e.evidence)
                continue
            field = symbols.get(field_refs[0].identity.target)
            if not field or field.kind != SymbolKind.FIELD or field.parent_identity != symbols[writer_id].parent_identity:
                tails.append((prefix, (call,), ("unsupported_property_state",)))
                continue
            state = field_refs[0].identity.target
            prefix += (node(state, PropertyStage.STATE),)
            readers = []
            for identity, reader in sorted(symbols.items()):
                if not reader or reader.kind != SymbolKind.METHOD or reader.parent_identity != field.parent_identity:
                    continue
                read = match_body(identity, r"return\s+(?P<field>\w+)\s*;", r"\s*")
                if not read:
                    continue
                references = refs(read, "field")
                if not any(e.identity.target == state for e in references):
                    continue
                if len(references) > 1:
                    candidates += tuple(e.identity.target for e in references)
                    candidate_evidence += tuple(p for e in references for p in e.evidence)
                for incoming in query.incoming_edges(identity, relations=frozenset({RelationType.CALL})):
                    consumer = incoming.identity.source
                    if consumer in {setter, writer_id, identity}:
                        continue
                    extra = (node(identity, PropertyStage.READER), node(consumer, PropertyStage.CONSUMER))
                    # Attach exact write/read source hashes alongside node anchors.
                    extra = (PropertyNode(extra[0].node, extra[0].stage, extra[0].evidence + (proof(read, "read"),
                              proof(write, "write"))), extra[1])
                    gaps = ("ambiguous_state_identity",) if len(references) > 1 else ()
                    readers.append((prefix + extra, (call,) + field_refs + references + (incoming,), gaps))
            tails.extend(readers or [(prefix, (call,) + field_refs, ("missing_downstream_consumer",))])

    relevant = {setter}
    pending = [setter]
    while pending:
        for edge in query.incoming_edges(pending.pop(), relations=frozenset({RelationType.CALL})):
            if edge.identity.source not in relevant:
                relevant.add(edge.identity.source)
                pending.append(edge.identity.source)
    paths: list[PropertyPath] = []
    stack: list[tuple[tuple[NodeIdentity, ...], tuple[GraphEdge, ...]]] = [((seed,), ())]
    states = 0
    while stack:
        if states >= bounds.max_states or len(paths) >= bounds.max_paths:
            diagnostics.add("state_or_path_limit")
            exhaustive = False
            break
        identities, calls = stack.pop()
        states += 1
        nodes = tuple(node(i, PropertyStage.MODEL if i == setter else PropertyStage.ENTRY if j == 0 else PropertyStage.SUPPORT)
                      for j, i in enumerate(identities) if query.node(i) is not None)
        gaps = []
        for identity in identities:
            symbol = symbols.get(identity)
            mapping = roles.get(NodeIdentity.for_symbol(symbol.parent_identity)) if symbol and symbol.parent_identity else None
            if mapping and mapping.status == MappingStatus.AMBIGUOUS:
                gaps.append("ambiguous_call_role")
            elif mapping and mapping.resolved and mapping.resolved.component not in {None, component}:
                gaps.append("cross_component_call")
        current = identities[-1]
        if current == setter:
            if not calls:
                gaps.append("missing_entry_call")
            gaps.extend(binding_gaps)
            for tail, support, problems in tails or [((), (), ())]:
                if len(paths) >= bounds.max_paths:
                    diagnostics.add("path_limit")
                    exhaustive = False
                    break
                all_nodes = nodes + tail
                locations = () if all(any(a.source_range for a in n.node.anchors) for n in all_nodes) else ("missing_source_location",)
                paths.append(PropertyPath(all_nodes, calls, binding, support, tuple(sorted(set(candidates))),
                                          tuple(sorted(set(gaps + list(problems) + list(locations)))),
                                          tuple(sorted(set(candidate_evidence), key=lambda p: p.sort_key))))
            continue
        outgoing = tuple(e for e in query.outgoing_edges(current, relations=frozenset({RelationType.CALL}))
                         if e.identity.target in relevant)
        if outgoing and len(calls) < bounds.max_depth and not gaps:
            for edge in reversed(outgoing):
                if edge.identity.target in identities:
                    diagnostics.add("cycle_cut")
                    exhaustive = False
                else:
                    stack.append((identities + (edge.identity.target,), calls + (edge,)))
            if any(e.identity.target not in identities for e in outgoing):
                continue
        if outgoing and len(calls) >= bounds.max_depth:
            diagnostics.add("depth_limit")
            exhaustive = False
        paths.append(PropertyPath(nodes, calls, None, (), (), tuple(sorted(set(gaps + ["missing_setter_call"])))))
    if component not in {c.node.identity for c in domain.components}:
        diagnostics.add("unknown_component")
        exhaustive = False
    if any(workspace.resolve(path).read_text(encoding="utf-8") != text for path, text in source.files.items()):
        raise ValueError("Source changed during property query.")
    status = (PropertyStatus.AMBIGUOUS if len(paths) > 1 or any(p.status == PropertyStatus.AMBIGUOUS for p in paths)
              else PropertyStatus.COMPLETE if exhaustive and paths and paths[0].status == PropertyStatus.COMPLETE
              else PropertyStatus.INCOMPLETE)
    return PropertyTrace(graph.repository_key, graph.snapshot_key, seed, setter, component, status,
                         tuple(paths), exhaustive, tuple(sorted(diagnostics)))
