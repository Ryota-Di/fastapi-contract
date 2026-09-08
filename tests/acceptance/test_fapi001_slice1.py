from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from fastapi_contract.adapters.fastapi import FastApiSnapshotExtractor
from fastapi_contract.application.checker import CheckStatus, ContractChecker
from fastapi_contract.cli import exit_code_for
from fastapi_contract.codec.json import CanonicalJsonSnapshotCodec
from fastapi_contract.reporting.text import TextReporter
from fastapi_contract.rules.fapi001 import Fapi001ResponseProjectionRule


class User(BaseModel):
    id: int
    email: str


def _app(exclude: set[str] | None) -> FastAPI:
    app = FastAPI()

    @app.get(
        "/users",
        response_model=User,
        response_model_exclude=exclude,
        operation_id="get_user",
    )
    def get_user() -> dict[str, object]:
        return {"id": 1, "email": "a@example.com"}

    return app


def _check(baseline_app: FastAPI, current_app: FastAPI):
    extractor = FastApiSnapshotExtractor()
    codec = CanonicalJsonSnapshotCodec()
    baseline = codec.decode(codec.encode(extractor.extract(baseline_app)))
    current = codec.decode(codec.encode(extractor.extract(current_app)))
    checker = ContractChecker(rules=(Fapi001ResponseProjectionRule(),))
    return checker.check(baseline, current)


def test_openapi_blind_spot_is_detected_end_to_end() -> None:
    baseline_app = _app(None)
    current_app = _app({"email"})

    assert baseline_app.openapi() == current_app.openapi()
    assert TestClient(baseline_app).get("/users").json() == {
        "id": 1,
        "email": "a@example.com",
    }
    assert TestClient(current_app).get("/users").json() == {"id": 1}

    result = _check(baseline_app, current_app)

    assert result.status is CheckStatus.BREAKING
    assert len(result.findings) == 1
    assert result.findings[0].rule_id == "FAPI001"
    assert result.findings[0].evidence.removed_fields[0].segments == ("email",)
    assert exit_code_for(result) == 1

    rendered = TextReporter().render(result)
    assert "FAPI001" in rendered
    assert "GET /users" in rendered
    assert "email" in rendered


def test_semantic_noop_remains_safe_end_to_end() -> None:
    baseline_app = _app(None)
    current_app = _app(set())

    result = _check(baseline_app, current_app)

    assert result.status is CheckStatus.SAFE
    assert result.findings == ()
    assert exit_code_for(result) == 0
    assert "supported contract surface" in TextReporter().render(result).lower()


def test_unsupported_relevant_change_is_review_end_to_end() -> None:
    class Profile(BaseModel):
        email: str

    class NestedUser(BaseModel):
        id: int
        profile: Profile

    baseline_app = FastAPI()
    current_app = FastAPI()

    @baseline_app.get("/users", response_model=NestedUser)
    def baseline_user() -> dict[str, object]:
        return {"id": 1, "profile": {"email": "a@example.com"}}

    @current_app.get(
        "/users",
        response_model=NestedUser,
        response_model_exclude={"profile": {"email"}},
    )
    def current_user() -> dict[str, object]:
        return {"id": 1, "profile": {"email": "a@example.com"}}

    result = _check(baseline_app, current_app)

    assert result.status is CheckStatus.REVIEW
    assert exit_code_for(result) == 1
    assert "REVIEW" in TextReporter().render(result)


def test_ambiguous_route_identity_is_error_end_to_end() -> None:
    baseline_app = FastAPI()
    current_app = FastAPI()

    @baseline_app.get("/users/{id}", response_model=User)
    def baseline_by_id(id: str) -> dict[str, str]:
        return {"id": id, "email": "a@example.com"}

    @baseline_app.get("/users/{name}", response_model=User)
    def baseline_by_name(name: str) -> dict[str, str]:
        return {"id": name, "email": "a@example.com"}

    @current_app.get("/users/{id}", response_model=User)
    def current_by_id(id: str) -> dict[str, str]:
        return {"id": id, "email": "a@example.com"}

    result = _check(baseline_app, current_app)

    assert result.status is CheckStatus.ERROR
    assert result.error.code == "AMBIGUOUS_ROUTE_IDENTITY"
    assert exit_code_for(result) == 2
    assert "ERROR" in TextReporter().render(result)
