import json
from dataclasses import replace
from itertools import permutations

import pytest
from tests.unit.test_body_binding_v2 import slot as body_slot
from tests.unit.test_body_binding_v2 import snapshot as body_snapshot
from tests.unit.test_parameter_facts import occurrence, region
from tests.unit.test_parameter_facts import snapshot as parameter_snapshot
from tests.unit.test_response_v2 import slot, snapshot

from fastapi_contract.application.checker import CheckResult, CheckStatus
from fastapi_contract.application.response import ContractFactChecker
from fastapi_contract.domain.blocker import BlockerCode, FactBlocker
from fastapi_contract.domain.facts import ProjectionFact, ProjectionState
from fastapi_contract.domain.finding import (
    CompatibilityImpact,
    EvidenceSide,
    ResponseOwnership,
)
from fastapi_contract.domain.finding_order import finding_sort_key
from fastapi_contract.reporting.text import TextReporter


@pytest.mark.parametrize("name", ['a"b', "a\\b", "a\nb", "名前", "", "a.b"])
def test_all_wire_evidence_uses_json_escaping(name):
    response = replace(
        slot("diagnostic_python_name"), runtime_wire_name=name, documented_wire_name=name
    )
    before = snapshot(response)
    after = snapshot(replace(response, projection=ProjectionFact(ProjectionState.EXCLUDED)))
    checker = ContractFactChecker()
    response_result = checker.check(before, after)
    body_result = checker.check(
        body_snapshot(body_slot(keys=(name,))), body_snapshot(body_slot(keys=()))
    )
    parameter_result = checker.check(parameter_snapshot(occurrence(name)), parameter_snapshot())
    requirement_result = checker.check(
        parameter_snapshot(occurrence(name)), parameter_snapshot(occurrence(name, required=True))
    )
    for result in (response_result, body_result, parameter_result, requirement_result):
        output = TextReporter().render(result)
        assert result.status is CheckStatus.BREAKING
        assert json.dumps(name, ensure_ascii=True) in output
        assert len(output.splitlines()) == 2
        assert "diagnostic_python_name" not in output


def test_response_ownership_is_produced_by_rule():
    old = replace(slot("user_id"), runtime_wire_name="user_id", documented_wire_name="userId")
    new = replace(old, runtime_wire_name="userId")
    result = ContractFactChecker().check(snapshot(old), snapshot(new))
    assert (
        result.findings[0].evidence.losses[0].ownership
        is ResponseOwnership.RUNTIME_KEY_UNDOCUMENTED
    )
    assert "old runtime key was not documented by OpenAPI" in TextReporter().render(result)


def test_blockers_remain_attached_to_each_response_candidate_and_side():
    old = snapshot(slot("a"), slot("b"), slot("lost"))
    after = snapshot(
        slot(
            "a",
            state=ProjectionState.UNKNOWN,
            blocker=FactBlocker(BlockerCode.UNSUPPORTED_SELECTOR, "opaque-a"),
        ),
        slot(
            "b",
            state=ProjectionState.UNKNOWN,
            blocker=FactBlocker(BlockerCode.CONDITIONAL_EXCLUSION, "opaque-b"),
        ),
        slot("lost", state=ProjectionState.EXCLUDED),
    )
    result = ContractFactChecker().check(old, after)
    assert result.status is CheckStatus.BREAKING
    review = next(f for f in result.findings if f.impact is CompatibilityImpact.UNKNOWN)
    assert [
        (c.wire_key, c.blockers[0].side, c.blockers[0].blocker.code)
        for c in review.evidence.candidates
    ] == [
        ("a", EvidenceSide.CURRENT, BlockerCode.UNSUPPORTED_SELECTOR),
        ("b", EvidenceSide.CURRENT, BlockerCode.CONDITIONAL_EXCLUSION),
    ]
    lines = TextReporter().render(result).splitlines()
    assert any('"a": unsupported_response_selector (current)' in line for line in lines)
    assert any('"b": conditional_field_exclusion (current)' in line for line in lines)
    assert not any('"a": conditional_field_exclusion' in line for line in lines)
    assert "opaque" not in "\n".join(lines)


def test_unknown_parameter_region_does_not_invent_wire_key():
    before = parameter_snapshot(regions=(region(),))
    after = parameter_snapshot()
    result = ContractFactChecker().check(before, after)
    output = TextReporter().render(result)
    assert result.status is CheckStatus.REVIEW
    assert "query parameter region (wire identity unresolved)" in output
    assert "header" not in output and "cookie" not in output
    assert 'parameter "' not in output


def test_bounded_unknown_parameter_region_reports_possible_keys_only():
    result = ContractFactChecker().check(
        parameter_snapshot(regions=(region("token"),)), parameter_snapshot()
    )
    output = TextReporter().render(result)
    assert 'region possibly containing query "token"' in output
    assert "is no longer bound" not in output


def test_finding_order_independent_of_insertion_and_nested_evidence_order():
    checker = ContractFactChecker()
    first = checker.check(snapshot(slot("z")), snapshot(slot("z", state=ProjectionState.EXCLUDED)))
    second = checker.check(parameter_snapshot(occurrence()), parameter_snapshot())
    third = checker.check(body_snapshot(body_slot()), body_snapshot(body_slot(keys=("userId",))))
    findings = first.findings + second.findings + third.findings
    outputs = {
        TextReporter().render(CheckResult(CheckStatus.BREAKING, order))
        for order in permutations(findings)
    }
    assert len(outputs) == 1
    assert sorted(findings, key=finding_sort_key) == sorted(
        reversed(findings), key=finding_sort_key
    )


def test_error_suppresses_partial_findings():
    from fastapi_contract.application.checker import AnalysisError

    loss = ContractFactChecker().check(
        snapshot(slot("x")), snapshot(slot("x", state=ProjectionState.EXCLUDED))
    )
    error = CheckResult(
        CheckStatus.ERROR, loss.findings, AnalysisError("ANALYSIS_FAILED", "failed")
    )
    assert TextReporter().render(error) == "ERROR ANALYSIS_FAILED: failed"


def test_collision_provenance_reports_only_affected_side():
    old = snapshot(
        slot("left", wire="key"), slot("right", wire="key", state=ProjectionState.EXCLUDED)
    )
    new = snapshot(slot("left", wire="key"), slot("right", wire="key"))
    result = ContractFactChecker().check(old, new)
    candidate = result.findings[0].evidence.candidates[0]
    assert candidate.blockers[0].side is EvidenceSide.CURRENT
    assert "response_wire_collision (current)" in TextReporter().render(result)
