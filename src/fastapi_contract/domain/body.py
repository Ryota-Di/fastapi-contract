"""Top-level JSON input binding relations; no requiredness or value constraints."""

from dataclasses import dataclass
from enum import StrEnum

from fastapi_contract.domain.blocker import BlockerCode, FactBlocker


def _canonical(keys: tuple[str, ...]) -> None:
    if keys != tuple(sorted(set(keys))):
        raise ValueError("Binding keys require unique canonical ordering")


@dataclass(frozen=True)
class KnownBindingKeys:
    keys: tuple[str, ...]

    def __post_init__(self) -> None:
        _canonical(self.keys)


@dataclass(frozen=True)
class UnknownBindingKeys:
    blocker: FactBlocker
    # Dependency scope only: these keys MIGHT participate. Never accepted-key facts.
    possible_keys: tuple[str, ...] | None

    def __post_init__(self) -> None:
        if self.blocker.code not in (
            BlockerCode.BODY_ALIAS,
            BlockerCode.BODY_VALIDATION,
            BlockerCode.BODY_DOCUMENTATION,
        ):
            raise ValueError("Invalid body slot blocker")
        if self.possible_keys is not None:
            _canonical(self.possible_keys)


@dataclass(frozen=True)
class BodyInputSlotFact:
    diagnostic_name: str
    anchor_key: str | None
    accepted_binding_keys: KnownBindingKeys | UnknownBindingKeys

    def __post_init__(self) -> None:
        if isinstance(self.accepted_binding_keys, KnownBindingKeys) and self.anchor_key is None:
            raise ValueError("Known binding requires a resolved anchor")


class BodyBindingKind(StrEnum):
    ABSENT = "absent"
    MODEL = "model"
    OUTSIDE_SLICE = "outside_slice"


@dataclass(frozen=True)
class BodyBindingFacts:
    kind: BodyBindingKind
    slots: tuple[BodyInputSlotFact, ...] = ()
    blockers: tuple[FactBlocker, ...] = ()

    def __post_init__(self) -> None:
        if self.kind is not BodyBindingKind.MODEL and self.slots:
            raise ValueError("Only model body facts carry slots")
        if (self.kind is BodyBindingKind.OUTSIDE_SLICE) != bool(self.blockers):
            raise ValueError("Only outside-slice bodies require surface blockers")
        if any(
            b.code
            not in (
                BlockerCode.BODY_INPUT,
                BlockerCode.BODY_VALIDATION,
                BlockerCode.BODY_DOCUMENTATION,
                BlockerCode.BODY_RUNTIME,
            )
            for b in self.blockers
        ):
            raise ValueError("Invalid body surface blocker")
        names = tuple(s.diagnostic_name for s in self.slots)
        _canonical(names)
        if self.blockers != tuple(sorted(set(self.blockers))):
            raise ValueError("Body blockers require unique canonical ordering")
