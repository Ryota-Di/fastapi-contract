"""Hidden declared-input binding loss; identity is location plus canonical wire name."""

from collections import Counter, defaultdict

from fastapi_contract.domain.blocker import BlockerCode, FactBlocker
from fastapi_contract.domain.facts import RouteFacts
from fastapi_contract.domain.finding import (
    CompatibilityImpact,
    EvidenceSide,
    Finding,
    ParameterBindingEvidence,
    ScopedBlocker,
    evidence_side,
)
from fastapi_contract.domain.parameters import (
    ParameterFacts,
    ParameterKey,
    ParameterLocation,
    ParameterOccurrence,
    ParameterRegion,
    ParameterVisibility,
    region_order,
)


def parameter_index(facts: ParameterFacts) -> dict[ParameterKey, list[ParameterOccurrence]]:
    index: dict[ParameterKey, list[ParameterOccurrence]] = defaultdict(list)
    for occurrence in facts.occurrences:
        if isinstance(occurrence.binding, ParameterKey):
            index[occurrence.binding].append(occurrence)
    return index


class ParameterRegionIndex:
    """Index bounded uncertainty without scanning unrelated regions for each candidate."""

    def __init__(self, facts: ParameterFacts) -> None:
        self.keys: dict[ParameterKey, list[ParameterRegion]] = defaultdict(list)
        self.locations: dict[ParameterLocation, list[ParameterRegion]] = defaultdict(list)
        for region in facts.regions():
            if region.possible_keys is None:
                for location in region.possible_locations:
                    self.locations[location].append(region)
            else:
                for key in region.possible_keys:
                    self.keys[key].append(region)

    def overlapping(self, key: ParameterKey) -> tuple[ParameterRegion, ...]:
        return tuple(self.keys.get(key, ())) + tuple(self.locations.get(key.location, ()))


def signature(occurrences: list[ParameterOccurrence]) -> Counter[tuple[object, ...]]:
    return Counter(o.semantic_signature() for o in occurrences)


def hidden_possible(occurrences: list[ParameterOccurrence]) -> bool:
    return any(o.visibility is not ParameterVisibility.DOCUMENTED for o in occurrences)


class ParameterBindingRule:
    owner = "hidden-parameter-binding"

    def check(self, before: RouteFacts, after: RouteFacts) -> tuple[Finding, ...]:
        old, new = parameter_index(before.parameters), parameter_index(after.parameters)
        old_regions = ParameterRegionIndex(before.parameters)
        new_regions = ParameterRegionIndex(after.parameters)
        findings = []
        addressed: set[ParameterKey] = set()
        for key in sorted(old):
            a, b = old[key], new.get(key, [])
            if not hidden_possible(a):
                continue
            ar, br = old_regions.overlapping(key), new_regions.overlapping(key)
            if signature(a) == signature(b) and Counter(ar) == Counter(br):
                continue
            collision = len(a) > 1 or len(b) > 1
            # A unique surviving binding does not change merely because requirement/visibility did.
            if len(a) == len(b) == 1 and Counter(ar) == Counter(br):
                continue
            blockers = {r.blocker for r in (*ar, *br)}
            if collision:
                blockers.add(FactBlocker(BlockerCode.PARAMETER_COLLISION, key.wire_name))
            if any(o.visibility is ParameterVisibility.UNKNOWN for o in a):
                blockers.add(FactBlocker(BlockerCode.PARAMETER_VISIBILITY))
            if blockers:
                impact = CompatibilityImpact.UNKNOWN
            elif not b:
                impact = CompatibilityImpact.INCOMPATIBLE
            else:
                continue
            addressed.add(key)
            findings.append(
                Finding(
                    self.owner,
                    impact,
                    after.key,
                    ParameterBindingEvidence(
                        key.location,
                        key.wire_name,
                        tuple(sorted(blockers)),
                        scoped_blockers=tuple(
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
                                    ScopedBlocker(evidence_side(len(a) > 1, len(b) > 1), blocker)
                                    for blocker in blockers
                                    if blocker.code is BlockerCode.PARAMETER_COLLISION
                                ]
                                + [
                                    ScopedBlocker(EvidenceSide.BASELINE, blocker)
                                    for blocker in blockers
                                    if blocker.code is BlockerCode.PARAMETER_VISIBILITY
                                ]
                            )
                        ),
                    ),
                )
            )

        # Lost/changed unknown identities cannot be manufactured into named binding losses.
        lost_regions = Counter(before.parameters.regions()) - Counter(after.parameters.regions())
        for region in sorted(lost_regions, key=region_order):
            if region.visibility is ParameterVisibility.DOCUMENTED:
                continue
            if any(region.overlaps(key) for key in addressed):
                continue
            findings.append(
                Finding(
                    self.owner,
                    CompatibilityImpact.UNKNOWN,
                    after.key,
                    ParameterBindingEvidence(
                        None,
                        None,
                        (region.blocker,),
                        region,
                        (ScopedBlocker(EvidenceSide.BASELINE, region.blocker),),
                    ),
                )
            )
        return tuple(findings)
