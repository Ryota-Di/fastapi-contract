"""Canonical current finding order, independent of public numbering and repr."""

import json

from fastapi_contract.domain.finding import (
    BodyBindingEvidence,
    BodyCandidate,
    Finding,
    ParameterBindingEvidence,
    ParameterRequirementEvidence,
    ProjectionEvidence,
    ResponseCandidate,
    ResponseEvidence,
    ScopedBlocker,
)
from fastapi_contract.domain.parameters import region_order


def scoped_order(values: tuple[ScopedBlocker, ...]) -> tuple[tuple[str, str, str], ...]:
    return tuple(
        sorted((v.side.value, v.blocker.code.value, v.blocker.fingerprint) for v in values)
    )


def candidate_order(value: BodyCandidate | ResponseCandidate) -> str:
    return json.dumps(
        [
            value.wire_key,
            value.anchor_key if isinstance(value, BodyCandidate) else None,
            sorted(value.diagnostic_slots),
            scoped_order(value.blockers),
        ],
        ensure_ascii=True,
        separators=(",", ":"),
    )


def finding_sort_key(finding: Finding) -> tuple[str, ...]:
    e = finding.evidence
    location = ""
    candidate = ""
    detail: list[object]
    if isinstance(e, ResponseEvidence):
        candidate = json.dumps(
            sorted(e.lost_wire_keys)
            or [c.wire_key for c in sorted(e.candidates, key=candidate_order)],
            ensure_ascii=True,
        )
        detail = [
            sorted((v.wire_key, v.ownership.value) for v in e.losses),
            sorted(candidate_order(c) for c in e.candidates),
        ]
    elif isinstance(e, BodyBindingEvidence):
        candidate = json.dumps(
            sorted((v.wire_key, v.anchor_key) for v in e.lost_bindings)
            or [candidate_order(c) for c in sorted(e.candidates, key=candidate_order)],
            ensure_ascii=True,
        )
        detail = [
            sorted((v.wire_key, v.anchor_key) for v in e.uncertain_bindings),
            sorted(candidate_order(c) for c in e.candidates),
        ]
    elif isinstance(e, (ParameterBindingEvidence, ParameterRequirementEvidence)):
        location = e.location.value if e.location is not None else ""
        candidate = json.dumps(e.wire_name, ensure_ascii=True)
        detail = [scoped_order(e.scoped_blockers)]
        if isinstance(e, ParameterBindingEvidence):
            detail.append(None if e.candidate_region is None else region_order(e.candidate_region))
        else:
            detail.extend([e.before_required, e.after_required])
    else:
        assert isinstance(e, ProjectionEvidence)
        detail = [e.reason, [p.segments for p in e.removed_fields]]
    blockers = (
        []
        if isinstance(e, ProjectionEvidence)
        else sorted((b.code.value, b.fingerprint) for b in e.blockers)
    )
    return (
        finding.route.path,
        finding.route.method,
        finding.rule_id,
        location,
        candidate,
        finding.impact.value,
        json.dumps([detail, blockers], ensure_ascii=True, separators=(",", ":")),
    )
