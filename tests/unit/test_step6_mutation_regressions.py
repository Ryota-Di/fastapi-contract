import json
from dataclasses import replace

import pytest
from tests.support import route, selection, snapshot

from fastapi_contract.application.checker import CheckStatus, ContractChecker
from fastapi_contract.codec.json import CanonicalJsonSnapshotCodec, SnapshotCodecError
from fastapi_contract.domain.finding import CompatibilityImpact
from fastapi_contract.domain.model import (
    Completeness,
    FactoryDefault,
    FieldSelection,
    ResponseStateKind,
    StaticDefault,
    UnsupportedSelection,
)
from fastapi_contract.rules.fapi001 import Fapi001ResponseProjectionRule


def test_schema_removed_field_is_not_attributed_to_unknown_exclude() -> None:
    before = route(fields=("id", "email"))
    after = route(fields=("id",), exclude=selection("email"))

    assert Fapi001ResponseProjectionRule().check(before, after) == ()


def test_old_unsupported_shape_with_policy_change_stays_review() -> None:
    before = route(response_state=ResponseStateKind.UNSUPPORTED)
    after = route(exclude=selection("email"))

    findings = Fapi001ResponseProjectionRule().check(before, after)

    assert len(findings) == 1
    assert findings[0].impact is CompatibilityImpact.UNKNOWN
    assert findings[0].evidence.reason


def test_new_include_alone_requires_review() -> None:
    findings = Fapi001ResponseProjectionRule().check(route(), route(include=selection("id")))

    assert len(findings) == 1
    assert findings[0].impact is CompatibilityImpact.UNKNOWN
    assert findings[0].evidence.reason


def test_different_method_with_narrowing_policy_is_not_a_matched_break() -> None:
    result = ContractChecker(rules=(Fapi001ResponseProjectionRule(),)).check(
        snapshot(route(method="GET")),
        snapshot(route(method="POST", exclude=selection("email"))),
    )

    assert result.status is CheckStatus.SAFE
    assert result.findings == ()


def _all_variants_snapshot():
    value = route(fields=("factory", "required", "static"), include=selection("required"))
    fields = value.response.shape.fields
    shape = replace(
        value.response.shape,
        fields=(
            replace(fields[0], default=FactoryDefault()),
            fields[1],
            replace(fields[2], default=StaticDefault(is_none=True)),
        ),
    )
    policy = replace(
        value.response.policy,
        exclude=FieldSelection(
            UnsupportedSelection('["dict",[]]'),
            Completeness.INCOMPLETE,
            "nested selector",
        ),
    )
    return snapshot(replace(value, response=replace(value.response, shape=shape, policy=policy)))


def _variant_nodes(value):
    if isinstance(value, dict):
        if "type" in value:
            yield value
        for item in value.values():
            yield from _variant_nodes(item)
    elif isinstance(value, list):
        for item in value:
            yield from _variant_nodes(item)


@pytest.mark.parametrize(
    "tag",
    [
        "object",
        "scalar",
        "object_selection",
        "whole_selection",
        "no_default",
        "static_default",
        "factory_default",
        "unsupported_selection",
    ],
)
@pytest.mark.parametrize("corruption", ["unknown", "missing"])
def test_every_codec_variant_requires_its_discriminator(tag, corruption) -> None:
    codec = CanonicalJsonSnapshotCodec()
    original = _all_variants_snapshot()
    assert codec.decode(codec.encode(original)) == original
    payload = json.loads(codec.encode(original))
    node = next(node for node in _variant_nodes(payload) if node["type"] == tag)
    if corruption == "unknown":
        node["type"] = "mystery"
    else:
        del node["type"]

    with pytest.raises(SnapshotCodecError):
        codec.decode(json.dumps(payload))


@pytest.mark.parametrize("location", ["root", "metadata", "response"])
def test_codec_rejects_unrecognized_fields(location) -> None:
    codec = CanonicalJsonSnapshotCodec()
    payload = json.loads(codec.encode(snapshot(route())))
    target = {
        "root": payload,
        "metadata": payload["metadata"],
        "response": payload["application"]["routes"][0]["contract"]["response"],
    }[location]
    target["unknown_contract_fact"] = True

    with pytest.raises(SnapshotCodecError):
        codec.decode(json.dumps(payload))


@pytest.mark.parametrize("version", [True, 1.0, "1", None])
def test_codec_schema_version_requires_exact_integer_type(version) -> None:
    codec = CanonicalJsonSnapshotCodec()
    payload = json.loads(codec.encode(snapshot(route())))
    payload["metadata"]["schema_version"] = version

    with pytest.raises(SnapshotCodecError):
        codec.decode(json.dumps(payload))


@pytest.mark.parametrize("side", ["baseline", "current"])
def test_checker_rejects_unsupported_schema_without_codec(side) -> None:
    baseline = snapshot(route())
    current = snapshot(route(exclude=selection("email")))
    if side == "baseline":
        baseline = replace(baseline, metadata=replace(baseline.metadata, schema_version=2))
    else:
        current = replace(current, metadata=replace(current.metadata, schema_version=2))

    result = ContractChecker(rules=(Fapi001ResponseProjectionRule(),)).check(baseline, current)

    assert result.status is CheckStatus.ERROR
    assert result.error is not None
    assert result.error.code == "INCOMPATIBLE_SCHEMA"
    assert result.findings == ()
