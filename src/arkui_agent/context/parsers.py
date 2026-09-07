"""Finite Task extraction and fail-closed unified diff parsing."""

from __future__ import annotations

import re

from .inputs import (
    Change, ChangeKind, Diagnostic, DiffLine, FileChange, Hint, HintKind, Hunk,
    InputError, LineKind, LineRange, Origin, ParseResult, ParseStatus, Provenance,
    Revision, Side, Task, TextSpan, require, revision_diagnostics, validate_path,
)


TASK_RULE = "task-labels-v1"
DIFF_RULE = "unified-diff-v1"
_LABEL = re.compile(r"\[(component|symbol|property|action|test_intent):([^\[\]\r\n]*)\]")
_UT = re.compile(r"\s*给\s*(?P<component>[A-Za-z_][A-Za-z_0-9]*)\s*的\s*"
                 r"(?P<property>[A-Za-z_][A-Za-z_0-9]*)\s*属性\s*(?P<action>补)\s*"
                 r"(?P<test_intent>UT)\s*[。.!！]?\s*")
_HUNK = re.compile(r"@@ -([0-9]+)(?:,([0-9]+))? \+([0-9]+)(?:,([0-9]+))? @@(.*)")
_METADATA = re.compile(r"(?:index [0-9a-fA-F]+\.\.[0-9a-fA-F]+(?: [0-7]{6})?"
                       r"|(?:old mode|new mode|new file mode|deleted file mode) [0-7]{6}"
                       r"|similarity index (?:100|[0-9]{1,2})%)")


