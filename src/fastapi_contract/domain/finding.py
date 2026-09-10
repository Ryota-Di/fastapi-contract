"""Rule evidence and compatibility impact, separate from observed facts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from fastapi_contract.domain.facts import FactBlocker
from fastapi_contract.domain.model import RouteKey
from fastapi_contract.domain.parameters import ParameterLocation, ParameterRegion


class CompatibilityImpact(StrEnum):
    INCOMPATIBLE = "incompatible"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class FieldPath:
    segments: tuple[str, ...]


@dataclass(frozen=True)
class ProjectionEvidence:
    removed_fields: tuple[FieldPath, ...] = ()
    reason: str | None = None


@dataclass(frozen=True)
class Finding:
    rule_id: str
    impact: CompatibilityImpact
    route: RouteKey
    evidence: (
        ProjectionEvidence
        | ResponseEvidence
        | BodyBindingEvidence
        | ParameterBindingEvidence
        | ParameterRequirementEvidence
    )


@dataclass(frozen=True)
class ResponseEvidence:
    lost_wire_keys: tuple[str, ...] = ()
    blockers: tuple[FactBlocker, ...] = ()
    losses: tuple[ResponseLossContext, ...] = ()
    candidates: tuple[ResponseCandidate, ...] = ()


@dataclass(frozen=True, order=True)
class BodyBindingRelation:
    wire_key: str
    anchor_key: str


@dataclass(frozen=True)
class BodyBindingEvidence:
    lost_bindings: tuple[BodyBindingRelation, ...] = ()
    uncertain_bindings: tuple[BodyBindingRelation, ...] = ()
    blockers: tuple[FactBlocker, ...] = ()
    candidates: tuple[BodyCandidate, ...] = ()


@dataclass(frozen=True)
class ParameterBindingEvidence:
    location: ParameterLocation | None
    wire_name: str | None
    blockers: tuple[FactBlocker, ...] = ()
    candidate_region: ParameterRegion | None = None
    scoped_blockers: tuple[ScopedBlocker, ...] = ()


@dataclass(frozen=True)
class ParameterRequirementEvidence:
    location: ParameterLocation
    wire_name: str
    before_required: bool | None
    after_required: bool | None
    blockers: tuple[FactBlocker, ...] = ()
    scoped_blockers: tuple[ScopedBlocker, ...] = ()


class EvidenceSide(StrEnum):
    BASELINE = "baseline"
    CURRENT = "current"
    BOTH = "both"


@dataclass(frozen=True, order=True)
class ScopedBlocker:
    side: EvidenceSide
    blocker: FactBlocker


class ResponseOwnership(StrEnum):
    DOCUMENTED_KEY_RETAINED = "documented_key_retained"
    RUNTIME_KEY_UNDOCUMENTED = "runtime_key_undocumented"


@dataclass(frozen=True, order=True)
class ResponseLossContext:
    wire_key: str
    ownership: ResponseOwnership


@dataclass(frozen=True)
class ResponseCandidate:
    wire_key: str | None
    diagnostic_slots: tuple[str, ...]
    blockers: tuple[ScopedBlocker, ...]


@dataclass(frozen=True)
class BodyCandidate:
    wire_key: str | None
    anchor_key: str | None
    diagnostic_slots: tuple[str, ...]
    blockers: tuple[ScopedBlocker, ...]


def evidence_side(baseline: bool, current: bool) -> EvidenceSide:
    """Provenance for a comparison-derived blocker present on at least one side."""
    if not baseline and not current:
        raise ValueError("Evidence requires an affected side")
    if baseline and current:
        return EvidenceSide.BOTH
    return EvidenceSide.BASELINE if baseline else EvidenceSide.CURRENT
