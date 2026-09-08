import json

import pytest
from tests.support import route, selection, snapshot

from fastapi_contract.codec.json import CanonicalJsonSnapshotCodec, SnapshotCodecError
from fastapi_contract.domain.model import ResponseStateKind


def test_snapshot_round_trip_preserves_domain_value() -> None:
    original = snapshot(route(fields=("id", "email"), exclude=selection("email")))
    codec = CanonicalJsonSnapshotCodec()

    decoded = codec.decode(codec.encode(original))

    assert decoded == original


def test_snapshot_round_trip_preserves_explicit_unsupported_state() -> None:
    original = snapshot(
        route(
            response_state=ResponseStateKind.UNSUPPORTED,
            exclude=selection("email"),
            unsupported_reason="nested response model",
        )
    )
    codec = CanonicalJsonSnapshotCodec()

    decoded = codec.decode(codec.encode(original))

    assert decoded == original
    decoded_response = decoded.application.routes[0].contract.response
    assert decoded_response.state is ResponseStateKind.UNSUPPORTED
    assert decoded_response.reason == "nested response model"


def test_snapshot_encoding_is_deterministic() -> None:
    value = snapshot(route(fields=("id", "name", "email"), exclude=selection("name", "email")))
    codec = CanonicalJsonSnapshotCodec()

    first = codec.encode(value)
    second = codec.encode(value)

    assert first == second


def test_none_and_empty_selection_remain_distinct_snapshot_encodings() -> None:
    codec = CanonicalJsonSnapshotCodec()
    absent = codec.encode(snapshot(route(exclude=None)))
    empty = codec.encode(snapshot(route(exclude=selection())))

    assert absent != empty


def test_snapshot_encoding_preserves_utf8_text_without_ascii_escape() -> None:
    value = snapshot(route(fields=("id", "名前"), exclude=selection("名前")))

    encoded = CanonicalJsonSnapshotCodec().encode(value)

    assert "名前" in encoded


def test_union_nodes_have_explicit_type_discriminators() -> None:
    value = snapshot(route(fields=("id", "email"), exclude=selection("email")))
    payload = json.loads(CanonicalJsonSnapshotCodec().encode(value))

    response = payload["application"]["routes"][0]["contract"]["response"]
    assert response["shape"]["type"] == "object"
    assert response["policy"]["exclude"]["root"]["type"] == "object_selection"
    first_selection = response["policy"]["exclude"]["root"]["fields"][0]["selection"]
    assert first_selection["type"] == "whole_selection"


def test_unknown_union_discriminator_fails_closed() -> None:
    value = snapshot(route(fields=("id", "email"), exclude=selection("email")))
    codec = CanonicalJsonSnapshotCodec()
    payload = json.loads(codec.encode(value))
    payload["application"]["routes"][0]["contract"]["response"]["shape"]["type"] = "mystery"

    with pytest.raises(SnapshotCodecError):
        codec.decode(json.dumps(payload, separators=(",", ":"), sort_keys=True))


def test_schema_version_mismatch_fails_closed() -> None:
    value = snapshot(route())
    codec = CanonicalJsonSnapshotCodec()
    payload = json.loads(codec.encode(value))
    payload["metadata"]["schema_version"] = 999

    with pytest.raises(SnapshotCodecError):
        codec.decode(json.dumps(payload, separators=(",", ":"), sort_keys=True))


@pytest.mark.parametrize(
    "malformed",
    [
        "",
        "{",
        "[]",
        '{"metadata": {}}',
    ],
)
def test_malformed_snapshot_fails_closed(malformed: str) -> None:
    with pytest.raises(SnapshotCodecError):
        CanonicalJsonSnapshotCodec().decode(malformed)
