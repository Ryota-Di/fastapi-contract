"""Explicit, strict parameter transport mapping for the final v2 schema."""

from typing import Any

from fastapi_contract.codec.schema_v1 import SnapshotCodecError
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
)


def _object(value: Any, keys: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != set(keys.split()):
        raise SnapshotCodecError("Missing or unexpected parameter fields")
    return value


def _string(value: Any) -> str:
    if type(value) is not str:
        raise SnapshotCodecError("Expected parameter string")
    return str(value)


def _array(value: Any) -> list[Any]:
    if not isinstance(value, list):
        raise SnapshotCodecError("Expected parameter array")
    return value


def _blocker(value: Any) -> FactBlocker | None:
    if value is None:
        return None
    b = _object(value, "code fingerprint")
    return FactBlocker(BlockerCode(_string(b["code"])), _string(b["fingerprint"]))


def _key(value: Any) -> ParameterKey:
    k = _object(value, "location wire_name")
    return ParameterKey(ParameterLocation(_string(k["location"])), _string(k["wire_name"]))


def _region(value: Any) -> ParameterRegion:
    r = _object(value, "possible_locations possible_keys blocker visibility")
    blocker = _blocker(r["blocker"])
    if blocker is None:
        raise SnapshotCodecError("Unknown region requires blocker")
    return ParameterRegion(
        tuple(ParameterLocation(_string(v)) for v in _array(r["possible_locations"])),
        None if r["possible_keys"] is None else tuple(_key(v) for v in _array(r["possible_keys"])),
        blocker,
        ParameterVisibility(_string(r["visibility"])),
    )


def decode_parameters(value: Any) -> ParameterFacts:
    facts = _object(value, "coverage occurrences unresolved_regions")
    occurrences = []
    for raw in _array(facts["occurrences"]):
        o = _object(raw, "diagnostic_origin origin_kind binding required visibility")
        b = o["binding"]
        if not isinstance(b, dict):
            raise SnapshotCodecError("Expected parameter binding object")
        binding: ParameterKey | ParameterRegion
        if b.get("kind") == "known":
            b = _object(b, "kind key")
            binding = _key(b["key"])
        elif b.get("kind") == "unknown":
            b = _object(b, "kind region")
            binding = _region(b["region"])
        else:
            raise SnapshotCodecError("Unknown parameter binding discriminator")
        required = _object(o["required"], "value blocker")
        visibility = _object(o["visibility"], "state blocker")
        occurrences.append(
            ParameterOccurrence(
                _string(o["diagnostic_origin"]),
                ParameterOrigin(_string(o["origin_kind"])),
                binding,
                required["value"],
                ParameterVisibility(_string(visibility["state"])),
                _blocker(required["blocker"]),
                _blocker(visibility["blocker"]),
            )
        )
    return ParameterFacts(
        tuple(occurrences),
        tuple(_region(r) for r in _array(facts["unresolved_regions"])),
        ParameterCoverage(_string(facts["coverage"])),
    )


def _blocker_json(value: FactBlocker | None) -> dict[str, str] | None:
    return None if value is None else {"code": value.code.value, "fingerprint": value.fingerprint}


def _key_json(key: ParameterKey) -> dict[str, str]:
    return {"location": key.location.value, "wire_name": key.wire_name}


def _region_json(region: ParameterRegion) -> dict[str, Any]:
    return {
        "possible_locations": [v.value for v in region.possible_locations],
        "possible_keys": None
        if region.possible_keys is None
        else [_key_json(k) for k in region.possible_keys],
        "blocker": _blocker_json(region.blocker),
        "visibility": region.visibility.value,
    }


def encode_parameters(facts: ParameterFacts) -> dict[str, Any]:
    return {
        "coverage": facts.coverage.value,
        "occurrences": [
            {
                "diagnostic_origin": o.diagnostic_origin,
                "origin_kind": o.origin_kind.value,
                "binding": {"kind": "known", "key": _key_json(o.binding)}
                if isinstance(o.binding, ParameterKey)
                else {"kind": "unknown", "region": _region_json(o.binding)},
                "required": {"value": o.required, "blocker": _blocker_json(o.requirement_blocker)},
                "visibility": {
                    "state": o.visibility.value,
                    "blocker": _blocker_json(o.visibility_blocker),
                },
            }
            for o in facts.occurrences
        ],
        "unresolved_regions": [_region_json(r) for r in facts.unresolved_regions],
    }
