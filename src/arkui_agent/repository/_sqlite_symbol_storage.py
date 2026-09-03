"""SQLite persistence details for the backend-agnostic symbol index."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Sequence
from pathlib import Path


SCHEMA_VERSION = 3


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

CREATE TABLE IF NOT EXISTS test_entities (
    identity TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('fixture', 'case')),
    display_name TEXT NOT NULL,
    file_path TEXT NOT NULL,
    start_line INTEGER NOT NULL,
    start_column INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    end_column INTEGER NOT NULL,
    FOREIGN KEY (file_path) REFERENCES files(path)
);

CREATE TABLE IF NOT EXISTS test_fixture_cases (
    fixture_identity TEXT NOT NULL,
    case_identity TEXT PRIMARY KEY,
    FOREIGN KEY (fixture_identity) REFERENCES test_entities(identity) ON DELETE CASCADE,
    FOREIGN KEY (case_identity) REFERENCES test_entities(identity) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS test_case_bodies (
    case_identity TEXT PRIMARY KEY,
    file_path TEXT NOT NULL,
    start_line INTEGER NOT NULL,
    start_column INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    end_column INTEGER NOT NULL,
    FOREIGN KEY (case_identity) REFERENCES test_entities(identity) ON DELETE CASCADE,
    FOREIGN KEY (file_path) REFERENCES files(path)
);

CREATE TABLE IF NOT EXISTS test_symbol_references (
    case_identity TEXT NOT NULL,
    symbol_identity TEXT NOT NULL,
    file_path TEXT NOT NULL,
    start_line INTEGER NOT NULL,
    start_column INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    end_column INTEGER NOT NULL,
    PRIMARY KEY (
        case_identity,
        symbol_identity,
        file_path,
        start_line,
        start_column,
        end_line,
        end_column
    ),
    FOREIGN KEY (case_identity) REFERENCES test_entities(identity) ON DELETE CASCADE,
    FOREIGN KEY (symbol_identity) REFERENCES symbols(identity) ON DELETE CASCADE,
    FOREIGN KEY (file_path) REFERENCES files(path)
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
CREATE INDEX IF NOT EXISTS test_entities_by_kind_name
    ON test_entities(kind, display_name, file_path, start_line, start_column, identity);
CREATE INDEX IF NOT EXISTS test_fixture_cases_by_fixture
    ON test_fixture_cases(fixture_identity, case_identity);
CREATE INDEX IF NOT EXISTS test_symbol_references_by_case
    ON test_symbol_references(
        case_identity, symbol_identity, file_path, start_line, start_column
    );
CREATE INDEX IF NOT EXISTS test_symbol_references_by_symbol
    ON test_symbol_references(
        symbol_identity, case_identity, file_path, start_line, start_column
    );
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
        test_entities: Sequence[
            tuple[str, str, str, str, int, int, int, int]
        ],
        fixture_cases: Sequence[tuple[str, str]],
        test_case_bodies: Sequence[tuple[str, str, int, int, int, int]],
        test_symbol_references: Sequence[
            tuple[str, str, str, int, int, int, int]
        ],
    ) -> None:
        try:
            with self._connection:
                self._connection.execute("DELETE FROM test_symbol_references")
                self._connection.execute("DELETE FROM test_case_bodies")
                self._connection.execute("DELETE FROM test_fixture_cases")
                self._connection.execute("DELETE FROM test_entities")
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
                self._connection.executemany(
                    """
                    INSERT INTO test_entities(
                        identity,
                        kind,
                        display_name,
                        file_path,
                        start_line,
                        start_column,
                        end_line,
                        end_column
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    test_entities,
                )
                self._connection.executemany(
                    """
                    INSERT INTO test_fixture_cases(fixture_identity, case_identity)
                    VALUES (?, ?)
                    """,
                    fixture_cases,
                )
                self._connection.executemany(
                    """
                    INSERT INTO test_case_bodies(
                        case_identity,
                        file_path,
                        start_line,
                        start_column,
                        end_line,
                        end_column
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    test_case_bodies,
                )
                self._connection.executemany(
                    """
                    INSERT INTO test_symbol_references(
                        case_identity,
                        symbol_identity,
                        file_path,
                        start_line,
                        start_column,
                        end_line,
                        end_column
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    test_symbol_references,
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

    def test_entity(self, identity: str, kind: str) -> sqlite3.Row | None:
        rows = self._query(
            "SELECT * FROM test_entities WHERE identity = ? AND kind = ?",
            (identity, kind),
        )
        return rows[0] if rows else None

    def test_entities_by_name(
        self, kind: str, display_name: str
    ) -> tuple[sqlite3.Row, ...]:
        return self._query(
            """
            SELECT * FROM test_entities
            WHERE kind = ? AND display_name = ?
            ORDER BY file_path, start_line, start_column, identity
            """,
            (kind, display_name),
        )

    def test_case(self, identity: str) -> sqlite3.Row | None:
        rows = self._query(
            """
            SELECT
                test_entities.*,
                test_fixture_cases.fixture_identity,
                test_case_bodies.file_path AS body_file_path,
                test_case_bodies.start_line AS body_start_line,
                test_case_bodies.start_column AS body_start_column,
                test_case_bodies.end_line AS body_end_line,
                test_case_bodies.end_column AS body_end_column
            FROM test_entities
            JOIN test_fixture_cases
              ON test_fixture_cases.case_identity = test_entities.identity
            LEFT JOIN test_case_bodies
              ON test_case_bodies.case_identity = test_entities.identity
            WHERE test_entities.identity = ? AND test_entities.kind = 'case'
            """,
            (identity,),
        )
        return rows[0] if rows else None

    def test_cases_by_name(self, display_name: str) -> tuple[sqlite3.Row, ...]:
        return self._query(
            """
            SELECT
                test_entities.*,
                test_fixture_cases.fixture_identity,
                test_case_bodies.file_path AS body_file_path,
                test_case_bodies.start_line AS body_start_line,
                test_case_bodies.start_column AS body_start_column,
                test_case_bodies.end_line AS body_end_line,
                test_case_bodies.end_column AS body_end_column
            FROM test_entities
            JOIN test_fixture_cases
              ON test_fixture_cases.case_identity = test_entities.identity
            LEFT JOIN test_case_bodies
              ON test_case_bodies.case_identity = test_entities.identity
            WHERE test_entities.kind = 'case' AND test_entities.display_name = ?
            ORDER BY
                test_entities.file_path,
                test_entities.start_line,
                test_entities.start_column,
                test_entities.identity
            """,
            (display_name,),
        )

    def test_cases_for_fixture(
        self, fixture_identity: str
    ) -> tuple[sqlite3.Row, ...]:
        return self._query(
            """
            SELECT
                test_entities.*,
                test_fixture_cases.fixture_identity,
                test_case_bodies.file_path AS body_file_path,
                test_case_bodies.start_line AS body_start_line,
                test_case_bodies.start_column AS body_start_column,
                test_case_bodies.end_line AS body_end_line,
                test_case_bodies.end_column AS body_end_column
            FROM test_fixture_cases
            JOIN test_entities
              ON test_entities.identity = test_fixture_cases.case_identity
            LEFT JOIN test_case_bodies
              ON test_case_bodies.case_identity = test_entities.identity
            WHERE test_fixture_cases.fixture_identity = ?
            ORDER BY
                test_entities.file_path,
                test_entities.start_line,
                test_entities.start_column,
                test_entities.identity
            """,
            (fixture_identity,),
        )

    def directly_referenced_symbols(
        self, case_identity: str
    ) -> tuple[sqlite3.Row, ...]:
        return self._query(
            """
            SELECT DISTINCT symbols.*
            FROM test_symbol_references
            JOIN symbols
              ON symbols.identity = test_symbol_references.symbol_identity
            WHERE test_symbol_references.case_identity = ?
            ORDER BY symbols.identity
            """,
            (case_identity,),
        )

    def test_cases_for_symbol(
        self, symbol_identity: str
    ) -> tuple[sqlite3.Row, ...]:
        return self._query(
            """
            SELECT DISTINCT
                test_entities.*,
                test_fixture_cases.fixture_identity,
                test_case_bodies.file_path AS body_file_path,
                test_case_bodies.start_line AS body_start_line,
                test_case_bodies.start_column AS body_start_column,
                test_case_bodies.end_line AS body_end_line,
                test_case_bodies.end_column AS body_end_column
            FROM test_symbol_references
            JOIN test_entities
              ON test_entities.identity = test_symbol_references.case_identity
            JOIN test_fixture_cases
              ON test_fixture_cases.case_identity = test_entities.identity
            LEFT JOIN test_case_bodies
              ON test_case_bodies.case_identity = test_entities.identity
            WHERE test_symbol_references.symbol_identity = ?
            ORDER BY
                test_entities.file_path,
                test_entities.start_line,
                test_entities.start_column,
                test_entities.identity
            """,
            (symbol_identity,),
        )

    def test_symbol_references(
        self, case_identity: str, symbol_identity: str
    ) -> tuple[sqlite3.Row, ...]:
        return self._query(
            """
            SELECT file_path, start_line, start_column, end_line, end_column
            FROM test_symbol_references
            WHERE case_identity = ? AND symbol_identity = ?
            ORDER BY file_path, start_line, start_column, end_line, end_column
            """,
            (case_identity, symbol_identity),
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
