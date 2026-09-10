import json
from dataclasses import replace

import pytest
from tests.integration.test_parameters import app, extract, spec

from fastapi_contract.application.checker import CheckStatus
from fastapi_contract.application.response import ContractFactChecker
from fastapi_contract.codec.json import SnapshotCodecError
from fastapi_contract.codec.schema_v2 import SnapshotV2Codec
from fastapi_contract.domain.blocker import BlockerCode, FactBlocker
from fastapi_contract.domain.parameters import (
    ParameterCoverage,
    ParameterFacts,
    ParameterKey,
    ParameterLocation,
    ParameterOccurrence,
    ParameterOrigin,
    ParameterRegion,
    ParameterVisibility,
    occurrence_order,
    region_order,
)


def occurrence(name="token", *, required=False, visibility=ParameterVisibility.HIDDEN):
    return ParameterOccurrence(
        name,
        ParameterOrigin.DIRECT,
        ParameterKey(ParameterLocation.QUERY, name),
        required,
        visibility,
        FactBlocker(BlockerCode.PARAMETER_REQUIREMENT) if required is None else None,
        FactBlocker(BlockerCode.PARAMETER_VISIBILITY)
        if visibility is ParameterVisibility.UNKNOWN
        else None,
    )


def snapshot(*items, regions=()):
    base = extract(app(keep=False))
    partial = regions or any(
        o.required is None
        or o.visibility is ParameterVisibility.UNKNOWN
        or isinstance(o.binding, ParameterRegion)
        for o in items
    )
    facts = ParameterFacts(
        tuple(sorted(items, key=occurrence_order)),
        tuple(sorted(regions, key=region_order)),
        ParameterCoverage.PARTIAL if partial else ParameterCoverage.COMPLETE,
    )
    return replace(base, routes=(replace(base.routes[0], parameters=facts),))


def compare(a, b):
    return ContractFactChecker().check(a, b)


def region(name=None, *, location=ParameterLocation.QUERY, fingerprint="x"):
    return ParameterRegion(
        (location,),
        None if name is None else (ParameterKey(location, name),),
        FactBlocker(BlockerCode.PARAMETER_BINDING, fingerprint),
    )


def test_unknown_requirement_does_not_block_binding_loss():
    result = compare(snapshot(occurrence(required=None)), snapshot())
    assert result.status is CheckStatus.BREAKING
    assert len(result.findings) == 1
    assert result.findings[0].rule_id == "hidden-parameter-binding"


@pytest.mark.parametrize(
    "old,new,status",
    [(None, True, "REVIEW"), (True, None, "SAFE"), (None, False, "SAFE"), (None, None, "SAFE")],
)
def test_unknown_requirement_direction(old, new, status):
    assert (
        compare(snapshot(occurrence(required=old)), snapshot(occurrence(required=new))).status.value
        == status
    )


def test_overlapping_unknown_region_blocks_only_matching_key():
    r = region("token")
    before = snapshot(occurrence(), occurrence("independent"), regions=(r,))
    after = snapshot(regions=(r,))
    result = compare(before, after)
    assert result.status is CheckStatus.BREAKING
    assert {(f.evidence.wire_name, f.impact.value) for f in result.findings} == {
        ("token", "unknown"),
        ("independent", "incompatible"),
    }


def test_overlapping_unchanged_region_blocks_requirement_when_changed():
    r = region("token")
    result = compare(
        snapshot(occurrence(), regions=(r,)), snapshot(occurrence(required=True), regions=(r,))
    )
    assert result.status is CheckStatus.REVIEW
    assert len(result.findings) == 1
    assert result.findings[0].rule_id == "hidden-parameter-requirement"


def test_changed_region_prevents_claim_of_unique_surviving_binding():
    result = compare(snapshot(occurrence()), snapshot(occurrence(), regions=(region("token"),)))
    assert result.status is CheckStatus.REVIEW
    assert result.findings[0].evidence.wire_name == "token"


