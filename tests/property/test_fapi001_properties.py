from hypothesis import assume, given
from hypothesis import strategies as st
from tests.support import route, selection

from fastapi_contract.domain.finding import CompatibilityImpact
from fastapi_contract.rules.fapi001 import Fapi001ResponseProjectionRule

_FIELD_NAMES = ("a", "b", "c", "d")
_field_sets = st.sets(st.sampled_from(_FIELD_NAMES), max_size=len(_FIELD_NAMES))


@given(before_exclude=_field_sets, after_exclude=_field_sets)
def test_widening_never_reports_breaking(
    before_exclude: set[str],
    after_exclude: set[str],
) -> None:
    assume(after_exclude <= before_exclude)
    before = route(fields=_FIELD_NAMES, exclude=selection(*before_exclude))
    after = route(fields=_FIELD_NAMES, exclude=selection(*after_exclude))

    findings = Fapi001ResponseProjectionRule().check(before, after)

    assert all(finding.impact is not CompatibilityImpact.INCOMPATIBLE for finding in findings)


@given(before_exclude=_field_sets, after_exclude=_field_sets)
def test_confirmed_new_exclusion_never_becomes_safe(
    before_exclude: set[str],
    after_exclude: set[str],
) -> None:
    assume(before_exclude <= after_exclude)
    assume(bool(after_exclude - before_exclude))
    before = route(fields=_FIELD_NAMES, exclude=selection(*before_exclude))
    after = route(fields=_FIELD_NAMES, exclude=selection(*after_exclude))

    findings = Fapi001ResponseProjectionRule().check(before, after)

    assert any(finding.impact is CompatibilityImpact.INCOMPATIBLE for finding in findings)


@given(exclude=_field_sets)
def test_identical_supported_contract_never_emits_finding(exclude: set[str]) -> None:
    value = route(fields=_FIELD_NAMES, exclude=selection(*exclude))

    assert Fapi001ResponseProjectionRule().check(value, value) == ()


@given(exclude=st.lists(st.sampled_from(_FIELD_NAMES), unique=True))
def test_exclude_order_is_semantically_irrelevant(exclude: list[str]) -> None:
    before = route(fields=_FIELD_NAMES, exclude=selection(*exclude))
    after = route(fields=_FIELD_NAMES, exclude=selection(*reversed(exclude)))

    assert Fapi001ResponseProjectionRule().check(before, after) == ()
