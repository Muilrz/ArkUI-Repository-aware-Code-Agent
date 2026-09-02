"""SQLite persistence details for the backend-agnostic symbol index."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Sequence
from pathlib import Path


SCHEMA_VERSION = 1


class SQLiteSymbolStorageError(RuntimeError):
    """Internal persistence failure hidden by the public index boundary."""


_SCHEMA = """
CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS files (
    path TEXT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS symbols (
    identity TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    display_name TEXT NOT NULL,
    qualified_name TEXT NOT NULL,
    parent_identity TEXT,
    namespace_identity TEXT
);

CREATE TABLE IF NOT EXISTS symbol_ranges (
    symbol_identity TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('declaration', 'definition')),
    file_path TEXT NOT NULL,
    start_line INTEGER NOT NULL,
    start_column INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    end_column INTEGER NOT NULL,
    PRIMARY KEY (symbol_identity, role),
    FOREIGN KEY (symbol_identity) REFERENCES symbols(identity) ON DELETE CASCADE,
    FOREIGN KEY (file_path) REFERENCES files(path)
);

CREATE TABLE IF NOT EXISTS symbol_references (
    symbol_identity TEXT NOT NULL,
    file_path TEXT NOT NULL,
    start_line INTEGER NOT NULL,
    start_column INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    end_column INTEGER NOT NULL,
    PRIMARY KEY (
        symbol_identity,
        file_path,
        start_line,
        start_column,
        end_line,
        end_column
    ),
    FOREIGN KEY (symbol_identity) REFERENCES symbols(identity) ON DELETE CASCADE,
    FOREIGN KEY (file_path) REFERENCES files(path)
);

