"""Current route and response semantics. No framework config or transport metadata."""

from dataclasses import dataclass, field
from enum import StrEnum

from fastapi_contract.compat.v1.model import EnvironmentSnapshot, RouteKey, RouteMatchKey
from fastapi_contract.domain.blocker import BlockerCode as BlockerCode
from fastapi_contract.domain.blocker import FactBlocker as FactBlocker
from fastapi_contract.domain.body import BodyBindingFacts
from fastapi_contract.domain.parameters import ParameterFacts, unavailable_parameters


class ProjectionState(StrEnum):
    INCLUDED = "included"
    EXCLUDED = "excluded"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ProjectionFact:
    state: ProjectionState
    blocker: FactBlocker | None = None

    def __post_init__(self) -> None:
        if (self.state is ProjectionState.UNKNOWN) != (self.blocker is not None):
            raise ValueError("Unknown projection requires a blocker; known projection forbids one")
        if self.blocker and self.blocker.code not in (
            BlockerCode.UNSUPPORTED_SELECTOR,
            BlockerCode.CONDITIONAL_EXCLUSION,
        ):
            raise ValueError("Blocker is not valid for a projection fact")


@dataclass(frozen=True)
class ResponseSlotFact:
    diagnostic_name: str
    documented_wire_name: str | None
    runtime_wire_name: str
    projection: ProjectionFact


@dataclass(frozen=True)
class ResponseFacts:
    slots: tuple[ResponseSlotFact, ...] = ()
    surface_blockers: tuple[FactBlocker, ...] = ()

    def __post_init__(self) -> None:
        if any(
            b.code
            not in (
                BlockerCode.MODEL_SERIALIZER,
                BlockerCode.UNSUPPORTED_MODEL,
                BlockerCode.DOCUMENTATION_UNKNOWN,
            )
            for b in self.surface_blockers
        ):
            raise ValueError("Blocker is not valid for a response surface")


@dataclass(frozen=True)
class RouteFacts:
    key: RouteKey
    match_key: RouteMatchKey
    response: ResponseFacts
    # None means not observed in programmatic inputs; final v2 transport rejects it.
    body_binding: BodyBindingFacts | None = None
    parameters: ParameterFacts = field(default_factory=unavailable_parameters)


@dataclass(frozen=True)
class CanonicalSnapshot:
    environment: EnvironmentSnapshot
    routes: tuple[RouteFacts, ...]
