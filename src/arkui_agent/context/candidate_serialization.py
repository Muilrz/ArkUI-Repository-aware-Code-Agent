"""Closed annotation-driven E codec: JSON never names importable Python classes."""

from __future__ import annotations

import json
from dataclasses import fields, is_dataclass
from enum import Enum
from pathlib import PurePosixPath
from types import UnionType
from typing import get_args, get_origin, get_type_hints

from .materialization import ContextCandidateSet, MaterializationError


def _encode(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, PurePosixPath):
        return value.as_posix()
    if is_dataclass(value) and not isinstance(value, type):
        return {"type": type(value).__name__, **{f.name: _encode(getattr(value, f.name)) for f in fields(value)}}
    if isinstance(value, (tuple, frozenset)):
        items = [_encode(v) for v in value]
        return sorted(items, key=lambda v: json.dumps(v, sort_keys=True)) if isinstance(value, frozenset) else items
    return value


def _decode(value: object, annotation: object) -> object:
    origin = get_origin(annotation)
    if origin is UnionType:
        for choice in get_args(annotation):
            if isinstance(value, dict) and isinstance(choice, type) and is_dataclass(choice):
                if value.get("type") == choice.__name__:
                    return _decode(value, choice)
            elif type(value) is choice:
                return value
        raise MaterializationError("Invalid union member.")
    if origin in (tuple, frozenset):
        if type(value) is not list:
            raise MaterializationError("Expected JSON array.")
        arguments = get_args(annotation)
        if len(arguments) == 2 and arguments[1] is Ellipsis:
            values = [_decode(v, arguments[0]) for v in value]
        elif origin is frozenset:
            values = [_decode(v, arguments[0]) for v in value]
        else:
            if len(value) != len(arguments):
                raise MaterializationError("Tuple arity mismatch.")
            values = [_decode(v, kind) for v, kind in zip(value, arguments)]
        return origin(values)
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        if type(value) is not str:
            raise MaterializationError("Expected enum string.")
        return annotation(value)
    if annotation is PurePosixPath:
        if type(value) is not str:
            raise MaterializationError("Expected relative source path.")
        from arkui_agent.repository.model import RepositoryFile
        return RepositoryFile.from_path(value).path
    if isinstance(annotation, type) and is_dataclass(annotation):
        hints = get_type_hints(annotation)
        names = {f.name for f in fields(annotation)}
        if type(value) is not dict or set(value) != {"type", *names} or value["type"] != annotation.__name__:
            raise MaterializationError("Unknown/missing record fields or type.")
        return annotation(**{name: _decode(value[name], hints[name]) for name in names})
    if type(value) is not annotation:
        raise MaterializationError("Invalid scalar type.")
    return value


def _object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise MaterializationError("Duplicate JSON key.")
        result[key] = value
    return result


def dumps(value: ContextCandidateSet) -> str:
    if type(value) is not ContextCandidateSet:
        raise MaterializationError("Expected ContextCandidateSet.")
    return json.dumps({"schema": "p3-context-candidates-v1", "result": _encode(value)},
                      ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def loads(text: str) -> ContextCandidateSet:
    try:
        document = json.loads(text, object_pairs_hook=_object)
        if (type(document) is not dict or set(document) != {"schema", "result"}
                or document["schema"] != "p3-context-candidates-v1"):
            raise MaterializationError("Unsupported context candidate envelope.")
        return _decode(document["result"], ContextCandidateSet)
    except (ValueError, TypeError, RecursionError) as error:
        raise MaterializationError(str(error)) from error