def test_unknown_binding_changes_are_local_region_evidence():
    result = compare(snapshot(regions=(region(),)), snapshot())
    assert result.status is CheckStatus.REVIEW
    assert result.findings[0].evidence.location is None
    assert result.findings[0].evidence.candidate_region.possible_locations == (
        ParameterLocation.QUERY,
    )
    assert (
        compare(snapshot(regions=(region(),)), snapshot(regions=(region(),))).status
        is CheckStatus.SAFE
    )


@pytest.mark.parametrize("new_count", [0, 1, 2, 3])
def test_collision_multiplicity_policy(new_count):
    item = occurrence()
    result = compare(snapshot(item, item), snapshot(*([item] * new_count)))
    assert result.status is (CheckStatus.SAFE if new_count == 2 else CheckStatus.REVIEW)
    codec = SnapshotV2Codec()
    assert (
        len(codec.decode(codec.encode(snapshot(item, item))).facts.routes[0].parameters.occurrences)
        == 2
    )


def payload():
    return json.loads(SnapshotV2Codec().encode(extract(app(spec(alias="token"), keep=False))))


@pytest.mark.parametrize(
    "path",
    [
        (),
        ("occurrences", 0),
        ("occurrences", 0, "binding"),
        ("occurrences", 0, "binding", "key"),
        ("occurrences", 0, "required"),
        ("occurrences", 0, "visibility"),
    ],
)
@pytest.mark.parametrize("operation", ["missing", "extra"])
def test_exact_parameter_transport_fields(path, operation):
    data = payload()
    target = data["application"]["routes"][0]["parameters"]
    for part in path:
        target = target[part]
    if operation == "extra":
        target["extra"] = 1
    else:
        target.pop(next(iter(target)))
    with pytest.raises(SnapshotCodecError):
        SnapshotV2Codec().decode(json.dumps(data))


@pytest.mark.parametrize(
    "path,value",
    [
        (("coverage",), "invented"),
        (("coverage",), "partial"),
        (("coverage",), "unavailable"),
        (("occurrences", 0, "origin_kind"), "invented"),
        (("occurrences", 0, "diagnostic_origin"), None),
        (("occurrences", 0, "binding", "kind"), "invented"),
        (("occurrences", 0, "binding", "key", "location"), "path"),
        (("occurrences", 0, "binding", "key", "wire_name"), False),
        (("occurrences", 0, "required", "value"), 1),
        (("occurrences", 0, "required", "value"), None),
        (
            ("occurrences", 0, "required", "blocker"),
            {"code": "parameter_requirement_unknown", "fingerprint": ""},
        ),
        (("occurrences", 0, "visibility", "state"), "unknown"),
        (("occurrences", 0, "visibility", "state"), "invented"),
        (
            ("occurrences", 0, "visibility", "blocker"),
            {"code": "parameter_visibility_unknown", "fingerprint": ""},
        ),
    ],
)
def test_parameter_discriminators_and_invariants(path, value):
    data = payload()
    target = data["application"]["routes"][0]["parameters"]
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value
    with pytest.raises(SnapshotCodecError):
        SnapshotV2Codec().decode(json.dumps(data))


@pytest.mark.parametrize(
    "attribute,value",
    [
        ("possible_locations", []),
        ("possible_locations", ["path"]),
        ("possible_locations", ["query", "query"]),
        ("possible_locations", ["query", "header"]),
        ("possible_keys", []),
        ("possible_keys", [{"location": "header", "wire_name": "x"}]),
        ("possible_keys", [{"location": "query", "wire_name": "x"}] * 2),
        ("blocker", None),
        ("blocker", {"code": "body_binding_collision", "fingerprint": ""}),
        ("visibility", "invented"),
    ],
)
def test_malformed_unknown_regions_rejected(attribute, value):
    data = json.loads(SnapshotV2Codec().encode(snapshot(regions=(region(),))))
    target = data["application"]["routes"][0]["parameters"]["unresolved_regions"][0]
    target[attribute] = value
    with pytest.raises(SnapshotCodecError):
        SnapshotV2Codec().decode(json.dumps(data))


