from __future__ import annotations

import unittest
from dataclasses import replace

from arkui_agent.context import Origin, Provenance, parse_task, parse_unified_diff
from arkui_agent.knowledge import SnapshotIdentity
from arkui_agent.repository.model import RepositoryFile, SourceLocation, SourceRange, Symbol, SymbolIdentity, SymbolKind
from arkui_agent.retrieval.candidates import (
    CandidateInputError, CandidateQuery, Channel, EvidenceSide, NameSelector, QueryOrigin,
    RetrievalBounds, SymbolSeed,
)
from arkui_agent.retrieval.planning import change_request, task_request
from arkui_agent.retrieval.service import _queries
from arkui_agent.retrieval.channels import fact_paths
from arkui_agent.retrieval.reference_call import DirectCallRelation


class CandidatePlanningTests(unittest.TestCase):
    def test_hints_are_name_queries_with_original_provenance_not_identities(self) -> None:
        task = parse_task("分析 [symbol:demo::Set(int)] [component:Unknown]", repository="repo",
                          target_revision="a" * 40, source_id="task").value
        request = task_request(task)
        self.assertTrue(request.queries)
        self.assertTrue(all(isinstance(q.selector, NameSelector) for q in request.queries))
        self.assertTrue(any(q.selector.text == "demo::Set(int)" for q in request.queries))
        extracted = [o.provenance for q in request.queries for o in q.origins if o.label.startswith("hint:")]
        self.assertTrue(all(p.origin is Origin.EXTRACTED and p.span is not None for p in extracted))
        self.assertEqual(request.input, task)

    def test_unknown_multiline_text_retained_as_literal_line_queries(self) -> None:
        raw = "未知组件为何失效？\n保留第二行 🧪"
        task = parse_task(raw, repository="repo", target_revision="a" * 40, source_id="task").value
        request = task_request(task)
        self.assertEqual(request.input.text, raw)
        self.assertEqual([q.selector.text for q in request.queries], raw.splitlines())
        self.assertTrue(all(q.channel is Channel.TEXT for q in request.queries))

    def test_query_dedup_merges_origins_without_order_dependence(self) -> None:
        one = CandidateQuery(Channel.SYMBOL, NameSelector("Set"), (QueryOrigin(Provenance("one", Origin.EXPLICIT), "hint"),))
        two = replace(one, origins=(QueryOrigin(Provenance("two", Origin.EXPLICIT), "seed"),))
        self.assertEqual(_queries((one, two, one)), _queries((two, one)))
        self.assertEqual(len(_queries((one, two))[0].origins), 2)
        self.assertEqual(one.query_id, two.query_id)

    def test_change_without_explicit_seeds_is_unresolved_and_ranges_are_not_mapped(self) -> None:
        change = parse_unified_diff("--- a.cpp\n+++ a.cpp\n@@ -1 +1 @@\n-a\n+b\n",
                                    repository="repo", base_revision="b" * 40, head_revision="a" * 40, source_id="diff").value
        request = change_request(change, ())
        self.assertEqual(request.queries, ())
        self.assertTrue(request.diagnostics)
        identity = SnapshotIdentity("s", "g", "repo", "a" * 40)
        seed = SymbolSeed(SymbolIdentity("backend-id"), identity, EvidenceSide.NEW)
        request = change_request(change, (seed,), channels=(Channel.REFERENCE,))
        self.assertEqual(request.queries[0].selector, seed)
        self.assertEqual(request.input.files, change.files)

    def test_bounds_reject_bool_zero_negative_and_nonintegral_values(self) -> None:
        for value in (True, 0, -1, 1.5):
            with self.assertRaises(CandidateInputError):
                RetrievalBounds(max_queries=value)

    def test_call_source_paths_include_embedded_endpoint_sources(self) -> None:
        def symbol(identity, path):
            file = RepositoryFile.from_path(path)
            extent = SourceRange(SourceLocation(file, 1, 1), SourceLocation(file, 1, 10))
            return Symbol(SymbolIdentity(identity), SymbolKind.FUNCTION, identity, identity, definition=extent)

        caller = symbol("caller", "src/caller.cpp")
        callee = symbol("callee", "include/callee.h")
        relation = DirectCallRelation(caller.identity, callee.identity, caller, callee, caller.definition)
        self.assertEqual(fact_paths(relation), ("include/callee.h", "src/caller.cpp"))


if __name__ == "__main__":
    unittest.main()
