"""Compare resolved key-to-slot relations, never framework configuration or Python identity."""

from collections import defaultdict

from fastapi_contract.domain.blocker import BlockerCode, FactBlocker
from fastapi_contract.domain.body import (
    BodyBindingFacts,
    BodyBindingKind,
    BodyInputSlotFact,
    KnownBindingKeys,
    UnknownBindingKeys,
)
from fastapi_contract.domain.facts import RouteFacts
from fastapi_contract.domain.finding import (
    BodyBindingEvidence,
    BodyBindingRelation,
    BodyCandidate,
    CompatibilityImpact,
    EvidenceSide,
    Finding,
    ScopedBlocker,
    evidence_side,
)


def binding_surface(body: BodyBindingFacts) -> dict[str, tuple[BodyInputSlotFact, ...]]:
    result: dict[str, list[BodyInputSlotFact]] = defaultdict(list)
    for slot in body.slots:
        keys = slot.accepted_binding_keys
        if isinstance(keys, KnownBindingKeys):
            for key in keys.keys:
                result[key].append(slot)
    return {key: tuple(slots) for key, slots in result.items()}


def _anchors(body: BodyBindingFacts) -> dict[str, tuple[BodyInputSlotFact, ...]]:
    result: dict[str, list[BodyInputSlotFact]] = defaultdict(list)
    for slot in body.slots:
        if slot.anchor_key is not None:
            result[slot.anchor_key].append(slot)
    return {key: tuple(slots) for key, slots in result.items()}


def _unknown_for(body: BodyBindingFacts, key: str) -> tuple[FactBlocker, ...]:
    return tuple(
        s.accepted_binding_keys.blocker
        for s in body.slots
        if isinstance(s.accepted_binding_keys, UnknownBindingKeys)
        and (
            s.accepted_binding_keys.possible_keys is None
            or key in s.accepted_binding_keys.possible_keys
        )
    )


def _signature(slots: tuple[BodyInputSlotFact, ...]) -> tuple[str, ...]:
    # Preserve duplicate contributors, while ignoring reporting-only Python names.
    return tuple(sorted(s.anchor_key for s in slots if s.anchor_key is not None))


