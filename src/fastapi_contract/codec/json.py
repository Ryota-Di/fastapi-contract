"""Strict schema-v1 JSON transport; only registered domain variants are decoded."""

from __future__ import annotations

import json
from dataclasses import fields, is_dataclass
from enum import Enum
from types import UnionType
from typing import Any, Union, get_args, get_origin, get_type_hints

from fastapi_contract.domain import model


class SnapshotCodecError(ValueError):
    pass


_TAGS: dict[type[Any], str] = {
    model.ObjectShape: "object",
    model.ScalarShape: "scalar",
    model.WholeSelection: "whole_selection",
    model.ObjectSelection: "object_selection",
    model.UnsupportedSelection: "unsupported_selection",
    model.NoDefault: "no_default",
    model.StaticDefault: "static_default",
    model.FactoryDefault: "factory_default",
}


def _encode(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        result = {field.name: _encode(getattr(value, field.name)) for field in fields(value)}
        if type(value) in _TAGS:
            result["type"] = _TAGS[type(value)]
        return result
    if isinstance(value, tuple):
        return [_encode(item) for item in value]
    if value is None or type(value) in (str, int, bool):
        return value
    raise SnapshotCodecError(f"Unsupported snapshot value: {type(value).__name__}")


def _decode(value: Any, expected: Any) -> Any:
    origin = get_origin(expected)
    args = get_args(expected)
    if origin in (Union, UnionType):
        for variant in args:
            try:
                return _decode(value, variant)
            except SnapshotCodecError:
                pass
        raise SnapshotCodecError("Value does not match any declared variant")
    if origin is tuple:
        if not isinstance(value, list):
            raise SnapshotCodecError("Expected array")
        if not args:
            if value:
                raise SnapshotCodecError("Expected empty array")
            return ()
        if len(args) == 2 and args[1] is Ellipsis:
            return tuple(_decode(item, args[0]) for item in value)
        raise SnapshotCodecError("Unsupported tuple schema")
    if isinstance(expected, type) and issubclass(expected, Enum):
        if type(value) is not str:
            raise SnapshotCodecError("Expected enum string")
        try:
            return expected(value)
        except ValueError as exc:
            raise SnapshotCodecError("Unknown enum value") from exc
    if isinstance(expected, type) and is_dataclass(expected):
        if not isinstance(value, dict):
            raise SnapshotCodecError("Expected object")
        hints = get_type_hints(expected)
        keys = set(hints)
        if expected in _TAGS:
            keys.add("type")
            if value.get("type") != _TAGS[expected]:
                raise SnapshotCodecError("Unknown or incorrect union discriminator")
        if set(value) != keys:
            raise SnapshotCodecError("Missing or unexpected snapshot fields")
        result = expected(**{name: _decode(value[name], hint) for name, hint in hints.items()})
        _validate(result)
        return result
    if expected in (str, int, bool, type(None)) and type(value) is expected:
        return value
    raise SnapshotCodecError("Incorrect snapshot value type")


def _validate(value: object) -> None:
    if isinstance(value, model.SnapshotMetadata) and value.schema_version != 1:
        raise SnapshotCodecError("Only snapshot schema version 1 is supported")
    if isinstance(value, model.ResponseContract):
        if value.state is model.ResponseStateKind.SUPPORTED:
            valid = value.shape is not None and value.policy is not None and value.reason is None
        elif value.state is model.ResponseStateKind.UNSUPPORTED:
            valid = value.shape is None and value.policy is not None and bool(value.reason)
        else:
            valid = value.shape is None and value.policy is None and value.reason is None
        if not valid:
            raise SnapshotCodecError("Inconsistent response state")
    if isinstance(value, model.FieldSelection):
        if value.completeness is model.Completeness.INCOMPLETE:
            if not value.incomplete_reason:
                raise SnapshotCodecError("Incomplete selection requires a reason")
        elif (
            not isinstance(value.root, model.ObjectSelection) or value.incomplete_reason is not None
        ):
            raise SnapshotCodecError("Invalid complete selection")
    if isinstance(value, (model.ObjectShape, model.ObjectSelection)):
        names = [
            field.logical_name if isinstance(field, model.ObjectField) else field.name
            for field in value.fields
        ]
        if names != sorted(set(names)):
            raise SnapshotCodecError("Fields must have unique canonical ordering")
    if isinstance(value, model.RouteContract) and value.key.method != value.match_key.method:
        raise SnapshotCodecError("Route methods disagree")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SnapshotCodecError("Duplicate JSON key")
        result[key] = value
    return result


def _invalid_constant(value: str) -> Any:
    raise SnapshotCodecError(f"Invalid JSON constant: {value}")


class CanonicalJsonSnapshotCodec:
    def encode(self, snapshot: model.ContractSnapshot) -> str:
        try:
            payload = _encode(snapshot)
            _decode(payload, model.ContractSnapshot)
            return json.dumps(
                payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
            )
        except (TypeError, ValueError, RecursionError) as exc:
            raise SnapshotCodecError(str(exc)) from exc

    def decode(self, text: str) -> model.ContractSnapshot:
        try:
            payload = json.loads(
                text, object_pairs_hook=_unique_object, parse_constant=_invalid_constant
            )
            result = _decode(payload, model.ContractSnapshot)
            if not isinstance(result, model.ContractSnapshot):
                raise SnapshotCodecError("Expected contract snapshot")
            return result
        except (TypeError, ValueError, RecursionError) as exc:
            raise SnapshotCodecError(str(exc)) from exc
