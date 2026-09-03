"""Backend-agnostic repository and symbol data contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import PurePath, PurePosixPath, PureWindowsPath


@dataclass(frozen=True, slots=True)
class RepositoryFile:
    """Identity of one file as a canonical repository-relative POSIX path."""

    path: PurePosixPath

    def __post_init__(self) -> None:
        if not isinstance(self.path, PurePosixPath):
            raise TypeError("RepositoryFile.path must be a PurePosixPath.")
        _validate_repository_relative_path(self.path)

    @classmethod
    def from_path(cls, path: str | PurePath) -> RepositoryFile:
        """Create a file identity from an already repository-relative path."""

        raw_path = path.as_posix() if isinstance(path, PurePath) else path
        if "\\" in raw_path:
            raise ValueError("Repository file path must use POSIX separators.")
        if PureWindowsPath(raw_path).anchor:
            raise ValueError("Repository file path must be relative.")
        canonical_path = PurePosixPath(raw_path)
        if canonical_path.as_posix() != raw_path:
            raise ValueError(f"Repository file path is not canonical: {raw_path}")
        return cls(canonical_path)

    def to_dict(self) -> dict[str, object]:
        return {"path": self.path.as_posix()}


@dataclass(frozen=True, slots=True)
class SourceLocation:
    """A 1-based line and column within a repository file."""

    file: RepositoryFile
    line: int
    column: int

    def __post_init__(self) -> None:
        if self.line < 1:
            raise ValueError("SourceLocation.line must be at least 1.")
        if self.column < 1:
            raise ValueError("SourceLocation.column must be at least 1.")

    def to_dict(self) -> dict[str, object]:
        return {
            "file": self.file.path.as_posix(),
            "line": self.line,
            "column": self.column,
        }


@dataclass(frozen=True, slots=True)
class SourceRange:
    """A half-open source range ``[start, end)`` within one file."""

    start: SourceLocation
    end: SourceLocation

    def __post_init__(self) -> None:
        if self.start.file != self.end.file:
            raise ValueError("SourceRange endpoints must be in the same file.")
        if (self.end.line, self.end.column) < (self.start.line, self.start.column):
            raise ValueError("SourceRange.end must not precede SourceRange.start.")

    @property
    def file(self) -> RepositoryFile:
        return self.start.file

    def to_dict(self) -> dict[str, object]:
        return {"start": self.start.to_dict(), "end": self.end.to_dict()}


@dataclass(frozen=True, slots=True)
class SymbolIdentity:
    """Opaque stable identity supplied by a semantic backend or persistence layer."""

    value: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            raise ValueError("SymbolIdentity.value must not be empty.")


class SymbolKind(str, Enum):
    NAMESPACE = "namespace"
    CLASS = "class"
    STRUCT = "struct"
    FUNCTION = "function"
    METHOD = "method"
    FIELD = "field"
    ENUM = "enum"
    TEST_FIXTURE = "test_fixture"
    TEST_CASE = "test_case"


@dataclass(frozen=True, slots=True)
class Symbol:
    """Minimal identity, naming, containment, and source facts for one symbol."""

    identity: SymbolIdentity
    kind: SymbolKind
    display_name: str
    qualified_name: str
    declaration: SourceRange | None = None
    definition: SourceRange | None = None
    parent_identity: SymbolIdentity | None = None
    namespace_identity: SymbolIdentity | None = None

    def __post_init__(self) -> None:
        if not self.display_name:
            raise ValueError("Symbol.display_name must not be empty.")
        if not self.qualified_name:
            raise ValueError("Symbol.qualified_name must not be empty.")
        if self.declaration is None and self.definition is None:
            raise ValueError("Symbol requires a declaration or definition range.")

    def to_dict(self) -> dict[str, object]:
        return {
            "identity": self.identity.value,
            "kind": self.kind.value,
            "display_name": self.display_name,
            "qualified_name": self.qualified_name,
            "declaration": (
                None if self.declaration is None else self.declaration.to_dict()
            ),
            "definition": (
                None if self.definition is None else self.definition.to_dict()
            ),
            "parent_identity": (
                None if self.parent_identity is None else self.parent_identity.value
            ),
            "namespace_identity": (
                None
                if self.namespace_identity is None
                else self.namespace_identity.value
            ),
        }


@dataclass(frozen=True, slots=True)
class TestFixture:
    """A discovered repository test fixture independent of recognition syntax."""

    identity: SymbolIdentity
    display_name: str
    source_range: SourceRange

    def __post_init__(self) -> None:
        if not self.display_name:
            raise ValueError("TestFixture.display_name must not be empty.")

    def to_dict(self) -> dict[str, object]:
        return {
            "identity": self.identity.value,
            "display_name": self.display_name,
            "source_range": self.source_range.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class TestCase:
    """A discovered test case attached to one exact fixture identity."""

    identity: SymbolIdentity
    display_name: str
    fixture_identity: SymbolIdentity
    source_range: SourceRange

    def __post_init__(self) -> None:
        if not self.display_name:
            raise ValueError("TestCase.display_name must not be empty.")
        if self.identity == self.fixture_identity:
            raise ValueError("TestCase identity must differ from fixture identity.")

    def to_dict(self) -> dict[str, object]:
        return {
            "identity": self.identity.value,
            "display_name": self.display_name,
            "fixture_identity": self.fixture_identity.value,
            "source_range": self.source_range.to_dict(),
        }


def _validate_repository_relative_path(path: PurePosixPath) -> None:
    if path.as_posix() in {"", "."}:
        raise ValueError("Repository file path must identify a file.")
    if "\\" in path.as_posix():
        raise ValueError("Repository file path must use POSIX separators.")
    if path.is_absolute() or PureWindowsPath(path.as_posix()).anchor:
        raise ValueError("Repository file path must be relative.")
    if ".." in path.parts:
        raise ValueError("Repository file path must not traverse outside the root.")
