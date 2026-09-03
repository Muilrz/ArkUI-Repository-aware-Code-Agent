"""Identity-safe declaration and definition retrieval over the symbol index."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from arkui_agent.repository import SourceRange, Symbol, SymbolIdentity, SymbolIndex


class SymbolCandidateMatch(str, Enum):
    DISPLAY_NAME = "display_name"
    QUALIFIED_NAME = "qualified_name"


@dataclass(frozen=True, slots=True)
class SymbolCandidates:
    """Deterministically ordered candidates for one exact name query."""

    query: str
    match: SymbolCandidateMatch
    symbols: tuple[Symbol, ...]


class DefinitionDeclarationRetrievalError(RuntimeError):
    """Base error for declaration/definition retrieval."""


class SymbolCandidateNotFoundError(DefinitionDeclarationRetrievalError):
    """Raised when candidate resolution receives an empty candidate set."""


class AmbiguousSymbolCandidateError(DefinitionDeclarationRetrievalError):
    """Raised when a name query has more than one valid identity."""

    def __init__(self, candidates: SymbolCandidates) -> None:
        self.candidates = candidates
        identities = ", ".join(
            symbol.identity.value for symbol in candidates.symbols
        )
        super().__init__(
            f"Ambiguous {candidates.match.value} query {candidates.query!r}; "
            f"candidate identities: {identities}"
        )


class UnknownSymbolIdentityError(DefinitionDeclarationRetrievalError):
    """Raised when exact lookup receives an identity absent from the index."""


class DefinitionDeclarationRetriever:
    """Separate candidate discovery from identity-based source fact lookup."""

    def __init__(self, symbol_index: SymbolIndex) -> None:
        self._symbol_index = symbol_index

    def candidates_by_name(self, display_name: str) -> SymbolCandidates:
        """Return all exact display-name candidates without resolving ambiguity."""

        return SymbolCandidates(
            query=display_name,
            match=SymbolCandidateMatch.DISPLAY_NAME,
            symbols=self._symbol_index.find_by_name(display_name),
        )

    def candidates_by_qualified_name(
        self, qualified_name: str
    ) -> SymbolCandidates:
        """Return all exact qualified-name candidates, including overloads."""

        return SymbolCandidates(
            query=qualified_name,
            match=SymbolCandidateMatch.QUALIFIED_NAME,
            symbols=self._symbol_index.find_by_qualified_name(qualified_name),
        )

    def resolve_unique(self, candidates: SymbolCandidates) -> SymbolIdentity:
        """Resolve exactly one candidate or report not-found/ambiguity explicitly."""

        if not candidates.symbols:
            raise SymbolCandidateNotFoundError(
                f"No symbol matches {candidates.match.value} {candidates.query!r}."
            )
        if len(candidates.symbols) > 1:
            raise AmbiguousSymbolCandidateError(candidates)
        return candidates.symbols[0].identity

    def declaration(self, identity: SymbolIdentity) -> SourceRange | None:
        """Return the declaration for one exact opaque identity when recorded."""

        return self._symbol(identity).declaration

    def definition(self, identity: SymbolIdentity) -> SourceRange | None:
        """Return the definition for one exact opaque identity when recorded."""

        return self._symbol(identity).definition

    def _symbol(self, identity: SymbolIdentity) -> Symbol:
        symbol = self._symbol_index.get(identity)
        if symbol is None:
            raise UnknownSymbolIdentityError(
                f"Symbol identity is not present in the index: {identity.value!r}."
            )
        return symbol
