from tests.support import route, selection

from fastapi_contract.domain.finding import CompatibilityImpact, FieldPath
from fastapi_contract.domain.model import Completeness, ResponseStateKind
from fastapi_contract.rules.fapi001 import Fapi001ResponseProjectionRule


def test_added_exclude_is_incompatible() -> None:
    before = route(exclude=None)
    after = route(exclude=selection("email"))

    findings = Fapi001ResponseProjectionRule().check(before, after)

    assert len(findings) == 1
    finding = findings[0]
    assert finding.rule_id == "FAPI001"
    assert finding.impact is CompatibilityImpact.INCOMPATIBLE
    assert finding.evidence.removed_fields == (FieldPath(("email",)),)


def test_removed_exclude_is_no_finding() -> None:
    before = route(exclude=selection("email"))
    after = route(exclude=None)

    assert Fapi001ResponseProjectionRule().check(before, after) == ()


def test_none_to_empty_exclude_is_semantic_noop() -> None:
    before = route(exclude=None)
    after = route(exclude=selection())

    assert Fapi001ResponseProjectionRule().check(before, after) == ()


def test_unknown_exclude_name_does_not_remove_a_response_field() -> None:
    before = route(exclude=None)
    after = route(exclude=selection("does_not_exist"))

    assert Fapi001ResponseProjectionRule().check(before, after) == ()


def test_known_and_unknown_excludes_report_only_real_removed_fields() -> None:
    before = route(exclude=None)
    after = route(exclude=selection("email", "does_not_exist"))

    findings = Fapi001ResponseProjectionRule().check(before, after)

    assert len(findings) == 1
    assert findings[0].evidence.removed_fields == (FieldPath(("email",)),)


def test_swapping_excluded_field_reports_only_newly_removed_field() -> None:
    before = route(fields=("id", "name", "email"), exclude=selection("email"))
    after = route(fields=("id", "name", "email"), exclude=selection("name"))

    findings = Fapi001ResponseProjectionRule().check(before, after)

    assert len(findings) == 1
    assert findings[0].impact is CompatibilityImpact.INCOMPATIBLE
    assert findings[0].evidence.removed_fields == (FieldPath(("name",)),)


def test_multiple_newly_removed_fields_are_reported_deterministically() -> None:
    before = route(fields=("id", "name", "email"), exclude=None)
    after = route(fields=("id", "name", "email"), exclude=selection("name", "email"))

    findings = Fapi001ResponseProjectionRule().check(before, after)

    assert len(findings) == 1
    assert findings[0].evidence.removed_fields == (
        FieldPath(("email",)),
        FieldPath(("name",)),
    )


def test_incomplete_selector_change_is_review_not_safe() -> None:
    before = route(exclude=None)
    after = route(
        exclude=selection(
            "profile",
            completeness=Completeness.INCOMPLETE,
            reason="nested response selection is not supported",
        )
    )

    findings = Fapi001ResponseProjectionRule().check(before, after)

    assert len(findings) == 1
    assert findings[0].impact is CompatibilityImpact.UNKNOWN
    assert findings[0].evidence.reason


def test_all_selector_change_is_review_not_safe() -> None:
    before = route(exclude=None)
    after = route(
        exclude=selection(
            "__all__",
            completeness=Completeness.INCOMPLETE,
            reason="__all__ response selection is not supported",
        )
    )

    findings = Fapi001ResponseProjectionRule().check(before, after)

    assert len(findings) == 1
    assert findings[0].impact is CompatibilityImpact.UNKNOWN


def test_response_include_plus_exclude_change_is_review_in_slice1() -> None:
    before = route(include=selection("id"), exclude=None)
    after = route(include=selection("id"), exclude=selection("email"))

    findings = Fapi001ResponseProjectionRule().check(before, after)

    assert len(findings) == 1
    assert findings[0].impact is CompatibilityImpact.UNKNOWN


def test_unchanged_unsupported_include_does_not_create_review_noise() -> None:
    before = route(include=selection("id"), exclude=None)
    after = route(include=selection("id"), exclude=None)

    assert Fapi001ResponseProjectionRule().check(before, after) == ()


def test_unsupported_shape_with_relevant_policy_change_is_review() -> None:
    before = route(response_state=ResponseStateKind.UNSUPPORTED, exclude=None)
    after = route(
        response_state=ResponseStateKind.UNSUPPORTED,
        exclude=selection("email"),
    )

    findings = Fapi001ResponseProjectionRule().check(before, after)

    assert len(findings) == 1
    assert findings[0].impact is CompatibilityImpact.UNKNOWN


def test_supported_to_unsupported_with_relevant_policy_change_is_review() -> None:
    before = route(exclude=None)
    after = route(
        response_state=ResponseStateKind.UNSUPPORTED,
        exclude=selection("email"),
    )

    findings = Fapi001ResponseProjectionRule().check(before, after)

    assert len(findings) == 1
    assert findings[0].impact is CompatibilityImpact.UNKNOWN


def test_unsupported_shape_without_policy_change_is_no_finding() -> None:
    before = route(response_state=ResponseStateKind.UNSUPPORTED, exclude=None)
    after = route(response_state=ResponseStateKind.UNSUPPORTED, exclude=None)

    assert Fapi001ResponseProjectionRule().check(before, after) == ()


def test_new_field_that_is_immediately_excluded_is_not_a_removed_old_field() -> None:
    before = route(fields=("id", "email"), exclude=None)
    after = route(fields=("id", "email", "name"), exclude=selection("name"))

    assert Fapi001ResponseProjectionRule().check(before, after) == ()


def test_response_model_field_change_without_projection_change_is_not_fapi001() -> None:
    before = route(fields=("id", "email"), exclude=None)
    after = route(fields=("id",), exclude=None)

    assert Fapi001ResponseProjectionRule().check(before, after) == ()


def test_no_response_model_is_outside_fapi001() -> None:
    before = route(response_state=ResponseStateKind.NO_MODEL)
    after = route(response_state=ResponseStateKind.NO_MODEL)

    assert Fapi001ResponseProjectionRule().check(before, after) == ()
