"""Reproducibility metadata and revision validation for benchmark runs."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass

from arkui_agent.repository import RepositoryWorkspace


class BenchmarkEnvironmentError(RuntimeError):
    """Raised when required repository or tool metadata cannot be established."""


class BenchmarkRevisionMismatchError(BenchmarkEnvironmentError):
    """Raised before execution when annotations target another checkout revision."""


@dataclass(frozen=True, slots=True)
class ToolVersion:
    name: str
    version: str

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "version": self.version}


@dataclass(frozen=True, slots=True)
class BenchmarkEnvironment:
    repository_revision: str
    tools: tuple[ToolVersion, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "repository_revision": self.repository_revision,
            "tools": [tool.to_dict() for tool in self.tools],
        }


def read_repository_revision(workspace: RepositoryWorkspace) -> str:
    """Read the exact Git commit for an explicitly configured repository root."""

    completed = _run_metadata_command(
        ("git", "-C", os.fspath(workspace.root), "rev-parse", "HEAD"),
        "Git revision",
    )
    revision = completed.stdout.strip()
    if len(revision) != 40 or any(character not in "0123456789abcdef" for character in revision.lower()):
        raise BenchmarkEnvironmentError(
            f"Git returned an invalid repository revision: {revision!r}."
        )
    return revision


def read_tool_version(name: str, executable: str | os.PathLike[str]) -> ToolVersion:
    """Capture the first version line without recording a machine-specific path."""

    executable_path = shutil.which(os.fspath(executable))
    if executable_path is None:
        raise BenchmarkEnvironmentError(
            f"Required benchmark tool is unavailable: {os.fspath(executable)!r}."
        )
    completed = _run_metadata_command((executable_path, "--version"), f"{name} version")
    first_line = next(
        (line.strip() for line in completed.stdout.splitlines() if line.strip()), ""
    )
    if not first_line:
        raise BenchmarkEnvironmentError(f"{name} returned no version information.")
    return ToolVersion(name, first_line)


def validate_repository_revision(expected: str, actual: str) -> None:
    if expected != actual:
        raise BenchmarkRevisionMismatchError(
            "Benchmark repository revision mismatch: "
            f"suite expects {expected}, checkout is {actual}."
        )


def _run_metadata_command(
    command: tuple[str, ...], label: str
) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:
        raise BenchmarkEnvironmentError(f"Unable to read {label}: {exc}") from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip() or f"exit code {completed.returncode}"
        raise BenchmarkEnvironmentError(f"Unable to read {label}: {detail}")
    return completed
