"""Bind a P3-F product and smoke it through the public C1, D and E consumers."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))

from arkui_agent.context import parse_task  # noqa: E402
from arkui_agent.context.materialization import materialize_context  # noqa: E402
from arkui_agent.knowledge import (  # noqa: E402
    BuildStatus, GitSourceReader, KnowledgeManifest, PrebuiltSnapshotReader,
    QueryRequirement, loads,
)
from arkui_agent.retrieval.candidates import (  # noqa: E402
    CandidateQuery, Channel, EvidenceSide, NameSelector, QueryOrigin,
    RetrievalRequest,
)
from arkui_agent.retrieval.expansion import GraphExpander  # noqa: E402
from arkui_agent.retrieval.service import CandidateRetriever  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--knowledge-root", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--qualified-name", required=True)
    parser.add_argument("--task", required=True)
    args = parser.parse_args()

    root = args.knowledge_root.resolve()
    value = loads((root / "manifest.json").read_text(encoding="utf-8"))
    if (not isinstance(value, KnowledgeManifest) or value.last_usable is None
            or value.latest_attempt is None
            or value.latest_attempt.status is not BuildStatus.SUCCEEDED):
        parser.error("Smoke requires a successfully published last_usable generation.")
    snapshot = value.last_usable
    requirement = QueryRequirement(args.repository, snapshot.identity.revision,
                                   snapshot.scope, snapshot.configuration)
    reader = PrebuiltSnapshotReader(
        root / "manifest.json", artifact_root=root,
        source=GitSourceReader(args.repository_root, repository=args.repository),
    )
    with reader.bind(requirement) as session:
        parsed = parse_task(args.task, repository=args.repository,
                            target_revision=snapshot.identity.revision,
                            source_id="p3-f-real-smoke")
        if parsed.value is None:
            parser.error("Task input was rejected.")
        query = CandidateQuery(
            Channel.SYMBOL, NameSelector(args.qualified_name, qualified=True),
            (QueryOrigin(parsed.value.provenance, "P3-F acceptance symbol"),),
        )
        direct = CandidateRetriever().retrieve(
            RetrievalRequest(parsed.value, EvidenceSide.TARGET, (query,)), session
        )
        expansion = GraphExpander().expand(direct, session)
        materialized = materialize_context(expansion, target=session)
    payload = {
        "generation": snapshot.identity.generation,
        "revision": snapshot.identity.revision,
        "scope": snapshot.scope.kind.value,
        "qualified_name": args.qualified_name,
        "direct_candidates": len(direct.candidates),
        "expansion": {
            "nodes": expansion.node_count,
            "edges": expansion.edge_count,
            "paths": expansion.path_count,
            "queries": expansion.query_count,
            "diagnostics": expansion.diagnostics,
        },
        "context_candidates": len(materialized.candidates),
        "snippets": len(materialized.snippets),
        "bindings": [item.snapshot.identity.generation for item in materialized.bindings],
        "passed": bool(direct.candidates) and materialized.bindings == (session.reference,),
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
