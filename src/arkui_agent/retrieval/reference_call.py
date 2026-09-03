"""Identity-safe reference and direct-call retrieval over the symbol index."""

from __future__ import annotations

from dataclasses import dataclass

from arkui_agent.repository import (
    SourceRange,
    Symbol,
    SymbolIdentity,
    SymbolIndex,
    SymbolSemanticFacts,
)
from arkui_agent.retrieval.definition_declaration import UnknownSymbolIdentityError


@dataclass(frozen=True, slots=True)
class ReferenceResult:
    """One exact source reference attached to an opaque symbol identity."""

    identity: SymbolIdentity
    source_range: SourceRange


@dataclass(frozen=True, slots=True)
class DirectCallRelation:
    """One stored direct-call edge with the best available caller provenance.

    ``source_range`` is the caller definition, falling back to its declaration.
    Existing P1 facts do not carry the exact call-site range. An unresolved
    endpoint remains explicit through its identity and a ``None`` symbol.
    """

    caller_identity: SymbolIdentity
    callee_identity: SymbolIdentity
    caller: Symbol | None
    callee: Symbol | None
    source_range: SourceRange | None

    def __post_init__(self) -> None:
        if self.caller is not None and self.caller.identity != self.caller_identity:
            raise ValueError("DirectCallRelation caller identity does not match symbol.")
        if self.callee is not None and self.callee.identity != self.callee_identity:
            raise ValueError("DirectCallRelation callee identity does not match symbol.")

    @property
    def has_dangling_endpoint(self) -> bool:
        return self.caller is None or self.callee is None


class ReferenceCallRetriever:
    """Retrieve persisted references and direct calls using exact identities."""

    def __init__(self, symbol_index: SymbolIndex) -> None:
        self._symbol_index = symbol_index

    def references(self, identity: SymbolIdentity) -> tuple[ReferenceResult, ...]:
        """Return deduplicated references ordered by repository source range."""

        _, facts = self._indexed_facts(identity)
        unique_ranges = set(facts.references)
        return tuple(
            ReferenceResult(identity, source_range)
            for source_range in sorted(unique_ranges, key=_range_sort_key)
        )

    def callers(self, identity: SymbolIdentity) -> tuple[DirectCallRelation, ...]:
        """Return only stored direct callers; do not infer reciprocal edges."""

        callee, facts = self._indexed_facts(identity)
        relations = {
            (caller_identity, identity): self._relation(
                caller_identity=caller_identity,
                callee_identity=identity,
                callee=callee,
            )
            for caller_identity in facts.callers
        }
        return tuple(relations[key] for key in sorted(relations, key=_identity_pair_key))

    def callees(self, identity: SymbolIdentity) -> tuple[DirectCallRelation, ...]:
        """Return only stored direct callees; do not traverse or infer edges."""

        caller, facts = self._indexed_facts(identity)
        relations = {
            (identity, callee_identity): self._relation(
                caller_identity=identity,
                callee_identity=callee_identity,
                caller=caller,
            )
            for callee_identity in facts.callees
        }
        return tuple(relations[key] for key in sorted(relations, key=_identity_pair_key))

    def _relation(
        self,
        *,
        caller_identity: SymbolIdentity,
        callee_identity: SymbolIdentity,
        caller: Symbol | None = None,
        callee: Symbol | None = None,
    ) -> DirectCallRelation:
        resolved_caller = caller or self._symbol_index.get(caller_identity)
        resolved_callee = callee or self._symbol_index.get(callee_identity)
        return DirectCallRelation(
            caller_identity=caller_identity,
            callee_identity=callee_identity,
            caller=resolved_caller,
            callee=resolved_callee,
            source_range=_symbol_provenance(resolved_caller),
        )

    def _indexed_facts(
        self, identity: SymbolIdentity
    ) -> tuple[Symbol, SymbolSemanticFacts]:
        symbol = self._symbol_index.get(identity)
        if symbol is None:
            raise UnknownSymbolIdentityError(
                f"Symbol identity is not present in the index: {identity.value!r}."
            )
        facts = self._symbol_index.semantic_facts(identity)
        if facts is None:
            raise UnknownSymbolIdentityError(
                f"Symbol facts are not present in the index: {identity.value!r}."
            )
        return symbol, facts


def _symbol_provenance(symbol: Symbol | None) -> SourceRange | None:
    if symbol is None:
        return None
    return symbol.definition or symbol.declaration


def _range_sort_key(source_range: SourceRange) -> tuple[object, ...]:
    return (
        source_range.file.path.as_posix(),
        source_range.start.line,
        source_range.start.column,
        source_range.end.line,
        source_range.end.column,
    )


def _identity_pair_key(
    pair: tuple[SymbolIdentity, SymbolIdentity],
) -> tuple[str, str]:
    return pair[0].value, pair[1].value
