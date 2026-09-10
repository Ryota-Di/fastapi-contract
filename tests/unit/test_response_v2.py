import json
from dataclasses import replace
from pathlib import Path

import pytest

from fastapi_contract.application.checker import CheckStatus
from fastapi_contract.application.response import ResponseFactChecker
from fastapi_contract.codec.json import (
    CanonicalJsonSnapshotCodec,
    SnapshotCodecError,
    snapshot_schema_version,
)
from fastapi_contract.codec.schema_v2 import SnapshotV2Codec, SnapshotV2Document
from fastapi_contract.domain.body import BodyBindingFacts, BodyBindingKind
from fastapi_contract.domain.facts import (
    BlockerCode,
    CanonicalSnapshot,
    FactBlocker,
    ProjectionFact,
    ProjectionState,
    ResponseFacts,
    ResponseSlotFact,
    RouteFacts,
)
from fastapi_contract.domain.model import EnvironmentSnapshot, RouteKey, RouteMatchKey
from fastapi_contract.reporting.text import TextReporter


def slot(name, *, wire=None, state=ProjectionState.INCLUDED, blocker=None):
    return ResponseSlotFact(name, wire or name, wire or name, ProjectionFact(state, blocker))


def snapshot(*slots, blockers=()):
    return CanonicalSnapshot(
        EnvironmentSnapshot("3.12", "f", "s", "p"),
        (
            RouteFacts(
                RouteKey("GET", "/x"),
                RouteMatchKey("GET", "^/x$"),
                ResponseFacts(tuple(sorted(slots, key=lambda s: s.diagnostic_name)), blockers),
                BodyBindingFacts(BodyBindingKind.ABSENT),
            ),
        ),
    )


def test_published_v1_golden_is_frozen():
    original = (Path(__file__).parents[1] / "fixtures/schema-v1.json").read_text()
    codec = CanonicalJsonSnapshotCodec()
    decoded = codec.decode(original)
    assert type(decoded).__module__ == "fastapi_contract.compat.v1.model"
    assert codec.encode(decoded) == original


def test_v2_roundtrip_transport_metadata_and_duplicate_contributors():
    facts = snapshot(slot("a", wire="id"), slot("b", wire="id"))
    document = SnapshotV2Document(facts, "arbitrary-producer")
    codec = SnapshotV2Codec()
    encoded = codec.encode(document)
    assert codec.decode(encoded) == document
    assert codec.encode(codec.decode(encoded)) == encoded
    assert len(codec.decode(encoded).facts.routes[0].response.slots) == 2
    assert "schema_version" not in CanonicalSnapshot.__dataclass_fields__
    assert "tool_version" not in CanonicalSnapshot.__dataclass_fields__


@pytest.mark.parametrize("version", [True, False, 2.0, "2", None, 1, 999])
def test_v2_exact_version_gate(version):
    codec = SnapshotV2Codec()
    payload = json.loads(codec.encode(snapshot(slot("x"))))
    payload["metadata"]["schema_version"] = version
    with pytest.raises(SnapshotCodecError):
        codec.decode(json.dumps(payload))


@pytest.mark.parametrize("version", [True, 2.0, "2", None, 999])
def test_dispatch_exact_version_gate(version):
    with pytest.raises(SnapshotCodecError):
        snapshot_schema_version(json.dumps({"metadata": {"schema_version": version}}))


@pytest.mark.parametrize(
    "path",
    [
        (),
        ("metadata",),
        ("application",),
        ("application", "routes", 0),
        ("application", "routes", 0, "response"),
        ("application", "routes", 0, "response", "slots", 0),
        ("application", "routes", 0, "response", "slots", 0, "projection"),
    ],
)
@pytest.mark.parametrize("mutation", ["missing", "extra"])
def test_v2_exact_fields_at_every_level(path, mutation):
    codec = SnapshotV2Codec()
    payload = json.loads(codec.encode(snapshot(slot("x"))))
    target = payload
    for key in path:
        target = target[key]
    if mutation == "missing":
        target.pop(next(iter(target)))
    else:
        target["unexpected"] = None
    with pytest.raises(SnapshotCodecError):
        codec.decode(json.dumps(payload))


