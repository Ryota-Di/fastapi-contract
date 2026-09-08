"""Rule evidence and compatibility impact, separate from observed facts."""

from dataclasses import dataclass
from enum import StrEnum

from fastapi_contract.domain.model import RouteKey


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
    evidence: ProjectionEvidence
