"""Explicit v2 wire schema; no reflection over canonical domain dataclasses."""

import json
from dataclasses import dataclass
from importlib.metadata import version
from typing import Any

from fastapi_contract.codec.parameter_v2 import decode_parameters, encode_parameters
from fastapi_contract.codec.schema_v1 import SnapshotCodecError, _invalid_constant, _unique_object
from fastapi_contract.domain.body import (
    BodyBindingFacts,
    BodyBindingKind,
    BodyInputSlotFact,
    KnownBindingKeys,
    UnknownBindingKeys,
)
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


@dataclass(frozen=True)
class SnapshotV2Document:
    facts: CanonicalSnapshot
    tool_version: str


def _object(value: Any, keys: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != set(keys.split()):
        raise SnapshotCodecError("Missing or unexpected v2 fields")
    return value


def _string(value: Any) -> str:
    if type(value) is not str:
        raise SnapshotCodecError("Expected string")
    return str(value)


def _array(value: Any) -> list[Any]:
    if not isinstance(value, list):
        raise SnapshotCodecError("Expected array")
    return value


def _blocker(value: Any) -> FactBlocker:
    item = _object(value, "code fingerprint")
    return FactBlocker(BlockerCode(_string(item["code"])), _string(item["fingerprint"]))


def _blocker_json(blocker: FactBlocker) -> dict[str, str]:
    return {"code": blocker.code.value, "fingerprint": blocker.fingerprint}


def _decode_body(value: Any) -> BodyBindingFacts:
    body = _object(value, "kind slots blockers")
    slots = []
    for entry in _array(body["slots"]):
        s = _object(entry, "diagnostic_name anchor_key accepted_binding_keys")
        value_keys = s["accepted_binding_keys"]
        if not isinstance(value_keys, dict):
            raise SnapshotCodecError("Expected binding keys object")
        binding: KnownBindingKeys | UnknownBindingKeys
        if value_keys.get("kind") == "known":
            k = _object(value_keys, "kind keys")
            binding = KnownBindingKeys(tuple(_string(key) for key in _array(k["keys"])))
        elif value_keys.get("kind") == "unknown":
            k = _object(value_keys, "kind blocker possible_keys")
            binding = UnknownBindingKeys(
                _blocker(k["blocker"]),
                None
                if k["possible_keys"] is None
                else tuple(_string(key) for key in _array(k["possible_keys"])),
            )
        else:
            raise SnapshotCodecError("Unknown body binding discriminator")
        slots.append(
            BodyInputSlotFact(
                _string(s["diagnostic_name"]),
                None if s["anchor_key"] is None else _string(s["anchor_key"]),
                binding,
            )
        )
    return BodyBindingFacts(
        BodyBindingKind(_string(body["kind"])),
        tuple(slots),
        tuple(_blocker(b) for b in _array(body["blockers"])),
    )


def _encode_body(body: BodyBindingFacts | None) -> dict[str, Any]:
    if body is None:
        raise SnapshotCodecError("Final v2 requires observed body binding facts")

    def keys(value: KnownBindingKeys | UnknownBindingKeys) -> dict[str, Any]:
        if isinstance(value, KnownBindingKeys):
            return {"kind": "known", "keys": list(value.keys)}
        return {
            "kind": "unknown",
            "blocker": _blocker_json(value.blocker),
            "possible_keys": list(value.possible_keys) if value.possible_keys is not None else None,
        }

    return {
        "kind": body.kind.value,
        "slots": [
            {
                "diagnostic_name": s.diagnostic_name,
                "anchor_key": s.anchor_key,
                "accepted_binding_keys": keys(s.accepted_binding_keys),
            }
            for s in body.slots
        ],
        "blockers": [_blocker_json(b) for b in body.blockers],
    }


def _decode(payload: Any) -> SnapshotV2Document:
    root = _object(payload, "metadata application")
    meta = _object(root["metadata"], "schema_version tool_version environment")
    if type(meta["schema_version"]) is not int or meta["schema_version"] != 2:
        raise SnapshotCodecError("Expected exact integer schema version 2")
    env = _object(
        meta["environment"], "python_version fastapi_version starlette_version pydantic_version"
    )
    environment = EnvironmentSnapshot(
        *(
            _string(env[k])
            for k in ("python_version", "fastapi_version", "starlette_version", "pydantic_version")
        )
    )
    application = _object(root["application"], "routes")
    routes = []
    for value in _array(application["routes"]):
        r = _object(value, "key match_key response body_binding parameters")
        key = _object(r["key"], "method path")
        match = _object(r["match_key"], "method normalized_path_regex")
        response = _object(r["response"], "slots surface_blockers")
        slots = []
        for entry in _array(response["slots"]):
            s = _object(entry, "diagnostic_name documented_wire_name runtime_wire_name projection")
            p = _object(s["projection"], "state blocker")
            projection = ProjectionFact(
                ProjectionState(_string(p["state"])),
                None if p["blocker"] is None else _blocker(p["blocker"]),
            )
            slots.append(
                ResponseSlotFact(
                    _string(s["diagnostic_name"]),
                    None
                    if s["documented_wire_name"] is None
                    else _string(s["documented_wire_name"]),
                    _string(s["runtime_wire_name"]),
                    projection,
                )
            )
        names = [s.diagnostic_name for s in slots]
        if names != sorted(set(names)):
            raise SnapshotCodecError("Slots require unique canonical diagnostic ordering")
        blockers = tuple(_blocker(b) for b in _array(response["surface_blockers"]))
        if blockers != tuple(sorted(set(blockers))):
            raise SnapshotCodecError("Blockers require unique canonical ordering")
        route = RouteFacts(
            RouteKey(_string(key["method"]), _string(key["path"])),
            RouteMatchKey(_string(match["method"]), _string(match["normalized_path_regex"])),
            ResponseFacts(tuple(slots), blockers),
            _decode_body(r["body_binding"]),
            decode_parameters(r["parameters"]),
        )
        if route.key.method != route.match_key.method:
            raise SnapshotCodecError("Route methods disagree")
        routes.append(route)
    keys = [(r.match_key, r.key) for r in routes]
    if keys != sorted(keys):
        raise SnapshotCodecError("Routes require canonical ordering")
    # Duplicate runtime identities are preserved for application-level ERROR, just as v1.
    return SnapshotV2Document(
        CanonicalSnapshot(environment, tuple(routes)),
        _string(meta["tool_version"]),
    )


class SnapshotV2Codec:
    def encode(self, value: CanonicalSnapshot | SnapshotV2Document) -> str:
        document = (
            value
            if isinstance(value, SnapshotV2Document)
            else SnapshotV2Document(value, version("fastapi-contract"))
        )
        env = document.facts.environment
        payload = {
            "metadata": {
                "schema_version": 2,
                "tool_version": document.tool_version,
                "environment": {
                    "python_version": env.python_version,
                    "fastapi_version": env.fastapi_version,
                    "starlette_version": env.starlette_version,
                    "pydantic_version": env.pydantic_version,
                },
            },
            "application": {
                "routes": [
                    {
                        "key": {"method": r.key.method, "path": r.key.path},
                        "body_binding": _encode_body(r.body_binding),
                        "parameters": encode_parameters(r.parameters),
                        "match_key": {
                            "method": r.match_key.method,
                            "normalized_path_regex": r.match_key.normalized_path_regex,
                        },
                        "response": {
                            "slots": [
                                {
                                    "diagnostic_name": s.diagnostic_name,
                                    "documented_wire_name": s.documented_wire_name,
                                    "runtime_wire_name": s.runtime_wire_name,
                                    "projection": {
                                        "state": s.projection.state.value,
                                        "blocker": _blocker_json(s.projection.blocker)
                                        if s.projection.blocker
                                        else None,
                                    },
                                }
                                for s in sorted(r.response.slots, key=lambda s: s.diagnostic_name)
                            ],
                            "surface_blockers": [
                                _blocker_json(b) for b in sorted(r.response.surface_blockers)
                            ],
                        },
                    }
                    for r in sorted(document.facts.routes, key=lambda r: (r.match_key, r.key))
                ]
            },
        }
        try:
            _decode(payload)
            return json.dumps(
                payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
            )
        except (TypeError, ValueError, RecursionError) as exc:
            raise SnapshotCodecError(str(exc)) from exc

    def decode(self, text: str) -> SnapshotV2Document:
        try:
            return _decode(
                json.loads(text, object_pairs_hook=_unique_object, parse_constant=_invalid_constant)
            )
        except (TypeError, ValueError, RecursionError) as exc:
            raise SnapshotCodecError(str(exc)) from exc
