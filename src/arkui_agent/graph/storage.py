"""Versioned JSON snapshot adapter; graph query remains storage-independent."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from arkui_agent.graph.model import (
    EdgeIdentity, GraphEdge, GraphNode, NodeIdentity, NodeKind,
    RelationEvidence, RelationType, SourceAnchor,
)
from arkui_agent.graph.projection import GraphSnapshot, project_index
from arkui_agent.graph.query import GraphQueryError
from arkui_agent.repository.index import SymbolIndex
from arkui_agent.repository.model import RepositoryFile, SourceLocation, SourceRange, SymbolIdentity


GRAPH_FILENAME = "code-graph.json"


class GraphStorageError(GraphQueryError):
    """Snapshot I/O, format, or scope mismatch; never an empty graph."""


class GraphStore:
    """One repository/P1 snapshot in an explicitly supplied runtime directory.

    Each scope has an isolated path. Rebuild replaces all records atomically;
    a failed projection/write preserves the last complete snapshot. A loaded
    snapshot/query remains independent of subsequent rebuild/delete operations.
    """

    def __init__(
        self, runtime_directory: str | Path, *, repository_key: str, snapshot_key: str,
    ) -> None:
        if not str(runtime_directory).strip():
            raise ValueError("Runtime directory must not be empty.")
        if not repository_key.strip() or not snapshot_key.strip():
            raise ValueError("Graph store requires repository and snapshot keys.")
        self.repository_key = repository_key
        self.snapshot_key = snapshot_key
        self.path = (
            Path(runtime_directory).expanduser().resolve() / "graph"
            / _scope_digest(repository_key) / _scope_digest(snapshot_key) / GRAPH_FILENAME
        )

    def rebuild(self, index: SymbolIndex) -> GraphSnapshot:
        snapshot = project_index(index, repository_key=self.repository_key,
                                 snapshot_key=self.snapshot_key)
        self.save(snapshot)
        return snapshot

    def save(self, snapshot: GraphSnapshot) -> None:
        self._check_scope(snapshot.repository_key, snapshot.snapshot_key)
        data = _encode(snapshot)
        temporary: Path | None = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                                    dir=self.path.parent, suffix=".tmp", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(data)
            temporary.replace(self.path)
        except OSError as error:
            raise GraphStorageError(f"Unable to save graph snapshot: {self.path}") from error
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def load(self) -> GraphSnapshot:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if (not isinstance(payload, dict) or type(payload.get("schema_version")) is not int
                    or payload["schema_version"] != 1):
                raise ValueError("Unsupported graph snapshot schema.")
            if payload.get("projection") != "p1-index-v1":
                raise ValueError("Unsupported graph projection version.")
            self._check_scope(payload["repository_key"], payload["snapshot_key"])
            return _decode(payload)
        except (OSError, UnicodeError, ValueError, TypeError, KeyError, IndexError) as error:
            raise GraphStorageError(f"Unable to load graph snapshot: {self.path}") from error

    def delete(self) -> None:
        """Delete this exact generated file; repeated deletion is safe."""
        try:
            self.path.unlink(missing_ok=True)
        except OSError as error:
            raise GraphStorageError(f"Unable to delete graph snapshot: {self.path}") from error

    def _check_scope(self, repository_key: str, snapshot_key: str) -> None:
        if (repository_key, snapshot_key) != (self.repository_key, self.snapshot_key):
            raise GraphStorageError("Graph snapshot repository/snapshot scope mismatch.")


def _scope_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _node_id(identity: NodeIdentity) -> list[str]:
    return [identity.namespace, identity.key]


def _anchor(anchor: SourceAnchor) -> dict[str, object]:
    return {
        "symbol": None if anchor.symbol_identity is None else anchor.symbol_identity.value,
        "file": None if anchor.file is None else anchor.file.path.as_posix(),
        "range": None if anchor.source_range is None else anchor.source_range.to_dict(),
    }


def _encode(snapshot: GraphSnapshot) -> str:
    return json.dumps({
        "schema_version": 1, "projection": "p1-index-v1",
        "repository_key": snapshot.repository_key, "snapshot_key": snapshot.snapshot_key,
        "nodes": [{
            "identity": _node_id(node.identity), "kind": node.kind.value,
            "display_name": node.display_name, "anchors": [_anchor(a) for a in node.anchors],
        } for node in snapshot.nodes],
        "edges": [{
            "source": _node_id(edge.identity.source), "target": _node_id(edge.identity.target),
            "relation": edge.identity.relation.value,
            "evidence": [{"provenance": e.provenance, "anchor": _anchor(e.anchor),
                          "description": e.description} for e in edge.evidence],
        } for edge in snapshot.edges],
    }, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n"


def _read_identity(value: Any) -> NodeIdentity:
    if not isinstance(value, list) or len(value) != 2 or not all(isinstance(v, str) for v in value):
        raise ValueError("Invalid node identity record.")
    return NodeIdentity(*value)


def _read_anchor(value: dict[str, Any]) -> SourceAnchor:
    source_range = None
    if value["range"] is not None:
        def location(item: dict[str, Any]) -> SourceLocation:
            if type(item["line"]) is not int or type(item["column"]) is not int:
                raise ValueError("Source coordinates must be integers.")
            return SourceLocation(RepositoryFile.from_path(item["file"]), item["line"], item["column"])
        source_range = SourceRange(location(value["range"]["start"]), location(value["range"]["end"]))
    if value["symbol"] is not None and not isinstance(value["symbol"], str):
        raise ValueError("Invalid symbol identity record.")
    return SourceAnchor(
        None if value["symbol"] is None else SymbolIdentity(value["symbol"]),
        None if value["file"] is None else RepositoryFile.from_path(value["file"]), source_range,
    )


def _decode(payload: dict[str, Any]) -> GraphSnapshot:
    if not isinstance(payload["nodes"], list) or not isinstance(payload["edges"], list):
        raise ValueError("Graph snapshot records must be arrays.")
    nodes = []
    for item in payload["nodes"]:
        if not isinstance(item["display_name"], str):
            raise ValueError("Invalid graph node name.")
        nodes.append(GraphNode(_read_identity(item["identity"]), NodeKind(item["kind"]),
                               item["display_name"], tuple(_read_anchor(a) for a in item["anchors"])))
    edges = []
    for item in payload["edges"]:
        evidence = []
        for record in item["evidence"]:
            if not all(isinstance(record[k], str) for k in ("provenance", "description")):
                raise ValueError("Invalid relation evidence record.")
            evidence.append(RelationEvidence(record["provenance"], _read_anchor(record["anchor"]),
                                             record["description"]))
        edges.append(GraphEdge(EdgeIdentity(_read_identity(item["source"]), _read_identity(item["target"]),
                                             RelationType(item["relation"])), tuple(evidence)))
    return GraphSnapshot(payload["repository_key"], payload["snapshot_key"], tuple(nodes), tuple(edges))
