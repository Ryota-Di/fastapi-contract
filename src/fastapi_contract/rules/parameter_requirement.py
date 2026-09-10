"""Missing-input requirement tightening only on the same unique parameter binding."""

from collections import Counter

from fastapi_contract.domain.blocker import BlockerCode, FactBlocker
from fastapi_contract.domain.facts import RouteFacts
from fastapi_contract.domain.finding import (
    CompatibilityImpact,
    EvidenceSide,
    Finding,
    ParameterRequirementEvidence,
    ScopedBlocker,
    evidence_side,
)
from fastapi_contract.domain.parameters import ParameterVisibility
from fastapi_contract.rules.parameter_binding import (
    ParameterRegionIndex,
    hidden_possible,
    parameter_index,
    signature,
)


class ParameterRequirementRule:
    owner = "hidden-parameter-requirement"

    def check(self, before: RouteFacts, after: RouteFacts) -> tuple[Finding, ...]:
        old, new = parameter_index(before.parameters), parameter_index(after.parameters)
        old_regions = ParameterRegionIndex(before.parameters)
        new_regions = ParameterRegionIndex(after.parameters)
        findings = []
        for key in sorted(old.keys() & new.keys()):
            # Old hidden collisions belong to binding; a newly hidden requirement is independent.
            if len(old[key]) != 1 or len(new[key]) != 1:
                if (
                    not hidden_possible(old[key])
                    and hidden_possible(new[key])
                    and signature(old[key]) != signature(new[key])
                    and Counter((o.required, o.requirement_blocker) for o in old[key])
                    != Counter((o.required, o.requirement_blocker) for o in new[key])
                    and any(o.required is not True for o in old[key])
                    and any(o.required is not False for o in new[key])
                ):
                    findings.append(
                        Finding(
                            self.owner,
                            CompatibilityImpact.UNKNOWN,
                            after.key,
                            ParameterRequirementEvidence(
                                key.location,
                                key.wire_name,
                                None,
                                None,
                                (FactBlocker(BlockerCode.PARAMETER_COLLISION, key.wire_name),),
                                (
                                    ScopedBlocker(
                                        evidence_side(len(old[key]) > 1, len(new[key]) > 1),
                                        FactBlocker(BlockerCode.PARAMETER_COLLISION, key.wire_name),
                                    ),
                                ),
                            ),
                        )
                    )
                continue
            a, b = old[key][0], new[key][0]
            if a.visibility is b.visibility is ParameterVisibility.DOCUMENTED:
                continue
            if a.required is True or b.required is False:
                continue
            if (a.required, a.requirement_blocker) == (b.required, b.requirement_blocker):
                continue
            ar, br = old_regions.overlapping(key), new_regions.overlapping(key)
            # Changed overlapping regions are already owned by binding uncertainty.
            if Counter(ar) != Counter(br) and a.visibility is not ParameterVisibility.DOCUMENTED:
                continue
            blockers = {r.blocker for r in (*ar, *br)}
            blockers.update(v for v in (a.requirement_blocker, b.requirement_blocker) if v)
            if (
                a.visibility is not ParameterVisibility.HIDDEN
                and b.visibility is not ParameterVisibility.HIDDEN
            ):
                blockers.add(FactBlocker(BlockerCode.PARAMETER_VISIBILITY))
            findings.append(
                Finding(
                    self.owner,
                    CompatibilityImpact.UNKNOWN if blockers else CompatibilityImpact.INCOMPATIBLE,
                    after.key,
                    ParameterRequirementEvidence(
                        key.location,
                        key.wire_name,
                        a.required,
                        b.required,
                        tuple(sorted(blockers)),
                        tuple(
                            sorted(
                                [
                                    ScopedBlocker(side, r.blocker)
                                    for side, regions in (
                                        (EvidenceSide.BASELINE, ar),
                                        (EvidenceSide.CURRENT, br),
                                    )
                                    for r in regions
                                ]
                                + [
                                    ScopedBlocker(side, o.requirement_blocker)
                                    for side, o in (
                                        (EvidenceSide.BASELINE, a),
                                        (EvidenceSide.CURRENT, b),
                                    )
                                    if o.requirement_blocker
                                ]
                                + [
                                    ScopedBlocker(
                                        evidence_side(
                                            a.visibility is ParameterVisibility.UNKNOWN,
                                            b.visibility is ParameterVisibility.UNKNOWN,
                                        ),
                                        blocker,
                                    )
                                    for blocker in blockers
                                    if blocker.code is BlockerCode.PARAMETER_VISIBILITY
                                ]
                            )
                        ),
                    ),
                )
            )
        return tuple(findings)
