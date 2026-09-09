"""Thin C1 adapters over public P1/P2 query interfaces only."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, TypeVar

from arkui_agent.graph.domain import ComponentMapping, MappingStatus, RoleMapping
from arkui_agent.graph.model import GraphEdge, GraphNode, NodeIdentity
from arkui_agent.graph.query import GraphQueryError
from arkui_agent.knowledge import BoundKnowledge
from arkui_agent.repository.index import SymbolIndexError, TestedSymbolMapping
from arkui_agent.repository.model import Symbol, TestCase, TestFixture
from arkui_agent.repository.text_search import RepositoryTextSearch, RepositoryTextSearchError, TextSearchQuery, TextSearchQueryError, TextSearchResult
from .candidates import (
    CandidateFact, CandidateQuery, Channel, GraphSeed, NameSelector, RangeFact,
    RetrievalBounds, RetrievalStatus, SymbolSeed, canonical, fact_key,
)
from .definition_declaration import DefinitionDeclarationRetriever, DefinitionDeclarationRetrievalError
from .reference_call import DirectCallRelation, ReferenceCallRetriever


_T = TypeVar("_T")


def fact_paths(fact: CandidateFact) -> tuple[str, ...]:
    ranges = []
    anchors = []
    if isinstance(fact, Symbol):
        ranges = [fact.declaration, fact.definition]
    elif isinstance(fact, RangeFact):
        ranges = [fact.source_range]
    elif isinstance(fact, DirectCallRelation):
        ranges = [fact.source_range]
        for endpoint in (fact.caller, fact.callee):
            if endpoint is not None:
                ranges.extend((endpoint.declaration, endpoint.definition))
    elif isinstance(fact, (TestFixture, TestCase)):
        ranges = [fact.source_range]
        if isinstance(fact, TestCase):
            ranges.append(fact.body_range)
    elif isinstance(fact, TestedSymbolMapping):
        ranges = list(fact.references)
    elif isinstance(fact, GraphNode):
        anchors = list(fact.anchors)
    elif isinstance(fact, GraphEdge):
        anchors = [e.anchor for e in fact.evidence]
    elif isinstance(fact, (RoleMapping, ComponentMapping)):
        anchors = [e.anchor for e in fact.evidence]
        if isinstance(fact, RoleMapping):
            anchors += [e.anchor for candidate in fact.candidates for e in candidate.evidence]
        else:
            anchors += list(fact.node.anchors)
    return tuple(sorted({r.file.path.as_posix() for r in ranges if r is not None}
                        | {a.file.path.as_posix() for a in anchors if a.file is not None}))


def fact_uncertainty(fact: CandidateFact) -> tuple[bool, bool]:
    if isinstance(fact, DirectCallRelation):
        return False, fact.has_dangling_endpoint or fact.source_range is None
    if isinstance(fact, RoleMapping):
        return fact.status is MappingStatus.AMBIGUOUS, fact.status is MappingStatus.UNKNOWN
    if isinstance(fact, (GraphNode, GraphEdge)):
        return False, not fact_paths(fact)
    return False, False


@dataclass(frozen=True, slots=True)
class ChannelResult:
    facts: tuple[CandidateFact, ...]
    status: RetrievalStatus
    diagnostics: tuple[str, ...]
    calls: int
    observed: int
    ambiguous: bool
    unresolved: bool
    truncated: bool
    unresolved_fact_keys: tuple[str, ...] = ()


class _LimitReached(Exception):
    pass


class _Unresolved(Exception):
    pass


class PublicChannelAdapter:
    """One instance per bound read scope; channel call budgets span all queries."""

    def __init__(self, view: BoundKnowledge, bounds: RetrievalBounds,
                 text_search: RepositoryTextSearch | None = None) -> None:
        self.view = view
        self.bounds = bounds
        self.text = text_search
        self.definitions = DefinitionDeclarationRetriever(view.index)
        self.references = ReferenceCallRetriever(view.index)
        self.graph = view.graph.query()
        self.calls: dict[Channel, int] = {}

    def execute(self, query: CandidateQuery) -> ChannelResult:
        run = _ChannelRun(self, query)
        return run.execute()

    def search_text(self, query: TextSearchQuery) -> tuple[TextSearchResult, ...]:
        # Tool discovery belongs to the text query's failure boundary. Symbol-only
        # requests must remain usable when no text-search tool is installed.
        if self.text is None:
            self.text = RepositoryTextSearch(self.view.workspace)
        return self.text.search(query)


class _ChannelRun:
    def __init__(self, adapter: PublicChannelAdapter, query: CandidateQuery) -> None:
        self.adapter = adapter
        self.query = query
        self.facts: dict[str, list[CandidateFact]] = {}
        self.diagnostics: list[str] = []
        self.ambiguous = self.unresolved = self.truncated = False
        self.calls = self.observed = 0
        self.unresolved_fact_keys: set[str] = set()
        self.fingerprinted = {item.path for item in adapter.view.reference.snapshot.source.files}

    def call(self, function: Callable[..., _T], *args: object, **kwargs: object) -> _T:
        channel = self.query.channel
        if self.adapter.calls.get(channel, 0) >= self.adapter.bounds.max_calls_per_channel:
            self.truncated = True
            self.diagnostics.append("channel_call_limit")
            raise _LimitReached
        self.adapter.calls[channel] = self.adapter.calls.get(channel, 0) + 1
        self.calls += 1
        return function(*args, **kwargs)

    def offer(self, fact: CandidateFact) -> None:
        self.observed += 1
        if self.observed > self.adapter.bounds.max_records_per_query:
            self.truncated = True
            self.diagnostics.append("record_inspection_limit")
            raise _LimitReached
        if not set(fact_paths(fact)).issubset(self.fingerprinted):
            self.unresolved = True
            self.diagnostics.append("source_outside_binding_fingerprint")
            return
        key = canonical(fact_key(fact))
        if key not in self.facts and len(self.facts) >= self.adapter.bounds.max_results_per_query:
            self.truncated = True
            self.diagnostics.append("query_result_limit")
            raise _LimitReached
        self.facts.setdefault(key, []).append(fact)
        ambiguous, unresolved = fact_uncertainty(fact)
        self.ambiguous |= ambiguous
        self.unresolved |= unresolved
        if unresolved:
            self.diagnostics.append("fact_has_unresolved_endpoint_or_source_or_domain_role")

    def symbols(self) -> tuple[Symbol, ...]:
        selector = self.query.selector
        if isinstance(selector, NameSelector):
            method = (self.adapter.definitions.candidates_by_qualified_name if selector.qualified
                      else self.adapter.definitions.candidates_by_name)
            found = self.call(method, selector.text).symbols
            self.ambiguous |= len(found) > 1
            if len(found) > self.adapter.bounds.max_name_candidates:
                self.truncated = True
                self.diagnostics.append("name_fanout_limit")
            found = tuple(sorted(found, key=lambda s: s.identity.value))[:self.adapter.bounds.max_name_candidates]
        elif isinstance(selector, SymbolSeed):
            symbol = self.call(self.adapter.view.index.get, selector.identity)
            found = () if symbol is None else (symbol,)
        else:
            raise _Unresolved("channel_requires_symbol_selector")
        eligible = tuple(s for s in found if set(fact_paths(s)).issubset(self.fingerprinted))
        if len(eligible) != len(found):
            self.unresolved = True
            self.diagnostics.append("seed_source_outside_binding_fingerprint")
        if not eligible and (self.query.channel is not Channel.SYMBOL or isinstance(selector, SymbolSeed)):
            raise _Unresolved("symbol_seed_not_resolved")
        return eligible

    def execute(self) -> ChannelResult:
        if self.query.channel in (Channel.INHERIT, Channel.OVERRIDE, Channel.MOCK):
            return ChannelResult((), RetrievalStatus.UNSUPPORTED, ("no_production_relation_provider",), 0, 0, False, False, False)
        if isinstance(self.query.selector, NameSelector):
            text = self.query.selector.text
            if len(text) > self.adapter.bounds.max_query_characters:
                return ChannelResult((), RetrievalStatus.TRUNCATED, ("query_character_limit",), 0, 0, False, False, True)
            if "\n" in text or "\r" in text:
                return ChannelResult((), RetrievalStatus.UNSUPPORTED, ("multiline_selector_not_supported",), 0, 0, False, False, False)
        try:
            self.run()
        except _LimitReached:
            pass  # Budget exhaustion is explicit; already observed facts remain usable.
        except _Unresolved as error:
            self.unresolved = True
            self.diagnostics.append(str(error))
        except (RepositoryTextSearchError, TextSearchQueryError, SymbolIndexError,
                DefinitionDeclarationRetrievalError, GraphQueryError) as error:
            # Atomic per-query failure: do not advertise partially collected query facts as complete.
            diagnostics = tuple(sorted(set(self.diagnostics + [type(error).__name__ + ": " + str(error)])))
            return ChannelResult((), RetrievalStatus.FAILURE, diagnostics,
                                 self.calls, self.observed, self.ambiguous, self.unresolved, self.truncated)
        facts = tuple(fact for key in sorted(self.facts) for fact in self.facts[key])
        status = (RetrievalStatus.TRUNCATED if self.truncated else RetrievalStatus.UNRESOLVED if self.unresolved
                  else RetrievalStatus.OK if facts else RetrievalStatus.EMPTY)
        return ChannelResult(facts, status, tuple(sorted(set(self.diagnostics))), self.calls, self.observed,
                             self.ambiguous, self.unresolved, self.truncated, tuple(sorted(self.unresolved_fact_keys)))

    def run(self) -> None:
        channel, selector = self.query.channel, self.query.selector
        view = self.adapter.view
        if channel is Channel.TEXT:
            if not isinstance(selector, NameSelector):
                raise _Unresolved("text_requires_literal_input")
            files = view.reference.snapshot.scope.text_files
            if not files:
                raise _Unresolved("text_scope_unavailable")
            for path in files:
                query = TextSearchQuery(selector.text, path_scope=path,
                                        limit=self.adapter.bounds.max_results_per_query + 1)
                for match in self.call(self.adapter.search_text, query):
                    self.offer(RangeFact("text", match.source_range, matched_text=match.matched_text, line_text=match.line_text))
            return
        if channel in (Channel.TEST_FIXTURES, Channel.TEST_CASES, Channel.DOMAIN_COMPONENT):
            if not isinstance(selector, NameSelector):
                raise _Unresolved("channel_requires_name")
            if channel is Channel.DOMAIN_COMPONENT:
                records = self.call(lambda: view.domain.components)
                matches = tuple(c for c in records if selector.text in (c.node.display_name, c.node.identity.key))
            else:
                method = view.index.find_test_fixtures if channel is Channel.TEST_FIXTURES else view.index.find_test_cases
                matches = self.call(method, selector.text)
            self.ambiguous |= len(matches) > 1
            for fact in sorted(matches, key=lambda x: canonical(fact_key(x))):
                self.offer(fact)
            return
        if channel is Channel.TESTS_FOR_FIXTURE:
            if not isinstance(selector, SymbolSeed) or self.call(view.index.get_test_fixture, selector.identity) is None:
                raise _Unresolved("fixture_identity_not_resolved")
            for fact in self.call(view.index.test_cases_for_fixture, selector.identity):
                self.offer(fact)
            return
        if channel is Channel.DOMAIN_MEMBERS:
            if not isinstance(selector, GraphSeed):
                raise _Unresolved("component_identity_required")
            components = self.call(lambda: view.domain.components)
            if not any(c.node.identity == selector.identity for c in components):
                raise _Unresolved("component_identity_not_resolved")
            for fact in self.call(view.domain.members, selector.identity):
                self.offer(fact)
            return
        graph_channels = (Channel.GRAPH_NODE, Channel.GRAPH_INCOMING, Channel.GRAPH_OUTGOING, Channel.DOMAIN_LOOKUP)
        if isinstance(selector, GraphSeed):
            if channel not in graph_channels:
                raise _Unresolved("graph_seed_not_applicable_to_channel")
            identities = (selector.identity,)
        else:
            symbols = self.symbols()
            identities = tuple(NodeIdentity.for_symbol(s.identity) for s in symbols)
            if channel not in graph_channels:
                for symbol in symbols:
                    identity = symbol.identity
                    if channel is Channel.SYMBOL:
                        self.offer(symbol)
                    elif channel in (Channel.DECLARATION, Channel.DEFINITION):
                        method = (self.adapter.definitions.declaration if channel is Channel.DECLARATION
                                  else self.adapter.definitions.definition)
                        source_range = self.call(method, identity)
                        if source_range is None:
                            self.unresolved = True
                            self.diagnostics.append("source_range_not_recorded")
                        else:
                            self.offer(RangeFact(channel.value, source_range, identity))
                    elif channel is Channel.REFERENCE:
                        for reference in self.call(self.adapter.references.references, identity):
                            self.offer(RangeFact("reference", reference.source_range, reference.identity))
                    elif channel in (Channel.CALLERS, Channel.CALLEES):
                        method = self.adapter.references.callers if channel is Channel.CALLERS else self.adapter.references.callees
                        for relation in self.call(method, identity):
                            self.offer(relation)
                    elif channel in (Channel.TESTS_FOR_SYMBOL, Channel.TEST_MAPPING):
                        method = view.index.test_cases_for_symbol if channel is Channel.TESTS_FOR_SYMBOL else view.index.tested_symbol_mappings_for_symbol
                        for fact in self.call(method, identity):
                            self.offer(fact)
                    else:
                        raise _Unresolved("selector_channel_combination_not_supported")
                return
        for identity in identities:
            if channel is Channel.DOMAIN_LOOKUP:
                mapping = self.call(view.domain.lookup, identity)
                if mapping is None:
                    self.unresolved = True
                    self.diagnostics.append("domain_mapping_not_recorded")
                else:
                    self.offer(mapping)
                continue
            node = self.call(self.adapter.graph.node, identity)
            if node is None:
                self.unresolved = True
                self.diagnostics.append("graph_seed_not_resolved")
                continue
            if channel is Channel.GRAPH_NODE:
                self.offer(node)
            else:
                unavailable = tuple(sorted(relation.value for relation in view.graph.unavailable_relations))
                if unavailable:
                    self.unresolved = True
                    self.diagnostics.append("unavailable_relations:" + ",".join(unavailable))
                method = self.adapter.graph.incoming_edges if channel is Channel.GRAPH_INCOMING else self.adapter.graph.outgoing_edges
                for edge in self.call(method, identity):
                    # Direct endpoint validation is not recursive expansion. P2
                    # can retain symbol-only nodes for dangling P1 endpoints.
                    for endpoint in (edge.identity.source, edge.identity.target):
                        endpoint_node = self.call(self.adapter.graph.node, endpoint)
                        if (endpoint_node is None or not fact_paths(endpoint_node)
                                or not set(fact_paths(endpoint_node)).issubset(self.fingerprinted)):
                            self.unresolved = True
                            self.unresolved_fact_keys.add(canonical(fact_key(edge)))
                            self.diagnostics.append("graph_endpoint_unresolved")
                    self.offer(edge)
