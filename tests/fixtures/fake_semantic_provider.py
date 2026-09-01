"""Reusable in-memory implementation of the semantic provider contract."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from types import TracebackType
from typing import Self, TypeVar

from arkui_agent.repository import (
    RepositoryFile,
    SemanticProviderClosedError,
    SemanticProviderError,
    SourceRange,
    Symbol,
    SymbolIdentity,
)


class FakeSemanticProvider:
    """Return configured P1 model facts without interpreting symbol identities."""

    def __init__(
        self,
        symbols: Iterable[Symbol] = (),
        *,
        references: Mapping[SymbolIdentity, Iterable[SourceRange]] | None = None,
        callers: Mapping[SymbolIdentity, Iterable[Symbol]] | None = None,
        callees: Mapping[SymbolIdentity, Iterable[Symbol]] | None = None,
        query_error: SemanticProviderError | None = None,
    ) -> None:
        self._symbols = tuple(symbols)
        self._symbols_by_identity = {
            symbol.identity: symbol for symbol in self._symbols
        }
        if len(self._symbols_by_identity) != len(self._symbols):
            raise ValueError("Fake provider symbol identities must be unique.")
        self._references = _freeze_mapping(references)
        self._callers = _freeze_mapping(callers)
        self._callees = _freeze_mapping(callees)
        self._query_error = query_error
        self._closed = False

    def symbols_in_file(self, file: RepositoryFile) -> tuple[Symbol, ...]:
        self._before_query()
        return tuple(
            symbol
            for symbol in self._symbols
            if _symbol_belongs_to_file(symbol, file)
        )

    def declaration(self, identity: SymbolIdentity) -> SourceRange | None:
        self._before_query()
        symbol = self._symbols_by_identity.get(identity)
        return None if symbol is None else symbol.declaration

    def definition(self, identity: SymbolIdentity) -> SourceRange | None:
        self._before_query()
        symbol = self._symbols_by_identity.get(identity)
        return None if symbol is None else symbol.definition

    def references(self, identity: SymbolIdentity) -> tuple[SourceRange, ...]:
        self._before_query()
        return self._references.get(identity, ())

    def callers(self, identity: SymbolIdentity) -> tuple[Symbol, ...]:
        self._before_query()
        return self._callers.get(identity, ())

    def callees(self, identity: SymbolIdentity) -> tuple[Symbol, ...]:
        self._before_query()
        return self._callees.get(identity, ())

    def close(self) -> None:
        self._closed = True

    def __enter__(self) -> Self:
        self._ensure_open()
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def _before_query(self) -> None:
        self._ensure_open()
        if self._query_error is not None:
            raise self._query_error

    def _ensure_open(self) -> None:
        if self._closed:
            raise SemanticProviderClosedError("Semantic provider is closed.")


_Fact = TypeVar("_Fact")


def _freeze_mapping(
    values: Mapping[SymbolIdentity, Iterable[_Fact]] | None,
) -> dict[SymbolIdentity, tuple[_Fact, ...]]:
    if values is None:
        return {}
    return {identity: tuple(items) for identity, items in values.items()}


def _symbol_belongs_to_file(symbol: Symbol, file: RepositoryFile) -> bool:
    return any(
        range_ is not None and range_.file == file
        for range_ in (symbol.declaration, symbol.definition)
    )
