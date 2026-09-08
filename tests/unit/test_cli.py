import pytest
from tests.support import route, selection, snapshot

from fastapi_contract.application.checker import ContractChecker
from fastapi_contract.cli import exit_code_for
from fastapi_contract.rules.fapi001 import Fapi001ResponseProjectionRule


def _check(baseline, current):  # type: ignore[no-untyped-def]
    checker = ContractChecker(rules=(Fapi001ResponseProjectionRule(),))
    return checker.check(baseline, current)


@pytest.mark.parametrize(
    ("baseline", "current", "expected"),
    [
        (
            snapshot(route(exclude=selection("email"))),
            snapshot(route(exclude=None)),
            0,
        ),
        (
            snapshot(route(exclude=None)),
            snapshot(route(exclude=selection("email"))),
            1,
        ),
        (
            snapshot(route(include=selection("id"), exclude=None)),
            snapshot(route(include=selection("id"), exclude=selection("email"))),
            1,
        ),
        (
            snapshot(
                route(path="/users/{id}", match_regex="^/users/(?P<param>[^/]+)$"),
                route(path="/users/{name}", match_regex="^/users/(?P<param>[^/]+)$"),
            ),
            snapshot(route(path="/users/{id}", match_regex="^/users/(?P<param>[^/]+)$")),
            2,
        ),
    ],
    ids=["safe", "breaking", "review", "error"],
)
def test_exit_code_contract(
    baseline,
    current,
    expected: int,
) -> None:
    assert exit_code_for(_check(baseline, current)) == expected
