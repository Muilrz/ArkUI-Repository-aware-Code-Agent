"""Shared Task/Change inputs; retrieval and Context Pack are later milestones."""

from .inputs import (
    Change, ChangeKind, Diagnostic, DiffLine, FileChange, Hint, HintKind, Hunk,
    InputError, LineKind, LineRange, Origin, ParseResult, ParseStatus, Provenance,
    Revision, RevisionStatus, Side, Task, TextSpan,
)
from .parsers import parse_task, parse_unified_diff
from .serialization import dumps, from_dict, loads, to_dict

__all__ = [
    "Change", "ChangeKind", "Diagnostic", "DiffLine", "FileChange", "Hint", "HintKind",
    "Hunk", "InputError", "LineKind", "LineRange", "Origin", "ParseResult", "ParseStatus",
    "Provenance", "Revision", "RevisionStatus", "Side", "Task", "TextSpan",
    "parse_task", "parse_unified_diff", "dumps", "from_dict", "loads", "to_dict",
]
