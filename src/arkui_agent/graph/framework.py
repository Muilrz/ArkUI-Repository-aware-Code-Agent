"""Conservative framework primitives over a quiescent P1/P2 snapshot.

This is a bounded evidence matcher, not a C++ parser or a trace builder.
Unsupported bodies deliberately produce diagnostics instead of guessed edges.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from arkui_agent.graph.domain import DomainMap, RoleCandidate
from arkui_agent.graph.model import (
    EdgeIdentity, GraphEdge, NodeIdentity, NodeKind, RelationEvidence, RelationType, SourceAnchor,
)
from arkui_agent.graph.projection import GraphSnapshot, project_index
from arkui_agent.repository.index import SymbolIndex
from arkui_agent.repository.model import RepositoryFile, SourceLocation, SourceRange, Symbol, SymbolIdentity, SymbolKind
from arkui_agent.repository.workspace import RepositoryWorkspace


RULESET = "arkui.framework.v1"
_FACTORY_FILE = "interfaces/inner_api/ace_kit/include/ui/base/referenced.h"
_MACRO_FILE = "frameworks/core/components_ng/base/view_stack_processor.h"
_CREATE = r"return\s+(?:AceType::)?MakeRefPtr<(?P<target>\w+)>\(\);"
_UPDATE = (r"ACE_UPDATE_(?P<kind>LAYOUT|PAINT)_PROPERTY\(\s*(?P<target>\w+)\s*,"
           r"\s*\w+\s*,\s*\w+\s*\);")
_OPERATIONS = {
    (NodeKind.LAYOUT_ALGORITHM, "Measure"): (RelationType.MEASURE,
        r"void Measure\(LayoutWrapper\* layoutWrapper\) override;"),
    (NodeKind.LAYOUT_ALGORITHM, "Layout"): (RelationType.LAYOUT,
        r"void Layout\(LayoutWrapper\* layoutWrapper\) override;"),
    (NodeKind.LAYOUT_ALGORITHM, "MeasureContent"): (RelationType.MEASURE,
        r"std::optional<SizeF> MeasureContent\( const LayoutConstraintF& contentConstraint, "
        r"LayoutWrapper\* layoutWrapper\) override;"),
    (NodeKind.OVERLAY_MANAGER, "ShowMenu"): (RelationType.SHOW,
        r"void ShowMenu\(int32_t targetId, const NG::OffsetF& offset, RefPtr<FrameNode> menu = nullptr\);"),
    (NodeKind.OVERLAY_MANAGER, "HideMenu"): (RelationType.CLOSE,
        r"void HideMenu\(const RefPtr<FrameNode>& menu, int32_t targetId, bool isMenuOnTouch = false, "
        r"const HideMenuType& reason = HideMenuType::NORMAL\);"),
}


@dataclass(frozen=True, slots=True, order=True)
class FrameworkDiagnostic:
    subject: NodeIdentity
    rule: str
    reason: str


@dataclass(frozen=True, slots=True)
class FrameworkExtraction:
    graph: GraphSnapshot
    diagnostics: tuple[FrameworkDiagnostic, ...]
    ruleset_identity: str = RULESET


class _SourceEvidence:
    """Read-only, per-build text snapshot. Positions use P1's character columns."""

    def __init__(self, workspace: RepositoryWorkspace) -> None:
        self.workspace = workspace
        self.files: dict[str, str] = {}

    def read(self, path: str) -> str:
        if path not in self.files:
            self.files[path] = self.workspace.resolve(path).read_text(encoding="utf-8")
        return self.files[path]

    def window(self, location: SourceLocation, *, line_start: bool = False) -> tuple[str, int]:
        text = self.read(location.file.path.as_posix())
        lines = text.splitlines(keepends=True)
        if location.line > len(lines) or location.column > len(lines[location.line - 1]) + 1:
            return "", len(text)
        offset = sum(map(len, lines[:location.line - 1])) + (0 if line_start else location.column - 1)
        # Only complete tiny bodies/signatures are accepted; never scan to a
        # later method or infer enclosing function from a nearby name.
        return text[offset:offset + 2048], offset

    def range(self, file: RepositoryFile, start: int, end: int) -> SourceRange:
        text = self.read(file.path.as_posix())

        def location(offset: int) -> SourceLocation:
            return SourceLocation(file, text.count("\n", 0, offset) + 1,
                                  offset - text.rfind("\n", 0, offset))

        return SourceRange(location(start), location(end))

    def proof(self, rule: str, range_: SourceRange, symbol: SymbolIdentity | None = None) -> RelationEvidence:
        text = self.read(range_.file.path.as_posix())
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        return RelationEvidence(f"{RULESET}.{rule}", SourceAnchor(symbol, source_range=range_),
                                f"matched reviewed source template; normalized-newline source sha256={digest}")