class _Unsupported(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def _result(value: Task | Change, raw: str, provenance: Provenance) -> ParseResult:
    diagnostics = revision_diagnostics(value)
    return ParseResult(ParseStatus.UNRESOLVED if diagnostics else ParseStatus.OK,
                       value, diagnostics, raw, provenance)


def _rejected(error: InputError | _Unsupported, raw: str, provenance: Provenance) -> ParseResult:
    return ParseResult(ParseStatus.UNSUPPORTED if isinstance(error, _Unsupported)
                       else ParseStatus.INVALID, None,
                       (Diagnostic(error.code, str(error), "input"),), raw, provenance)


def parse_task(text: str, *, repository: str, target_revision: str | None,
               source_id: str, hints: tuple[Hint, ...] = ()) -> ParseResult:
    """Extract labels and one documented Chinese UT template, without resolution."""
    require(type(text) is str, "invalid_type", "Task text must be a string.")
    provenance = Provenance(source_id, Origin.INPUT)
    try:
        require(type(hints) is tuple and all(type(hint) is Hint for hint in hints),
                "invalid_type", "Explicit hints must be a tuple of Hint records.")
        require(all(h.provenance.origin is Origin.EXPLICIT for h in hints),
                "invalid_provenance", "Caller hints must be explicit.")
        extracted: list[Hint] = []
        for match in _LABEL.finditer(text):
            start, end = match.span(2)
            while start < end and text[start].isspace():
                start += 1
            while end > start and text[end - 1].isspace():
                end -= 1
            require(start < end, "invalid_hint", "Recognized label has an empty value.")
            extracted.append(Hint(HintKind(match[1]), text[start:end],
                                  Provenance(source_id, Origin.EXTRACTED,
                                             TextSpan(start, end), TASK_RULE)))
        match = _UT.fullmatch(text)
        if match is not None:
            for kind in ("component", "property", "action", "test_intent"):
                start, end = match.span(kind)
                extracted.append(Hint(HintKind(kind), text[start:end],
                                      Provenance(source_id, Origin.EXTRACTED,
                                                 TextSpan(start, end), "task-zh-ut-v1")))
        return _result(Task(repository, Revision(target_revision), text,
                            hints + tuple(extracted), provenance), text, provenance)
    except InputError as error:
        return _rejected(error, text, provenance)


def _range(side: Side, start: str, count: str | None) -> LineRange:
    # Unified zero-count N denotes the gap after line N, including 0 at BOF.
    try:
        first, length = int(start), 1 if count is None else int(count)
    except ValueError as error:
        raise InputError("invalid_range", "Invalid integer in hunk header.") from error
    require(length == 0 or first >= 1, "invalid_range", "Nonempty diff range starts at line 1 or later.")
    normalized = first + 1 if length == 0 else first
    return LineRange(side, normalized, normalized + length)


def _path(raw: str, prefix: str | None) -> str | None:
    if raw == "/dev/null":
        return None
    if raw.startswith('"'):
        raise _Unsupported("quoted_path", "Git-quoted/escaped paths are not supported.")
    if prefix is not None:
        require(raw.startswith(prefix), "invalid_path", "Expected Git side prefix.")
        raw = raw[len(prefix):]
    validate_path(raw)
    return raw


class _DiffParser:
    def __init__(self, raw: str, source_id: str) -> None:
        self.source_id = source_id
        require(re.search(r"\r(?!\n)", raw) is None, "invalid_line", "Bare CR is not a supported line separator.")
        self.lines = raw.splitlines(keepends=True)
        require(all(not any(char in line for char in "\v\f\x1c\x1d\x1e\x85\u2028\u2029")
                    for line in self.lines), "invalid_line", "Only LF/CRLF diff line separators are accepted.")
        self.offsets = [0]
        for line in self.lines:
            self.offsets.append(self.offsets[-1] + len(line))
        self.i = 0

    def line(self) -> str:
        return self.lines[self.i].removesuffix("\n").removesuffix("\r")

    def provenance(self, start: int) -> Provenance:
        return Provenance(self.source_id, Origin.DIFF,
                          TextSpan(self.offsets[start], self.offsets[self.i]), DIFF_RULE)

    def hunk(self) -> Hunk:
        start = self.i
        match = _HUNK.fullmatch(self.line())
        require(match is not None, "invalid_hunk", "Malformed unified hunk header.")
        old = _range(Side.OLD, match[1], match[2])
        new = _range(Side.NEW, match[3], match[4])
        self.i += 1
        body: list[DiffLine] = []
        old_count = new_count = 0
        kinds = {" ": LineKind.CONTEXT, "+": LineKind.ADD, "-": LineKind.DELETE}
        while self.i < len(self.lines):
            line = self.line()
            if line == "\\ No newline at end of file":
                body.append(DiffLine(LineKind.NO_NEWLINE, line))
                self.i += 1
                continue
            if old_count == old.count and new_count == new.count:
                break
            require(bool(line) and line[0] in kinds, "invalid_hunk", "Truncated or malformed hunk body.")
            kind = kinds[line[0]]
            body.append(DiffLine(kind, line[1:]))
            old_count += kind in (LineKind.CONTEXT, LineKind.DELETE)
            new_count += kind in (LineKind.CONTEXT, LineKind.ADD)
            require(old_count <= old.count and new_count <= new.count,
                    "invalid_range", "Hunk body exceeds declared counts.")
            self.i += 1
        return Hunk(old, new, match[5], tuple(body), self.provenance(start))

    def file(self) -> FileChange:
        start = self.i
        git_paths: tuple[str | None, str | None] | None = None
        metadata: list[str] = []
        rename: dict[str, str | None] = {}
        if self.line().startswith("diff --git "):
            header = self.line()[11:]
            if '"' in header or len(header.split(" ")) != 2:
                raise _Unsupported("git_path_syntax", "Git header supports unquoted paths without spaces only.")
            a, b = header.split(" ")
            git_paths = (_path(a, "a/"), _path(b, "b/"))
            require(all(path is not None for path in git_paths), "invalid_path", "Git header cannot use /dev/null.")
            self.i += 1
            while self.i < len(self.lines):
                line = self.line()
                if line.startswith(("--- ", "diff --git ")):
                    break
                if line.startswith(("rename from ", "rename to ")):
                    key, raw = ("old", line[12:]) if line.startswith("rename from ") else ("new", line[10:])
                    require(key not in rename, "invalid_metadata", "Duplicate rename header.")
                    rename[key] = _path(raw, None)
                elif _METADATA.fullmatch(line) is None:
                    raise _Unsupported("diff_extension", "Unsupported Git metadata: " + line)
                require(line not in metadata, "invalid_metadata", "Duplicate metadata line.")
                if not line.startswith("rename "):
                    key = line.rsplit(" ", 1)[0] if not line.startswith("index ") else "index"
                    require(not any(previous.startswith(key + " ") for previous in metadata),
                            "invalid_metadata", "Conflicting metadata entries.")
                metadata.append(line)
                self.i += 1

        old_path: str | None
        new_path: str | None
        has_headers = self.i < len(self.lines) and self.line().startswith("--- ")
        if has_headers:
            old_path = _path(self.line()[4:].split("\t", 1)[0], "a/" if git_paths else None)
            self.i += 1
            require(self.i < len(self.lines) and self.line().startswith("+++ "),
                    "invalid_header", "Missing +++ file header.")
            new_path = _path(self.line()[4:].split("\t", 1)[0], "b/" if git_paths else None)
            self.i += 1
        elif git_paths:
            old_path, new_path = git_paths
            if any(line.startswith("new file mode ") for line in metadata):
                old_path = None
            if any(line.startswith("deleted file mode ") for line in metadata):
                new_path = None
        else:
            raise InputError("invalid_header", "Expected unified file headers.")

        if git_paths:
            require((old_path is None or old_path == git_paths[0])
                    and (new_path is None or new_path == git_paths[1]),
                    "invalid_header", "Git and unified paths disagree.")
        if old_path is None:
            kind = ChangeKind.ADD
        elif new_path is None:
            kind = ChangeKind.DELETE
        elif old_path != new_path:
            kind = ChangeKind.RENAME
        else:
            kind = ChangeKind.MODIFY
        if rename:
            require(kind is ChangeKind.RENAME and rename == {"old": old_path, "new": new_path},
                    "invalid_metadata", "Rename metadata must be paired and match paths.")
        if git_paths and kind is ChangeKind.RENAME:
            require(bool(rename), "invalid_metadata", "Git rename requires from/to metadata.")
        if git_paths and kind is not ChangeKind.RENAME:
            require(git_paths[0] == git_paths[1], "invalid_header", "Non-rename Git paths must agree.")
        old_mode = any(line.startswith("old mode ") for line in metadata)
        new_mode = any(line.startswith("new mode ") for line in metadata)
        require(old_mode == new_mode and (not old_mode or kind in (ChangeKind.MODIFY, ChangeKind.RENAME)),
                "invalid_metadata", "Mode changes require an old/new pair on existing files.")
        for prefix, expected in (("new file mode ", ChangeKind.ADD), ("deleted file mode ", ChangeKind.DELETE)):
            if any(line.startswith(prefix) for line in metadata):
                require(kind is expected, "invalid_metadata", "File mode metadata conflicts with paths.")
        hunks: list[Hunk] = []
        while self.i < len(self.lines) and self.line().startswith("@@"):
            hunks.append(self.hunk())
        require(bool(hunks) or (git_paths is not None and bool(metadata)),
                "invalid_hunk", "Text file headers require at least one hunk.")
        if not hunks and kind is ChangeKind.MODIFY:
            require(any(line.startswith("old mode ") for line in metadata)
                    and any(line.startswith("new mode ") for line in metadata),
                    "invalid_metadata", "No-hunk modification requires a mode pair.")
        return FileChange(old_path, new_path, kind, tuple(hunks), tuple(metadata), self.provenance(start))

    def parse(self) -> tuple[FileChange, ...]:
        for raw_line in self.lines:
            line = raw_line.rstrip("\r\n")
            if line.startswith(("diff --cc ", "diff --combined ", "@@@")):
                raise _Unsupported("combined_diff", "Combined diffs require a separate parser.")
            if line == "GIT binary patch" or (line.startswith("Binary files ") and line.endswith(" differ")):
                raise _Unsupported("binary_diff", "Binary diffs are not text hunks.")
        files: list[FileChange] = []
        while self.i < len(self.lines):
            files.append(self.file())
        return tuple(files)


def parse_unified_diff(raw_diff: str, *, repository: str, base_revision: str | None,
                       head_revision: str | None, source_id: str) -> ParseResult:
    """Parse a complete supported diff atomically; retain raw input on failure."""
    require(type(raw_diff) is str, "invalid_type", "Diff input must be a string.")
    provenance = Provenance(source_id, Origin.INPUT)
    try:
        base, head = Revision(base_revision), Revision(head_revision)
        files = _DiffParser(raw_diff, source_id).parse()
        return _result(Change(repository, base, head, files, raw_diff, provenance), raw_diff, provenance)
    except (InputError, _Unsupported) as error:
        return _rejected(error, raw_diff, provenance)
