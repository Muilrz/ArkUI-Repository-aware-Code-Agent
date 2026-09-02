"""Backend-agnostic persistent index for P1 repository symbol facts."""

from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Any, Self

from arkui_agent.repository._sqlite_symbol_storage import (
    SQLiteSymbolStorage,
    SQLiteSymbolStorageError,
)
from arkui_agent.repository.model import (
    RepositoryFile,
    SourceLocation,
    SourceRange,
    Symbol,
    SymbolIdentity,
    SymbolKind,
)


SYMBOL_INDEX_FILENAME = "symbol-index.sqlite3"


class SymbolIndexError(RuntimeError):
    """Public failure boundary for symbol index operations."""


class SymbolIndexClosedError(SymbolIndexError):
    """Raised when an index operation is attempted after close."""


@dataclass(frozen=True, slots=True)
class SymbolSemanticFacts:
    """Backend-independent semantic relations attached to one symbol identity."""

    identity: SymbolIdentity
    references: tuple[SourceRange, ...] = ()
    callers: tuple[SymbolIdentity, ...] = ()
    callees: tuple[SymbolIdentity, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.references, tuple):
            raise TypeError("SymbolSemanticFacts.references must be a tuple.")
        if not isinstance(self.callers, tuple):
            raise TypeError("SymbolSemanticFacts.callers must be a tuple.")
        if not isinstance(self.callees, tuple):
            raise TypeError("SymbolSemanticFacts.callees must be a tuple.")


class SymbolIndex:
    """Persist and query exact P1 model facts using opaque symbol identities."""

    def __init__(self, database_path: str | os.PathLike[str]) -> None:
        if isinstance(database_path, str) and not database_path.strip():
            raise SymbolIndexError("Symbol index database path must not be empty.")
        self.database_path = Path(database_path).expanduser().resolve(strict=False)
        self._closed = False
        try:
            self._storage = SQLiteSymbolStorage(self.database_path)
        except SQLiteSymbolStorageError as exc:
            raise SymbolIndexError(str(exc)) from exc

    @classmethod
    def in_runtime_directory(
        cls, runtime_directory: str | os.PathLike[str]
    ) -> SymbolIndex:
        """Create an index at the standard filename under an explicit runtime dir."""

        if isinstance(runtime_directory, str) and not runtime_directory.strip():
            raise SymbolIndexError("Runtime directory must not be empty.")
        return cls(Path(runtime_directory) / SYMBOL_INDEX_FILENAME)

    def rebuild(
        self,
        symbols: Iterable[Symbol],
        *,
        files: Iterable[RepositoryFile] = (),
        semantic_facts: Iterable[SymbolSemanticFacts] = (),
    ) -> None:
        """Atomically replace the index with one unified-model snapshot."""

        self._require_open()
        symbol_by_identity = _unique_symbols(symbols)
        facts_by_identity = _merge_semantic_facts(semantic_facts)
        unknown_fact_sources = set(facts_by_identity).difference(symbol_by_identity)
        if unknown_fact_sources:
            unknown = min(identity.value for identity in unknown_fact_sources)
            raise SymbolIndexError(
                f"Semantic facts require an indexed source symbol: {unknown}"
            )

        file_set = set(files)
        range_records: list[tuple[str, str, str, int, int, int, int]] = []
        symbol_records: list[tuple[str, str, str, str, str | None, str | None]] = []
        for identity, symbol in sorted(
            symbol_by_identity.items(), key=lambda item: item[0].value
        ):
            symbol_records.append(
                (
                    identity.value,
                    symbol.kind.value,
                    symbol.display_name,
                    symbol.qualified_name,
                    _identity_value(symbol.parent_identity),
                    _identity_value(symbol.namespace_identity),
                )
            )
            for role, source_range in (
                ("declaration", symbol.declaration),
                ("definition", symbol.definition),
            ):
                if source_range is None:
                    continue
                file_set.add(source_range.file)
                range_records.append(
                    _range_record(identity, role, source_range)
                )

        reference_records: set[tuple[str, str, int, int, int, int]] = set()
        relation_records: set[tuple[str, str, str]] = set()
        for identity, facts in facts_by_identity.items():
            for reference in facts.references:
                file_set.add(reference.file)
                reference_records.add(
                    (
                        identity.value,
                        reference.file.path.as_posix(),
                        reference.start.line,
                        reference.start.column,
                        reference.end.line,
                        reference.end.column,
                    )
                )
            relation_records.update(
                (identity.value, "caller", caller.value)
                for caller in facts.callers
            )
            relation_records.update(
                (identity.value, "callee", callee.value)
                for callee in facts.callees
            )

        try:
            self._storage.replace_all(
                files=tuple(
                    (file.path.as_posix(),)
                    for file in sorted(file_set, key=lambda item: item.path.as_posix())
                ),
                symbols=tuple(symbol_records),
                ranges=tuple(sorted(range_records)),
                references=tuple(sorted(reference_records)),
                relations=tuple(sorted(relation_records)),
            )
        except SQLiteSymbolStorageError as exc:
            raise SymbolIndexError(str(exc)) from exc

    def get(self, identity: SymbolIdentity) -> Symbol | None:
        """Return the symbol for an exact opaque identity."""

        self._require_open()
        try:
            row = self._storage.symbol(identity.value)
            return None if row is None else self._symbol_from_row(row)
        except SQLiteSymbolStorageError as exc:
            raise SymbolIndexError(str(exc)) from exc

    def find_by_name(self, display_name: str) -> tuple[Symbol, ...]:
        """Return every exact display-name match without merging identities."""

        self._require_open()
        try:
            return tuple(
                self._symbol_from_row(row)
                for row in self._storage.symbols_by_name(display_name)
            )
        except SQLiteSymbolStorageError as exc:
            raise SymbolIndexError(str(exc)) from exc

    def find_by_qualified_name(self, qualified_name: str) -> tuple[Symbol, ...]:
        """Return every exact qualified-name match in deterministic order."""

        self._require_open()
        try:
            return tuple(
                self._symbol_from_row(row)
                for row in self._storage.symbols_by_qualified_name(qualified_name)
            )
        except SQLiteSymbolStorageError as exc:
            raise SymbolIndexError(str(exc)) from exc

    def symbols_in_file(self, file: RepositoryFile) -> tuple[Symbol, ...]:
        """Return symbols with a declaration or definition in the file."""

        self._require_open()
        try:
            return tuple(
                self._symbol_from_row(row)
                for row in self._storage.symbols_in_file(file.path.as_posix())
            )
        except SQLiteSymbolStorageError as exc:
            raise SymbolIndexError(str(exc)) from exc

    def files(self) -> tuple[RepositoryFile, ...]:
        """Return all explicit or source-derived file records."""

        self._require_open()
        try:
            return tuple(
                RepositoryFile.from_path(row["path"])
                for row in self._storage.files()
            )
        except SQLiteSymbolStorageError as exc:
            raise SymbolIndexError(str(exc)) from exc

    def semantic_facts(
        self, identity: SymbolIdentity
    ) -> SymbolSemanticFacts | None:
        """Return raw persisted relation facts for an exact indexed identity."""

        self._require_open()
        try:
            if self._storage.symbol(identity.value) is None:
                return None
            references = tuple(
                _source_range_from_row(row)
                for row in self._storage.references(identity.value)
            )
            relations = self._storage.relations(identity.value)
        except SQLiteSymbolStorageError as exc:
            raise SymbolIndexError(str(exc)) from exc
        return SymbolSemanticFacts(
            identity=identity,
            references=references,
            callers=tuple(
                SymbolIdentity(row["target_identity"])
                for row in relations
                if row["relation_kind"] == "caller"
            ),
            callees=tuple(
                SymbolIdentity(row["target_identity"])
                for row in relations
                if row["relation_kind"] == "callee"
            ),
        )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._storage.close()
        except SQLiteSymbolStorageError as exc:
            raise SymbolIndexError(str(exc)) from exc

    def __enter__(self) -> Self:
        self._require_open()
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def _symbol_from_row(self, row: Any) -> Symbol:
        identity = SymbolIdentity(row["identity"])
        ranges = {
            range_row["role"]: _source_range_from_row(range_row)
            for range_row in self._storage.ranges(identity.value)
        }
        return Symbol(
            identity=identity,
            kind=SymbolKind(row["kind"]),
            display_name=row["display_name"],
            qualified_name=row["qualified_name"],
            declaration=ranges.get("declaration"),
            definition=ranges.get("definition"),
            parent_identity=_optional_identity(row["parent_identity"]),
            namespace_identity=_optional_identity(row["namespace_identity"]),
        )

    def _require_open(self) -> None:
        if self._closed:
            raise SymbolIndexClosedError("Symbol index is closed.")


