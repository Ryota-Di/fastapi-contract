"""Own losses in the effective projected wire surface, excluding documented losses."""

from collections import defaultdict

from fastapi_contract.domain.facts import (
    BlockerCode,
    FactBlocker,
    ProjectionState,
    ResponseFacts,
    ResponseSlotFact,
    RouteFacts,
)
from fastapi_contract.domain.finding import (
    CompatibilityImpact,
    EvidenceSide,
    Finding,
    ResponseCandidate,
    ResponseEvidence,
    ResponseLossContext,
    ResponseOwnership,
    ScopedBlocker,
    evidence_side,
)


def surface(response: ResponseFacts) -> dict[str, tuple[ResponseSlotFact, ...]]:
    result: dict[str, list[ResponseSlotFact]] = defaultdict(list)
    for slot in response.slots:
        if slot.projection.state is not ProjectionState.EXCLUDED:
            result[slot.runtime_wire_name].append(slot)
    return {key: tuple(value) for key, value in result.items()}


def _signature(slots: tuple[ResponseSlotFact, ...]) -> tuple[tuple[str, str, str], ...]:
    # Diagnostic names are deliberately not identities.
    return tuple(
        sorted(
            (
                s.projection.state.value,
                s.projection.blocker.code.value if s.projection.blocker else "",
                s.projection.blocker.fingerprint if s.projection.blocker else "",
            )
            for s in slots
        )
    )


class ResponseSurfaceRule:
    def check(self, before: RouteFacts, after: RouteFacts) -> tuple[Finding, ...]:
        old, new = surface(before.response), surface(after.response)
        old_docs = {
            s.documented_wire_name
            for s in before.response.slots
            if s.documented_wire_name is not None
        }
        new_docs = {
            s.documented_wire_name
            for s in after.response.slots
            if s.documented_wire_name is not None
        }
        documented_losses = old_docs - new_docs
        candidates: list[ResponseCandidate] = []
        lost: list[str] = []
        losses: list[ResponseLossContext] = []
        wide = tuple(
            ScopedBlocker(side, blocker)
            for side, facts in (
                (EvidenceSide.BASELINE, before.response),
                (EvidenceSide.CURRENT, after.response),
            )
            for blocker in facts.surface_blockers
        )
        for key in sorted(old.keys() | new.keys()):
            left, right = old.get(key, ()), new.get(key, ())
            if _signature(left) == _signature(right):
                continue
            blockers = tuple(
                ScopedBlocker(side, slot.projection.blocker)
                for side, slots in ((EvidenceSide.BASELINE, left), (EvidenceSide.CURRENT, right))
                for slot in slots
                if slot.projection.blocker is not None
            )
            if len(left) > 1 or len(right) > 1:
                blockers += (
                    ScopedBlocker(
                        evidence_side(len(left) > 1, len(right) > 1),
                        FactBlocker(BlockerCode.WIRE_COLLISION, key),
                    ),
                )
            if blockers:
                candidates.append(
                    ResponseCandidate(
                        key,
                        tuple(sorted(s.diagnostic_name for s in left + right)),
                        tuple(sorted(blockers)),
                    )
                )
            elif left and not right and key not in documented_losses:
                if wide:
                    candidates.append(
                        ResponseCandidate(
                            key, tuple(sorted(s.diagnostic_name for s in left)), tuple(sorted(wide))
                        )
                    )
                else:
                    lost.append(key)
                    losses.append(
                        ResponseLossContext(
                            key,
                            ResponseOwnership.DOCUMENTED_KEY_RETAINED
                            if key in old_docs and key in new_docs
                            else ResponseOwnership.RUNTIME_KEY_UNDOCUMENTED,
                        )
                    )
        # A changed unresolved surface may have no identifiable wire candidate.
        if (
            wide
            and not candidates
            and (
                {key: _signature(slots) for key, slots in old.items()}
                != {key: _signature(slots) for key, slots in new.items()}
                or before.response.surface_blockers != after.response.surface_blockers
            )
        ):
            candidates.append(ResponseCandidate(None, (), tuple(sorted(wide))))
        findings = []
        if lost:
            findings.append(
                Finding(
                    "response-wire-surface",
                    CompatibilityImpact.INCOMPATIBLE,
                    after.key,
                    ResponseEvidence(tuple(lost), losses=tuple(losses)),
                )
            )
        if candidates:
            findings.append(
                Finding(
                    "response-wire-surface",
                    CompatibilityImpact.UNKNOWN,
                    after.key,
                    ResponseEvidence(
                        blockers=tuple(sorted({b.blocker for c in candidates for b in c.blockers})),
                        candidates=tuple(candidates),
                    ),
                )
            )
        return tuple(findings)
