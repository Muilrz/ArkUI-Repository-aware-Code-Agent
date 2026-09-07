"""Strict, versioned wire format for knowledge manifests and read results."""

from __future__ import annotations

import json
from dataclasses import fields
from enum import Enum
from types import UnionType
from typing import get_args, get_origin, get_type_hints

from .model import MODEL_TYPES, ManifestError, Model, require


def _encode(value: object) -> object:
    if isinstance(value, Model):
        return {"type": type(value).__name__, **{f.name: _encode(getattr(value, f.name)) for f in fields(value)}}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple):
        return [_encode(item) for item in value]
    return value


def dumps(value: Model) -> str:
    require(type(value).__name__ in MODEL_TYPES and isinstance(value, Model), "Unknown knowledge record.")
    return json.dumps({"schema_version": 1, "record": _encode(value)},
                      ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _decode(value: object, annotation: object) -> object:
    if get_origin(annotation) is UnionType:
        choices = get_args(annotation)
        if value is None and type(None) in choices:
            return None
        if type(value) is dict:
            tag = value.get("type")
            cls = MODEL_TYPES.get(tag) if type(tag) is str else None
            require(cls in choices, "Invalid union record.")
            return _decode(value, cls)
        require(type(value) in choices, "Invalid union scalar.")
        return value
    if get_origin(annotation) is tuple:
        require(type(value) is list, "Expected array.")
        return tuple(_decode(item, get_args(annotation)[0]) for item in value)
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        require(type(value) is str, "Expected enum string.")
        return annotation(value)
    if isinstance(annotation, type) and issubclass(annotation, Model):
        hints = get_type_hints(annotation)
        require(type(value) is dict and set(value) == {"type", *hints}
                and value["type"] == annotation.__name__, "Unknown or missing record field.")
        return annotation(**{name: _decode(value[name], kind) for name, kind in hints.items()})
    require(type(value) is annotation, "Invalid scalar type.")
    return value


def _object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        require(key not in result, "Duplicate JSON key.")
        result[key] = value
    return result


def loads(text: str) -> Model:
    try:
        require(type(text) is str, "Expected JSON string.")
        payload = json.loads(text, object_pairs_hook=_object)
        require(type(payload) is dict and set(payload) == {"schema_version", "record"}, "Invalid envelope.")
        require(type(payload["schema_version"]) is int and payload["schema_version"] == 1,
                "Unsupported knowledge schema version.")
        record = payload["record"]
        require(type(record) is dict and type(record.get("type")) is str, "Missing record type.")
        cls = MODEL_TYPES.get(record["type"])
        require(cls is not None, "Unknown record type.")
        return _decode(record, cls)
    except (ValueError, RecursionError) as error:
        raise ManifestError(str(error)) from error
