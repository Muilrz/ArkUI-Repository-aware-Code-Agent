"""Immutable, platform-neutral input contracts; no repository queries."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import UnionType
from typing import get_args, get_origin, get_type_hints

from arkui_agent.repository.model import RepositoryFile


class InputError(ValueError):
    """Invalid input, including malformed serialized contracts."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def require(condition: bool, code: str, message: str) -> None:
    if not condition:
        raise InputError(code, message)


def matches(value: object, annotation: object) -> bool:
    if get_origin(annotation) is UnionType:
        return any(matches(value, item) for item in get_args(annotation))
    if get_origin(annotation) is tuple:
        return isinstance(value, tuple) and all(
            matches(item, get_args(annotation)[0]) for item in value
        )
    return type(value) is annotation


class Record:
    __slots__ = ()

    def __post_init__(self) -> None:
        for name, annotation in get_type_hints(type(self)).items():
            require(matches(getattr(self, name), annotation), "invalid_type", name)
        self.validate()

    def validate(self) -> None:
        pass


class Origin(str, Enum):
    INPUT = "input"
    EXPLICIT = "explicit"
    EXTRACTED = "extracted"
    DIFF = "diff"


@dataclass(frozen=True, slots=True)
class TextSpan(Record):
    start: int
    end: int

    def validate(self) -> None:
        require(0 <= self.start < self.end, "invalid_span", "Expected nonempty [start,end).")


@dataclass(frozen=True, slots=True)
class Provenance(Record):
    source_id: str
    origin: Origin
    span: TextSpan | None = None
    rule: str | None = None

    def validate(self) -> None:
        require(bool(self.source_id.strip()), "invalid_source", "source_id is required.")
        if self.origin in (Origin.EXTRACTED, Origin.DIFF):
            require(self.span is not None and bool(self.rule), "invalid_provenance",
                    "Parsed provenance requires a span and rule/version.")


class RevisionStatus(str, Enum):
    DECLARED = "declared"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True, slots=True)
class Revision(Record):
    value: str | None

    def validate(self) -> None:
        require(self.value is None or bool(self.value.strip()), "invalid_revision",
                "A blank revision is invalid; use null for an absent revision.")

    @property
    def status(self) -> RevisionStatus:
        return RevisionStatus.UNRESOLVED if self.value is None else RevisionStatus.DECLARED


class HintKind(str, Enum):
    COMPONENT = "component"
    SYMBOL = "symbol"
    PROPERTY = "property"
    ACTION = "action"
    TEST_INTENT = "test_intent"


@dataclass(frozen=True, slots=True)
class Hint(Record):
    kind: HintKind
    value: str
    provenance: Provenance

    def validate(self) -> None:
        require(bool(self.value.strip()), "invalid_hint", "Hint value is required.")
        require(self.provenance.origin in (Origin.EXPLICIT, Origin.EXTRACTED),
                "invalid_provenance", "Hint origin must be explicit or extracted.")

    @property
    def resolution(self) -> str:
        return "unresolved"


@dataclass(frozen=True, slots=True)
class Task(Record):
    repository: str
    target_revision: Revision
    text: str
    hints: tuple[Hint, ...]
    provenance: Provenance

    def validate(self) -> None:
        require(bool(self.repository.strip()), "invalid_repository", "repository is required.")
        require(bool(self.text.strip()) or bool(self.hints), "empty_task",
                "Task needs text or structured hints.")
        for hint in self.hints:
            if hint.provenance.origin is Origin.EXTRACTED:
                span = hint.provenance.span
                require(span is not None and span.end <= len(self.text)
                        and hint.provenance.source_id == self.provenance.source_id
                        and self.text[span.start:span.end] == hint.value,
                        "invalid_provenance", "Extracted hint must quote its Task text.")


class Side(str, Enum):
    OLD = "old"
    NEW = "new"


@dataclass(frozen=True, slots=True)
class LineRange(Record):
    """Whole-line interval, 1-based lines/columns, exclusive end, column always 1."""

    side: Side
    start_line: int
    end_line: int
    start_column: int = 1
    end_column: int = 1

    def validate(self) -> None:
        require(1 <= self.start_line <= self.end_line
                and self.start_column == self.end_column == 1,
                "invalid_range", "Expected 1-based whole-line half-open range.")

    @property
    def count(self) -> int:
        return self.end_line - self.start_line


