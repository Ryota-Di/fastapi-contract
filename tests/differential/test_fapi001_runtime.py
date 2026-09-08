import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from fastapi_contract.adapters.fastapi import FastApiSnapshotExtractor
from fastapi_contract.domain.finding import CompatibilityImpact
from fastapi_contract.rules.fapi001 import Fapi001ResponseProjectionRule


class Payload(BaseModel):
    id: int
    name: str
    email: str


def _app(exclude: set[str] | None) -> FastAPI:
    app = FastAPI()

    @app.get("/payload", response_model=Payload, response_model_exclude=exclude)
    def payload() -> dict[str, object]:
        return {"id": 1, "name": "Ada", "email": "a@example.com"}

    return app


def _only_contract(app: FastAPI):
    snapshot = FastApiSnapshotExtractor().extract(app)
    routes = [
        item.contract
        for item in snapshot.application.routes
        if item.contract.key.path == "/payload"
    ]
    assert len(routes) == 1
    return routes[0]


def _removed_by_checker(before: FastAPI, after: FastAPI) -> set[str]:
    findings = Fapi001ResponseProjectionRule().check(
        _only_contract(before),
        _only_contract(after),
    )
    incompatible = [
        finding for finding in findings if finding.impact is CompatibilityImpact.INCOMPATIBLE
    ]
    if not incompatible:
        return set()
    assert len(incompatible) == 1
    return {
        path.segments[0]
        for path in incompatible[0].evidence.removed_fields
        if len(path.segments) == 1
    }


def _runtime_keys(app: FastAPI) -> set[str]:
    response = TestClient(app).get("/payload")
    assert response.status_code == 200
    return set(response.json())


@pytest.mark.parametrize(
    ("before_exclude", "after_exclude"),
    [
        (None, {"email"}),
        ({"email"}, None),
        (None, {"does_not_exist"}),
        ({"email"}, {"name"}),
        (set(), {"name", "email"}),
    ],
)
def test_checker_agrees_with_fastapi_runtime_for_supported_projection_cases(
    before_exclude: set[str] | None,
    after_exclude: set[str] | None,
) -> None:
    before = _app(before_exclude)
    after = _app(after_exclude)

    runtime_removed = _runtime_keys(before) - _runtime_keys(after)
    checker_removed = _removed_by_checker(before, after)

    assert checker_removed == runtime_removed
