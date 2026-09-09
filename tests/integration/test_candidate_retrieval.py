from __future__ import annotations

import os
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from arkui_agent.context import Origin, Provenance, parse_task, parse_unified_diff
from arkui_agent.graph.domain import ComponentMapping, RoleMapping
from arkui_agent.graph.model import GraphEdge, NodeIdentity
from arkui_agent.knowledge import SnapshotReadError
from arkui_agent.repository.model import Symbol, SymbolIdentity, TestCase
from arkui_agent.repository.index import TestedSymbolMapping
from arkui_agent.repository.text_search import RepositoryTextSearch, TextSearchMode, TextSearchQuery
from arkui_agent.retrieval.candidates import (
    CandidateQuery, Channel, EvidenceSide, GraphSeed, NameSelector, QueryOrigin, RangeFact,
    RetrievalBounds, RetrievalRequest, RetrievalStatus, SymbolSeed,
)
from arkui_agent.retrieval.channels import PublicChannelAdapter
from arkui_agent.retrieval.planning import change_request, task_request
from arkui_agent.retrieval.reference_call import DirectCallRelation
from arkui_agent.retrieval.service import CandidateRetriever
from tests.fixtures.candidate_retrieval import CandidateFixture, EXPECTED_SET_IDENTITIES


class CandidateRetrievalTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.fixture = CandidateFixture(Path(temporary.name))
        self.session = self.fixture.reader.bind(self.fixture.requirement)
        self.addCleanup(self.session.close)
        self.task = parse_task("[symbol:demo::Set]", repository=self.fixture.requirement.repository,
                               target_revision=self.fixture.requirement.revision, source_id="task").value
        self.origin = (QueryOrigin(Provenance("explicit", Origin.EXPLICIT), "query"),)

    def query(self, channel, selector):
        return CandidateQuery(channel, selector, self.origin)

    def seed(self, identity, side=EvidenceSide.TARGET):
        return SymbolSeed(SymbolIdentity(identity), self.session.reference.snapshot.identity, side)

    def retrieve(self, queries, bounds=RetrievalBounds(), factory=PublicChannelAdapter):
        request = RetrievalRequest(self.task, EvidenceSide.TARGET, tuple(queries))
        return CandidateRetriever(bounds=bounds, adapter_factory=factory).retrieve(request, self.session)

    def test_overloads_and_duplicate_name_channels_keep_identities_and_merge_provenance(self) -> None:
        queries = (self.query(Channel.SYMBOL, NameSelector("Set")),
                   self.query(Channel.SYMBOL, NameSelector("demo::Set", True)))
        result = self.retrieve(queries)
        self.assertEqual(sorted(c.observations[0].identity.value for c in result.candidates), list(EXPECTED_SET_IDENTITIES))
        self.assertTrue(all(c.ambiguous and len(c.provenance) == 2 for c in result.candidates))
        self.assertTrue(all(c.snapshot == self.session.reference.snapshot.identity for c in result.candidates))
        self.assertTrue(all(c.source_hashes for c in result.candidates))
        self.assertEqual(result.to_json(), self.retrieve(tuple(reversed(queries))).to_json())

    def test_task_and_explicit_change_seeds_use_same_public_channels(self) -> None:
        channels = (Channel.SYMBOL, Channel.DECLARATION, Channel.DEFINITION, Channel.REFERENCE, Channel.TEST_MAPPING)
        task_result = CandidateRetriever().retrieve(task_request(self.task, channels=channels), self.session)
        change = parse_unified_diff("--- src/widget.cpp\n+++ src/widget.cpp\n@@ -4 +4 @@\n-old\n+new\n",
                                    repository=self.task.repository, base_revision="b" * 40,
                                    head_revision=self.task.target_revision.value, source_id="diff").value
        seeds = tuple(self.seed(identity, EvidenceSide.NEW) for identity in EXPECTED_SET_IDENTITIES)
        result = CandidateRetriever().retrieve(change_request(change, seeds, channels=channels), self.session)
        self.assertEqual(sorted(type(f).__name__ for c in result.candidates for f in c.observations),
                         sorted(type(f).__name__ for c in task_result.candidates for f in c.observations))
        self.assertTrue(all(c.side is EvidenceSide.NEW for c in result.candidates))
        self.assertTrue({c.candidate_id for c in result.candidates}.isdisjoint(c.candidate_id for c in task_result.candidates))

    def test_real_rg_uses_only_bound_text_files_and_preserves_exact_source(self) -> None:
        result = self.retrieve((self.query(Channel.TEXT, NameSelector("Set")),))
        self.assertEqual(result.status, RetrievalStatus.OK)
        self.assertTrue(result.candidates)
        for candidate in result.candidates:
            fact = candidate.observations[0]
            self.assertIsInstance(fact, RangeFact)
            self.assertEqual(fact.matched_text, "Set")
            self.assertIn(fact.source_range.file.path.as_posix(), self.fixture.scope.text_files)
            self.assertTrue(candidate.source_hashes)
        excluded = self.retrieve((self.query(Channel.TEXT, NameSelector("synthetic source")),))
        self.assertEqual(excluded.status, RetrievalStatus.EMPTY)  # README is fingerprinted but outside text scope.

    def test_p1_and_p2_same_call_merge_without_losing_dangling_endpoint(self) -> None:
        result = self.retrieve((self.query(Channel.CALLEES, self.seed("caller")),
                                self.query(Channel.CALLERS, self.seed("set:int")),
                                self.query(Channel.GRAPH_OUTGOING,
                                           GraphSeed(NodeIdentity("symbol", "caller"), self.seed("caller").snapshot, EvidenceSide.TARGET))))
        calls = [c for c in result.candidates if any(isinstance(f, DirectCallRelation) for f in c.observations)]
        known = next(c for c in calls if any(isinstance(f, DirectCallRelation) and f.callee_identity.value == "set:int" for f in c.observations))
        self.assertTrue(any(isinstance(f, GraphEdge) for f in known.observations))
        self.assertEqual(len(known.provenance), 3)
        dangling = next(c for c in calls if any(isinstance(f, DirectCallRelation) and f.has_dangling_endpoint for f in c.observations))
        self.assertTrue(dangling.unresolved)
        self.assertTrue(any("unavailable_relations" in d for r in result.reports for d in r.diagnostics))

    def test_tests_mapping_fixture_case_and_empty_mapping_are_distinct(self) -> None:
        result = self.retrieve((self.query(Channel.TEST_CASES, NameSelector("CaseOne")),
                                self.query(Channel.TEST_FIXTURES, NameSelector("WidgetTest")),
                                self.query(Channel.TESTS_FOR_FIXTURE, self.seed("fixture:WidgetTest")),
                                self.query(Channel.TESTS_FOR_SYMBOL, self.seed("set:int")),
                                self.query(Channel.TEST_MAPPING, self.seed("set:int"))))
        cases = [c for c in result.candidates if isinstance(c.observations[0], TestCase)]
        self.assertEqual(len(cases), 1)
        self.assertEqual(len(cases[0].provenance), 3)
        mappings = [f for c in result.candidates for f in c.observations if isinstance(f, TestedSymbolMapping)]
        self.assertEqual(len(mappings), 1)
        self.assertTrue(mappings[0].references)
        empty = self.retrieve((self.query(Channel.TEST_MAPPING, self.seed("set:double")),))
        self.assertEqual(empty.status, RetrievalStatus.EMPTY)

    def test_direct_domain_component_lookup_and_members_use_existing_facts(self) -> None:
        result = self.retrieve((self.query(Channel.DOMAIN_COMPONENT, NameSelector("Widget")),
                                self.query(Channel.DOMAIN_LOOKUP, self.seed("widget")),
                                self.query(Channel.DOMAIN_MEMBERS, GraphSeed(NodeIdentity("arkui.component", "widget"),
                                                                           self.seed("widget").snapshot, EvidenceSide.TARGET))))
        self.assertTrue(any(isinstance(f, ComponentMapping) for c in result.candidates for f in c.observations))
        mappings = [c for c in result.candidates if isinstance(c.observations[0], RoleMapping)]
        self.assertEqual(len(mappings), 1)
        self.assertEqual(len(mappings[0].provenance), 2)
        unknown = self.retrieve((self.query(Channel.DOMAIN_COMPONENT, NameSelector("Unknown")),))
        self.assertEqual(unknown.status, RetrievalStatus.EMPTY)

    def test_empty_unsupported_unresolved_are_separate(self) -> None:
        result = self.retrieve((self.query(Channel.SYMBOL, NameSelector("Unknown")),
                                self.query(Channel.MOCK, NameSelector("Set")),
                                self.query(Channel.REFERENCE, self.seed("not-indexed"))))
        self.assertEqual({r.status for r in result.reports},
                         {RetrievalStatus.EMPTY, RetrievalStatus.UNSUPPORTED, RetrievalStatus.UNRESOLVED})
        self.assertEqual(result.candidates, ())

    def test_real_missing_text_tool_is_failure_without_suppressing_symbol_results(self) -> None:
        class MissingToolText(RepositoryTextSearch):
            def __init__(self, workspace):
                super().__init__(workspace)
                self.workspace = workspace

            def search(self, query):
                original = os.environ.get("PATH")
                try:
                    os.environ["PATH"] = ""
                    return RepositoryTextSearch(self.workspace).search(query)
                finally:
                    if original is None:
                        os.environ.pop("PATH", None)
                    else:
                        os.environ["PATH"] = original

        result = self.retrieve((self.query(Channel.TEXT, NameSelector("Set")),
                                self.query(Channel.SYMBOL, NameSelector("Set"))),
                               factory=lambda view, bounds: PublicChannelAdapter(view, bounds, MissingToolText(view.workspace)))
        self.assertEqual(result.status, RetrievalStatus.FAILURE)
        self.assertTrue(result.candidates)
        text = next(r for r in result.reports if r.query.channel is Channel.TEXT)
        self.assertEqual(text.status, RetrievalStatus.FAILURE)
        self.assertTrue(any("TextSearchToolUnavailableError" in d for d in text.diagnostics))

    def test_real_rg_backend_error_is_failure(self) -> None:
        class InvalidRegexText(RepositoryTextSearch):
            def search(self, query):
                return super().search(TextSearchQuery("[", mode=TextSearchMode.REGEX, path_scope=query.path_scope))

        result = self.retrieve((self.query(Channel.TEXT, NameSelector("Set")),),
                               factory=lambda view, bounds: PublicChannelAdapter(view, bounds, InvalidRegexText(view.workspace)))
        self.assertEqual(result.status, RetrievalStatus.FAILURE)
        self.assertEqual(result.candidates, ())
        self.assertTrue(any("TextSearchBackendError" in d for d in result.reports[0].diagnostics))

    def test_name_query_call_and_candidate_budgets_preserve_truncation(self) -> None:
        queries = (self.query(Channel.SYMBOL, NameSelector("Set")),
                   self.query(Channel.SYMBOL, NameSelector("demo::Set", True)))
        for bounds in (RetrievalBounds(max_name_candidates=1), RetrievalBounds(max_results_per_query=1),
                       RetrievalBounds(max_candidates_per_channel=1), RetrievalBounds(max_candidates=1),
                       RetrievalBounds(max_queries=1), RetrievalBounds(max_calls_per_channel=1),
                       RetrievalBounds(max_records_per_query=1)):
            result = self.retrieve(queries, bounds)
            self.assertEqual(result.status, RetrievalStatus.TRUNCATED)
            self.assertTrue(result.truncated)
            self.assertLessEqual(len(result.candidates), bounds.max_candidates)
            self.assertTrue(all(c.ambiguous for c in result.candidates))
            self.assertEqual(result.to_json(), self.retrieve(tuple(reversed(queries)), bounds).to_json())
        exact = self.retrieve((queries[0],), RetrievalBounds(max_results_per_query=2))
        self.assertEqual(exact.status, RetrievalStatus.OK)

    def test_wrong_revision_generation_or_side_never_queries_identity_as_fact(self) -> None:
        wrong = replace(self.seed("set:int"), side=EvidenceSide.OLD)
        result = self.retrieve((self.query(Channel.SYMBOL, wrong),))
        self.assertEqual(result.status, RetrievalStatus.UNRESOLVED)
        self.assertEqual(result.reports[0].calls, 0)
        wrong = replace(self.seed("set:int"), snapshot=replace(self.seed("set:int").snapshot, generation="other"))
        self.assertEqual(self.retrieve((self.query(Channel.SYMBOL, wrong),)).candidates, ())
        task = replace(self.task, target_revision=replace(self.task.target_revision, value=None))
        result = CandidateRetriever().retrieve(task_request(task), self.session)
        self.assertEqual(result.status, RetrievalStatus.UNRESOLVED)
        self.assertEqual(result.reports, ())

    def test_source_drift_aborts_whole_retrieval_at_session_exit(self) -> None:
        class DriftingText(RepositoryTextSearch):
            def search(inner, query):
                matches = super().search(query)
                (self.fixture.repo / "src/widget.cpp").write_text("drift\n", encoding="utf-8")
                return matches

        with self.assertRaises(SnapshotReadError):
            self.retrieve((self.query(Channel.TEXT, NameSelector("Set")),),
                          factory=lambda view, bounds: PublicChannelAdapter(view, bounds, DriftingText(view.workspace)))

    def test_graph_truncation_keeps_unavailable_relations_and_serialized_diagnostics(self) -> None:
        query = self.query(Channel.GRAPH_OUTGOING, self.seed("caller"))
        result = self.retrieve((query,), RetrievalBounds(max_results_per_query=1))
        report = result.reports[0]
        self.assertTrue(report.truncated and report.unresolved)
        self.assertTrue(any("unavailable_relations" in d for d in report.diagnostics))
        payload = json.loads(result.to_json())
        self.assertEqual(payload["status"], "truncated")
        self.assertEqual(payload["result"]["reports"][0]["diagnostics"], list(report.diagnostics))
        self.assertEqual(payload["result"]["binding"]["snapshot"]["identity"]["generation"], "c1")

    def test_graph_only_dangling_endpoint_remains_unresolved(self) -> None:
        result = self.retrieve((self.query(Channel.GRAPH_OUTGOING, self.seed("caller")),))
        dangling = next(c for c in result.candidates if any(
            isinstance(f, GraphEdge) and f.identity.target.key == "external" for f in c.observations))
        self.assertTrue(dangling.unresolved)
        self.assertIn("graph_endpoint_unresolved", result.reports[0].diagnostics)

    def test_artifact_replacement_aborts_before_returning_candidates(self) -> None:
        path = self.fixture.artifacts / self.session.reference.snapshot.artifacts.graph.path
        path.write_text("{}", encoding="utf-8")
        with self.assertRaises(SnapshotReadError):
            self.retrieve((self.query(Channel.SYMBOL, NameSelector("Set")),))

    def test_signature_hint_is_unresolved_and_selector_limits_do_not_query(self) -> None:
        result = self.retrieve((self.query(Channel.REFERENCE, NameSelector("demo::Set(int)", True)),))
        self.assertEqual(result.status, RetrievalStatus.UNRESOLVED)
        self.assertEqual(result.candidates, ())
        result = self.retrieve((self.query(Channel.TEXT, NameSelector("too long")),), RetrievalBounds(max_query_characters=3))
        self.assertEqual(result.status, RetrievalStatus.TRUNCATED)
        self.assertEqual(result.reports[0].calls, 0)
        result = self.retrieve((self.query(Channel.TEXT, NameSelector("one\ntwo")),))
        self.assertEqual(result.status, RetrievalStatus.UNSUPPORTED)
        self.assertEqual(result.reports[0].calls, 0)


if __name__ == "__main__":
    unittest.main()