class LineKind(str, Enum):
    CONTEXT = "context"
    ADD = "add"
    DELETE = "delete"
    NO_NEWLINE = "no_newline"


@dataclass(frozen=True, slots=True)
class DiffLine(Record):
    kind: LineKind
    text: str

    def validate(self) -> None:
        require("\n" not in self.text and "\r" not in self.text, "invalid_line",
                "DiffLine excludes line terminators.")
        if self.kind is LineKind.NO_NEWLINE:
            require(self.text == "\\ No newline at end of file", "invalid_marker",
                    "Invalid no-newline marker.")


@dataclass(frozen=True, slots=True)
class Hunk(Record):
    old_range: LineRange
    new_range: LineRange
    section: str
    lines: tuple[DiffLine, ...]
    provenance: Provenance

    def validate(self) -> None:
        require(self.old_range.side is Side.OLD and self.new_range.side is Side.NEW,
                "invalid_side", "Hunk ranges must retain old/new sides.")
        old = sum(line.kind in (LineKind.CONTEXT, LineKind.DELETE) for line in self.lines)
        new = sum(line.kind in (LineKind.CONTEXT, LineKind.ADD) for line in self.lines)
        require((old, new) == (self.old_range.count, self.new_range.count),
                "invalid_range", "Hunk counts disagree with body.")
        require(old + new > 0, "invalid_range", "Empty hunk is invalid.")
        ended: set[Side] = set()
        for i, line in enumerate(self.lines):
            if line.kind is LineKind.NO_NEWLINE:
                require(i > 0 and self.lines[i - 1].kind is not LineKind.NO_NEWLINE,
                        "invalid_marker", "No-newline marker needs a preceding content line.")
                previous = self.lines[i - 1].kind
                if previous in (LineKind.CONTEXT, LineKind.DELETE):
                    ended.add(Side.OLD)
                if previous in (LineKind.CONTEXT, LineKind.ADD):
                    ended.add(Side.NEW)
            else:
                require(not (Side.OLD in ended and line.kind in (LineKind.CONTEXT, LineKind.DELETE))
                        and not (Side.NEW in ended and line.kind in (LineKind.CONTEXT, LineKind.ADD)),
                        "invalid_marker", "Content follows EOF on the same side.")


class ChangeKind(str, Enum):
    MODIFY = "modify"
    ADD = "add"
    DELETE = "delete"
    RENAME = "rename"


def validate_path(path: str | None) -> None:
    if path is not None:
        require(not any(ord(char) < 32 or ord(char) == 127 for char in path),
                "invalid_path", "Control characters are forbidden in paths.")
        try:
            RepositoryFile.from_path(path)
        except ValueError as error:
            raise InputError("invalid_path", str(error)) from error


@dataclass(frozen=True, slots=True)
class FileChange(Record):
    old_path: str | None
    new_path: str | None
    kind: ChangeKind
    hunks: tuple[Hunk, ...]
    metadata: tuple[str, ...]
    provenance: Provenance

    def validate(self) -> None:
        validate_path(self.old_path)
        validate_path(self.new_path)
        valid = {
            ChangeKind.ADD: self.old_path is None and self.new_path is not None,
            ChangeKind.DELETE: self.old_path is not None and self.new_path is None,
            ChangeKind.MODIFY: self.old_path is not None and self.old_path == self.new_path,
            ChangeKind.RENAME: self.old_path is not None and self.new_path is not None
            and self.old_path != self.new_path,
        }
        require(valid[self.kind], "invalid_paths", "Change kind disagrees with paths.")
        ended: set[Side] = set()
        for hunk in self.hunks:
            require(not (Side.OLD in ended and hunk.old_range.count)
                    and not (Side.NEW in ended and hunk.new_range.count),
                    "invalid_marker", "A later hunk contains content after EOF.")
            if self.kind is ChangeKind.ADD:
                require(hunk.old_range.start_line == hunk.old_range.end_line == 1,
                        "invalid_range", "Added file has no old-side lines.")
            if self.kind is ChangeKind.DELETE:
                require(hunk.new_range.start_line == hunk.new_range.end_line == 1,
                        "invalid_range", "Deleted file has no new-side lines.")
            for i, line in enumerate(hunk.lines):
                if line.kind is LineKind.NO_NEWLINE:
                    kind = hunk.lines[i - 1].kind
                    if kind in (LineKind.CONTEXT, LineKind.DELETE):
                        ended.add(Side.OLD)
                    if kind in (LineKind.CONTEXT, LineKind.ADD):
                        ended.add(Side.NEW)
        for previous, current in zip(self.hunks, self.hunks[1:]):
            require(previous.old_range.end_line <= current.old_range.start_line
                    and previous.new_range.end_line <= current.new_range.start_line,
                    "invalid_range", "Hunks must be ordered and non-overlapping on both sides.")


