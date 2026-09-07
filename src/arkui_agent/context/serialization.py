"""Strict JSON v1 serialization for P3 input records (not Context Pack)."""

from __future__ import annotations

import json
from dataclasses import fields
from enum import Enum
from types import UnionType
from typing import cast, get_args, get_origin, get_type_hints

from .inputs import Change, InputError, ParseResult, RECORD_TYPES, Record, Task, require


def _encode(value: object) -> object:
    if isinstance(value, Record):
        return {"$type": type(value).__name__, **{
            field.name: _encode(getattr(value, field.name)) for field in fields(value)
        }}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple):
        return [_encode(item) for item in value]
    return value


def to_dict(value: Task | Change | ParseResult) -> dict[str, object]:
    require(type(value) in (Task, Change, ParseResult), "invalid_type", "Invalid input root.")
    return {"schema_version": 1, "payload": _encode(value)}


def dumps(value: Task | Change | ParseResult) -> str:
    return json.dumps(to_dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _decode(value: object, annotation: object) -> object:
    if get_origin(annotation) is UnionType:
        choices = get_args(annotation)
        if value is None and type(None) in choices:
            return None
        if isinstance(value, dict):
            selected = RECORD_TYPES.get(value.get("$type")) if isinstance(value.get("$type"), str) else None
            require(selected in choices, "invalid_type", "Unexpected record type.")
            return _decode(value, selected)
        for choice in choices:
            if type(value) is choice:
                return value
        raise InputError("invalid_type", "Unexpected union value.")
    if get_origin(annotation) is tuple:
        require(type(value) is list, "invalid_type", "Expected JSON array.")
        return tuple(_decode(item, get_args(annotation)[0]) for item in value)
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        require(type(value) is str, "invalid_type", "Expected enum string.")
        try:
            return annotation(value)
        except ValueError as error:
            raise InputError("invalid_enum", str(error)) from error
    if isinstance(annotation, type) and issubclass(annotation, Record):
        hints = get_type_hints(annotation)
        require(type(value) is dict and set(value) == {"$type", *hints}
                and value["$type"] == annotation.__name__, "invalid_schema",
                "Unknown/missing fields or record type.")
        return annotation(**{name: _decode(value[name], kind) for name, kind in hints.items()})
    require(type(value) is annotation, "invalid_type", "Unexpected scalar type.")
    return value


def from_dict(document: dict[str, object]) -> Task | Change | ParseResult:
    require(type(document) is dict and set(document) == {"schema_version", "payload"},
            "invalid_schema", "Expected versioned input envelope.")
    require(type(document["schema_version"]) is int and document["schema_version"] == 1,
            "unsupported_version", "Only input schema version 1 is supported.")
    return cast(Task | Change | ParseResult, _decode(document["payload"], Task | Change | ParseResult))


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        require(key not in result, "invalid_json", "Duplicate JSON key.")
        result[key] = value
    return result


def loads(document: str) -> Task | Change | ParseResult:
    require(type(document) is str, "invalid_type", "JSON input must be text.")
    try:
        decoded = json.loads(document, object_pairs_hook=_unique_object)
    except (ValueError, RecursionError) as error:
        if isinstance(error, InputError):
            raise
        raise InputError("invalid_json", str(error)) from error
    return from_dict(decoded)
