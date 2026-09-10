"""Deterministic consumer evidence, with the published legacy format preserved."""

import json

from fastapi_contract.application.checker import CheckResult, CheckStatus
from fastapi_contract.domain.finding import (
    BodyBindingEvidence,
    ParameterBindingEvidence,
    ParameterRequirementEvidence,
    ProjectionEvidence,
    ResponseEvidence,
    ResponseOwnership,
    ScopedBlocker,
)
from fastapi_contract.domain.finding_order import candidate_order, finding_sort_key


def _quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=True)


def _blockers(values: tuple[ScopedBlocker, ...]) -> str:
    return ", ".join(f"{b.blocker.code.value} ({b.side.value})" for b in sorted(values))


class TextReporter:
    def render(self, result: CheckResult) -> str:
        if result.status is CheckStatus.ERROR:
            if result.error is None:
                return "ERROR: Missing analysis error details"
            return f"ERROR {result.error.code}: {result.error.message}"
        if result.status is CheckStatus.SAFE:
            return "SAFE: No incompatibility detected in the supported contract surface."
        lines = [result.status.value]
        legacy = all(isinstance(f.evidence, ProjectionEvidence) for f in result.findings)
        findings = result.findings if legacy else sorted(result.findings, key=finding_sort_key)
        for finding in findings:
            route = f"{finding.route.method} {finding.route.path}"
            prefix = f"{finding.rule_id} {route}: "
            e = finding.evidence
            if isinstance(e, (ParameterBindingEvidence, ParameterRequirementEvidence)):
                if e.location is not None and e.wire_name is not None:
                    candidate = f"hidden {e.location.value} parameter {_quote(e.wire_name)}"
                elif isinstance(e, ParameterBindingEvidence) and e.candidate_region is not None:
                    region = e.candidate_region
                    if region.possible_keys is not None:
                        candidate = "parameter region possibly containing " + ", ".join(
                            f"{k.location.value} {_quote(k.wire_name)}"
                            for k in region.possible_keys
                        )
                    else:
                        candidate = (
                            "/".join(v.value for v in region.possible_locations)
                            + " parameter region (wire identity unresolved)"
                        )
                else:
                    candidate = "parameter region (wire identity unresolved)"
                if e.blockers:
                    lines.append(
                        prefix + f"Cannot confirm {candidate}: " + _blockers(e.scoped_blockers)
                    )
                elif isinstance(e, ParameterRequirementEvidence):
                    lines.append(
                        prefix + f"Hidden {e.location.value} parameter {_quote(e.wire_name)} "
                        "changed from optional to required."
                    )
                else:
                    assert e.location is not None and e.wire_name is not None
                    lines.append(
                        prefix + f"Hidden {e.location.value} parameter {_quote(e.wire_name)} "
                        "is no longer bound."
                    )
            elif isinstance(e, BodyBindingEvidence):
                for relation in sorted(e.lost_bindings):
                    lines.append(
                        prefix + f"Request body key {_quote(relation.wire_key)} "
                        f"is no longer bound to input slot {_quote(relation.anchor_key)}."
                    )
                for candidate_body in sorted(e.candidates, key=candidate_order):
                    if candidate_body.wire_key is not None:
                        name = f"body key {_quote(candidate_body.wire_key)}"
                    else:
                        name = "body input (wire identity unresolved)"
                    if candidate_body.anchor_key is not None:
                        name += f" at input slot {_quote(candidate_body.anchor_key)}"
                    elif candidate_body.diagnostic_slots:
                        name += " at diagnostic slot " + ", ".join(
                            _quote(s) for s in sorted(candidate_body.diagnostic_slots)
                        )
                    lines.append(
                        prefix + f"Cannot confirm {name}: " + _blockers(candidate_body.blockers)
                    )
            elif isinstance(e, ResponseEvidence):
                for loss in sorted(e.losses):
                    ownership = (
                        "key remains documented by OpenAPI"
                        if loss.ownership is ResponseOwnership.DOCUMENTED_KEY_RETAINED
                        else "old runtime key was not documented by OpenAPI"
                    )
                    lines.append(
                        prefix
                        + f"Response wire key {_quote(loss.wire_key)} is no longer produced; "
                        f"{ownership}."
                    )
                for candidate_response in sorted(e.candidates, key=candidate_order):
                    name = (
                        f"response wire key {_quote(candidate_response.wire_key)}"
                        if candidate_response.wire_key is not None
                        else "response surface (wire identity unresolved)"
                    )
                    lines.append(
                        prefix + f"Cannot confirm {name}: " + _blockers(candidate_response.blockers)
                    )
            else:
                # Published FAPI001 text is deliberately byte-preserved.
                if e.reason:
                    detail = f"reason: {e.reason}"
                else:
                    removed = ", ".join(".".join(path.segments) for path in e.removed_fields)
                    detail = f"response fields removed by projection: {removed}"
                lines.append(prefix + detail)
        return "\n".join(lines)