@pytest.mark.parametrize(
    "state,blocker",
    [
        ("included", {"code": "unsupported_response_selector", "fingerprint": "x"}),
        ("excluded", {"code": "unsupported_response_selector", "fingerprint": "x"}),
        ("unknown", None),
        ("invented", None),
        ("unknown", {"code": "made_up", "fingerprint": "x"}),
    ],
)
def test_v2_projection_invariants(state, blocker):
    codec = SnapshotV2Codec()
    payload = json.loads(codec.encode(snapshot(slot("x"))))
    payload["application"]["routes"][0]["response"]["slots"][0]["projection"] = {
        "state": state,
        "blocker": blocker,
    }
    with pytest.raises(SnapshotCodecError):
        codec.decode(json.dumps(payload))


def test_duplicate_json_keys_rejected_before_dispatch_and_decode():
    text = (
        SnapshotV2Codec()
        .encode(snapshot(slot("x")))
        .replace('"schema_version":2', '"schema_version":2,"schema_version":2')
    )
    for decoder in (SnapshotV2Codec().decode, snapshot_schema_version):
        with pytest.raises(SnapshotCodecError, match="Duplicate JSON key"):
            decoder(text)


def test_canonical_slot_order_validation():
    codec = SnapshotV2Codec()
    payload = json.loads(codec.encode(snapshot(slot("a"), slot("b"))))
    payload["application"]["routes"][0]["response"]["slots"].reverse()
    with pytest.raises(SnapshotCodecError, match="canonical"):
        codec.decode(json.dumps(payload))


def test_candidate_local_unknown_does_not_hide_confirmed_sibling_loss():
    blocked = FactBlocker(BlockerCode.UNSUPPORTED_SELECTOR, "nested")
    old = snapshot(slot("id"), slot("notes"), slot("other"))
    new = snapshot(
        slot("id"),
        slot("notes", state=ProjectionState.EXCLUDED),
        slot("other", state=ProjectionState.UNKNOWN, blocker=blocked),
    )
    result = ResponseFactChecker().check(old, new)
    assert result.status is CheckStatus.BREAKING
    assert next(
        f for f in result.findings if f.evidence.lost_wire_keys
    ).evidence.lost_wire_keys == ("notes",)
    assert next(f for f in result.findings if f.evidence.blockers).evidence.blockers == (blocked,)
    assert "notes" in TextReporter().render(result)
    assert "unsupported_response_selector" in TextReporter().render(result)


def test_unknown_is_not_absence_and_preserves_relevant_change_identity():
    first = slot(
        "notes",
        state=ProjectionState.UNKNOWN,
        blocker=FactBlocker(BlockerCode.UNSUPPORTED_SELECTOR, "one"),
    )
    second = replace(
        first,
        projection=ProjectionFact(
            ProjectionState.UNKNOWN, FactBlocker(BlockerCode.UNSUPPORTED_SELECTOR, "two")
        ),
    )
    checker = ResponseFactChecker()
    assert checker.check(snapshot(slot("notes")), snapshot(first)).status is CheckStatus.REVIEW
    assert checker.check(snapshot(first), snapshot(first)).status is CheckStatus.SAFE
    assert checker.check(snapshot(first), snapshot(second)).status is CheckStatus.REVIEW


def test_active_collision_is_local_and_breaking_precedes_review():
    old = snapshot(
        slot("a", wire="id"), slot("b", wire="id", state=ProjectionState.EXCLUDED), slot("notes")
    )
    new = snapshot(
        slot("a", wire="id"), slot("b", wire="id"), slot("notes", state=ProjectionState.EXCLUDED)
    )
    result = ResponseFactChecker().check(old, new)
    assert result.status is CheckStatus.BREAKING
    assert next(
        f for f in result.findings if f.evidence.lost_wire_keys
    ).evidence.lost_wire_keys == ("notes",)
    assert (
        next(f for f in result.findings if f.evidence.blockers).evidence.blockers[0].code
        is BlockerCode.WIRE_COLLISION
    )


