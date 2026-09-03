"""Explicit macro recognition for repository test fixtures and cases."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass

from arkui_agent.repository.model import (
    RepositoryFile,
    SourceLocation,
    SourceRange,
    SymbolIdentity,
    TestCase,
    TestFixture,
)
from arkui_agent.repository.workspace import RepositoryWorkspace


ARKUI_FIXTURE_TEST_MACROS = (
    "HWTEST_F",
    "HWTEST_P",
    "TEST_F",
    "TEST_P",
)


class TestDiscoveryError(RuntimeError):
    """Raised when an explicitly requested test source cannot be inspected."""


@dataclass(frozen=True, slots=True)
class TestDiscovery:
    """Deterministically ordered test entities discovered from repository files."""

    fixtures: tuple[TestFixture, ...]
    cases: tuple[TestCase, ...]


class TestMacroRecognizer:
    """Recognize an explicit allowlist of fixture-style test macros.

    This is deliberately lexical recognition, not C++ semantic resolution.
    A referenced fixture uses the nearest preceding same-name class/struct
    declaration in the file when available. This lexical association avoids
    claiming general C++ inheritance or name resolution. Case identity also
    includes its exact source position.
    """

    def __init__(self, macro_names: Iterable[str] = ARKUI_FIXTURE_TEST_MACROS) -> None:
        names = tuple(sorted(set(macro_names)))
        if not names or any(not _IDENTIFIER.fullmatch(name) for name in names):
            raise ValueError("Test macro names must be non-empty C identifiers.")
        alternatives = "|".join(re.escape(name) for name in names)
        self.macro_names = names
        self._invocation = re.compile(
            rf"(?m)^[ \t]*(?P<macro>{alternatives})[ \t]*\("
            rf"[ \t\r\n]*(?P<fixture>[A-Za-z_]\w*)[ \t\r\n]*,"
            rf"[ \t\r\n]*(?P<case>[A-Za-z_]\w*)"
        )

    def recognize(self, file: RepositoryFile, source: str) -> TestDiscovery:
        """Return fixture/case entities from explicit macro invocations in one file."""

        declarations = _class_declarations(source)
        fixtures: dict[SymbolIdentity, TestFixture] = {}
        cases: list[TestCase] = []
        for match in self._invocation.finditer(source):
            fixture_name = match.group("fixture")
            case_name = match.group("case")
            fixture_range, has_declaration = _fixture_range(
                file,
                source,
                fixture_name,
                match.start(),
                match.span("fixture"),
                declarations,
            )
            case_range = _source_range(file, source, *match.span("case"))
            fixture_identity_parts = [fixture_name]
            if has_declaration:
                fixture_identity_parts.extend(
                    (
                        str(fixture_range.start.line),
                        str(fixture_range.start.column),
                    )
                )
            fixture_identity = _identity("fixture", file, *fixture_identity_parts)
            fixture = fixtures.setdefault(
                fixture_identity,
                TestFixture(
                    identity=fixture_identity,
                    display_name=fixture_name,
                    source_range=fixture_range,
                ),
            )
            cases.append(
                TestCase(
                    identity=_identity(
                        "case",
                        file,
                        fixture_name,
                        case_name,
                        str(case_range.start.line),
                        str(case_range.start.column),
                    ),
                    display_name=case_name,
                    fixture_identity=fixture.identity,
                    source_range=case_range,
                )
            )
        return TestDiscovery(
            fixtures=tuple(sorted(fixtures.values(), key=_fixture_sort_key)),
            cases=tuple(sorted(cases, key=_case_sort_key)),
        )


class RepositoryTestDiscoverer:
    """Read explicit repository files and apply a separate test recognizer."""

    def __init__(
        self,
        workspace: RepositoryWorkspace,
        recognizer: TestMacroRecognizer | None = None,
    ) -> None:
        self._workspace = workspace
        self._recognizer = recognizer or TestMacroRecognizer()

    def discover(self, files: Iterable[RepositoryFile]) -> TestDiscovery:
        fixtures: list[TestFixture] = []
        cases: list[TestCase] = []
        for file in sorted(set(files), key=lambda item: item.path.as_posix()):
            path = self._workspace.resolve(file.path.as_posix())
            try:
                source = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                raise TestDiscoveryError(
                    f"Unable to read test source: {file.path.as_posix()}"
                ) from exc
            discovered = self._recognizer.recognize(file, source)
            fixtures.extend(discovered.fixtures)
            cases.extend(discovered.cases)
        return TestDiscovery(
            fixtures=tuple(sorted(fixtures, key=_fixture_sort_key)),
            cases=tuple(sorted(cases, key=_case_sort_key)),
        )


_IDENTIFIER = re.compile(r"[A-Za-z_]\w*")
_CLASS_DECLARATION = re.compile(
    r"\b(?:class|struct)[ \t\r\n]+(?P<name>[A-Za-z_]\w*)\b"
)


def _class_declarations(source: str) -> dict[str, tuple[tuple[int, int], ...]]:
    declarations: dict[str, list[tuple[int, int]]] = {}
    for match in _CLASS_DECLARATION.finditer(source):
        declarations.setdefault(match.group("name"), []).append(match.span("name"))
    return {name: tuple(spans) for name, spans in declarations.items()}


def _fixture_range(
    file: RepositoryFile,
    source: str,
    fixture_name: str,
    invocation_offset: int,
    fallback_span: tuple[int, int],
    declarations: dict[str, tuple[tuple[int, int], ...]],
) -> tuple[SourceRange, bool]:
    preceding = tuple(
        span
        for span in declarations.get(fixture_name, ())
        if span[0] < invocation_offset
    )
    if preceding:
        return _source_range(file, source, *preceding[-1]), True
    return _source_range(file, source, *fallback_span), False


def _identity(kind: str, file: RepositoryFile, *parts: str) -> SymbolIdentity:
    payload = "\0".join((kind, file.path.as_posix(), *parts)).encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    return SymbolIdentity(f"test-entity:{digest}")


def _source_range(
    file: RepositoryFile, source: str, start_offset: int, end_offset: int
) -> SourceRange:
    return SourceRange(
        _source_location(file, source, start_offset),
        _source_location(file, source, end_offset),
    )


def _source_location(
    file: RepositoryFile, source: str, offset: int
) -> SourceLocation:
    line = source.count("\n", 0, offset) + 1
    line_start = source.rfind("\n", 0, offset) + 1
    return SourceLocation(file, line, offset - line_start + 1)


def _fixture_sort_key(fixture: TestFixture) -> tuple[object, ...]:
    return (
        fixture.source_range.file.path.as_posix(),
        fixture.source_range.start.line,
        fixture.source_range.start.column,
        fixture.display_name,
        fixture.identity.value,
    )


def _case_sort_key(case: TestCase) -> tuple[object, ...]:
    return (
        case.source_range.file.path.as_posix(),
        case.source_range.start.line,
        case.source_range.start.column,
        case.display_name,
        case.identity.value,
    )
