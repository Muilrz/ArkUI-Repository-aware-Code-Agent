"""Deterministic ArkUI annotations over P1 symbols and an existing P2 snapshot."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum

from arkui_agent.graph.model import (
    GraphNode, NodeIdentity, NodeKind, RelationEvidence, SourceAnchor,
)
from arkui_agent.graph.projection import GraphSnapshot
from arkui_agent.repository.index import SymbolIndex
from arkui_agent.repository.model import RepositoryFile, SymbolIdentity, SymbolKind


FRAMEWORK_ROLES = frozenset({
    NodeKind.BRIDGE, NodeKind.MODEL, NodeKind.PATTERN, NodeKind.LAYOUT_PROPERTY,
    NodeKind.PAINT_PROPERTY, NodeKind.LAYOUT_ALGORITHM, NodeKind.OVERLAY_MANAGER,
})


@dataclass(frozen=True, slots=True)
class ComponentSpec:
    key: str
    display_name: str

    def __post_init__(self) -> None:
        if not self.key.strip() or not self.display_name.strip():
            raise ValueError("Component key and display name must be nonempty.")

    @property
    def identity(self) -> NodeIdentity:
        return NodeIdentity("arkui.component", self.key)


@dataclass(frozen=True, slots=True)
class RoleRule:
    """Reviewed conjunction of semantic class, exact qualified name and file.

    component_key is an explicit association, never inferred from a suffix or
    common directory ancestor. None denotes a shared framework service.
    """

    rule_id: str
    role: NodeKind
    qualified_name: str
    file: RepositoryFile
    component_key: str | None

    def __post_init__(self) -> None:
        if not self.rule_id.strip() or not self.qualified_name.strip():
            raise ValueError("Role rule requires an ID and exact qualified name.")
        if not isinstance(self.role, NodeKind) or self.role not in FRAMEWORK_ROLES:
            raise ValueError("Unsupported framework role.")


class MappingStatus(str, Enum):
    RECOGNIZED = "recognized"
    UNKNOWN = "unknown"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True, slots=True)
class RoleCandidate:
    role: NodeKind
    component: NodeIdentity | None
    evidence: tuple[RelationEvidence, ...]


@dataclass(frozen=True, slots=True)
class RoleMapping:
    identity: NodeIdentity
    status: MappingStatus
    candidates: tuple[RoleCandidate, ...]
    reason: str
    evidence: tuple[RelationEvidence, ...]

    @property
    def resolved(self) -> RoleCandidate | None:
        return self.candidates[0] if self.status == MappingStatus.RECOGNIZED else None


@dataclass(frozen=True, slots=True)
class ComponentMapping:
    node: GraphNode
    evidence: tuple[RelationEvidence, ...]


@dataclass(frozen=True, slots=True)
class DomainMap:
    """Scoped domain metadata; P1 records and P2 generic graph remain unchanged."""

    repository_key: str
    snapshot_key: str
    ruleset_identity: str
    mappings: tuple[RoleMapping, ...]
    components: tuple[ComponentMapping, ...]

    def lookup(self, identity: NodeIdentity) -> RoleMapping | None:
        return next((item for item in self.mappings if item.identity == identity), None)

    def members(self, component: NodeIdentity) -> tuple[RoleMapping, ...]:
        """Only unambiguous associations, in stable symbol identity order."""
        return tuple(item for item in self.mappings
                     if item.resolved is not None and item.resolved.component == component)

    def to_dict(self) -> dict[str, object]:
        """JSON-compatible metadata including rule and source evidence."""
        return {
            "schema_version": 1, "repository_key": self.repository_key,
            "snapshot_key": self.snapshot_key, "ruleset_identity": self.ruleset_identity,
            "components": [{"identity": c.node.identity.value, "kind": c.node.kind.value,
                            "display_name": c.node.display_name,
                            "evidence": [_evidence_dict(e) for e in c.evidence]} for c in self.components],
            "mappings": [{
                "identity": m.identity.value, "status": m.status.value, "reason": m.reason,
                "evidence": [_evidence_dict(e) for e in m.evidence],
                "candidates": [{"role": c.role.value,
                                "component": None if c.component is None else c.component.value,
                                "evidence": [_evidence_dict(e) for e in c.evidence]} for c in m.candidates],
            } for m in self.mappings],
        }


def _evidence_dict(evidence: RelationEvidence) -> dict[str, object]:
    anchor = evidence.anchor
    return {
        "provenance": evidence.provenance, "description": evidence.description,
        "symbol": None if anchor.symbol_identity is None else anchor.symbol_identity.value,
        "file": None if anchor.file is None else anchor.file.path.as_posix(),
        "range": None if anchor.source_range is None else anchor.source_range.to_dict(),
    }


def _unique_evidence(items: list[RelationEvidence]) -> tuple[RelationEvidence, ...]:
    return tuple(sorted(set(items), key=lambda item: item.sort_key))


class ArkUIRoleMapper:
    def __init__(self, components: tuple[ComponentSpec, ...], rules: tuple[RoleRule, ...]) -> None:
        self._components = {component.key: component for component in components}
        if len(self._components) != len(components):
            raise ValueError("Duplicate component key.")
        if len({rule.rule_id for rule in rules}) != len(rules):
            raise ValueError("Duplicate role rule ID.")
        if any(rule.component_key is not None and rule.component_key not in self._components for rule in rules):
            raise ValueError("Role rule refers to an unknown component.")
        self._rules = tuple(sorted(rules, key=lambda rule: rule.rule_id))
        payload = [
            sorted((c.key, c.display_name) for c in components),
            [(r.rule_id, r.role.value, r.qualified_name, r.file.path.as_posix(), r.component_key)
             for r in self._rules],
        ]
        self.ruleset_identity = "arkui-role:v1:" + hashlib.sha256(
            json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

    def map(self, index: SymbolIndex, graph: GraphSnapshot) -> DomainMap:
        """Annotate one consistent P1/P2 snapshot without reading or parsing C++.

        All graph symbol nodes receive a decision. Missing/unsupported facts
        remain unknown. Inconsistent supplied snapshots fail explicitly.
        """
        mappings = tuple(self._map_node(index, node) for node in graph.nodes
                         if node.identity.namespace == "symbol")
        components = []
        for spec in sorted(self._components.values(), key=lambda item: item.identity):
            evidence = _unique_evidence([
                e for mapping in mappings if mapping.resolved is not None
                and mapping.resolved.component == spec.identity for e in mapping.resolved.evidence
            ])
            if evidence:
                components.append(ComponentMapping(
                    GraphNode(spec.identity, NodeKind.COMPONENT, spec.display_name,
                              tuple(e.anchor for e in evidence)), evidence,
                ))
        return DomainMap(graph.repository_key, graph.snapshot_key, self.ruleset_identity,
                         mappings, tuple(components))

    def _map_node(self, index: SymbolIndex, node: GraphNode) -> RoleMapping:
        symbol = index.get(SymbolIdentity(node.identity.key))
        evidence = tuple(RelationEvidence("p2.graph.anchor", a, "existing graph source anchor")
                         for a in node.anchors)

        def unknown(reason: str) -> RoleMapping:
            return RoleMapping(node.identity, MappingStatus.UNKNOWN, (), reason, evidence)

        if symbol is None:
            return unknown("missing_p1_symbol")
        if symbol.kind != SymbolKind.CLASS or node.kind != NodeKind.CLASS:
            return unknown("unsupported_symbol_kind")
        ranges = tuple(dict.fromkeys(r for r in (symbol.declaration, symbol.definition) if r is not None))
        if node.display_name != symbol.display_name or any(
            SourceAnchor(symbol.identity, source_range=r) not in node.anchors for r in ranges
        ):
            raise ValueError(f"P1/graph snapshot mismatch: {node.identity.value}")
        rules = tuple(r for r in self._rules if r.qualified_name == symbol.qualified_name)
        if not rules:
            return unknown("no_qualified_name_rule")
        allowed_files = {rule.file for rule in rules}
        # A class can be forward-declared in unrelated headers. P1's definition
        # is authoritative; a matching declaration cannot override a definition
        # elsewhere. Keep all original anchors for audit, including forward refs.
        authority = symbol.definition or symbol.declaration
        assert authority is not None
        if authority.file not in allowed_files:
            return unknown("source_file_mismatch")
        candidates: dict[tuple[str, str], list[RelationEvidence]] = {}
        for rule in rules:
            for source_range in ranges:
                if source_range.file == rule.file:
                    candidates.setdefault((rule.role.value, rule.component_key or ""), []).append(
                        RelationEvidence(
                            f"arkui.role.v1.{rule.rule_id}",
                            SourceAnchor(symbol.identity, source_range=source_range),
                            f"P1 class {symbol.qualified_name}; exact file {rule.file.path.as_posix()}; "
                            f"catalog association {rule.component_key or 'shared service'}",
                        )
                    )
        matches = tuple(RoleCandidate(
            NodeKind(role), None if not component else self._components[component].identity,
            _unique_evidence(candidates[(role, component)]),
        ) for role, component in sorted(candidates))
        status = MappingStatus.RECOGNIZED if len(matches) == 1 else MappingStatus.AMBIGUOUS
        return RoleMapping(node.identity, status, matches,
                           "exact_catalog_match" if len(matches) == 1 else "conflicting_role_or_component_rules",
                           evidence)
