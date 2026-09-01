"""Safe, read-only access to an explicitly configured repository root."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final


ARKUI_REPO_ROOT: Final = "ARKUI_REPO_ROOT"


class RepositoryWorkspaceError(ValueError):
    """Base error for repository workspace configuration and paths."""


class RepositoryConfigurationError(RepositoryWorkspaceError):
    """Raised when required repository configuration is unavailable."""


class RepositoryRootError(RepositoryWorkspaceError):
    """Raised when a configured repository root is invalid."""


class RepositoryPathError(RepositoryWorkspaceError):
    """Raised when a repository-relative path violates the root boundary."""


@dataclass(frozen=True, slots=True, init=False)
class RepositoryWorkspace:
    """A validated, read-only boundary around an external repository.

    Construction validates and normalizes the repository root. The workspace
    only resolves paths; it intentionally exposes no file mutation API.
    """

    root: Path
    read_only: bool = field(default=True, init=False)

    def __init__(self, repository_root: str | os.PathLike[str]) -> None:
        object.__setattr__(self, "root", _validate_repository_root(repository_root))
        object.__setattr__(self, "read_only", True)

    @classmethod
    def from_environment(cls) -> RepositoryWorkspace:
        """Create a workspace from ``ARKUI_REPO_ROOT`` when explicitly called."""

        repository_root = os.environ.get(ARKUI_REPO_ROOT)
        if repository_root is None:
            raise RepositoryConfigurationError(
                f"Environment variable {ARKUI_REPO_ROOT} is not set."
            )
        if not repository_root.strip():
            raise RepositoryConfigurationError(
                f"Environment variable {ARKUI_REPO_ROOT} is empty."
            )
        return cls(repository_root)

    def resolve(self, relative_path: str | os.PathLike[str]) -> Path:
        """Resolve a repository-relative path without allowing root escape."""

        path = Path(relative_path)
        if path.anchor:
            raise RepositoryPathError(
                f"Repository path must be relative, got: {relative_path!s}"
            )

        try:
            resolved = (self.root / path).resolve(strict=False)
        except (OSError, RuntimeError) as exc:
            raise RepositoryPathError(
                f"Repository path cannot be resolved: {relative_path!s}"
            ) from exc

        try:
            resolved.relative_to(self.root)
        except ValueError as exc:
            raise RepositoryPathError(
                f"Repository path escapes root: {relative_path!s}"
            ) from exc
        return resolved


def _validate_repository_root(repository_root: str | os.PathLike[str]) -> Path:
    if isinstance(repository_root, str) and not repository_root.strip():
        raise RepositoryRootError("Repository root must not be empty.")

    path = Path(repository_root).expanduser()
    try:
        resolved = path.resolve(strict=True)
    except FileNotFoundError as exc:
        raise RepositoryRootError(
            f"Repository root does not exist: {repository_root!s}"
        ) from exc
    except (OSError, RuntimeError) as exc:
        raise RepositoryRootError(
            f"Repository root cannot be resolved: {repository_root!s}"
        ) from exc

    if not resolved.is_dir():
        raise RepositoryRootError(
            f"Repository root is not a directory: {repository_root!s}"
        )
    return resolved