CREATE TABLE IF NOT EXISTS symbol_relations (
    source_identity TEXT NOT NULL,
    relation_kind TEXT NOT NULL CHECK (relation_kind IN ('caller', 'callee')),
    target_identity TEXT NOT NULL,
    PRIMARY KEY (source_identity, relation_kind, target_identity),
    FOREIGN KEY (source_identity) REFERENCES symbols(identity) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS symbols_by_display_name
    ON symbols(display_name, qualified_name, identity);
CREATE INDEX IF NOT EXISTS symbols_by_qualified_name
    ON symbols(qualified_name, identity);
CREATE INDEX IF NOT EXISTS symbol_ranges_by_file
    ON symbol_ranges(file_path, symbol_identity);
CREATE INDEX IF NOT EXISTS symbol_references_by_identity
    ON symbol_references(symbol_identity, file_path, start_line, start_column);
CREATE INDEX IF NOT EXISTS symbol_relations_by_source
    ON symbol_relations(source_identity, relation_kind, target_identity);
"""


class SQLiteSymbolStorage:
    """Store primitive index records without exposing SQLite to index users."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        try:
            database_path.parent.mkdir(parents=True, exist_ok=True)
            self._connection = sqlite3.connect(database_path)
            self._connection.row_factory = sqlite3.Row
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._connection.executescript(_SCHEMA)
            self._connection.execute(
                "INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)",
                ("schema_version", str(SCHEMA_VERSION)),
            )
            self._connection.commit()
        except (OSError, sqlite3.Error) as exc:
            raise SQLiteSymbolStorageError(
                f"Unable to open symbol index database: {database_path}"
            ) from exc

    def replace_all(
        self,
        *,
        files: Sequence[tuple[str]],
        symbols: Sequence[tuple[str, str, str, str, str | None, str | None]],
        ranges: Sequence[tuple[str, str, str, int, int, int, int]],
        references: Sequence[tuple[str, str, int, int, int, int]],
        relations: Sequence[tuple[str, str, str]],
    ) -> None:
        try:
            with self._connection:
                self._connection.execute("DELETE FROM symbol_relations")
                self._connection.execute("DELETE FROM symbol_references")
                self._connection.execute("DELETE FROM symbol_ranges")
                self._connection.execute("DELETE FROM symbols")
                self._connection.execute("DELETE FROM files")
                self._connection.executemany(
                    "INSERT INTO files(path) VALUES (?)", files
                )
                self._connection.executemany(
                    """
                    INSERT INTO symbols(
                        identity,
                        kind,
                        display_name,
                        qualified_name,
                        parent_identity,
                        namespace_identity
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    symbols,
                )
                self._connection.executemany(
                    """
                    INSERT INTO symbol_ranges(
                        symbol_identity,
                        role,
                        file_path,
                        start_line,
                        start_column,
                        end_line,
                        end_column
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    ranges,
                )
                self._connection.executemany(
                    """
                    INSERT INTO symbol_references(
                        symbol_identity,
                        file_path,
                        start_line,
                        start_column,
                        end_line,
                        end_column
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    references,
                )
                self._connection.executemany(
                    """
                    INSERT INTO symbol_relations(
                        source_identity,
                        relation_kind,
                        target_identity
                    ) VALUES (?, ?, ?)
                    """,
                    relations,
                )
        except sqlite3.Error as exc:
            raise SQLiteSymbolStorageError("Unable to rebuild symbol index.") from exc

    def symbol(self, identity: str) -> sqlite3.Row | None:
        rows = self._query(
            "SELECT * FROM symbols WHERE identity = ?",
            (identity,),
        )
        return rows[0] if rows else None

    def symbols_by_name(self, display_name: str) -> tuple[sqlite3.Row, ...]:
        return self._query(
            """
            SELECT * FROM symbols
            WHERE display_name = ?
            ORDER BY qualified_name, kind, identity
            """,
            (display_name,),
        )

    def symbols_by_qualified_name(
        self, qualified_name: str
    ) -> tuple[sqlite3.Row, ...]:
        return self._query(
            """
            SELECT * FROM symbols
            WHERE qualified_name = ?
            ORDER BY display_name, kind, identity
            """,
            (qualified_name,),
        )

    def symbols_in_file(self, file_path: str) -> tuple[sqlite3.Row, ...]:
        return self._query(
            """
            SELECT DISTINCT symbols.*
            FROM symbols
            JOIN symbol_ranges
              ON symbol_ranges.symbol_identity = symbols.identity
            WHERE symbol_ranges.file_path = ?
            ORDER BY symbols.qualified_name, symbols.kind, symbols.identity
            """,
            (file_path,),
        )

    def files(self) -> tuple[sqlite3.Row, ...]:
        return self._query("SELECT path FROM files ORDER BY path")

    def ranges(self, identity: str) -> tuple[sqlite3.Row, ...]:
        return self._query(
            """
            SELECT role, file_path, start_line, start_column, end_line, end_column
            FROM symbol_ranges
            WHERE symbol_identity = ?
            ORDER BY role
            """,
            (identity,),
        )

    def references(self, identity: str) -> tuple[sqlite3.Row, ...]:
        return self._query(
            """
            SELECT file_path, start_line, start_column, end_line, end_column
            FROM symbol_references
            WHERE symbol_identity = ?
            ORDER BY file_path, start_line, start_column, end_line, end_column
            """,
            (identity,),
        )

    def relations(self, identity: str) -> tuple[sqlite3.Row, ...]:
        return self._query(
            """
            SELECT relation_kind, target_identity
            FROM symbol_relations
            WHERE source_identity = ?
            ORDER BY relation_kind, target_identity
            """,
            (identity,),
        )

    def close(self) -> None:
        try:
            self._connection.close()
        except sqlite3.Error as exc:
            raise SQLiteSymbolStorageError("Unable to close symbol index.") from exc

    def _query(
        self, statement: str, parameters: Iterable[object] = ()
    ) -> tuple[sqlite3.Row, ...]:
        try:
            return tuple(self._connection.execute(statement, tuple(parameters)))
        except sqlite3.Error as exc:
            raise SQLiteSymbolStorageError("Unable to query symbol index.") from exc
