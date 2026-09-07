"""Read the existing public DomainMap.to_dict format without role remapping."""

from __future__ import annotations

import json
from pathlib import Path

from .domain import ComponentMapping, DomainMap, MappingStatus, RoleCandidate, RoleMapping, FRAMEWORK_ROLES
from .model import GraphNode, NodeIdentity, NodeKind, RelationEvidence, SourceAnchor
from arkui_agent.repository.model import RepositoryFile, SourceLocation, SourceRange, SymbolIdentity


class DomainStorageError(ValueError):
    """Invalid or unavailable prebuilt domain metadata."""


def _identity(value: str) -> NodeIdentity:
    if not isinstance(value, str) or not value.startswith("graph-node:v1:"):
        raise ValueError("Invalid domain node identity.")
    parts = json.loads(value[len("graph-node:v1:"):])
    if not isinstance(parts, list) or len(parts) != 2 or not all(isinstance(p, str) for p in parts):
        raise ValueError("Invalid domain node identity.")
    return NodeIdentity(*parts)


def _evidence(value: dict[str, object]) -> RelationEvidence:
    def location(item: dict[str, object]) -> SourceLocation:
        if type(item["line"]) is not int or type(item["column"]) is not int:
            raise ValueError("Invalid domain evidence coordinates.")
        return SourceLocation(RepositoryFile.from_path(item["file"]), item["line"], item["column"])

    source_range = value["range"]
    if not all(isinstance(value[key], str) for key in ("provenance", "description")):
        raise ValueError("Invalid domain evidence text.")
    return RelationEvidence(value["provenance"], SourceAnchor(
        None if value["symbol"] is None else SymbolIdentity(value["symbol"]),
        None if value["file"] is None else RepositoryFile.from_path(value["file"]),
        None if source_range is None else SourceRange(location(source_range["start"]), location(source_range["end"])),
    ), value["description"])


def read_domain_map(path: str | Path, *, repository_key: str, snapshot_key: str,
                    ruleset_identity: str) -> DomainMap:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        if (type(value) is not dict or type(value.get("schema_version")) is not int
                or value["schema_version"] != 1
                or (value["repository_key"], value["snapshot_key"], value["ruleset_identity"])
                != (repository_key, snapshot_key, ruleset_identity)):
            raise ValueError("Domain schema, scope or ruleset mismatch.")
        if not isinstance(value["mappings"], list) or not isinstance(value["components"], list):
            raise ValueError("Domain records must be arrays.")
        components: list[ComponentMapping] = []
        for item in value["components"]:
            evidence = tuple(_evidence(e) for e in item["evidence"])
            if item["kind"] != NodeKind.COMPONENT.value or not isinstance(item["display_name"], str):
                raise ValueError("Invalid component metadata.")
            components.append(ComponentMapping(GraphNode(_identity(item["identity"]), NodeKind.COMPONENT,
                                                         item["display_name"], tuple(e.anchor for e in evidence)), evidence))
        mappings: list[RoleMapping] = []
        for item in value["mappings"]:
            candidates: list[RoleCandidate] = []
            for candidate in item["candidates"]:
                role = NodeKind(candidate["role"])
                if role not in FRAMEWORK_ROLES:
                    raise ValueError("Invalid framework role.")
                candidates.append(RoleCandidate(role, None if candidate["component"] is None
                                                else _identity(candidate["component"]),
                                                tuple(_evidence(e) for e in candidate["evidence"])))
            status = MappingStatus(item["status"])
            if not isinstance(item["reason"], str) or (
                status is MappingStatus.RECOGNIZED and len(candidates) != 1
            ):
                raise ValueError("Invalid domain mapping decision.")
            mappings.append(RoleMapping(_identity(item["identity"]), status, tuple(candidates), item["reason"],
                                        tuple(_evidence(e) for e in item["evidence"])))
        if (len({m.identity for m in mappings}) != len(mappings)
                or len({c.node.identity for c in components}) != len(components)):
            raise ValueError("Duplicate domain identity.")
        return DomainMap(repository_key, snapshot_key, ruleset_identity, tuple(mappings), tuple(components))
    except (OSError, UnicodeError, ValueError, TypeError, KeyError, IndexError, AttributeError) as error:
        raise DomainStorageError(f"Unable to read domain metadata: {path}") from error
