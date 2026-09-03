"""Private ripgrep adapter for repository text search."""

from __future__ import annotations

import base64
import binascii
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from arkui_agent.repository.model import (
    RepositoryFile,
    SourceLocation,
    SourceRange,
)
from arkui_agent.repository.text_search import (
    TextSearchBackendError,
    TextSearchMode,
    TextSearchQuery,
    TextSearchResult,
    TextSearchToolUnavailableError,
)
from arkui_agent.repository.workspace import RepositoryPathError, RepositoryWorkspace


SEARCH_TIMEOUT_SECONDS = 60


class RipgrepTextSearchBackend:
    """Translate the public text-search contract to ripgrep JSON output."""

    def __init__(self, workspace: RepositoryWorkspace, executable: str = "rg") -> None:
        resolved = shutil.which(executable)
        if resolved is None:
            raise TextSearchToolUnavailableError(
                f"Repository text-search tool is unavailable: {executable!r}."
            )
        self._workspace = workspace
        self._executable = resolved

    def search(
        self, query: TextSearchQuery, scope: Path
    ) -> tuple[TextSearchResult, ...]:
        command = [self._executable, "--json"]
        command.append("--case-sensitive" if query.case_sensitive else "--ignore-case")
        if query.mode is TextSearchMode.EXACT:
            command.append("--fixed-strings")
        relative_scope = scope.relative_to(self._workspace.root).as_posix() or "."
        command.extend(("--", query.text, relative_scope))

        try:
            completed = subprocess.run(
                command,
                cwd=self._workspace.root,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=SEARCH_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise TextSearchBackendError(
                "Repository text-search backend could not be executed."
            ) from exc

        if completed.returncode == 1:
            return ()
        if completed.returncode != 0:
            detail = completed.stderr.decode("utf-8", errors="replace").strip()
            message = "Repository text-search backend failed."
            if detail:
                message = f"{message} {detail}"
            raise TextSearchBackendError(message)
        return self._parse_output(completed.stdout)

    def _parse_output(self, output: bytes) -> tuple[TextSearchResult, ...]:
        results: list[TextSearchResult] = []
        try:
            lines = output.decode("utf-8").splitlines()
            for encoded_event in lines:
                event = json.loads(encoded_event)
                if event.get("type") != "match":
                    continue
                data = event["data"]
                file = self._repository_file(_json_text(data["path"]))
                line_number = int(data["line_number"])
                line_bytes = _json_bytes(data["lines"])
                line_text = line_bytes.decode("utf-8").rstrip("\r\n")
                for submatch in data["submatches"]:
                    start = int(submatch["start"])
                    end = int(submatch["end"])
                    matched_text = _json_bytes(submatch["match"]).decode("utf-8")
                    results.append(
                        TextSearchResult(
                            source_range=SourceRange(
                                SourceLocation(
                                    file,
                                    line_number,
                                    _character_column(line_bytes, start),
                                ),
                                SourceLocation(
                                    file,
                                    line_number,
                                    _character_column(line_bytes, end),
                                ),
                            ),
                            matched_text=matched_text,
                            line_text=line_text,
                        )
                    )
        except (KeyError, TypeError, ValueError, UnicodeError, json.JSONDecodeError) as exc:
            raise TextSearchBackendError(
                "Repository text-search backend returned invalid output."
            ) from exc
        return tuple(results)

    def _repository_file(self, path_text: str) -> RepositoryFile:
        candidate = Path(path_text)
        absolute = candidate if candidate.is_absolute() else self._workspace.root / candidate
        try:
            resolved = absolute.resolve(strict=True)
            relative = resolved.relative_to(self._workspace.root)
        except (OSError, RuntimeError, ValueError) as exc:
            raise RepositoryPathError(
                f"Text-search result escapes repository root: {path_text!r}."
            ) from exc
        return RepositoryFile.from_path(relative.as_posix())


def _json_text(value: Any) -> str:
    return _json_bytes(value).decode("utf-8")


def _json_bytes(value: Any) -> bytes:
    if not isinstance(value, dict):
        raise ValueError("ripgrep JSON text field is missing")
    text = value.get("text")
    if isinstance(text, str):
        return text.encode("utf-8")
    encoded = value.get("bytes")
    if isinstance(encoded, str):
        try:
            return base64.b64decode(encoded, validate=True)
        except binascii.Error as exc:
            raise ValueError("ripgrep JSON byte field is invalid") from exc
    raise ValueError("ripgrep JSON text field is missing")


def _character_column(line: bytes, byte_offset: int) -> int:
    if byte_offset < 0 or byte_offset > len(line):
        raise ValueError("ripgrep byte offset is outside its source line")
    return len(line[:byte_offset].decode("utf-8")) + 1
