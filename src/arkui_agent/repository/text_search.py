"""Backend-neutral repository text search contracts and facade."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Protocol

from arkui_agent.repository.model import RepositoryFile, SourceRange
from arkui_agent.repository.workspace import (
    RepositoryPathError,
    RepositoryWorkspace,
)


class TextSearchMode(str, Enum):
    EXACT = "exact"
    REGEX = "regex"


class RepositoryTextSearchError(RuntimeError):
    """Base failure boundary for repository text search."""


class TextSearchQueryError(ValueError):
    """Raised when a search request is invalid."""


class TextSearchToolUnavailableError(RepositoryTextSearchError):
    """Raised when no configured text-search backend can be started."""


class TextSearchBackendError(RepositoryTextSearchError):
    """Raised when the selected text-search backend fails."""


@dataclass(frozen=True, slots=True)
class TextSearchQuery:
    """A repository-relative text query independent of backend commands.

    ``file_globs`` are inclusive patterns matched against canonical
    repository-relative POSIX paths. ``limit`` selects the prefix of the
    globally sorted, filtered result set rather than a per-file limit.
    """

    text: str
    mode: TextSearchMode = TextSearchMode.EXACT
    case_sensitive: bool = True
    path_scope: str = "."
    file_globs: tuple[str, ...] = ()
    limit: int | None = None

    def __post_init__(self) -> None:
        if not self.text:
            raise TextSearchQueryError("Search text must not be empty.")
        if "\n" in self.text or "\r" in self.text:
            raise TextSearchQueryError("Search text must be single-line.")
        if not isinstance(self.mode, TextSearchMode):
            raise TypeError("TextSearchQuery.mode must be a TextSearchMode.")
        if not isinstance(self.case_sensitive, bool):
            raise TypeError("TextSearchQuery.case_sensitive must be a bool.")
        if not isinstance(self.file_globs, tuple):
            raise TypeError("TextSearchQuery.file_globs must be a tuple.")
        _validate_repository_expression(self.path_scope, allow_root=True)
        for pattern in self.file_globs:
            _validate_repository_expression(pattern, allow_root=False)
        if self.limit is not None and (
            isinstance(self.limit, bool) or self.limit < 1
        ):
            raise TextSearchQueryError("Search result limit must be positive.")


@dataclass(frozen=True, slots=True)
class TextSearchResult:
    """One textual match with exact repository source provenance."""

    source_range: SourceRange
    matched_text: str
    line_text: str

    @property
    def file(self) -> RepositoryFile:
        return self.source_range.file

    @property
    def line(self) -> int:
        return self.source_range.start.line

    @property
    def column(self) -> int:
        return self.source_range.start.column

    def to_dict(self) -> dict[str, object]:
        return {
            "source_range": self.source_range.to_dict(),
            "matched_text": self.matched_text,
            "line_text": self.line_text,
        }


class _TextSearchBackend(Protocol):
    def search(self, query: TextSearchQuery, scope: Path) -> tuple[TextSearchResult, ...]:
        """Return backend matches before public filtering and limiting."""


class RepositoryTextSearch:
    """Repository-bound text search with a replaceable private backend."""

    def __init__(self, workspace: RepositoryWorkspace) -> None:
        from arkui_agent.repository._ripgrep_text_search import RipgrepTextSearchBackend

        self._workspace = workspace
        self._backend: _TextSearchBackend = RipgrepTextSearchBackend(workspace)

    def search(self, query: TextSearchQuery) -> tuple[TextSearchResult, ...]:
        """Return deterministic matches, applying the global limit after sorting."""

        scope = self._workspace.resolve(query.path_scope)
        if not scope.exists():
            raise TextSearchQueryError(
                f"Search path scope does not exist: {query.path_scope!r}."
            )
        if not scope.is_file() and not scope.is_dir():
            raise TextSearchQueryError(
                f"Search path scope is not a file or directory: {query.path_scope!r}."
            )

        matches = self._backend.search(query, scope)
        filtered = {
            result
            for result in matches
            if not query.file_globs
            or any(result.file.path.match(pattern) for pattern in query.file_globs)
        }
        ordered = tuple(sorted(filtered, key=_result_sort_key))
        return ordered if query.limit is None else ordered[: query.limit]


def _validate_repository_expression(value: str, *, allow_root: bool) -> None:
    if not isinstance(value, str):
        raise TypeError("Repository path/filter expressions must be strings.")
    if not value or "\\" in value:
        raise RepositoryPathError(
            "Repository path/filter expressions must be non-empty POSIX paths."
        )
    if PureWindowsPath(value).anchor:
        raise RepositoryPathError("Repository path/filter must be relative.")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise RepositoryPathError("Repository path/filter must stay within root.")
    if value == "." and allow_root:
        return
    if path.as_posix() != value or path.as_posix() == ".":
        raise RepositoryPathError(
            f"Repository path/filter is not canonical: {value!r}."
        )


def _result_sort_key(result: TextSearchResult) -> tuple[object, ...]:
    source_range = result.source_range
    return (
        result.file.path.as_posix(),
        source_range.start.line,
        source_range.start.column,
        source_range.end.line,
        source_range.end.column,
        result.matched_text,
    )
