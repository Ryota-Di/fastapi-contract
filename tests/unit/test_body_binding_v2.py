import json
from dataclasses import replace
from pathlib import Path

import pytest
from tests.unit.test_response_v2 import snapshot as response_snapshot

from fastapi_contract.application.checker import CheckStatus
from fastapi_contract.application.response import ContractFactChecker
from fastapi_contract.codec.json import SnapshotCodecError
from fastapi_contract.codec.schema_v2 import SnapshotV2Codec, SnapshotV2Document
from fastapi_contract.domain.body import (
    BodyBindingFacts,
    BodyBindingKind,
    BodyInputSlotFact,
    KnownBindingKeys,
    UnknownBindingKeys,
)
from fastapi_contract.domain.facts import BlockerCode, FactBlocker
from fastapi_contract.domain.finding import BodyBindingRelation


def slot(name="user_id", anchor="userId", keys=("userId", "user_id")):
    return BodyInputSlotFact(name, anchor, KnownBindingKeys(tuple(sorted(keys))))


def snapshot(*slots, body=None):
    base = response_snapshot()
    body = body or BodyBindingFacts(
        BodyBindingKind.MODEL, tuple(sorted(slots, key=lambda s: s.diagnostic_name))
    )
    return replace(base, routes=(replace(base.routes[0], body_binding=body),))


def encoded_payload():
    return json.loads(SnapshotV2Codec().encode(snapshot(slot())))


def test_body_profile_roundtrip_and_metadata_preservation():
    codec = SnapshotV2Codec()
    original = SnapshotV2Document(snapshot(slot()), "producer")
    text = codec.encode(original)
    assert codec.decode(text) == original
    assert codec.encode(codec.decode(text)) == text
    assert "fact_profile" not in json.loads(text)["metadata"]
    assert "diagnostic_name" in text


def test_new_body_golden():
    text = (Path(__file__).parents[1] / "fixtures/schema-v2-body.json").read_text()
    codec = SnapshotV2Codec()
    assert codec.encode(codec.decode(text)) == text
    assert codec.decode(text).facts.routes[0].body_binding.kind is BodyBindingKind.MODEL


@pytest.mark.parametrize(
    "path",
    [
        ("metadata",),
        ("application", "routes", 0),
        ("application", "routes", 0, "body_binding"),
        ("application", "routes", 0, "body_binding", "slots", 0),
        ("application", "routes", 0, "body_binding", "slots", 0, "accepted_binding_keys"),
    ],
)
@pytest.mark.parametrize("mode", ["missing", "extra"])
def test_exact_body_transport_fields(path, mode):
    payload = encoded_payload()
    target = payload
    for key in path:
        target = target[key]
    if mode == "extra":
        target["unknown_field"] = False
    elif path == ("metadata",):
        target.pop("schema_version")
    elif path == ("application", "routes", 0):
        target.pop("body_binding")
    else:
        target.pop(next(iter(target)))
    with pytest.raises(SnapshotCodecError):
        SnapshotV2Codec().decode(json.dumps(payload))


@pytest.mark.parametrize(
    "binding",
    [
        {"kind": "known", "keys": ["z", "a"]},
        {"kind": "known", "keys": ["a", "a"]},
        {"kind": "known", "keys": [True]},
        {"kind": "known", "keys": "a"},
        {"kind": "known", "keys": ["a"], "blocker": None},
        {"kind": "unknown", "blocker": None, "possible_keys": None},
        {
            "kind": "unknown",
            "blocker": {"code": "model_serializer_override", "fingerprint": ""},
            "possible_keys": None,
        },
        {
            "kind": "unknown",
            "blocker": {"code": "unsupported_body_alias_form", "fingerprint": ""},
            "possible_keys": ["x", "x"],
        },
        {"kind": "invented", "keys": []},
        None,
    ],
)
def test_binding_discriminator_and_invariants(binding):
    payload = encoded_payload()
    payload["application"]["routes"][0]["body_binding"]["slots"][0]["accepted_binding_keys"] = (
        binding
    )
    with pytest.raises(SnapshotCodecError):
        SnapshotV2Codec().decode(json.dumps(payload))


@pytest.mark.parametrize(
    "kind,slots_present,blockers",
    [
        ("absent", True, []),
        ("outside_slice", True, []),
        ("outside_slice", False, []),
        ("model", True, [{"code": "unsupported_body_input", "fingerprint": ""}]),
        ("outside_slice", False, [{"code": "unsupported_body_alias_form", "fingerprint": ""}]),
        ("absent", False, [{"code": "unsupported_body_input", "fingerprint": ""}]),
        ("unknown", False, []),
    ],
)
def test_body_kind_and_blocker_scope(kind, slots_present, blockers):
    payload = encoded_payload()
    body = payload["application"]["routes"][0]["body_binding"]
    body["kind"] = kind
    body["blockers"] = blockers
    if not slots_present:
        body["slots"] = []
    with pytest.raises(SnapshotCodecError):
        SnapshotV2Codec().decode(json.dumps(payload))


