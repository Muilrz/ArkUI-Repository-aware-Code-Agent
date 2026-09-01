"""Deterministic, content-agnostic repository file discovery."""

from __future__ import annotations

import os
from collections.abc import Collection, Iterable
from enum import Enum
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath
from typing import Final

from arkui_agent.repository.model import RepositoryFile
from arkui_agent.repository.workspace import (
    RepositoryPathError,
    RepositoryWorkspace,
)


DEFAULT_EXCLUDED_DIRECTORIES: Final = frozenset(
    {
        ".cache",
        ".git",
        ".hg",
        ".svn",
        "__pycache__",
        "build",
        "dist",
        "gen",
        "generated",
        "node_modules",
        "out",
        "target",
        "var",
    }
)

_SOURCE_EXTENSIONS: Final = frozenset({".c", ".cc", ".cpp", ".cxx", ".m", ".mm"})
_HEADER_EXTENSIONS: Final = frozenset({".h", ".hh", ".hpp", ".hxx", ".inc"})
_TEST_DIRECTORY_NAMES: Final = frozenset({"test", "tests"})


class RepositoryFileType(str, Enum):
    """Minimal scanner-level file classification, not a semantic file model."""

    SOURCE = "source"
    HEADER = "header"
    TEST = "test"
    OTHER = "other"


def classify_repository_path(path: PurePosixPath) -> RepositoryFileType:
    """Classify a path from its name and extension without reading the file."""

    extension = path.suffix.casefold()
    if extension not in _SOURCE_EXTENSIONS | _HEADER_EXTENSIONS:
        return RepositoryFileType.OTHER

    parent_names = {part.casefold() for part in path.parts[:-1]}
    stem = path.stem.casefold()
    if (
        parent_names & _TEST_DIRECTORY_NAMES
        or stem.startswith("test_")
        or stem.endswith(("_test", "_unittest"))
    ):
        return RepositoryFileType.TEST
    if extension in _HEADER_EXTENSIONS:
        return RepositoryFileType.HEADER
    return RepositoryFileType.SOURCE


class RepositoryScanner:
    """Recursively discover files contained by a ``RepositoryWorkspace``."""

    def __init__(
        self,
        workspace: RepositoryWorkspace,
        *,
        excluded_directories: Collection[str] = DEFAULT_EXCLUDED_DIRECTORIES,
    ) -> None:
        self._workspace = workspace
        self._excluded_directories = frozenset(
            name.casefold() for name in excluded_directories
        )

    def scan(
        self,
        *,
        include_patterns: Iterable[str] = (),
        exclude_patterns: Iterable[str] = (),
        file_types: Collection[RepositoryFileType] | None = None,
    ) -> tuple[RepositoryFile, ...]:
        """Return sorted canonical paths matching the requested filters.

        Glob patterns are matched against the complete repository-relative
        POSIX path. Symbolic links are not followed or returned.
        """

        includes = tuple(include_patterns)
        excludes = tuple(exclude_patterns)
        selected_types = None if file_types is None else frozenset(file_types)
        discovered: list[RepositoryFile] = []

        for directory, directory_names, file_names in os.walk(
            self._workspace.root,
            topdown=True,
            onerror=_raise_scan_error,
            followlinks=False,
        ):
            directory_path = Path(directory)
            directory_names[:] = [
                name
                for name in sorted(directory_names)
                if self._should_descend(directory_path / name)
            ]

            for file_name in sorted(file_names):
                absolute_path = directory_path / file_name
                if absolute_path.is_symlink():
                    continue

                relative_path = absolute_path.relative_to(self._workspace.root)
                try:
                    resolved_path = self._workspace.resolve(relative_path)
                except RepositoryPathError:
                    continue
                if not resolved_path.is_file():
                    continue

                canonical_path = PurePosixPath(relative_path.as_posix())
                canonical_text = canonical_path.as_posix()
                if includes and not any(
                    fnmatchcase(canonical_text, pattern) for pattern in includes
                ):
                    continue
                if any(
                    fnmatchcase(canonical_text, pattern) for pattern in excludes
                ):
                    continue
                if (
                    selected_types is not None
                    and classify_repository_path(canonical_path) not in selected_types
                ):
                    continue
                discovered.append(RepositoryFile(canonical_path))

        return tuple(sorted(discovered, key=lambda file: file.path.as_posix()))

    def _should_descend(self, directory: Path) -> bool:
        if directory.name.casefold() in self._excluded_directories:
            return False
        if directory.is_symlink():
            return False

        relative_path = directory.relative_to(self._workspace.root)
        try:
            resolved_path = self._workspace.resolve(relative_path)
        except RepositoryPathError:
            return False
        return resolved_path.is_dir()


def _raise_scan_error(error: OSError) -> None:
    """Fail the scan rather than returning an incomplete file list."""

    raise error
