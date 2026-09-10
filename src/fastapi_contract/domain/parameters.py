"""Resolved parameter identities and candidate-scoped uncertainty, without framework types."""

import json
import re
from dataclasses import dataclass
from enum import StrEnum

from fastapi_contract.domain.blocker import BlockerCode, FactBlocker


class ParameterLocation(StrEnum):
    COOKIE = "cookie"
    HEADER = "header"
    QUERY = "query"


class ParameterVisibility(StrEnum):
    HIDDEN = "hidden"
    DOCUMENTED = "documented"
    UNKNOWN = "unknown"


class ParameterOrigin(StrEnum):
    DIRECT = "direct"
    DEPENDENCY = "resolved_dependency"


class ParameterCoverage(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, order=True)
class ParameterKey:
    location: ParameterLocation
    wire_name: str

    def __post_init__(self) -> None:
        if not isinstance(self.location, ParameterLocation) or type(self.wire_name) is not str:
            raise ValueError("Invalid parameter key")
        if self.location is ParameterLocation.HEADER and (
            not re.fullmatch(r"[!#$%&'*+.^_`|~0-9a-z-]+", self.wire_name)
        ):
            raise ValueError("Header key must be a canonical ASCII field name")


REGION_CODES = frozenset(
    {
        BlockerCode.PARAMETER_BINDING,
        BlockerCode.PARAMETER_MODEL,
        BlockerCode.PARAMETER_OVERRIDE,
        BlockerCode.PARAMETER_HEADER,
        BlockerCode.PARAMETER_RUNTIME,
        BlockerCode.PARAMETER_UNOBSERVED,
    }
)


@dataclass(frozen=True)
class ParameterRegion:
    possible_locations: tuple[ParameterLocation, ...]
    possible_keys: tuple[ParameterKey, ...] | None
    blocker: FactBlocker
    visibility: ParameterVisibility = ParameterVisibility.UNKNOWN

    def __post_init__(self) -> None:
        if (
            not self.possible_locations
            or any(not isinstance(v, ParameterLocation) for v in self.possible_locations)
            or self.possible_locations != tuple(sorted(set(self.possible_locations)))
        ):
            raise ValueError("Region locations require nonempty canonical ordering")
        if self.possible_keys is not None and (
            not self.possible_keys
            or self.possible_keys != tuple(sorted(set(self.possible_keys)))
            or any(k.location not in self.possible_locations for k in self.possible_keys)
        ):
            raise ValueError("Region keys require nonempty canonical in-location keys")
        if self.blocker.code not in REGION_CODES:
            raise ValueError("Invalid parameter region blocker")
        if not isinstance(self.visibility, ParameterVisibility):
            raise ValueError("Invalid region visibility")

    def overlaps(self, key: ParameterKey) -> bool:
        return key.location in self.possible_locations and (
            self.possible_keys is None or key in self.possible_keys
        )


@dataclass(frozen=True)
class ParameterOccurrence:
    diagnostic_origin: str
    origin_kind: ParameterOrigin
    binding: ParameterKey | ParameterRegion
    required: bool | None
    visibility: ParameterVisibility
    requirement_blocker: FactBlocker | None = None
    visibility_blocker: FactBlocker | None = None

    def __post_init__(self) -> None:
        if type(self.diagnostic_origin) is not str:
            raise ValueError("Invalid diagnostic origin")
        if not isinstance(self.origin_kind, ParameterOrigin):
            raise ValueError("Invalid parameter origin")
        if not isinstance(self.binding, (ParameterKey, ParameterRegion)):
            raise ValueError("Invalid parameter binding")
        if self.required is not None and type(self.required) is not bool:
            raise ValueError("Required must be boolean or unknown")
        if (self.required is None) != (self.requirement_blocker is not None):
            raise ValueError("Unknown requiredness requires a blocker")
        if (
            self.requirement_blocker
            and self.requirement_blocker.code is not BlockerCode.PARAMETER_REQUIREMENT
        ):
            raise ValueError("Invalid requirement blocker")
        if not isinstance(self.visibility, ParameterVisibility):
            raise ValueError("Invalid visibility")
        if (self.visibility is ParameterVisibility.UNKNOWN) != (
            self.visibility_blocker is not None
        ):
            raise ValueError("Unknown visibility requires a blocker")
        if (
            self.visibility_blocker
            and self.visibility_blocker.code is not BlockerCode.PARAMETER_VISIBILITY
        ):
            raise ValueError("Invalid visibility blocker")
        if isinstance(self.binding, ParameterRegion) and self.binding.visibility != self.visibility:
            raise ValueError("Unknown binding region visibility disagrees with occurrence")

    def semantic_signature(self) -> tuple[object, ...]:
        # Deliberately excludes origin kind, dependency path and Python argument name.
        return (
            self.binding,
            self.required,
            self.visibility,
            self.requirement_blocker,
            self.visibility_blocker,
        )