def test_unchanged_collision_does_not_block_other_key_loss():
    old = snapshot(slot("a", wire="id"), slot("b", wire="id"), slot("notes"))
    new = snapshot(
        slot("a", wire="id"), slot("b", wire="id"), slot("notes", state=ProjectionState.EXCLUDED)
    )
    result = ResponseFactChecker().check(old, new)
    assert result.status is CheckStatus.BREAKING
    assert len(result.findings) == 1


def test_model_surface_override_prevents_false_breaking():
    wide = (FactBlocker(BlockerCode.MODEL_SERIALIZER),)
    old = snapshot(slot("notes"), blockers=wide)
    new = snapshot(slot("notes", state=ProjectionState.EXCLUDED), blockers=wide)
    assert ResponseFactChecker().check(old, new).status is CheckStatus.REVIEW


def test_canonical_checker_environment_and_duplicate_identity_errors():
    baseline = snapshot(slot("x"))
    checker = ResponseFactChecker()
    changed = replace(baseline, environment=replace(baseline.environment, python_version="other"))
    assert checker.check(baseline, changed).status is CheckStatus.ERROR
    duplicate = replace(baseline, routes=baseline.routes * 2)
    assert checker.check(baseline, duplicate).error.code == "AMBIGUOUS_ROUTE_IDENTITY"


def test_route_match_key_not_display_name_controls_correspondence():
    baseline = snapshot(slot("notes"))
    current = snapshot(slot("notes", state=ProjectionState.EXCLUDED))
    r = current.routes[0]
    current = replace(current, routes=(replace(r, key=RouteKey("GET", "/renamed")),))
    assert ResponseFactChecker().check(baseline, current).status is CheckStatus.BREAKING
    current = replace(current, routes=(replace(r, match_key=RouteMatchKey("GET", "^/different$")),))
    assert ResponseFactChecker().check(baseline, current).status is CheckStatus.SAFE


@pytest.mark.parametrize("placement", ["projection", "surface"])
def test_blocker_scope_cannot_be_relabelled(placement):
    codec = SnapshotV2Codec()
    payload = json.loads(codec.encode(snapshot(slot("x"))))
    response = payload["application"]["routes"][0]["response"]
    if placement == "projection":
        response["slots"][0]["projection"] = {
            "state": "unknown",
            "blocker": {"code": "model_serializer_override", "fingerprint": ""},
        }
    else:
        response["surface_blockers"] = [
            {"code": "unsupported_response_selector", "fingerprint": ""}
        ]
    with pytest.raises(SnapshotCodecError):
        codec.decode(json.dumps(payload))


def test_v2_canonical_golden():
    original = (Path(__file__).parents[1] / "fixtures/schema-v2.json").read_text()
    codec = SnapshotV2Codec()
    assert codec.encode(codec.decode(original)) == original
    assert codec.decode(original).tool_version == "fixture"


def test_canonical_route_order_and_method_agreement():
    codec = SnapshotV2Codec()
    base = snapshot(slot("x"))
    second = replace(
        base.routes[0], key=RouteKey("GET", "/z"), match_key=RouteMatchKey("GET", "^/z$")
    )
    facts = replace(base, routes=(second, *base.routes))
    payload = json.loads(codec.encode(facts))
    assert payload["application"]["routes"][0]["key"]["path"] == "/x"
    payload["application"]["routes"].reverse()
    with pytest.raises(SnapshotCodecError, match="canonical"):
        codec.decode(json.dumps(payload))
    payload["application"]["routes"].reverse()
    payload["application"]["routes"][0]["match_key"]["method"] = "POST"
    with pytest.raises(SnapshotCodecError, match="methods"):
        codec.decode(json.dumps(payload))
