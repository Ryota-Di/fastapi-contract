from collections import UserDict
from types import MappingProxyType

import pytest

from fastapi_contract.adapters.fastapi import normalize_top_level_selection
from fastapi_contract.codec.json import CanonicalJsonSnapshotCodec
from fastapi_contract.domain.model import Completeness, ObjectSelection, WholeSelection


@pytest.mark.parametrize("factory", [dict, UserDict, MappingProxyType])
@pytest.mark.parametrize(
    "mapping",
    [{}, {"email": True}, {"email": Ellipsis}, {"email": True, "id": Ellipsis}],
)
def test_flat_mapping_canonicalizes_to_equivalent_field_collection(factory, mapping) -> None:
    actual = normalize_top_level_selection(factory(mapping))

    assert actual == normalize_top_level_selection(set(mapping))
    assert actual is not None
    assert actual.completeness is Completeness.COMPLETE
    assert isinstance(actual.root, ObjectSelection)
    assert tuple(entry.name for entry in actual.root.fields) == tuple(sorted(mapping))
    assert all(isinstance(entry.selection, WholeSelection) for entry in actual.root.fields)


@pytest.mark.parametrize(
    "mapping",
    [
        {"email": False},
        {"email": 1},
        {"email": None},
        {"email": {}},
        {"profile": {"email": True}},
        {"__all__": True},
        {0: Ellipsis},
        {"id": True, "profile": {"email": Ellipsis}},
    ],
)
def test_unsupported_mapping_is_incomplete(mapping) -> None:
    actual = normalize_top_level_selection(mapping)

    assert actual is not None
    assert actual.completeness is Completeness.INCOMPLETE
    assert actual.incomplete_reason


def test_nested_mapping_structure_survives_snapshot_codec() -> None:
    # Import locally to keep the regression focused on the public codec boundary.
    from tests.support import route, snapshot

    variants = [
        {"profile": {"email": True}},
        {"profile": {"name": True}},
        {"profile": {"email": Ellipsis}},
        {"profile": {"email": False}},
        {"profile": {"email": 1}},
        UserDict({"profile": MappingProxyType({"email": {0: True}})}),
    ]
    codec = CanonicalJsonSnapshotCodec()
    selections = [normalize_top_level_selection(value) for value in variants]

    assert len(set(selections)) == len(variants)
    for selection in selections:
        assert selection is not None
        assert selection.completeness is Completeness.INCOMPLETE
        original = snapshot(route(exclude=selection))
        assert codec.decode(codec.encode(original)) == original


@pytest.mark.parametrize("key", ["__all__", 0])
def test_unsupported_mapping_retains_mapping_structure(key) -> None:
    import json

    from fastapi_contract.domain.model import UnsupportedSelection

    result = normalize_top_level_selection({key: True})

    assert result is not None
    assert result.completeness is Completeness.INCOMPLETE
    assert isinstance(result.root, UnsupportedSelection)
    preserved = json.loads(result.root.canonical_value)
    assert preserved == ["dict", [[[type(key).__name__, key], ["bool", True]]]]
