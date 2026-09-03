"""Backend-agnostic contracts for deterministic P1 retrieval benchmarks."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any


BENCHMARK_SCHEMA_VERSION = 1


class BenchmarkValidationError(ValueError):
    """Raised when a benchmark annotation does not satisfy the public schema."""


class RetrievalKind(str, Enum):
    TEXT_SEARCH = "text_search"
    SEARCH_SYMBOL = "search_symbol"
    FIND_DECLARATION = "find_declaration"
    FIND_DEFINITION = "find_definition"
    FIND_REFERENCES = "find_references"
    FIND_CALLERS = "find_callers"
    FIND_CALLEES = "find_callees"
    FIND_TESTS = "find_tests"


class SymbolQueryMatch(str, Enum):
    DISPLAY_NAME = "display_name"
    QUALIFIED_NAME = "qualified_name"


class TextQueryMode(str, Enum):
    EXACT = "exact"
    REGEX = "regex"


@dataclass(frozen=True, slots=True)
class QualifiedSymbol:
    """One symbol expectation requiring opaque and qualified identity agreement."""

    identity: str
    qualified_name: str

    def __post_init__(self) -> None:
        _require_nonempty(self.identity, "symbol identity")
        _require_nonempty(self.qualified_name, "symbol qualified_name")

    def to_dict(self) -> dict[str, str]:
        return {"identity": self.identity, "qualified_name": self.qualified_name}


@dataclass(frozen=True, slots=True)
class ExpectedTest:
    identity: str
    display_name: str
    file: str

    def __post_init__(self) -> None:
        _require_nonempty(self.identity, "test identity")
        _require_nonempty(self.display_name, "test display_name")
        _validate_repository_file(self.file)

    def to_dict(self) -> dict[str, str]:
        return {
            "identity": self.identity,
            "display_name": self.display_name,
            "file": self.file,
        }


@dataclass(frozen=True, slots=True)
class ExpectedRelation:
    caller: QualifiedSymbol
    callee: QualifiedSymbol

    def __post_init__(self) -> None:
        if not isinstance(self.caller, QualifiedSymbol) or not isinstance(
            self.callee, QualifiedSymbol
        ):
            raise BenchmarkValidationError(
                "Relation endpoints must be QualifiedSymbol values."
            )

    def to_dict(self) -> dict[str, object]:
        return {"caller": self.caller.to_dict(), "callee": self.callee.to_dict()}


@dataclass(frozen=True, slots=True)
class ManualAnnotation:
    annotator: str
    rationale: str

    def __post_init__(self) -> None:
        _require_nonempty(self.annotator, "annotation annotator")
        _require_nonempty(self.rationale, "annotation rationale")

    def to_dict(self) -> dict[str, str]:
        return {"annotator": self.annotator, "rationale": self.rationale}


@dataclass(frozen=True, slots=True)
class ExpectedResults:
    """Static expected results; ``None`` means a dimension is not annotated."""

    files: tuple[str, ...] | None = None
    symbols: tuple[QualifiedSymbol, ...] | None = None
    tests: tuple[ExpectedTest, ...] | None = None
    relations: tuple[ExpectedRelation, ...] | None = None

    def __post_init__(self) -> None:
        if all(value is None for value in (self.files, self.symbols, self.tests, self.relations)):
            raise BenchmarkValidationError(
                "Expected results must annotate at least one result dimension."
            )
        for label, value in (
            ("files", self.files),
            ("symbols", self.symbols),
            ("tests", self.tests),
            ("relations", self.relations),
        ):
            if value is not None and not isinstance(value, tuple):
                raise BenchmarkValidationError(
                    f"Expected result {label} must be a tuple."
                )
        if self.files is not None:
            for file in self.files:
                _validate_repository_file(file)
            _require_unique(self.files, "expected files")
        if self.symbols is not None:
            _require_unique(
                tuple((item.identity, item.qualified_name) for item in self.symbols),
                "expected symbols",
            )
        if self.tests is not None:
            _require_unique(
                tuple((item.identity, item.display_name, item.file) for item in self.tests),
                "expected tests",
            )
        if self.relations is not None:
            _require_unique(
                tuple(
                    (
                        item.caller.identity,
                        item.caller.qualified_name,
                        item.callee.identity,
                        item.callee.qualified_name,
                    )
                    for item in self.relations
                ),
                "expected relations",
            )

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {}
        if self.files is not None:
            result["files"] = list(self.files)
        if self.symbols is not None:
            result["symbols"] = [item.to_dict() for item in self.symbols]
        if self.tests is not None:
            result["tests"] = [item.to_dict() for item in self.tests]
        if self.relations is not None:
            result["relations"] = [item.to_dict() for item in self.relations]
        return result


@dataclass(frozen=True, slots=True)
class TextSearchInput:
    text: str
    mode: TextQueryMode = TextQueryMode.EXACT
    case_sensitive: bool = True
    path_scope: str = "."
    file_globs: tuple[str, ...] = ()
    limit: int | None = None

    def __post_init__(self) -> None:
        _require_nonempty(self.text, "text query")
        if "\n" in self.text or "\r" in self.text:
            raise BenchmarkValidationError("Text query must be single-line.")
        if not isinstance(self.case_sensitive, bool):
            raise BenchmarkValidationError("case_sensitive must be a boolean.")
        if not isinstance(self.mode, TextQueryMode):
            raise BenchmarkValidationError("mode must be a TextQueryMode.")
        if not isinstance(self.file_globs, tuple):
            raise BenchmarkValidationError("file_globs must be a tuple.")
        _validate_repository_scope(self.path_scope)
        for pattern in self.file_globs:
            _validate_repository_pattern(pattern)
        if self.limit is not None and (
            isinstance(self.limit, bool) or self.limit < 1
        ):
            raise BenchmarkValidationError("Query limit must be positive.")

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": RetrievalKind.TEXT_SEARCH.value,
            "text": self.text,
            "mode": self.mode.value,
            "case_sensitive": self.case_sensitive,
            "path_scope": self.path_scope,
            "file_globs": list(self.file_globs),
            "limit": self.limit,
        }


@dataclass(frozen=True, slots=True)
class SymbolSearchInput:
    name: str
    match: SymbolQueryMatch
    limit: int | None = None

    def __post_init__(self) -> None:
        _require_nonempty(self.name, "symbol query name")
        if not isinstance(self.match, SymbolQueryMatch):
            raise BenchmarkValidationError("match must be a SymbolQueryMatch.")
        if self.limit is not None and (
            isinstance(self.limit, bool) or self.limit < 1
        ):
            raise BenchmarkValidationError("Query limit must be positive.")

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": RetrievalKind.SEARCH_SYMBOL.value,
            "name": self.name,
            "match": self.match.value,
            "limit": self.limit,
        }


@dataclass(frozen=True, slots=True)
class IdentityQueryInput:
    kind: RetrievalKind
    symbol: QualifiedSymbol

    def __post_init__(self) -> None:
        if not isinstance(self.kind, RetrievalKind):
            raise BenchmarkValidationError("kind must be a RetrievalKind.")
        if self.kind in {RetrievalKind.TEXT_SEARCH, RetrievalKind.SEARCH_SYMBOL}:
            raise BenchmarkValidationError(
                f"{self.kind.value} does not accept an identity query."
            )

    def to_dict(self) -> dict[str, object]:
        return {"kind": self.kind.value, "symbol": self.symbol.to_dict()}


BenchmarkQuery = TextSearchInput | SymbolSearchInput | IdentityQueryInput


@dataclass(frozen=True, slots=True)
class BenchmarkCase:
    case_id: str
    query: BenchmarkQuery
    expected: ExpectedResults
    annotation: ManualAnnotation

    def __post_init__(self) -> None:
        _require_nonempty(self.case_id, "case id")
        if not isinstance(
            self.query, (TextSearchInput, SymbolSearchInput, IdentityQueryInput)
        ):
            raise BenchmarkValidationError("case query has an unsupported type.")
        if not isinstance(self.expected, ExpectedResults):
            raise BenchmarkValidationError("case expected must be ExpectedResults.")
        if not isinstance(self.annotation, ManualAnnotation):
            raise BenchmarkValidationError("case annotation must be ManualAnnotation.")

    @property
    def kind(self) -> RetrievalKind:
        if isinstance(self.query, TextSearchInput):
            return RetrievalKind.TEXT_SEARCH
        if isinstance(self.query, SymbolSearchInput):
            return RetrievalKind.SEARCH_SYMBOL
        return self.query.kind

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.case_id,
            "query": self.query.to_dict(),
            "expected": self.expected.to_dict(),
            "annotation": self.annotation.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class BenchmarkSuite:
    suite_id: str
    repository: str
    repository_revision: str
    cases: tuple[BenchmarkCase, ...]
    schema_version: int = BENCHMARK_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != BENCHMARK_SCHEMA_VERSION:
            raise BenchmarkValidationError(
                f"Unsupported benchmark schema_version {self.schema_version}; "
                f"expected {BENCHMARK_SCHEMA_VERSION}."
            )
        _require_nonempty(self.suite_id, "suite id")
        _require_nonempty(self.repository, "repository")
        _require_nonempty(self.repository_revision, "repository revision")
        if not isinstance(self.cases, tuple):
            raise BenchmarkValidationError("Benchmark cases must be a tuple.")
        if not self.cases:
            raise BenchmarkValidationError("Benchmark suite must contain cases.")
        _require_unique(tuple(case.case_id for case in self.cases), "case ids")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "suite_id": self.suite_id,
            "repository": self.repository,
            "repository_revision": self.repository_revision,
            "cases": [case.to_dict() for case in self.cases],
        }


def load_benchmark_suite(path: str | Path) -> BenchmarkSuite:
    """Load a checked-in, human-authored benchmark suite without deriving answers."""

    source = Path(path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BenchmarkValidationError(
            f"Cannot load benchmark suite {source}: {exc}"
        ) from exc
    return benchmark_suite_from_dict(payload)


def benchmark_suite_from_dict(payload: object) -> BenchmarkSuite:
    root = _mapping(payload, "benchmark suite")
    _only_keys(
        root,
        {"schema_version", "suite_id", "repository", "repository_revision", "cases"},
        "benchmark suite",
    )
    cases = _list(root.get("cases"), "benchmark cases")
    return BenchmarkSuite(
        schema_version=_integer(root.get("schema_version"), "schema_version"),
        suite_id=_string(root.get("suite_id"), "suite_id"),
        repository=_string(root.get("repository"), "repository"),
        repository_revision=_string(
            root.get("repository_revision"), "repository_revision"
        ),
        cases=tuple(_case_from_dict(item) for item in cases),
    )


def _case_from_dict(payload: object) -> BenchmarkCase:
    value = _mapping(payload, "benchmark case")
    _only_keys(value, {"id", "query", "expected", "annotation"}, "benchmark case")
    annotation = _mapping(value.get("annotation"), "annotation")
    _only_keys(annotation, {"annotator", "rationale"}, "annotation")
    return BenchmarkCase(
        case_id=_string(value.get("id"), "case id"),
        query=_query_from_dict(value.get("query")),
        expected=_expected_from_dict(value.get("expected")),
        annotation=ManualAnnotation(
            annotator=_string(annotation.get("annotator"), "annotator"),
            rationale=_string(annotation.get("rationale"), "rationale"),
        ),
    )


def _query_from_dict(payload: object) -> BenchmarkQuery:
    value = _mapping(payload, "query")
    try:
        kind = RetrievalKind(_string(value.get("kind"), "query kind"))
    except ValueError as exc:
        raise BenchmarkValidationError(f"Unknown retrieval kind: {value.get('kind')!r}.") from exc
    if kind is RetrievalKind.TEXT_SEARCH:
        _only_keys(
            value,
            {"kind", "text", "mode", "case_sensitive", "path_scope", "file_globs", "limit"},
            "text_search query",
        )
        return TextSearchInput(
            text=_string(value.get("text"), "text"),
            mode=_enum(TextQueryMode, value.get("mode", TextQueryMode.EXACT.value), "text mode"),
            case_sensitive=_boolean(value.get("case_sensitive", True), "case_sensitive"),
            path_scope=_string(value.get("path_scope", "."), "path_scope"),
            file_globs=tuple(
                _string(item, "file_glob")
                for item in _list(value.get("file_globs", []), "file_globs")
            ),
            limit=_optional_integer(value.get("limit"), "limit"),
        )
    if kind is RetrievalKind.SEARCH_SYMBOL:
        _only_keys(value, {"kind", "name", "match", "limit"}, "search_symbol query")
        return SymbolSearchInput(
            name=_string(value.get("name"), "name"),
            match=_enum(SymbolQueryMatch, value.get("match"), "symbol match"),
            limit=_optional_integer(value.get("limit"), "limit"),
        )
    _only_keys(value, {"kind", "symbol"}, "identity query")
    return IdentityQueryInput(kind=kind, symbol=_qualified_symbol(value.get("symbol")))


def _expected_from_dict(payload: object) -> ExpectedResults:
    value = _mapping(payload, "expected results")
    _only_keys(value, {"files", "symbols", "tests", "relations"}, "expected results")
    return ExpectedResults(
        files=None if "files" not in value else tuple(
            _string(item, "expected file") for item in _list(value["files"], "expected files")
        ),
        symbols=None if "symbols" not in value else tuple(
            _qualified_symbol(item) for item in _list(value["symbols"], "expected symbols")
        ),
        tests=None if "tests" not in value else tuple(
            _expected_test(item) for item in _list(value["tests"], "expected tests")
        ),
        relations=None if "relations" not in value else tuple(
            _expected_relation(item)
            for item in _list(value["relations"], "expected relations")
        ),
    )


def _qualified_symbol(payload: object) -> QualifiedSymbol:
    value = _mapping(payload, "qualified symbol")
    _only_keys(value, {"identity", "qualified_name"}, "qualified symbol")
    return QualifiedSymbol(
        identity=_string(value.get("identity"), "symbol identity"),
        qualified_name=_string(value.get("qualified_name"), "symbol qualified_name"),
    )


def _expected_test(payload: object) -> ExpectedTest:
    value = _mapping(payload, "expected test")
    _only_keys(value, {"identity", "display_name", "file"}, "expected test")
    return ExpectedTest(
        identity=_string(value.get("identity"), "test identity"),
        display_name=_string(value.get("display_name"), "test display_name"),
        file=_string(value.get("file"), "test file"),
    )


def _expected_relation(payload: object) -> ExpectedRelation:
    value = _mapping(payload, "expected relation")
    _only_keys(value, {"caller", "callee"}, "expected relation")
    return ExpectedRelation(
        caller=_qualified_symbol(value.get("caller")),
        callee=_qualified_symbol(value.get("callee")),
    )


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise BenchmarkValidationError(f"{label} must be a JSON object.")
    return value


def _list(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise BenchmarkValidationError(f"{label} must be a JSON array.")
    return value


def _string(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise BenchmarkValidationError(f"{label} must be a string.")
    return value


def _boolean(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise BenchmarkValidationError(f"{label} must be a boolean.")
    return value


def _integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise BenchmarkValidationError(f"{label} must be an integer.")
    return value


def _optional_integer(value: object, label: str) -> int | None:
    return None if value is None else _integer(value, label)


def _enum(enum_type: type[Enum], value: object, label: str) -> Any:
    raw = _string(value, label)
    try:
        return enum_type(raw)
    except ValueError as exc:
        raise BenchmarkValidationError(f"Invalid {label}: {raw!r}.") from exc


def _only_keys(value: dict[str, Any], allowed: set[str], label: str) -> None:
    unknown = sorted(set(value).difference(allowed))
    if unknown:
        raise BenchmarkValidationError(
            f"Unknown {label} fields: {', '.join(unknown)}."
        )


def _require_nonempty(value: str, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise BenchmarkValidationError(f"{label} must not be empty.")


def _require_unique(values: tuple[object, ...], label: str) -> None:
    if len(values) != len(set(values)):
        raise BenchmarkValidationError(f"{label} must not contain duplicates.")


def _validate_repository_file(value: str) -> None:
    _require_nonempty(value, "repository file")
    path = PurePosixPath(value)
    if (
        "\\" in value
        or path.is_absolute()
        or PureWindowsPath(value).anchor
        or ".." in path.parts
        or path.as_posix() != value
        or value == "."
    ):
        raise BenchmarkValidationError(
            f"Repository file must be a canonical relative POSIX path: {value!r}."
        )


def _validate_repository_scope(value: str) -> None:
    if value == ".":
        return
    _validate_repository_file(value)


def _validate_repository_pattern(value: str) -> None:
    _validate_repository_file(value)