@dataclass(frozen=True, slots=True)
class Change(Record):
    repository: str
    base_revision: Revision
    head_revision: Revision
    files: tuple[FileChange, ...]
    raw_diff: str | None
    provenance: Provenance

    def validate(self) -> None:
        require(bool(self.repository.strip()), "invalid_repository", "repository is required.")
        require(bool(self.files), "empty_change", "Change needs at least one file.")
        for side in ("old_path", "new_path"):
            paths = [getattr(file, side) for file in self.files if getattr(file, side) is not None]
            require(len(paths) == len(set(paths)), "duplicate_file", "Duplicate path on one side.")
        if self.raw_diff is not None:
            for item in (*self.files, *(h for f in self.files for h in f.hunks)):
                if item.provenance.origin is Origin.DIFF:
                    span = item.provenance.span
                    require(span is not None and span.end <= len(self.raw_diff)
                            and item.provenance.source_id == self.provenance.source_id,
                            "invalid_provenance", "Diff span must refer to the original diff.")


class ParseStatus(str, Enum):
    OK = "ok"
    UNRESOLVED = "unresolved"
    INVALID = "invalid"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True, slots=True)
class Diagnostic(Record):
    code: str
    message: str
    field: str

    def validate(self) -> None:
        require(all(value.strip() for value in (self.code, self.message, self.field)),
                "invalid_diagnostic", "Diagnostic fields must be nonempty.")


def revision_diagnostics(value: Task | Change) -> tuple[Diagnostic, ...]:
    names = ("target_revision",) if isinstance(value, Task) else ("base_revision", "head_revision")
    return tuple(Diagnostic("missing_revision", "Revision is absent; no default is selected.", name)
                 for name in names if getattr(value, name).status is RevisionStatus.UNRESOLVED)


@dataclass(frozen=True, slots=True)
class ParseResult(Record):
    status: ParseStatus
    value: Task | Change | None
    diagnostics: tuple[Diagnostic, ...]
    raw_input: str
    provenance: Provenance

    def validate(self) -> None:
        if self.status in (ParseStatus.INVALID, ParseStatus.UNSUPPORTED):
            require(self.value is None and bool(self.diagnostics), "invalid_result",
                    "Rejected input requires diagnostics and no partial value.")
        else:
            require(self.value is not None, "invalid_result", "Parsed input requires a value.")
            raw = self.value.text if isinstance(self.value, Task) else self.value.raw_diff
            require(self.provenance == self.value.provenance and (raw is None or raw == self.raw_input),
                    "invalid_provenance", "Parsed result must retain its input text and source.")
            missing = revision_diagnostics(self.value)
            require(self.status is (ParseStatus.UNRESOLVED if missing else ParseStatus.OK)
                    and self.diagnostics == missing, "invalid_result",
                    "Result must expose all absent revisions.")


# Explicit registry, used only for the versioned input wire format.
RECORD_TYPES = {cls.__name__: cls for cls in (
    TextSpan, Provenance, Revision, Hint, Task, LineRange, DiffLine, Hunk,
    FileChange, Change, Diagnostic, ParseResult,
)}
