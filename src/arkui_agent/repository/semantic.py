"""Backend-agnostic contract for C++ semantic facts."""

from __future__ import annotations

from types import TracebackType
from typing import Protocol, Self, runtime_checkable

from arkui_agent.repository.model import (
    RepositoryFile,
    SourceRange,
    Symbol,
    SymbolIdentity,
)


class SemanticProviderError(RuntimeError):
    """Base boundary for operational semantic provider failures."""


class SemanticProviderClosedError(SemanticProviderError):
    """Raised when a query is attempted after a provider is closed."""


@runtime_checkable
class SemanticProvider(Protocol):
    """Read-only access to backend-independent semantic facts.

    Missing facts return ``None`` or an empty tuple. Operational backend
    failures raise ``SemanticProviderError``. Tuple results must have a stable
    order. ``close`` must be idempotent, and queries after close must fail.
    """

    def symbols_in_file(self, file: RepositoryFile) -> tuple[Symbol, ...]:
        """Return symbols declared or defined in ``file``.

        Document hierarchy may differ at out-of-class definition sites. Providers
        exposing SymbolObservation support evidence-based cross-file canonical
        merging; consumers must not choose conflicting facts by scan order.
        """

        ...

    def declaration(self, identity: SymbolIdentity) -> SourceRange | None:
        """Return the declaration range when known."""

        ...

    def definition(self, identity: SymbolIdentity) -> SourceRange | None:
        """Return the definition range when known."""

        ...

    def references(self, identity: SymbolIdentity) -> tuple[SourceRange, ...]:
        """Return source ranges that reference the symbol."""

        ...

    def callers(self, identity: SymbolIdentity) -> tuple[Symbol, ...]:
        """Return symbols that directly call the symbol."""

        ...

    def callees(self, identity: SymbolIdentity) -> tuple[Symbol, ...]:
        """Return symbols directly called by the symbol."""

        ...

    def close(self) -> None:
        """Release provider resources; repeated calls must be safe."""

        ...

    def __enter__(self) -> Self:
        ...

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        ...
