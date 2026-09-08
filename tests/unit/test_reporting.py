from tests.support import route, selection, snapshot

from fastapi_contract.application.checker import ContractChecker
from fastapi_contract.reporting.text import TextReporter
from fastapi_contract.rules.fapi001 import Fapi001ResponseProjectionRule


def _result(baseline, current):  # type: ignore[no-untyped-def]
    checker = ContractChecker(rules=(Fapi001ResponseProjectionRule(),))
    return checker.check(baseline, current)


def test_breaking_report_contains_actionable_rule_route_and_evidence() -> None:
    result = _result(
        snapshot(route(exclude=None)),
        snapshot(route(exclude=selection("email"))),
    )

    rendered = TextReporter().render(result)

    assert "BREAKING" in rendered
    assert "FAPI001" in rendered
    assert "GET /users" in rendered
    assert "email" in rendered


def test_review_report_contains_reason_for_uncertainty() -> None:
    result = _result(
        snapshot(route(include=selection("id"), exclude=None)),
        snapshot(route(include=selection("id"), exclude=selection("email"))),
    )

    rendered = TextReporter().render(result)

    assert "REVIEW" in rendered
    assert "FAPI001" in rendered
    assert "reason" in rendered.lower() or "unsupported" in rendered.lower()


def test_safe_report_is_scoped_to_supported_contract_surface() -> None:
    result = _result(
        snapshot(route(exclude=selection("email"))),
        snapshot(route(exclude=None)),
    )

    rendered = TextReporter().render(result)

    assert "SAFE" in rendered
    assert "supported contract surface" in rendered.lower()
    assert "fully compatible" not in rendered.lower()


def test_error_report_contains_analysis_error_code() -> None:
    result = _result(
        snapshot(
            route(path="/users/{id}", match_regex="^/users/(?P<param>[^/]+)$"),
            route(path="/users/{name}", match_regex="^/users/(?P<param>[^/]+)$"),
        ),
        snapshot(route(path="/users/{id}", match_regex="^/users/(?P<param>[^/]+)$")),
    )

    rendered = TextReporter().render(result)

    assert "ERROR" in rendered
    assert "AMBIGUOUS_ROUTE_IDENTITY" in rendered