def extract_framework_relations(
    index: SymbolIndex, generic: GraphSnapshot, domain: DomainMap, workspace: RepositoryWorkspace,
) -> FrameworkExtraction:
    """Return generic + typed edges; no input mutation or generated-data writes.

    MEASURE/LAYOUT/SHOW/CLOSE bind a recognized class to its declared operation,
    not a runtime invocation. CREATE/UPDATE_PROPERTY bind a method to the exact
    semantically referenced target class inside a supported complete tiny body.
    """
    if (domain.repository_key, domain.snapshot_key) != (generic.repository_key, generic.snapshot_key):
        raise ValueError("Domain/graph snapshot scope mismatch.")
    if project_index(index, repository_key=generic.repository_key, snapshot_key=generic.snapshot_key) != generic:
        raise ValueError("Expected the matching P1 generic projection, without domain edges.")
    source = _SourceEvidence(workspace)
    query = generic.query()
    edges = list(generic.edges)
    diagnostics: list[FrameworkDiagnostic] = []

    def diagnose(subject: NodeIdentity, rule: str, reason: str) -> None:
        diagnostics.append(FrameworkDiagnostic(subject, rule, reason))

    def role(identity: NodeIdentity) -> RoleCandidate | None:
        mapping = domain.lookup(identity)
        if mapping is None or mapping.resolved is None:
            diagnose(identity, "role", "missing_role" if mapping is None else mapping.status.value)
            return None
        return mapping.resolved

    def supports(symbol: Symbol, relation: RelationType, range_: SourceRange) -> tuple[GraphEdge, ...]:
        key = EdgeIdentity(NodeIdentity.for_file(range_.file), NodeIdentity.for_symbol(symbol.identity), relation)
        return tuple(e for e in query.incoming_edges(key.target) if e.identity == key)

    def emit(start: NodeIdentity, end: NodeIdentity, relation: RelationType, rule: str,
             backing: tuple[GraphEdge, ...], evidence: tuple[RelationEvidence, ...]) -> None:
        proofs = list(evidence)
        for edge in backing:
            proofs.extend(edge.evidence)
            proofs.append(RelationEvidence(f"{RULESET}.{rule}.generic", edge.evidence[0].anchor,
                                           f"supporting generic edge {edge.identity.value}"))
        edges.append(GraphEdge(EdgeIdentity(start, end, relation), tuple(proofs)))

    symbols = {node.identity: index.get(SymbolIdentity(node.identity.key)) for node in generic.nodes
               if node.identity.namespace == "symbol"}
    for identity, symbol in symbols.items():
        if symbol is None or symbol.kind != SymbolKind.METHOD:
            continue
        if symbol.parent_identity is None:
            diagnose(identity, "owner", "missing_semantic_parent")
            continue
        parent = NodeIdentity.for_symbol(symbol.parent_identity)
        owner = role(parent)
        if owner is None:
            continue
        owner_evidence = owner.evidence + (RelationEvidence(
            "p1.symbol.parent_identity", SourceAnchor(symbol.identity, source_range=symbol.declaration or symbol.definition),
            f"semantic parent {parent.value}; domain ruleset {domain.ruleset_identity}",
        ),)
        name = symbol.qualified_name.rsplit("::", 1)[-1]
        operation = _OPERATIONS.get((owner.role, name))
        if operation is not None:
            relation, pattern = operation
            declaration = symbol.declaration
            if declaration is not None:
                text, offset = source.window(declaration.start, line_start=True)
                pattern = pattern.replace(name, f"(?P<operation>{name})", 1)
                match = re.match(r"\s*" + pattern.replace(" ", r"\s+"), text)
                backing = supports(symbol, RelationType.DECLARE, declaration)
                # Verify the P1 selection actually denotes the matched method,
                # not a different overload on a nearby line.
                _, selection_offset = source.window(declaration.start)
                if match and offset + match.start("operation") == selection_offset and backing:
                    proof = source.proof("operation", source.range(declaration.file, offset, offset + match.end()),
                                         symbol.identity)
                    emit(parent, identity, relation, "operation", backing, owner_evidence + (proof,))
                    continue
            diagnose(identity, "operation", "unsupported_declaration_template")
            continue
        if owner.role not in {NodeKind.PATTERN, NodeKind.MODEL}:
            continue
        definition = symbol.definition
        if definition is None:
            diagnose(identity, "body", "missing_definition")
            continue
        text, offset = source.window(definition.start)
        body = _CREATE if owner.role == NodeKind.PATTERN else _UPDATE
        # Symbol identity/parent come exclusively from P1. The text matcher only
        # recognizes a bounded non-symbol factory/macro idiom at that anchor.
        pattern = re.escape(name) + r"\([^(){};\"'#]*\)(?:\s+override)?\s*\{\s*" + body + r"\s*\}"
        match = re.match(pattern, text)
        if match is None:
            diagnose(identity, "body", "unsupported_body_template")
            continue
        target_range = source.range(definition.file, offset + match.start("target"), offset + match.end("target"))
        references = tuple(e for e in query.outgoing_edges(NodeIdentity.for_file(definition.file))
                           if e.identity.relation == RelationType.REFERENCE and any(
                               p.anchor.source_range == target_range for p in e.evidence))
        if len(references) != 1:
            diagnose(identity, "reference", "missing_reference" if not references else "ambiguous_reference")
            continue
        reference = references[0]
        target = role(reference.identity.target)
        expected = ({NodeKind.LAYOUT_PROPERTY, NodeKind.PAINT_PROPERTY, NodeKind.LAYOUT_ALGORITHM}
                    if owner.role == NodeKind.PATTERN else
                    {NodeKind.LAYOUT_PROPERTY if match.group("kind") == "LAYOUT" else NodeKind.PAINT_PROPERTY})
        if target is None or target.role not in expected or owner.component is None or target.component != owner.component:
            diagnose(identity, "association", "unknown_ambiguous_or_cross_component_target")
            continue
        backing = supports(symbol, RelationType.DEFINE, definition) + (reference,)
        evidence = owner_evidence + target.evidence + (
            source.proof("body", source.range(definition.file, offset, offset + match.end()), symbol.identity),
        )
        if owner.role == NodeKind.PATTERN:
            factories = []
            for edge in query.outgoing_edges(identity):
                callee = symbols.get(edge.identity.target)
                if edge.identity.relation != RelationType.CALL or callee is None:
                    continue
                anchor = callee.definition or callee.declaration
                if (callee.qualified_name == "OHOS::Ace::Referenced::MakeRefPtr" and anchor is not None
                        and anchor.file.path.as_posix() == _FACTORY_FILE):
                    factory_text, factory_offset = source.window(anchor.start)
                    factory_match = re.match(
                        r"MakeRefPtr\(Args&&\.\.\. args\)\s*\{\s*return Claim<T, true>\(new T\("
                        r"std::forward<Args>\(args\)\.\.\.\)\);\s*\}", factory_text)
                    if factory_match:
                        factories.append(edge)
                        evidence += (source.proof("factory", source.range(anchor.file, factory_offset,
                                     factory_offset + factory_match.end()), callee.identity),)
            if len(factories) != 1:
                diagnose(identity, "factory", "missing_or_ambiguous_semantic_factory_call")
                continue
            emit(identity, reference.identity.target, RelationType.CREATE, "create", backing + tuple(factories), evidence)
        else:
            # Exact reviewed macro expansion, including the delegation to the
            # node macro. A renamed/no-op macro must never imply an update.
            kind = match.group("kind")
            title = kind.title()
            expansions = (
                f"#defineACE_UPDATE_{kind}_PROPERTY(target,name,value)do{{"
                f"autoframeNode=ViewStackProcessor::GetInstance()->GetMainFrameNode();"
                f"ACE_UPDATE_NODE_{kind}_PROPERTY(target,name,value,frameNode);}}while(false)",
                f"#defineACE_UPDATE_NODE_{kind}_PROPERTY(target,name,value,frameNode)do{{"
                f"CHECK_NULL_VOID(frameNode);autocast##target=(frameNode)->Get{title}PropertyPtr<target>();"
                f"if(cast##target){{cast##target->Update##name(value);}}}}while(false)",
            )
            macro_file = RepositoryFile.from_path(_MACRO_FILE)
            macro_text = source.read(_MACRO_FILE)
            macro_matches = []
            for macro_name in (f"ACE_UPDATE_{kind}_PROPERTY", f"ACE_UPDATE_NODE_{kind}_PROPERTY"):
                macro_matches.append(tuple(re.finditer(
                    r"(?m)^#define " + macro_name + r"\([^\n]*\)(?:[^\n]*\\\n)*[^\n]*", macro_text)))
            if any(len(items) != 1 for items in macro_matches) or any(
                re.sub(r"\s+", "", items[0].group().replace("\\\n", "")) != expansion
                for items, expansion in zip(macro_matches, expansions)
            ):
                diagnose(identity, "macro", "unsupported_macro_definition")
                continue
            evidence += tuple(source.proof("macro", source.range(macro_file, items[0].start(), items[0].end()))
                              for items in macro_matches)
            emit(identity, reference.identity.target, RelationType.UPDATE_PROPERTY, "update", backing, evidence)

    # Preserve direct TEST identity/provenance; enrich only real tested-symbol
    # mappings, never fixture membership or transitive/coverage guesses.
    for edge in generic.edges:
        if edge.identity.relation != RelationType.TEST or not any(
            e.provenance == "p1.tested_symbol_mapping.references" for e in edge.evidence
        ):
            continue
        target_symbol = symbols.get(edge.identity.target)
        target_id = edge.identity.target
        if target_symbol is not None and target_symbol.kind == SymbolKind.METHOD and target_symbol.parent_identity:
            target_id = NodeIdentity.for_symbol(target_symbol.parent_identity)
        target = role(target_id)
        if target is not None:
            emit(edge.identity.source, edge.identity.target, RelationType.TEST, "test", (edge,), target.evidence)
    diagnose(NodeIdentity("arkui.framework", "mock"), "mock", "unsupported_p1_mock_facts")
    if any(workspace.resolve(path).read_text(encoding="utf-8") != text for path, text in source.files.items()):
        raise ValueError("Source changed during framework extraction; rebuild the snapshot.")
    return FrameworkExtraction(GraphSnapshot(generic.repository_key, generic.snapshot_key, generic.nodes, tuple(edges)),
                               tuple(sorted(set(diagnostics))))
