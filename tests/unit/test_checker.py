from tests.support import route, selection, snapshot

from fastapi_contract.application.checker import CheckStatus, ContractChecker
from fastapi_contract.domain.model import SchemaVisibility
from fastapi_contract.rules.fapi001 import Fapi001ResponseProjectionRule


def _checker() -> ContractChecker:
    return ContractChecker(rules=(Fapi001ResponseProjectionRule(),))


def test_checker_reports_breaking_for_matched_route_narrowing() -> None:
    baseline = snapshot(route(exclude=None))
    current = snapshot(route(exclude=selection("email")))

    result = _checker().check(baseline, current)

    assert result.status is CheckStatus.BREAKING
    assert len(result.findings) == 1


def test_checker_reports_review_for_relevant_uncertainty() -> None:
    baseline = snapshot(route(include=selection("id"), exclude=None))
    current = snapshot(route(include=selection("id"), exclude=selection("email")))

    result = _checker().check(baseline, current)

    assert result.status is CheckStatus.REVIEW
    assert len(result.findings) == 1


def test_checker_reports_safe_for_widening() -> None:
    baseline = snapshot(route(exclude=selection("email")))
    current = snapshot(route(exclude=None))

    result = _checker().check(baseline, current)

    assert result.status is CheckStatus.SAFE
    assert result.findings == ()


def test_breaking_takes_precedence_over_review() -> None:
    baseline = snapshot(
        route(path="/breaking", match_regex="^/breaking$", exclude=None),
        route(
            path="/review",
            match_regex="^/review$",
            include=selection("id"),
            exclude=None,
        ),
    )
    current = snapshot(
        route(
            path="/breaking",
            match_regex="^/breaking$",
            exclude=selection("email"),
        ),
        route(
            path="/review",
            match_regex="^/review$",
            include=selection("id"),
            exclude=selection("email"),
        ),
    )

    result = _checker().check(baseline, current)

    assert result.status is CheckStatus.BREAKING
    assert len(result.findings) == 2


def test_hidden_matched_route_is_checked_by_fapi001() -> None:
    baseline = snapshot(
        route(
            exclude=None,
            schema_visibility=SchemaVisibility.HIDDEN,
        )
    )
    current = snapshot(
        route(
            exclude=selection("email"),
            schema_visibility=SchemaVisibility.HIDDEN,
        )
    )

    result = _checker().check(baseline, current)

    assert result.status is CheckStatus.BREAKING


def test_unmatched_routes_are_outside_fapi001_slice1() -> None:
    baseline = snapshot(route(path="/old", match_regex="^/old$"))
    current = snapshot(route(path="/new", match_regex="^/new$"))

    result = _checker().check(baseline, current)

    assert result.status is CheckStatus.SAFE
    assert result.findings == ()


def test_different_http_methods_do_not_match_for_fapi001() -> None:
    baseline = snapshot(route(method="GET"))
    current = snapshot(route(method="POST"))

    result = _checker().check(baseline, current)

    assert result.status is CheckStatus.SAFE
    assert result.findings == ()


def test_path_parameter_rename_still_matches_for_fapi001() -> None:
    baseline = snapshot(
        route(
            path="/users/{id}",
            match_regex="^/users/(?P<param>[^/]+)$",
            exclude=None,
        )
    )
    current = snapshot(
        route(
            path="/users/{user_id}",
            match_regex="^/users/(?P<param>[^/]+)$",
            exclude=selection("email"),
        )
    )

    result = _checker().check(baseline, current)

    assert result.status is CheckStatus.BREAKING


def test_ambiguous_runtime_route_identity_is_error_not_safe() -> None:
    baseline = snapshot(
        route(path="/users/{id}", match_regex="^/users/(?P<param>[^/]+)$"),
        route(path="/users/{name}", match_regex="^/users/(?P<param>[^/]+)$"),
    )
    current = snapshot(route(path="/users/{id}", match_regex="^/users/(?P<param>[^/]+)$"))

    result = _checker().check(baseline, current)

    assert result.status is CheckStatus.ERROR
    assert result.error.code == "AMBIGUOUS_ROUTE_IDENTITY"


def test_ambiguous_runtime_route_identity_in_current_is_error_not_safe() -> None:
    baseline = snapshot(route(path="/users/{id}", match_regex="^/users/(?P<param>[^/]+)$"))
    current = snapshot(
        route(path="/users/{id}", match_regex="^/users/(?P<param>[^/]+)$"),
        route(path="/users/{name}", match_regex="^/users/(?P<param>[^/]+)$"),
    )

    result = _checker().check(baseline, current)

    assert result.status is CheckStatus.ERROR
    assert result.error.code == "AMBIGUOUS_ROUTE_IDENTITY"


def test_analysis_error_bypasses_breaking_classification() -> None:
    baseline = snapshot(
        route(path="/breaking", match_regex="^/breaking$", exclude=None),
        route(path="/users/{id}", match_regex="^/users/(?P<param>[^/]+)$"),
        route(path="/users/{name}", match_regex="^/users/(?P<param>[^/]+)$"),
    )
    current = snapshot(
        route(
            path="/breaking",
            match_regex="^/breaking$",
            exclude=selection("email"),
        ),
        route(path="/users/{id}", match_regex="^/users/(?P<param>[^/]+)$"),
    )

    result = _checker().check(baseline, current)

    assert result.status is CheckStatus.ERROR


def test_incompatible_framework_environment_is_error_not_safe() -> None:
    baseline = snapshot(route(), fastapi_version="baseline")
    current = snapshot(route(), fastapi_version="current")

    result = _checker().check(baseline, current)

    assert result.status is CheckStatus.ERROR
    assert result.error.code == "INCOMPATIBLE_ENVIRONMENT"
