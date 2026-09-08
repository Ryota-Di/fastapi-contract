"""One-time, lossless normalization at the extraction boundary."""

import json
from collections.abc import Mapping

from fastapi_contract.domain.model import (
    Completeness,
    FieldSelection,
    ObjectSelection,
    SelectionEntry,
    UnsupportedSelection,
    WholeSelection,
)


def _preserve(value: object) -> object:
    if value is Ellipsis:
        return ["ellipsis"]
    if value is None or type(value) in (str, int, bool):
        return [type(value).__name__, value]
    if isinstance(value, (set, frozenset, list, tuple)):
        items = [_preserve(item) for item in value]
        if isinstance(value, (set, frozenset)):
            items.sort(key=lambda item: json.dumps(item, ensure_ascii=False))
        return [type(value).__name__, items]
    if isinstance(value, Mapping):
        entries = [[_preserve(key), _preserve(item)] for key, item in value.items()]
        entries.sort(key=lambda item: json.dumps(item[0], ensure_ascii=False))
        return ["dict", entries]
    raise ValueError(f"Cannot preserve selector value of type {type(value).__name__}")


def normalize_top_level_selection(value: object) -> FieldSelection | None:
    if value is None:
        return None
    if isinstance(value, Mapping) and all(
        type(key) is str and key != "__all__" and (item is True or item is Ellipsis)
        for key, item in value.items()
    ):
        # Pydantic uses these exact sentinels for whole-field exclusion.
        # In particular, 1 == True must not turn an unsupported value into it.
        value = tuple(value)
    if isinstance(value, (set, frozenset, list, tuple)) and all(
        type(item) is str and item != "__all__" for item in value
    ):
        names = sorted({str(item) for item in value})
        return FieldSelection(
            ObjectSelection(tuple(SelectionEntry(name, WholeSelection()) for name in names)),
            Completeness.COMPLETE,
            None,
        )
    return FieldSelection(
        UnsupportedSelection(
            json.dumps(_preserve(value), ensure_ascii=False, separators=(",", ":"))
        ),
        Completeness.INCOMPLETE,
        "Nested, reserved, or indexed response selection is unsupported in Slice 1",
    )
