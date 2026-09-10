"""User-invoked P3-D selected-scope observations; never freezes new evidence gold."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from dataclasses import fields, is_dataclass, replace
import hashlib
import json
import subprocess
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PROJECT / "src"), str(PROJECT)]

from scripts.run_c1_smoke import now, sha, digest, write, covers
from arkui_agent.context import parse_task, parse_unified_diff
from arkui_agent.graph import GraphStore, default_role_mapper, extract_framework_relations, project_index
from arkui_agent.graph.model import GraphEdge, NodeIdentity, RelationType
from arkui_agent.knowledge import (
    ArtifactKind, ArtifactReference, BuildAttempt, BuildConfiguration, BuildScope, BuildStatus,
    GitSourceReader, KnowledgeArtifacts, KnowledgeManifest, KnowledgeSnapshot, PrebuiltSnapshotReader,
    ProvenanceStatus, QueryRequirement, ScopeKind, SnapshotBuild, SnapshotIdentity, TextKnowledge, dumps, loads,
)
from arkui_agent.repository import RepositoryFile, SymbolIndex, SymbolIdentity
from arkui_agent.retrieval.candidates import (
    CandidateQuery, Channel, EvidenceSide, GraphSeed, QueryOrigin, RetrievalRequest, SymbolSeed, canonical,
)
from arkui_agent.retrieval.change_mapping import ChangedRangeMapper
from arkui_agent.retrieval.expansion import ExpansionPolicy, GraphExpander, TraceFamily, TraceRequest
from arkui_agent.graph.creation import CreationBounds, trace_component_creation
from arkui_agent.graph.property import PropertyBounds, trace_property_update
from arkui_agent.graph.layout import LayoutBounds, trace_measure_layout
from arkui_agent.graph.overlay import OverlayBounds, trace_overlay
from arkui_agent.retrieval.service import CandidateRetriever
from tests.fixtures.creation_cases import CASES as CREATION
from tests.fixtures.property_cases import REAL_CASES as PROPERTY, NATIVE_GAPS, STACK_GAPS
from tests.fixtures.layout_cases import REAL_CHECKS as LAYOUT_CHECKS, REAL_EXPECTED as LAYOUT_EXPECTED, MENU_CANDIDATES
from tests.fixtures.overlay_cases import REAL_CHECKS as OVERLAY_CHECKS, REAL_SHOW, REAL_CLOSE, REAL_SEED_DEFINITIONS, REAL_GAPS

REPOSITORY = "OpenHarmony/arkui_ace_engine"
REVISION = "0096f5bd943ed1f7fa56883aed0e2379f13c2885"
ROOT = "frameworks/core/components_ng/pattern"


def walk(value):
    yield value
    if is_dataclass(value) and not isinstance(value, type):
        for field in fields(value):
            yield from walk(getattr(value, field.name))
    elif isinstance(value, tuple):
        for item in value:
            yield from walk(item)


def source_checks(source, family):
    state = source.observe(())
    if state.revision != REVISION or state.dirty:
        raise ValueError("Expected clean frozen Task revision")
    checks = []
    if family == "creation":
        checks = [anchor for case in CREATION for anchor in case.source_evidence]
    elif family == "layout":
        checks = [(ROOT + "/" + path, line, fragment) for path, line, fragment in LAYOUT_CHECKS]
    elif family == "overlay":
        checks = list(OVERLAY_CHECKS)
    else:
        for case in PROPERTY:
            path = f"{ROOT}/{case.component.lower()}/{case.component.lower()}_model_ng.cpp"
            checks.extend(((case.entry_file, case.entry_line, case.entry + "("),
                           (path, case.native_line, "SetFontWeight(FrameNode*"),
                           (path, case.stack_line, "SetFontWeight(")))
    observations = []
    for path, line, fragment in checks:
        actual = source.workspace.resolve(path).read_text(encoding="utf-8").splitlines()[line - 1].strip()
        if fragment not in actual:
            raise ValueError(f"Frozen source anchor mismatch: {path}:{line}")
        observations.append(dict(path=path, line=line, source=actual, sha256=sha(source.workspace.resolve(path))))
    return observations


def prepare(source, family, output):
    checks = source_checks(source, family)
    output.mkdir(parents=True, exist_ok=False)
    started = now()
    tools = {name: subprocess.run((name, "--version"), capture_output=True, text=True, check=True,
        timeout=30).stdout for name in ("clangd", "git")}
    if "22.1.6" not in tools["clangd"]:
        raise ValueError("Frozen collector requires clangd 22.1.6")
    compile_db = source.workspace.root / "compile_commands.json"
    compile_hash = sha(compile_db) if compile_db.exists() else None
    print("Collect public P1 selected " + family + " facts", flush=True)
    if family == "layout":
        from tests.integration.test_layout_trace import collect_layout
        symbols, facts, _ = collect_layout(source.workspace, real=True)
    elif family == "property":
        from tests.integration.test_property_trace import collect_property
        symbols, facts, *_ = collect_property(source.workspace, real=True)
    elif family == "overlay":
        from tests.integration.test_overlay_trace import collect_overlay
        symbols, facts = collect_overlay(source.workspace, real=True)
    else:
        raise ValueError("Creation reuses the existing C1 manifest")
    paths = {row["path"] for row in checks}
    paths.update(item.path.as_posix() for item in walk((symbols, facts)) if isinstance(item, RepositoryFile))
    inventory = tuple(sorted(paths))
    observation = source.observe(inventory)
    if observation.revision != REVISION or observation.dirty:
        raise ValueError("Source changed during collection")
    identity = SnapshotIdentity("d-" + family, "d-" + family + "-" + digest((started, inventory))[:16], REPOSITORY, REVISION)
    database = output / "symbols.sqlite3"
    with SymbolIndex(database) as index:
        index.rebuild(symbols, files=tuple(RepositoryFile.from_path(p) for p in inventory), semantic_facts=facts)
        generic = project_index(index, repository_key=REPOSITORY, snapshot_key=identity.generation)
        domain = default_role_mapper().map(index, generic)
        graph = extract_framework_relations(index, generic, domain, source.workspace).graph
    store = GraphStore(output, repository_key=REPOSITORY, snapshot_key=identity.generation)
    store.save(graph)
    domain_path = output / "domain.json"
    write(domain_path, domain.to_dict())
    config = BuildConfiguration(digest((family, inventory, tools, compile_hash)), digest(tools),
        3, 1, 1, "rg-source-v1", "not-built:D-test-scope-empty", "p1-index-v1", domain.ruleset_identity,
        "arkui.framework.v1", ("-std=c++17",), (".", "frameworks", "interfaces/inner_api/ace", "interfaces/inner_api/ace_kit/include"), compile_hash)

    def artifact(kind, path, version):
        checksum = sha(path)
        return ArtifactReference(kind, graph.snapshot_key if kind is ArtifactKind.GRAPH else "sha256:" + checksum,
            identity, path.relative_to(output).as_posix(), checksum, version)

    artifacts = KnowledgeArtifacts(artifact(ArtifactKind.SYMBOL, database, 3), artifact(ArtifactKind.TEST, database, 3),
        artifact(ArtifactKind.GRAPH, store.path, 1), artifact(ArtifactKind.DOMAIN, domain_path, 1),
        TextKnowledge("sha256:" + observation.fingerprint.sha256, identity, observation.fingerprint.sha256, "rg-source-v1"))
    finished = now()
    if source.observe(inventory) != observation:
        raise ValueError("Source drift before publication")
    snapshot = KnowledgeSnapshot(identity, BuildScope(ScopeKind.SELECTED_FILES, inventory, (), ()),
        observation.fingerprint, config, artifacts, SnapshotBuild(identity.generation, BuildStatus.SUCCEEDED,
        finished, "explicit-D-selected-smoke", ProvenanceStatus.VERIFIED_BUILD, observation.fingerprint.sha256))
    manifest = KnowledgeManifest(snapshot, BuildAttempt(identity.generation, identity, BuildStatus.SUCCEEDED,
        "user-authorized P3-D smoke", started, finished, None))
    (output / "manifest.json").write_text(dumps(manifest), encoding="utf-8")
    write(output / "preparation.json", dict(started=started, finished=finished, inventory=inventory,
        manifest_sha256=sha(output / "manifest.json"), source_observations=checks, tools=tools, compile_database_sha256=compile_hash,
        symbols=len(symbols), edges=len(graph.edges), producer="public-P1-collector/P2-projection-framework"))
    print(f"Published {family}: {len(inventory)} files, {len(symbols)} symbols, {len(graph.edges)} edges", flush=True)


def bind(source, artifact_root):
    preparation = json.loads((artifact_root / "preparation.json").read_text(encoding="utf-8"))
    if preparation["manifest_sha256"] != sha(artifact_root / "manifest.json"):
        raise ValueError("Published manifest changed")
    manifest = loads((artifact_root / "manifest.json").read_text(encoding="utf-8"))
    snap = manifest.last_usable
    return PrebuiltSnapshotReader(artifact_root / "manifest.json", artifact_root=artifact_root, source=source).bind(
        QueryRequirement(snap.identity.repository, snap.identity.revision, snap.scope, snap.configuration))


def identity(view, name, anchor=None):
    matches = tuple(s for s in view.index.find_by_qualified_name(name)
        if anchor is None or covers(s.definition or s.declaration, *anchor))
    if len(matches) != 1:
        raise ValueError("Explicit frozen seed not unique: " + name)
    return NodeIdentity.for_symbol(matches[0].identity)


def requests(view, family):
    snap = view.reference.snapshot.identity

    def request(family, seed, component, **kwargs):
        return TraceRequest(family, GraphSeed(seed, snap, EvidenceSide.TARGET),
            NodeIdentity("arkui.component", component), "frozen P2 source-anchored task intent", **kwargs)

    if family == "creation":
        return [("creation-" + c.component, request(TraceFamily.CREATION,
            identity(view, c.entry_namespace + "::" + c.entry_name, (c.entry_file, c.entry_line)), c.component)) for c in CREATION]
    if family == "layout":
        return [("layout-" + slug, request(TraceFamily.LAYOUT,
            identity(view, "OHOS::Ace::NG::" + slug.title() + "Pattern"), slug)) for slug in ("button", "text", "menu")]
    if family == "property":
        result = []
        for c in PROPERTY[:2]:
            slug = c.component.lower()
            path = f"{ROOT}/{slug}/{slug}_model_ng.cpp"
            for variant, line in (("native", c.native_line), ("stack", c.stack_line)):
                setter = identity(view, "OHOS::Ace::NG::" + c.component + "ModelNG::SetFontWeight", (path, line))
                seed = identity(view, "OHOS::Ace::NG::" + c.entry, (c.entry_file, c.entry_line)) if variant == "native" else setter
                result.append(("property-" + slug + "-" + variant, request(TraceFamily.PROPERTY, seed, slug, setter=setter)))
        return result
    return [("overlay-menu", request(TraceFamily.OVERLAY,
        identity(view, REAL_SHOW[0], REAL_SEED_DEFINITIONS[REAL_SHOW[0]]), "menu",
        manager=identity(view, "OHOS::Ace::NG::OverlayManager"),
        close_seeds=tuple(identity(view, path[0], REAL_SEED_DEFINITIONS[path[0]]) for path in REAL_CLOSE)))]


def original_trace(view, request):
    args = (view.index, view.graph, view.domain, view.workspace)
    common = dict(seed=request.seed.identity, component=request.component)
    if request.family is TraceFamily.CREATION:
        return trace_component_creation(*args, **common, bounds=CreationBounds(2, 32, 1000))
    if request.family is TraceFamily.PROPERTY:
        return trace_property_update(*args, **common, setter=request.setter, bounds=PropertyBounds(2, 32, 1000))
    if request.family is TraceFamily.LAYOUT:
        return trace_measure_layout(*args, **common, bounds=LayoutBounds(32, 200))
    return trace_overlay(*args, manager=request.manager, component=request.component, show_seed=request.seed.identity,
        close_seeds=request.close_seeds, bounds=OverlayBounds(2, 32, 1000))


def audit(result, view):
    checks = dict(edge_provenance=True, hashes=True, seed_provenance=True, budget=True)
    edges = {e.identity: e for e in view.graph.edges}
    for report in result.reports:
        checks["seed_provenance"] &= bool(report.seed.candidate_ids or report.seed.query_ids)
        for edge in (x for x in walk(report.observation) if isinstance(x, GraphEdge)):
            checks["edge_provenance"] &= edge.identity in edges and set(edge.evidence).issubset(edges[edge.identity].evidence)
        for h in report.source_hashes:
            checks["hashes"] &= sha(view.workspace.resolve(h.path)) == h.sha256
    checks["budget"] = (result.node_count <= result.policy.max_nodes and result.edge_count <= result.policy.max_edges
        and result.path_count <= result.policy.max_paths and result.query_count <= result.policy.max_queries)
    return checks


def query(source, family, artifacts, output):
    checks = source_checks(source, family)
    report = dict(family=family, started=now(), source_observations=checks, cases=[], gold_status="proposed-not-human-frozen")
    with bind(source, artifacts) as session:
        report["snapshot"] = json.loads(canonical(session.reference))
        with session.read() as view:
            planned = requests(view, family)
        for name, request in planned:
            print("D query: " + name, flush=True)
            task = parse_task(name, repository=REPOSITORY, target_revision=REVISION, source_id="D-smoke:" + name).value
            ids = {request.seed.identity, *request.close_seeds} | {n for n in (request.setter, request.manager) if n is not None}
            queries = tuple(CandidateQuery(Channel.SYMBOL, SymbolSeed(SymbolIdentity(n.key), request.seed.snapshot, EvidenceSide.TARGET),
                (QueryOrigin(task.provenance, "source-anchored-trace-parameter"),)) for n in sorted(ids))
            direct = CandidateRetriever().retrieve(RetrievalRequest(task, EvidenceSide.TARGET, queries), session)
            result = GraphExpander().expand(direct, session, traces=(request,))
            repeat = GraphExpander().expand(direct, session, traces=(request,))
            trace_report = next(r for r in result.reports if r.trace_request == request)
            with session.read() as view:
                original = original_trace(view, request)
                assertions = audit(result, view)
                assertions["canonical_stable"] = result.to_json() == repeat.to_json()
                assertions["original_P2_preserved"] = trace_report.observation == original
                assertions["unsupported_preserved"] = set(result.unavailable_relations) == {RelationType.INHERIT, RelationType.OVERRIDE, RelationType.MOCK}
                names = {n.identity: view.index.get(SymbolIdentity(n.identity.key)).qualified_name
                    for n in view.graph.nodes if n.identity.namespace == "symbol" and view.index.get(SymbolIdentity(n.identity.key)) is not None}
                additions = sorted({(e.identity.relation.value, names.get(e.identity.source, e.identity.source.value),
                    names.get(e.identity.target, e.identity.target.value)) for r in result.reports for e in walk(r.observation) if isinstance(e, GraphEdge)})
                if family == "creation":
                    expected = next(c for c in CREATION if name == "creation-" + c.component)
                    assertions["frozen_P2_status_gaps"] = original.status.value == expected.expected_status and tuple(sorted(
                        {g for p in original.paths for g in p.issues})) == tuple(sorted(expected.expected_gaps))
                elif family == "property":
                    expected = NATIVE_GAPS if name.endswith("native") else STACK_GAPS
                    assertions["frozen_P2_status_gaps"] = original.status.value == "incomplete" and tuple(sorted(
                        {g for p in original.paths for g in p.gaps})) == tuple(sorted(expected))
                elif family == "layout":
                    expected = LAYOUT_EXPECTED[name.split("-")[-1].title()]
                    assertions["frozen_P2_status_gaps"] = (original.status.value, tuple(s.stage.value for s in original.stages), original.gaps) == expected
                    if name == "layout-menu":
                        assertions["all_Menu_candidates"] = {names[c.node.identity].split("::")[-1] for c in original.candidates} == set(MENU_CANDIDATES)
                else:
                    assertions["frozen_P2_status_gaps"] = (original.show.status.value, original.close.status.value) == ("incomplete", "ambiguous")
                    assertions["all_Close_paths"] = len(original.close.paths) == 2
                    assertions["manager_gap_animation"] = all(p.gaps == REAL_GAPS and p.animation.value == "unresolved"
                        for leg in (original.show, original.close) for p in leg.paths)
            budgets = []
            for policy in (ExpansionPolicy(max_queries=0), ExpansionPolicy(max_nodes=1), ExpansionPolicy(max_paths=0)):
                limited = GraphExpander(policy).expand(direct, session, traces=(request,))
                with session.read() as view:
                    valid = audit(limited, view)
                tr = next(r for r in limited.reports if r.trace_request == request)
                preserved = tr.summary is None or tr.summary == trace_report.summary
                budgets.append(dict(policy=json.loads(canonical(policy)), counts=(limited.node_count, limited.edge_count,
                    limited.path_count, limited.query_count), truncated=limited.truncated, summary_preserved=preserved,
                    reports=[dict(status=r.status, diagnostics=r.diagnostics) for r in limited.reports], audit=valid))
            assertions["budget_probes"] = all(all(b["audit"].values()) and b["summary_preserved"] for b in budgets)
            item = dict(case=name, checks=assertions, p2_summary=json.loads(canonical(trace_report.summary)),
                expansion_counts=(result.node_count, result.edge_count, result.path_count, result.query_count),
                direct_candidates=len(direct.candidates), proposed_additional_relations=additions,
                budget_probes=budgets, actual=json.loads(result.to_json()), passed=all(assertions.values()))
            report["cases"].append(item)
            print(json.dumps({k: item[k] for k in ("case", "checks", "p2_summary", "expansion_counts", "passed")}), flush=True)
    report["finished"] = now()
    report["passed"] = all(c["passed"] for c in report["cases"])
    write(output, report)
    return report["passed"]


def change_query(source_root, checkouts, artifacts, output):
    from scripts.run_c2_smoke import BASE, HEAD, FILES, ROWS, git
    raw = git(source_root, "diff", "--no-ext-diff", "--no-textconv", "--unified=0", "--no-renames", BASE, HEAD, "--", *FILES)
    if hashlib.sha256(raw).hexdigest() != "a0532aec1b6221e41ddd87638ac9b35c4f44c57faa94ef147f66b02db73dcfae":
        raise ValueError("Frozen C2 diff hash mismatch")
    diff = raw.decode("utf-8")
    change = parse_unified_diff(diff, repository=REPOSITORY, base_revision=BASE, head_revision=HEAD, source_id="frozen-C2-diff").value
    with ExitStack() as stack:
        base = stack.enter_context(bind(GitSourceReader(checkouts / "base", repository=REPOSITORY), artifacts / "base"))
        head = stack.enter_context(bind(GitSourceReader(checkouts / "head", repository=REPOSITORY), artifacts / "head"))
        upstream = ChangedRangeMapper().retrieve(change, base=base, head=head, channels=(Channel.SYMBOL,))
        result = GraphExpander().expand_change(upstream, base=base, head=head)
        repeat = GraphExpander().expand_change(upstream, base=base, head=head)
        assertions = dict(canonical_stable=result.to_json() == repeat.to_json(), mapping_preserved=result.upstream == upstream,
                          sides_distinct=base.reference.snapshot.identity != head.reference.snapshot.identity)
        assertions["frozen_ranges"] = [(r.anchor.file_index, r.anchor.hunk_index, r.anchor.side.value,
            r.anchor.changed_range.start_line, r.anchor.changed_range.end_line, r.status.value)
            for r in upstream.mapping.ranges] == [row[:6] for row in ROWS]
        for side, session in (("old", base), ("new", head)):
            with session.read() as view:
                assertions.update((side + ":" + k, v) for k, v in audit(getattr(result, side), view).items())
        limited = GraphExpander(ExpansionPolicy(max_queries=1)).expand_change(upstream, base=base, head=head)
        assertions["shared_query_limit"] = limited.old.query_count + limited.new.query_count == 1 and limited.old.truncated
        write(output, dict(passed=all(assertions.values()), checks=assertions, actual=json.loads(result.to_json()),
            budget_actual=json.loads(limited.to_json()), gold_status="proposed-not-human-frozen"))
        print(json.dumps(assertions), flush=True)
        return all(assertions.values())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "query", "change"))
    parser.add_argument("--family", choices=("creation", "property", "layout", "overlay"))
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--checkouts-root", type=Path)
    args = parser.parse_args()
    source = GitSourceReader(args.repository_root, repository=REPOSITORY)
    if args.mode == "prepare":
        prepare(source, args.family, args.artifacts.resolve())
    elif args.mode == "query":
        sys.exit(0 if query(source, args.family, args.artifacts.resolve(), args.output.resolve()) else 1)
    else:
        sys.exit(0 if change_query(args.repository_root, args.checkouts_root, args.artifacts.resolve(), args.output.resolve()) else 1)
