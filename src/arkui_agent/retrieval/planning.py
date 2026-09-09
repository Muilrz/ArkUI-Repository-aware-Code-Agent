"""Finite input-to-query planning; hints never become identities or facts."""

from arkui_agent.context import Change, HintKind, Task
from .candidates import (
    CandidateQuery, Channel, EvidenceSide, GraphSeed, NameSelector, QueryOrigin,
    RetrievalRequest, SymbolSeed,
)


SEED_CHANNELS = (
    Channel.SYMBOL, Channel.DECLARATION, Channel.DEFINITION, Channel.REFERENCE,
    Channel.CALLERS, Channel.CALLEES, Channel.TESTS_FOR_SYMBOL, Channel.TEST_MAPPING,
    Channel.GRAPH_NODE, Channel.DOMAIN_LOOKUP,
)
TASK_CHANNELS = (Channel.TEXT, *SEED_CHANNELS, Channel.TEST_FIXTURES, Channel.TEST_CASES, Channel.DOMAIN_COMPONENT)
GRAPH_CHANNELS = (Channel.GRAPH_NODE, Channel.GRAPH_INCOMING, Channel.GRAPH_OUTGOING, Channel.DOMAIN_LOOKUP, Channel.DOMAIN_MEMBERS)


def task_request(task: Task, *, channels: tuple[Channel, ...] = TASK_CHANNELS) -> RetrievalRequest:
    queries: list[CandidateQuery] = []
    if Channel.TEXT in channels:
        for number, line in enumerate(task.text.splitlines()):
            if line.strip():
                queries.append(CandidateQuery(Channel.TEXT, NameSelector(line),
                                              (QueryOrigin(task.provenance, f"task_text_line:{number}"),)))
    for hint in task.hints:
        origin = (QueryOrigin(hint.provenance, "hint:" + hint.kind.value),)
        if Channel.TEXT in channels:
            queries.append(CandidateQuery(Channel.TEXT, NameSelector(hint.value), origin))
        if hint.kind in (HintKind.COMPONENT, HintKind.SYMBOL, HintKind.PROPERTY):
            for channel in channels:
                if channel in (*SEED_CHANNELS, Channel.GRAPH_INCOMING, Channel.GRAPH_OUTGOING,
                               Channel.TEST_FIXTURES, Channel.TEST_CASES, Channel.INHERIT, Channel.OVERRIDE, Channel.MOCK):
                    queries.append(CandidateQuery(channel, NameSelector(hint.value, "::" in hint.value), origin))
        if hint.kind is HintKind.COMPONENT and Channel.DOMAIN_COMPONENT in channels:
            queries.append(CandidateQuery(Channel.DOMAIN_COMPONENT, NameSelector(hint.value), origin))
    return RetrievalRequest(task, EvidenceSide.TARGET, tuple(queries))


def change_request(change: Change, seeds: tuple[SymbolSeed | GraphSeed, ...], *,
                   side: EvidenceSide = EvidenceSide.NEW,
                   channels: tuple[Channel, ...] = SEED_CHANNELS) -> RetrievalRequest:
    queries: list[CandidateQuery] = []
    for seed in seeds:
        for channel in channels:
            if isinstance(seed, GraphSeed) and channel not in GRAPH_CHANNELS:
                continue
            if isinstance(seed, SymbolSeed) and channel in (Channel.TEXT, Channel.TEST_FIXTURES,
                                                           Channel.TEST_CASES, Channel.DOMAIN_COMPONENT):
                continue
            queries.append(CandidateQuery(channel, seed, (QueryOrigin(change.provenance, "explicit_change_seed"),)))
    return RetrievalRequest(change, side, tuple(queries), () if queries else ("change_seeds_unresolved:C2_required",))