def _unique_symbols(symbols: Iterable[Symbol]) -> dict[SymbolIdentity, Symbol]:
    unique: dict[SymbolIdentity, Symbol] = {}
    for symbol in symbols:
        existing = unique.get(symbol.identity)
        if existing is not None and existing != symbol:
            raise SymbolIndexError(
                "Conflicting symbol records share opaque identity "
                f"{symbol.identity.value!r}."
            )
        unique[symbol.identity] = symbol
    return unique


def _merge_semantic_facts(
    facts: Iterable[SymbolSemanticFacts],
) -> dict[SymbolIdentity, SymbolSemanticFacts]:
    references: dict[SymbolIdentity, set[SourceRange]] = {}
    callers: dict[SymbolIdentity, set[SymbolIdentity]] = {}
    callees: dict[SymbolIdentity, set[SymbolIdentity]] = {}
    for item in facts:
        references.setdefault(item.identity, set()).update(item.references)
        callers.setdefault(item.identity, set()).update(item.callers)
        callees.setdefault(item.identity, set()).update(item.callees)
    return {
        identity: SymbolSemanticFacts(
            identity=identity,
            references=tuple(sorted(references[identity], key=_range_sort_key)),
            callers=tuple(sorted(callers[identity], key=lambda item: item.value)),
            callees=tuple(sorted(callees[identity], key=lambda item: item.value)),
        )
        for identity in references.keys() | callers.keys() | callees.keys()
    }


def _range_record(
    identity: SymbolIdentity, role: str, source_range: SourceRange
) -> tuple[str, str, str, int, int, int, int]:
    return (
        identity.value,
        role,
        source_range.file.path.as_posix(),
        source_range.start.line,
        source_range.start.column,
        source_range.end.line,
        source_range.end.column,
    )


def _source_range_from_row(row: Any) -> SourceRange:
    file = RepositoryFile.from_path(row["file_path"])
    return SourceRange(
        SourceLocation(file, row["start_line"], row["start_column"]),
        SourceLocation(file, row["end_line"], row["end_column"]),
    )


def _range_sort_key(source_range: SourceRange) -> tuple[object, ...]:
    return (
        source_range.file.path.as_posix(),
        source_range.start.line,
        source_range.start.column,
        source_range.end.line,
        source_range.end.column,
    )


def _identity_value(identity: SymbolIdentity | None) -> str | None:
    return None if identity is None else identity.value


def _optional_identity(value: str | None) -> SymbolIdentity | None:
    return None if value is None else SymbolIdentity(value)