def test_parameter_duplicate_json_key_rejected():
    text = SnapshotV2Codec().encode(snapshot(occurrence()))
    text = text.replace('"coverage":"complete"', '"coverage":"complete","coverage":"complete"')
    with pytest.raises(SnapshotCodecError, match="Duplicate JSON key"):
        SnapshotV2Codec().decode(text)


def test_v2_profile_cannot_omit_parameters():
    data = payload()
    data["application"]["routes"][0].pop("parameters")
    with pytest.raises(SnapshotCodecError):
        SnapshotV2Codec().decode(json.dumps(data))


def test_noncanonical_parameter_order_rejected():
    data = json.loads(SnapshotV2Codec().encode(snapshot(occurrence("a"), occurrence("z"))))
    data["application"]["routes"][0]["parameters"]["occurrences"].reverse()
    with pytest.raises(SnapshotCodecError, match="canonical"):
        SnapshotV2Codec().decode(json.dumps(data))


@pytest.mark.parametrize("wire", ["X-Token", "", "é", "a b"])
def test_noncanonical_header_wire_rejected(wire):
    data = payload()
    key = data["application"]["routes"][0]["parameters"]["occurrences"][0]["binding"]["key"]
    key.update(location="header", wire_name=wire)
    with pytest.raises(SnapshotCodecError):
        SnapshotV2Codec().decode(json.dumps(data))


def test_roundtrip_independent_unknown_dimensions():
    item = occurrence(required=None, visibility=ParameterVisibility.UNKNOWN)
    facts = snapshot(item, regions=(region("other"),))
    codec = SnapshotV2Codec()
    assert codec.decode(codec.encode(facts)).facts == facts


def test_parameter_facts_cannot_be_silently_omitted_by_response_only_profile():
    facts = snapshot(occurrence())
    facts = replace(facts, routes=(replace(facts.routes[0], body_binding=None),))
    with pytest.raises(SnapshotCodecError):
        SnapshotV2Codec().encode(facts)


def test_documented_to_hidden_collision_with_independent_requirement_is_review():
    documented = occurrence(visibility=ParameterVisibility.DOCUMENTED)
    before = snapshot(documented, replace(documented, diagnostic_origin="other"))
    after = snapshot(occurrence(required=True), replace(documented, diagnostic_origin="other"))
    result = compare(before, after)
    assert result.status is CheckStatus.REVIEW
    assert len(result.findings) == 1
    assert result.findings[0].rule_id == "hidden-parameter-requirement"


@pytest.mark.parametrize(
    "code", ["parameter_binding_not_observed", "unsupported_parameter_runtime"]
)
def test_inventory_blocker_cannot_masquerade_as_partial_coverage(code):
    data = json.loads(SnapshotV2Codec().encode(snapshot(regions=(region(),))))
    data["application"]["routes"][0]["parameters"]["unresolved_regions"][0]["blocker"]["code"] = (
        code
    )
    with pytest.raises(SnapshotCodecError):
        SnapshotV2Codec().decode(json.dumps(data))


def test_parameter_golden_preserves_collisions_and_partial_coverage():
    from pathlib import Path

    text = (Path(__file__).parents[1] / "fixtures/schema-v2-parameters.json").read_text()
    codec = SnapshotV2Codec()
    document = codec.decode(text)
    assert codec.encode(document) == text
    facts = document.facts.routes[0].parameters
    assert facts.coverage is ParameterCoverage.PARTIAL
    assert len(facts.occurrences) == 2
    assert facts.occurrences[0].binding == facts.occurrences[1].binding
    assert facts.unresolved_regions[0].possible_keys is not None


def test_documented_collision_visibility_alone_does_not_own_requirement():
    optional = occurrence(visibility=ParameterVisibility.DOCUMENTED)
    required = replace(optional, diagnostic_origin="other", required=True)
    before = snapshot(optional, required)
    after = snapshot(replace(optional, visibility=ParameterVisibility.HIDDEN), required)
    assert compare(before, after).status is CheckStatus.SAFE