class BodyBindingRule:
    def check(self, before: RouteFacts, after: RouteFacts) -> tuple[Finding, ...]:
        old, new = before.body_binding, after.body_binding
        if old == new:
            return ()
        if old is None or new is None:
            other = old if old is not None else new
            if other is None or other.kind is BodyBindingKind.ABSENT:
                return ()
            return (
                Finding(
                    "request-body-binding",
                    CompatibilityImpact.UNKNOWN,
                    after.key,
                    BodyBindingEvidence(
                        blockers=(FactBlocker(BlockerCode.BODY_UNOBSERVED),),
                        candidates=(
                            BodyCandidate(
                                None,
                                None,
                                (),
                                (
                                    ScopedBlocker(
                                        EvidenceSide.BASELINE
                                        if old is None
                                        else EvidenceSide.CURRENT,
                                        FactBlocker(BlockerCode.BODY_UNOBSERVED),
                                    ),
                                ),
                            ),
                        ),
                    ),
                ),
            )
        if old.kind is BodyBindingKind.OUTSIDE_SLICE or new.kind is BodyBindingKind.OUTSIDE_SLICE:
            return (
                Finding(
                    "request-body-binding",
                    CompatibilityImpact.UNKNOWN,
                    after.key,
                    BodyBindingEvidence(
                        blockers=tuple(sorted(set(old.blockers + new.blockers))),
                        candidates=(
                            BodyCandidate(
                                None,
                                None,
                                (),
                                tuple(
                                    sorted(
                                        ScopedBlocker(side, blocker)
                                        for side, facts in (
                                            (EvidenceSide.BASELINE, old),
                                            (EvidenceSide.CURRENT, new),
                                        )
                                        for blocker in facts.blockers
                                    )
                                ),
                            ),
                        ),
                    ),
                ),
            )
        # Only common documented anchors are owned; whole body/slot changes belong to OpenAPI.
        left, right = _anchors(old), _anchors(new)
        old_surface, new_surface = binding_surface(old), binding_surface(new)
        lost: set[BodyBindingRelation] = set()
        uncertain: set[BodyBindingRelation] = set()
        blockers: set[FactBlocker] = set()
        candidates: list[BodyCandidate] = []

        def blocked(
            key: str | None,
            anchor: str | None,
            scoped: tuple[ScopedBlocker, ...],
            slots: tuple[str, ...] = (),
        ) -> None:
            candidates.append(
                BodyCandidate(key, anchor, tuple(sorted(slots)), tuple(sorted(scoped)))
            )
            blockers.update(b.blocker for b in scoped)
            if key is not None and anchor is not None:
                uncertain.add(BodyBindingRelation(key, anchor))

        for anchor in sorted(left.keys() & right.keys()):
            before_slots, after_slots = left[anchor], right[anchor]
            if len(before_slots) != 1 or len(after_slots) != 1:
                keys = {
                    key
                    for s in before_slots + after_slots
                    if isinstance(s.accepted_binding_keys, KnownBindingKeys)
                    for key in s.accepted_binding_keys.keys
                }
                changed_keys = {
                    key
                    for key in keys
                    if _signature(old_surface.get(key, ())) != _signature(new_surface.get(key, ()))
                }
                if changed_keys:
                    for key in sorted(changed_keys):
                        blocked(
                            key,
                            anchor,
                            (
                                ScopedBlocker(
                                    evidence_side(len(before_slots) > 1, len(after_slots) > 1),
                                    FactBlocker(BlockerCode.BODY_COLLISION, anchor),
                                ),
                            ),
                        )
                continue
            b, a = before_slots[0].accepted_binding_keys, after_slots[0].accepted_binding_keys
            if isinstance(b, UnknownBindingKeys) or isinstance(a, UnknownBindingKeys):
                if b != a:
                    known_keys = (b.keys if isinstance(b, KnownBindingKeys) else ()) + (
                        a.keys if isinstance(a, KnownBindingKeys) else ()
                    )
                    scoped = tuple(
                        ScopedBlocker(side, k.blocker)
                        for side, k in ((EvidenceSide.BASELINE, b), (EvidenceSide.CURRENT, a))
                        if isinstance(k, UnknownBindingKeys)
                    )
                    for key in sorted(set(known_keys)):
                        blocked(key, anchor, scoped)
                    if not known_keys:
                        blocked(None, anchor, scoped)
                continue
            for key in b.keys:
                old_group, new_group = old_surface.get(key, ()), new_surface.get(key, ())
                unknown_old, unknown_new = _unknown_for(old, key), _unknown_for(new, key)
                relation_lost = key not in a.keys
                changed_context = (
                    _signature(old_group) != _signature(new_group) or unknown_old != unknown_new
                )
                if not relation_lost and not changed_context:
                    continue
                candidate = BodyBindingRelation(key, anchor)
                if unknown_old or unknown_new:
                    blocked(
                        key,
                        anchor,
                        tuple(
                            ScopedBlocker(side, b)
                            for side, values in (
                                (EvidenceSide.BASELINE, unknown_old),
                                (EvidenceSide.CURRENT, unknown_new),
                            )
                            for b in values
                        ),
                    )
                elif relation_lost:
                    lost.add(candidate)
        # An unresolved after anchor is not evidence of an ordinary documented alias removal.
        for anchor in left.keys() - right.keys():
            for slot in left[anchor]:
                binding_keys = slot.accepted_binding_keys
                if isinstance(binding_keys, KnownBindingKeys):
                    for key in binding_keys.keys:
                        relevant = _unknown_for(new, key)
                        if relevant:
                            blocked(
                                key,
                                anchor,
                                tuple(ScopedBlocker(EvidenceSide.CURRENT, b) for b in relevant),
                            )
        findings = []
        if lost:
            findings.append(
                Finding(
                    "request-body-binding",
                    CompatibilityImpact.INCOMPATIBLE,
                    after.key,
                    BodyBindingEvidence(lost_bindings=tuple(sorted(lost))),
                )
            )
        if blockers:
            findings.append(
                Finding(
                    "request-body-binding",
                    CompatibilityImpact.UNKNOWN,
                    after.key,
                    BodyBindingEvidence(
                        uncertain_bindings=tuple(sorted(uncertain)),
                        blockers=tuple(sorted(blockers)),
                        candidates=tuple(candidates),
                    ),
                )
            )
        return tuple(findings)
