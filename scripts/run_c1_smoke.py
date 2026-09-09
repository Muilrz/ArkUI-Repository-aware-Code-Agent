"""Explicit, selected-file C1 acceptance only; no full suite or production refresh.

prepare publishes a manifest before query can start. Query never changes inventory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PROJECT / "src"), str(PROJECT)]

from arkui_agent.context import parse_task
from arkui_agent.graph import default_role_mapper, project_index, GraphStore
from arkui_agent.graph.domain import ComponentMapping, RoleMapping
from arkui_agent.graph.model import GraphEdge, GraphNode
from arkui_agent.knowledge import (
    ArtifactKind, ArtifactReference, BuildAttempt, BuildConfiguration, BuildScope, BuildStatus,
    GitSourceReader, KnowledgeArtifacts, KnowledgeManifest, KnowledgeSnapshot, PrebuiltSnapshotReader,
    ProvenanceStatus, QueryRequirement, ScopeKind, SnapshotBuild, SnapshotIdentity, TextKnowledge, dumps, loads,
)
from arkui_agent.repository import RepositoryFile, Symbol, SymbolIndex
from arkui_agent.retrieval.candidates import Channel, RangeFact, RetrievalBounds, RetrievalStatus, canonical
from arkui_agent.retrieval.channels import fact_paths
from arkui_agent.retrieval.planning import TASK_CHANNELS, task_request
from arkui_agent.retrieval.reference_call import DirectCallRelation, ReferenceCallRetriever
from arkui_agent.retrieval.service import CandidateRetriever
from tests.fixtures.c1_cases import (
    BOUNDS, CASES, CLOSURE_RULE, FROZEN_AT, HUMAN_APPROVER, PREPARATION_FILES, REPOSITORY, REVISION, TEXT_FILES,
)


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def write(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n")


def source_check(source):
    state = source.observe(())
    if state.revision != REVISION or state.dirty:
        raise ValueError("Expected frozen revision and clean checkout.")
    for case in CASES:
        for path, expected in ((case.entry_file, case.entry_hash), (case.model_file, case.model_hash)):
            if sha(source.workspace.resolve(path)) != expected:
                raise ValueError("Frozen source hash mismatch: " + path)
    return state


def prepare(source, output):
    from tests.integration.test_creation_trace import collect_creation

    started = now()
    before = source_check(source)
    output.mkdir(parents=True, exist_ok=False)
    tools = {name: subprocess.run((name, "--version"), check=True, capture_output=True,
                                  text=True, timeout=30).stdout for name in ("clangd", "rg", "git")}
    print("Preparing fixed P2 creation subset through public P1 collector", flush=True)
    symbols, facts, _ = collect_creation(source.workspace, CASES, real=True)
    # This closure rule is fixed before collection. No CandidateRetriever call
    # occurs here, nor can query add files to the published manifest.
    paths = set(PREPARATION_FILES)
    for symbol in symbols:
        paths.update(r.file.path.as_posix() for r in (symbol.declaration, symbol.definition) if r)
    for fact in facts:
        paths.update(r.file.path.as_posix() for r in fact.references)
    inventory = tuple(sorted(paths))
    observation = source.observe(inventory)
    if (observation.revision, observation.dirty, observation.tracked_files) != (before.revision, False, before.tracked_files):
        raise ValueError("Source changed during preparation.")
    scope = BuildScope(ScopeKind.SELECTED_FILES, inventory, (), TEXT_FILES)
    identity = SnapshotIdentity("c1-creation", "c1-" + digest((started, inventory))[:16], REPOSITORY, REVISION)
    database = output / "symbols.sqlite3"
    with SymbolIndex(database) as index:
        index.rebuild(symbols, files=tuple(RepositoryFile.from_path(p) for p in inventory), semantic_facts=facts)
        graph = project_index(index, repository_key=REPOSITORY, snapshot_key=identity.generation)
        domain = default_role_mapper().map(index, graph)
    store = GraphStore(output, repository_key=REPOSITORY, snapshot_key=identity.generation)
    store.save(graph)
    domain_path = output / "domain.json"
    write(domain_path, domain.to_dict())
    settings = dict(closure_rule=CLOSURE_RULE, preparation_files=PREPARATION_FILES,
                    collector="tests.integration.test_creation_trace.collect_creation",
                    collector_sha256=sha(PROJECT / "tests/integration/test_creation_trace.py"),
                    inventory=inventory, text_files=TEXT_FILES, test_files=(), tools=tools,
                    frozen_expected_sha256=sha(PROJECT / "tests/fixtures/c1_cases.py"))
    includes = (".", "frameworks", "interfaces/inner_api/ace", "interfaces/inner_api/ace_kit/include")
    compile_db = source.workspace.root / "compile_commands.json"
    settings["compile_database_sha256"] = sha(compile_db) if compile_db.exists() else None
    config = BuildConfiguration(digest(settings), digest(tools), 3, 1, 1, "rg-source-v1", "not-built:C1-test-scope-empty",
                                "p1-index-v1", domain.ruleset_identity, "not-built:C1-direct-graph",
                                ("-std=c++17",), includes, settings["compile_database_sha256"], CLOSURE_RULE)

    def artifact(kind, path, version):
        checksum = sha(path)
        return ArtifactReference(kind, graph.snapshot_key if kind is ArtifactKind.GRAPH else "sha256:" + checksum,
                                 identity, path.relative_to(output).as_posix(), checksum, version)

    artifacts = KnowledgeArtifacts(artifact(ArtifactKind.SYMBOL, database, 3), artifact(ArtifactKind.TEST, database, 3),
                                  artifact(ArtifactKind.GRAPH, store.path, 1), artifact(ArtifactKind.DOMAIN, domain_path, 1),
                                  TextKnowledge("sha256:" + observation.fingerprint.sha256, identity,
                                                observation.fingerprint.sha256, "rg-source-v1"))
    finished = now()
    if source.observe(inventory) != observation:
        raise ValueError("Source changed before publication.")
    build = SnapshotBuild(identity.generation, BuildStatus.SUCCEEDED, finished, "explicit-c1-smoke-preparation-v1",
                          ProvenanceStatus.VERIFIED_BUILD, observation.fingerprint.sha256)
    snapshot = KnowledgeSnapshot(identity, scope, observation.fingerprint, config, artifacts, build)
    manifest = KnowledgeManifest(snapshot, BuildAttempt(identity.generation, identity, BuildStatus.SUCCEEDED,
                                                        "user-authorized C1 selected-file validation", started, finished, None))
    (output / "manifest.json").write_text(dumps(manifest), encoding="utf-8")
    write(output / "preparation.json", dict(settings, started_at=started, finished_at=finished,
                                            generation=identity.generation, manifest_sha256=sha(output / "manifest.json")))
    print(f"Published {len(inventory)} files, {len(symbols)} symbols, {len(graph.edges)} edges; no C1 query yet", flush=True)


def covers(extent, path, line):
    return (extent is not None and extent.file.path.as_posix() == path and extent.start.line <= line
            and (line < extent.end.line or line == extent.end.line and extent.end.column > 1))


def audit(fact, view):
    """Independent exact public-read comparison; no expected fed into retrieval."""
    index = view.index
    refs = ReferenceCallRetriever(index)
    if isinstance(fact, Symbol):
        return fact == index.get(fact.identity)
    if isinstance(fact, DirectCallRelation):
        return (index.get(fact.caller_identity) is not None and fact in refs.callees(fact.caller_identity)
                or index.get(fact.callee_identity) is not None and fact in refs.callers(fact.callee_identity))
    if isinstance(fact, GraphEdge):
        return fact in view.graph.query().outgoing_edges(fact.identity.source)
    if isinstance(fact, GraphNode):
        return fact == view.graph.query().node(fact.identity)
    if isinstance(fact, RoleMapping):
        return fact == view.domain.lookup(fact.identity)
    if isinstance(fact, ComponentMapping):
        return fact in view.domain.components
    if isinstance(fact, RangeFact):
        if fact.role == "text":
            lines = view.workspace.resolve(fact.source_range.file.path).read_text(encoding="utf-8").splitlines()
            start, end = fact.source_range.start, fact.source_range.end
            return (start.line == end.line and lines[start.line - 1] == fact.line_text
                    and lines[start.line - 1][start.column - 1:end.column - 1] == fact.matched_text)
        if fact.role == "reference":
            return fact.source_range in tuple(r.source_range for r in refs.references(fact.identity))
        symbol = index.get(fact.identity)
        return symbol is not None and fact.source_range == getattr(symbol, fact.role)
    return False


def query(source, output):
    from dataclasses import replace
    if (output / "report.json").exists() or any(output.glob("*-actual.json")):
        raise ValueError("Preserve previous observations; this snapshot output already has a query run.")
    source_check(source)
    expected_digest = sha(PROJECT / "tests/fixtures/c1_cases.py")
    preparation = json.loads((output / "preparation.json").read_text(encoding="utf-8"))
    if expected_digest != preparation["frozen_expected_sha256"] or sha(output / "manifest.json") != preparation["manifest_sha256"]:
        raise ValueError("Expected or manifest changed after preparation.")
    manifest = loads((output / "manifest.json").read_text(encoding="utf-8"))
    snapshot = manifest.last_usable
    reader = PrebuiltSnapshotReader(output / "manifest.json", artifact_root=output, source=source)
    requirement = QueryRequirement(REPOSITORY, REVISION, snapshot.scope, snapshot.configuration)
    bounds = RetrievalBounds(**BOUNDS)
    channels = (*TASK_CHANNELS, Channel.GRAPH_INCOMING, Channel.GRAPH_OUTGOING, Channel.INHERIT, Channel.OVERRIDE, Channel.MOCK)
    report = dict(started_at=now(), human_approver=HUMAN_APPROVER, frozen_at=FROZEN_AT, revision=REVISION,
                  manifest_sha256=preparation["manifest_sha256"], expected_sha256=expected_digest,
                  inventory_count=len(snapshot.source.files), generation=snapshot.identity.generation, cases=[])
    with reader.bind(requirement) as session:
        report["freshness"] = session.reference.freshness.state.value
        for case in CASES:
            print("C1 query: " + case.component, flush=True)
            task = parse_task(case.task_text, repository=REPOSITORY, target_revision=REVISION,
                              source_id="frozen:c1-" + case.component).value
            request = task_request(task, channels=channels)
            # Identity correspondence is established from independent source anchors first.
            with session.read() as view:
                entries = tuple(s for s in view.index.find_by_qualified_name(case.qualified_entry)
                                if covers(s.definition or s.declaration, case.entry_file, case.entry_line))
                if len(entries) != 1:
                    raise ValueError("Frozen entry setup ambiguity: " + case.component)
                entry = entries[0]
            result = CandidateRetriever(bounds=bounds).retrieve(request, session)
            with (output / (case.component + "-actual.json")).open("x", encoding="utf-8") as stream:
                stream.write(result.to_json())
            reordered = CandidateRetriever(bounds=bounds).retrieve(replace(request, queries=tuple(reversed(request.queries))), session)
            facts = [f for c in result.candidates for f in c.observations]
            calls = [f for f in facts if isinstance(f, DirectCallRelation)]
            expected_calls = [f for f in calls if f.caller_identity == entry.identity and f.callee is not None
                              and f.callee.qualified_name == case.qualified_model]
            required = dict(symbol=any(isinstance(f, Symbol) and f.identity == entry.identity for f in facts),
                            definition=any(isinstance(f, RangeFact) and f.role == "definition" and f.identity == entry.identity
                                           and covers(f.source_range, case.entry_file, case.entry_line) for f in facts),
                            text=any(isinstance(f, RangeFact) and f.role == "text" and f.matched_text == case.entry_name
                                     and covers(f.source_range, case.entry_file, case.entry_line) for f in facts),
                            direct_call=bool(expected_calls))
            failures = []
            source_unproven = []
            with session.read() as view:
                for candidate in result.candidates:
                    if candidate.snapshot != snapshot.identity or not candidate.provenance:
                        failures.append("candidate_snapshot_or_query_provenance")
                    hashes = {h.path: h.sha256 for h in candidate.source_hashes}
                    for fact in candidate.observations:
                        if not audit(fact, view):
                            failures.append("public_fact_mismatch:" + type(fact).__name__)
                        if any(hashes.get(p) != sha(view.workspace.resolve(p)) for p in fact_paths(fact)):
                            failures.append("source_hash_mismatch")
                        if isinstance(fact, DirectCallRelation):
                            if fact.caller is None or fact.callee is None or fact.source_range is None:
                                source_unproven.append(canonical((fact.caller_identity, fact.callee_identity)))
                            else:
                                r = fact.source_range
                                body = view.workspace.resolve(r.file.path).read_text(encoding="utf-8").splitlines()[r.start.line-1:r.end.line]
                                if fact.callee.display_name not in "\n".join(body):
                                    source_unproven.append(canonical((fact.caller_identity, fact.callee_identity)))
                            if (fact.caller and fact.callee and "FrameNode::GetOrCreateFrameNode" in fact.caller.qualified_name
                                    and "InnerMenuPattern" in fact.callee.qualified_name):
                                failures.append("forbidden_Menu_CALL")
                for r in result.reports:
                    if r.query.channel is Channel.SYMBOL:
                        selector = r.query.selector
                        method = view.index.find_by_qualified_name if selector.qualified else view.index.find_by_name
                        matches = method(selector.text)
                        actual_ids = {f.identity for c in result.candidates if c.candidate_id in r.candidate_ids
                                      for f in c.observations if isinstance(f, Symbol)}
                        if actual_ids != {s.identity for s in matches} or r.ambiguous != (len(matches) > 1):
                            failures.append("overload_loss")
            unsupported = [r for r in result.reports if r.query.channel in (Channel.INHERIT, Channel.OVERRIDE, Channel.MOCK)]
            if {r.query.channel for r in unsupported} != {Channel.INHERIT, Channel.OVERRIDE, Channel.MOCK} or any(r.status is not RetrievalStatus.UNSUPPORTED for r in unsupported):
                failures.append("unsupported_contract")
            if any(r.status is RetrievalStatus.FAILURE for r in result.reports):
                failures.append("channel_failure")
            graph_reports = [r for r in result.reports if r.query.channel in (Channel.GRAPH_INCOMING, Channel.GRAPH_OUTGOING)
                             and r.query.selector.text == case.entry_name]
            if len(graph_reports) != 2 or any(not any("unavailable_relations:INHERIT,OVERRIDE" in d for d in r.diagnostics) for r in graph_reports):
                failures.append("lost_graph_unavailability")
            mapping = [r for r in result.reports if r.query.channel is Channel.TEST_MAPPING and r.query.selector.text == case.entry_name]
            if len(mapping) != 1 or mapping[0].status is not RetrievalStatus.EMPTY:
                failures.append("test_mapping_not_scope_empty")
            if result.to_json() != reordered.to_json():
                failures.append("query_order_changed_output")
            optional = dict(model_definition=any(covers(f.callee.definition, case.model_file, case.model_line) for f in expected_calls),
                            domain_component=any(isinstance(f, ComponentMapping) and f.node.identity.key == case.component for f in facts),
                            other_text_or_reference=sum(isinstance(f, RangeFact) and (f.role == "reference" and f.identity == entry.identity
                                or f.role == "text" and f.matched_text == case.entry_name and not covers(f.source_range, case.entry_file, case.entry_line)) for f in facts))
            item = dict(component=case.component, required=required, optional=optional, candidates=len(result.candidates),
                        status=result.status.value, truncated=result.truncated, failures=sorted(set(failures)),
                        source_unproven_calls=sorted(set(source_unproven)), provenance_valid=not failures,
                        reports=json.loads(canonical(result.reports)), diagnostics=result.diagnostics,
                        passed=all(required.values()) and not failures)
            report["cases"].append(item)
            print(json.dumps({k: item[k] for k in ("component", "required", "optional", "candidates", "truncated", "failures", "passed")}), flush=True)
    report["finished_at"] = now()
    report["passed"] = all(c["passed"] for c in report["cases"])
    write(output / "report.json", report)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "query"))
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = GitSourceReader(args.repository_root, repository=REPOSITORY)
    if args.mode == "prepare":
        prepare(source, args.output.resolve())
    else:
        sys.exit(query(source, args.output.resolve()))