def _blocker_order(value: FactBlocker | None) -> tuple[str, ...]:
    return () if value is None else (value.code.value, value.fingerprint)


def region_order(value: ParameterRegion) -> str:
    return json.dumps(
        [
            [v.value for v in value.possible_locations],
            None
            if value.possible_keys is None
            else [(k.location.value, k.wire_name) for k in value.possible_keys],
            _blocker_order(value.blocker),
            value.visibility.value,
        ],
        ensure_ascii=True,
        separators=(",", ":"),
    )


def occurrence_order(value: ParameterOccurrence) -> str:
    binding = value.binding
    return json.dumps(
        [
            ["key", binding.location.value, binding.wire_name]
            if isinstance(binding, ParameterKey)
            else ["region", region_order(binding)],
            value.required,
            value.visibility.value,
            _blocker_order(value.requirement_blocker),
            _blocker_order(value.visibility_blocker),
            value.diagnostic_origin,
            value.origin_kind.value,
        ],
        ensure_ascii=True,
        separators=(",", ":"),
    )


@dataclass(frozen=True)
class ParameterFacts:
    occurrences: tuple[ParameterOccurrence, ...]
    unresolved_regions: tuple[ParameterRegion, ...]
    coverage: ParameterCoverage

    def __post_init__(self) -> None:
        if not isinstance(self.coverage, ParameterCoverage):
            raise ValueError("Invalid parameter coverage")
        if self.occurrences != tuple(sorted(self.occurrences, key=occurrence_order)):
            raise ValueError("Occurrences require canonical ordering (multiplicity preserved)")
        if self.unresolved_regions != tuple(sorted(self.unresolved_regions, key=region_order)):
            raise ValueError("Regions require canonical ordering")
        unknown = bool(self.unresolved_regions) or any(
            isinstance(o.binding, ParameterRegion)
            or o.required is None
            or o.visibility is ParameterVisibility.UNKNOWN
            for o in self.occurrences
        )
        if (self.coverage is ParameterCoverage.COMPLETE) == unknown:
            raise ValueError("Parameter coverage disagrees with unresolved facts")
        if self.coverage is not ParameterCoverage.UNAVAILABLE and any(
            r.blocker.code in (BlockerCode.PARAMETER_UNOBSERVED, BlockerCode.PARAMETER_RUNTIME)
            for r in self.regions()
        ):
            raise ValueError("Inventory blocker requires unavailable coverage")
        if self.coverage is ParameterCoverage.UNAVAILABLE and (
            self.occurrences
            or len(self.unresolved_regions) != 1
            or self.unresolved_regions[0].possible_locations != tuple(ParameterLocation)
            or self.unresolved_regions[0].possible_keys is not None
            or self.unresolved_regions[0].visibility is not ParameterVisibility.UNKNOWN
            or self.unresolved_regions[0].blocker.code
            not in (BlockerCode.PARAMETER_UNOBSERVED, BlockerCode.PARAMETER_RUNTIME)
        ):
            raise ValueError("Unavailable surface requires one unbounded inventory blocker")

    def regions(self) -> tuple[ParameterRegion, ...]:
        return self.unresolved_regions + tuple(
            o.binding for o in self.occurrences if isinstance(o.binding, ParameterRegion)
        )


def unavailable_parameters(code: BlockerCode = BlockerCode.PARAMETER_UNOBSERVED) -> ParameterFacts:
    return ParameterFacts(
        (),
        (ParameterRegion(tuple(ParameterLocation), None, FactBlocker(code)),),
        ParameterCoverage.UNAVAILABLE,
    )