def test_unknown_scope_roundtrips_without_becoming_known_binding():
    unknown = BodyInputSlotFact(
        "sibling",
        None,
        UnknownBindingKeys(
            FactBlocker(BlockerCode.BODY_ALIAS, "structure-fingerprint"), ("legacy", "other")
        ),
    )
    document = SnapshotV2Document(snapshot(slot(), unknown), "test")
    codec = SnapshotV2Codec()
    assert codec.decode(codec.encode(document)) == document


def test_duplicate_binding_json_keys_are_rejected():
    text = (
        SnapshotV2Codec()
        .encode(snapshot(slot()))
        .replace('"kind":"known"', '"kind":"known","kind":"known"')
    )
    with pytest.raises(SnapshotCodecError, match="Duplicate JSON key"):
        SnapshotV2Codec().decode(text)


def test_slot_order_and_unresolved_known_anchor_rejected():
    payload = encoded_payload()
    entry = payload["application"]["routes"][0]["body_binding"]["slots"][0]
    entry["anchor_key"] = None
    with pytest.raises(SnapshotCodecError):
        SnapshotV2Codec().decode(json.dumps(payload))
    facts = snapshot(slot("a"), slot("b"))
    payload = json.loads(SnapshotV2Codec().encode(facts))
    payload["application"]["routes"][0]["body_binding"]["slots"].reverse()
    with pytest.raises(SnapshotCodecError, match="canonical"):
        SnapshotV2Codec().decode(json.dumps(payload))


def test_doubled_anchor_is_local_review_only_for_changed_relations():
    before = snapshot(
        slot("a", "x", ("a", "x")),
        slot("b", "x", ("b", "x")),
        slot("ok", "okAlias", ("ok", "okAlias")),
    )
    after = snapshot(
        slot("a", "x", ("x",)), slot("b", "x", ("x",)), slot("ok", "okAlias", ("okAlias",))
    )
    result = ContractFactChecker().check(before, after)
    assert result.status is CheckStatus.BREAKING
    assert next(f for f in result.findings if f.evidence.lost_bindings).evidence.lost_bindings == (
        BodyBindingRelation("ok", "okAlias"),
    )
    review = next(f for f in result.findings if f.evidence.blockers).evidence
    assert {r.wire_key for r in review.uncertain_bindings} == {"a", "b"}
    assert review.blockers[0].code is BlockerCode.BODY_COLLISION
    codec = SnapshotV2Codec()
    assert len(codec.decode(codec.encode(before)).facts.routes[0].body_binding.slots) == 3


def test_relation_direction_and_no_acceptance_rule():
    before, after = snapshot(slot()), snapshot(slot(keys=("userId",)))
    checker = ContractFactChecker()
    assert checker.check(before, after).status is CheckStatus.BREAKING
    assert checker.check(after, before).status is CheckStatus.SAFE
    assert {f.rule_id for f in checker.check(before, after).findings} == {"request-body-binding"}


def test_unobserved_pr1_body_is_not_silently_absent():
    base = response_snapshot()
    old = replace(base, routes=(replace(base.routes[0], body_binding=None),))
    result = ContractFactChecker().check(old, snapshot(slot()))
    assert result.status is CheckStatus.REVIEW
    assert result.findings[0].evidence.blockers[0].code is BlockerCode.BODY_UNOBSERVED
    codec = SnapshotV2Codec()
    with pytest.raises(SnapshotCodecError, match="observed body"):
        codec.encode(old)


def test_body_duplicate_profile_or_unknown_profile_is_rejected():
    payload = encoded_payload()
    payload["metadata"]["fact_profile"] = "unknown-profile"
    with pytest.raises(SnapshotCodecError):
        SnapshotV2Codec().decode(json.dumps(payload))


def test_no_global_review_for_unchanged_unsupported_sibling():
    unknown = BodyInputSlotFact(
        "sibling", None, UnknownBindingKeys(FactBlocker(BlockerCode.BODY_ALIAS, "x"), ("other",))
    )
    before, after = snapshot(slot(), unknown), snapshot(slot(keys=("userId",)), unknown)
    result = ContractFactChecker().check(before, after)
    assert result.status is CheckStatus.BREAKING
    assert len(result.findings) == 1
