"""Explicit frozen C2 acceptance; preparation completes before any production query."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))
from arkui_agent.context import parse_unified_diff, Side
from arkui_agent.graph import default_role_mapper, project_index, GraphStore
from arkui_agent.knowledge import (
    ArtifactKind, ArtifactReference, BuildAttempt, BuildConfiguration, BuildScope, BuildStatus,
    GitSourceReader, KnowledgeArtifacts, KnowledgeManifest, KnowledgeSnapshot, PrebuiltSnapshotReader,
    ProvenanceStatus, QueryRequirement, ScopeKind, SnapshotBuild, SnapshotIdentity, TextKnowledge, dumps, loads,
)
from arkui_agent.repository import (ClangdSemanticProvider, RepositoryFile, SymbolIndex,
                                    SymbolMergeConflict, canonicalize_symbols)
from arkui_agent.retrieval.candidates import canonical
from arkui_agent.retrieval.change_mapping import ChangedRangeMapper, MappingBounds

REPOSITORY = "OpenHarmony/arkui_ace_engine"
BASE = "5422984fee409dc6f0a679ab5fc7ed38c19aae92"
HEAD = "b29b394599624df784c0a7480a39537853d38821"
ROOT = "frameworks/core/components_ng/pattern/button/"
FILES = tuple(ROOT + p for p in ("toggle_button_paint_property.cpp", "toggle_button_paint_property.h", "toggle_button_pattern.h"))
EXPECTED = PROJECT / "docs/evaluation/p3-c2-change-annotation-draft.md"
CLOSURE = "c2-declaration-definition-source-v1"
INCLUDES = (".", "frameworks", "interfaces/inner_api/ace", "interfaces/inner_api/ace_kit/include")
M = "OHOS::Ace::NG::ToggleButtonPaintProperty::ToJsonValue"
T = "OHOS::Ace::ToggleTheme"
# Frozen source anchors, not derived from mapping output.
ROWS = (
    (0, 0, "old", 1, 1, "not_applicable", None, None),
    (0, 0, "new", 1, 41, "mapped", M, 22),
    (1, 0, "old", 22, 24, "unresolved", None, None),
    (1, 0, "new", 22, 26, "mapped", T, 24),
    (1, 1, "old", 53, 70, "mapped", M, 53),
    (1, 1, "new", 55, 56, "mapped", M, 55),
    (2, 0, "old", 22, 22, "unresolved", None, None),
    (2, 0, "new", 22, 23, "unresolved", None, None),
)


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def write(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n")


def git(repo, *args):
    # Selected C++ scope does not consume external LFS packages; retain Git pointers.
    return subprocess.run(("git", "-C", str(repo), *args), check=True, capture_output=True, timeout=300,
                          env=dict(os.environ, GIT_LFS_SKIP_SMUDGE="1")).stdout


def prepare(checkout, output, side):
    revision = BASE if side == "base" else HEAD
    primary = FILES[1:] if side == "base" else FILES
    source = GitSourceReader(checkout, repository=REPOSITORY)
    before = source.observe(primary)
    if before.revision != revision or before.dirty:
        raise ValueError("Expected clean frozen " + side + " revision")
    started = now()
    output.mkdir(parents=True, exist_ok=False)
    tool = subprocess.run(("clangd", "--version"), check=True, capture_output=True, text=True).stdout
    if "22.1.6" not in tool:
        raise ValueError("Frozen toolchain requires clangd 22.1.6")
    observations = []
    with ClangdSemanticProvider(source.workspace, executable="clangd", request_timeout=60,
                               fallback_flags=("-std=c++17", *("-I" + str(checkout / p) for p in INCLUDES))) as provider:
        observations.extend(provider.symbol_observations_in_files(tuple(RepositoryFile.from_path(path) for path in primary)))
        print(f"{side} public P1 fixed scope: {len(observations)} observations", flush=True)
    try:
        merged = canonicalize_symbols(observations)
    except SymbolMergeConflict as error:
        write(output / "setup-failure.json", dict(reason="conflicting_public_P1_facts", field=error.field,
                                                 observations=json.loads(canonical(error.observations))))
        raise
    symbols = {symbol.identity: symbol for symbol in merged}
    paths = set(primary)
    # Inventory follows all original facts, never actual C2 results or just winners.
    for observation in observations:
        symbol = observation.symbol
        paths.update(r.file.path.as_posix() for r in (symbol.declaration, symbol.definition) if r)
    inventory = tuple(sorted(paths))
    observation = source.observe(inventory)
    if source.observe(primary) != before:
        raise ValueError("Source changed during preparation")
    scope = BuildScope(ScopeKind.SELECTED_FILES, primary, (), ())
    identity = SnapshotIdentity("c2-" + side, "c2-" + side + "-" + digest((started, inventory))[:16], REPOSITORY, revision)
    database = output / "symbols.sqlite3"
    with SymbolIndex(database) as index:
        index.rebuild(tuple(symbols.values()), files=tuple(RepositoryFile.from_path(p) for p in primary))
        graph = project_index(index, repository_key=REPOSITORY, snapshot_key=identity.generation)
        domain = default_role_mapper().map(index, graph)
    store = GraphStore(output, repository_key=REPOSITORY, snapshot_key=identity.generation)
    store.save(graph)
    domain_path = output / "domain.json"
    write(domain_path, domain.to_dict())
    compile_db = checkout / "compile_commands.json"
    settings = dict(closure_rule=CLOSURE, semantic_files=primary, inventory=inventory, toolchain=tool,
                    normalization_rule="p1-declaration-site-canonical-v1",
                    compile_database_sha256=sha(compile_db) if compile_db.exists() else None,
                    expected_sha256=sha(EXPECTED), runner_sha256=sha(Path(__file__)))
    config = BuildConfiguration(digest(settings), digest(tool), 3, 1, 1, "rg-source-v1", "not-built:C2-test-scope-empty",
                                "p1-index-v1", domain.ruleset_identity, "not-built:C2-generic-graph",
                                ("-std=c++17",), INCLUDES, settings["compile_database_sha256"], CLOSURE)

    def artifact(kind, path, version):
        checksum = sha(path)
        return ArtifactReference(kind, graph.snapshot_key if kind is ArtifactKind.GRAPH else "sha256:" + checksum,
                                 identity, path.relative_to(output).as_posix(), checksum, version)

    artifacts = KnowledgeArtifacts(artifact(ArtifactKind.SYMBOL, database, 3), artifact(ArtifactKind.TEST, database, 3),
                                  artifact(ArtifactKind.GRAPH, store.path, 1), artifact(ArtifactKind.DOMAIN, domain_path, 1),
                                  TextKnowledge("sha256:" + observation.fingerprint.sha256, identity,
                                                observation.fingerprint.sha256, "rg-source-v1"))
    if source.observe(inventory) != observation:
        raise ValueError("Source changed before publication")
    finished = now()
    build = SnapshotBuild(identity.generation, BuildStatus.SUCCEEDED, finished, "explicit-c2-smoke-preparation-v1",
                          ProvenanceStatus.VERIFIED_BUILD, observation.fingerprint.sha256)
    manifest = KnowledgeManifest(KnowledgeSnapshot(identity, scope, observation.fingerprint, config, artifacts, build),
                                 BuildAttempt(identity.generation, identity, BuildStatus.SUCCEEDED,
                                              "user-authorized frozen C2 smoke", started, finished, None))
    (output / "manifest.json").write_text(dumps(manifest), encoding="utf-8")
    write(output / "preparation.json", dict(settings, finished_at=finished, generation=identity.generation,
                                            manifest_sha256=sha(output / "manifest.json")))
    print(f"{side}: manifest published, {len(inventory)} fingerprint files, {len(symbols)} symbols; no C2 query yet", flush=True)


def query(repository, checkouts, output):
    raw = git(repository, "diff", "--no-ext-diff", "--no-textconv", "--unified=0", "--no-renames", BASE, HEAD, "--", *FILES)
    if hashlib.sha256(raw).hexdigest() != "a0532aec1b6221e41ddd87638ac9b35c4f44c57faa94ef147f66b02db73dcfae":
        raise ValueError("Frozen diff hash mismatch")
    parsed = parse_unified_diff(raw.decode("utf-8"), repository=REPOSITORY, base_revision=BASE, head_revision=HEAD,
                                source_id="frozen:c2-toggle-button-change")
    if parsed.value is None:
        raise ValueError("Frozen diff parse failed: " + canonical(parsed))
    report = dict(started_at=now(), expected_sha256=sha(EXPECTED), ranges=[], snapshots={})
    with ExitStack() as stack:
        sessions = {}
        for side in ("base", "head"):
            root = output / side
            preparation = json.loads((root / "preparation.json").read_text(encoding="utf-8"))
            if preparation["expected_sha256"] != sha(EXPECTED) or preparation["manifest_sha256"] != sha(root / "manifest.json"):
                raise ValueError("Frozen expected or pre-query manifest changed")
            snapshot = loads((root / "manifest.json").read_text(encoding="utf-8")).last_usable
            source = GitSourceReader(checkouts / side, repository=REPOSITORY)
            sessions[side] = stack.enter_context(PrebuiltSnapshotReader(root / "manifest.json", artifact_root=root,
                                               source=source).bind(QueryRequirement(REPOSITORY, snapshot.identity.revision,
                                                                                   snapshot.scope, snapshot.configuration)))
            report["snapshots"][side] = json.loads(canonical(sessions[side].reference))
        # Both inventories and manifests already published. Production API starts here.
        report["first_query_at"] = now()
        mapper = ChangedRangeMapper(MappingBounds())
        actual = mapper.map(parsed.value, base=sessions["base"], head=sessions["head"])
        repeated = mapper.map(parsed.value, base=sessions["base"], head=sessions["head"])
        report["canonical_stable"] = actual.to_json() == repeated.to_json()
        (output / "actual.json").write_text(actual.to_json(), encoding="utf-8")
        report["range_count_valid"] = len(actual.ranges) == len(ROWS)
        for item, expected in zip(actual.ranges, ROWS):
            fi, hi, side, start, end, status, name, line = expected
            anchor = item.anchor
            session = sessions["base" if side == "old" else "head"]
            failures = []
            if (anchor.file_index, anchor.hunk_index, anchor.block_index, anchor.side.value,
                anchor.changed_range.start_line, anchor.changed_range.end_line) != (fi, hi, 0, side, start, end):
                failures.append("anchor_mismatch")
            if anchor.path != (None if fi == 0 and side == "old" else FILES[fi]):
                failures.append("path_mismatch")
            if item.binding != session.reference:
                failures.append("binding_mismatch")
            if item.status.value != status or item.ambiguous != (len(item.symbols) > 1):
                failures.append("status_or_ambiguity_mismatch")
            if not name and item.symbols:
                failures.append("expected_empty")
            reasons = [d.reason.value for d in item.diagnostics]
            allowed_reason = "file_absent_on_side" if status == "not_applicable" else "no_proven_symbol_extent" if status == "unresolved" else "intersection_only_no_enclosing_extent"
            if any(r != allowed_reason for r in reasons) or status != "mapped" and allowed_reason not in reasons:
                failures.append("unexpected_diagnostic")
            required = name is None
            observations = []
            with session.read() as view:
                for mapped in item.symbols:
                    symbol = view.index.get(mapped.seed.identity)
                    if symbol is None:
                        failures.append("missing_public_identity")
                        continue
                    if mapped.seed.snapshot != session.reference.snapshot.identity or mapped.seed.side.value != side:
                        failures.append("seed_side_generation_mismatch")
                    for proof in mapped.evidence:
                        extent = proof.extent
                        a, b = (start, 1), (end, 1)
                        left, right = (extent.start.line, extent.start.column), (extent.end.line, extent.end.column)
                        relation = ("point_interior" if left < a < right else None) if a == b else (
                            "enclosing" if left <= a and b <= right else "intersecting" if max(a, left) < min(b, right) else None)
                        if (extent != getattr(symbol, proof.field) or extent.file.path.as_posix() != anchor.path
                                or relation != proof.relation.value or relation is None):
                            failures.append("unproven_extent")
                        if symbol.qualified_name == name and extent.start.line <= line <= extent.end.line and proof.relation.value == "intersecting":
                            required = True
                    allowed_extra = ("OHOS::Ace::NG", "OHOS::Ace", "OHOS", "OHOS::Ace::NG::ToggleButtonPaintProperty")
                    if symbol.qualified_name != name and symbol.qualified_name not in allowed_extra:
                        failures.append("unexpected_extra_symbol:" + symbol.qualified_name)
                    observations.append(dict(symbol=json.loads(canonical(symbol)), mapping=json.loads(canonical(mapped))))
            if not required:
                failures.append("required_symbol_range_missing")
            row = dict(expected=expected, actual=json.loads(canonical(item)), observations=observations,
                       failures=failures, passed=not failures)
            report["ranges"].append(row)
            print(json.dumps(dict(range=expected[:5], names=[o["symbol"]["qualified_name"] for o in observations],
                                  status=item.status.value, ambiguity=item.ambiguous, diagnostics=reasons, failures=failures)), flush=True)
    report["finished_at"] = now()
    report["passed"] = report["range_count_valid"] and report["canonical_stable"] and all(r["passed"] for r in report["ranges"])
    write(output / "report.json", report)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "query"))
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--checkouts-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output = args.output.resolve()
    args.checkouts_root = args.checkouts_root.resolve()
    args.repository_root = args.repository_root.resolve()
    if "**Frozen expected**" not in EXPECTED.read_text(encoding="utf-8"):
        raise ValueError("Human freeze required")
    if args.mode == "prepare":
        for side, rev in (("base", BASE), ("head", HEAD)):
            checkout = args.checkouts_root / side
            if not checkout.exists():
                checkout.parent.mkdir(parents=True, exist_ok=True)
                git(args.repository_root, "clone", "--shared", "--no-checkout", str(args.repository_root), str(checkout))
                git(checkout, "config", "core.autocrlf", "false")
                git(checkout, "config", "core.longpaths", "true")
                git(checkout, "checkout", "--detach", rev)
            prepare(checkout, args.output / side, side)
    else:
        sys.exit(query(args.repository_root, args.checkouts_root, args.output))
