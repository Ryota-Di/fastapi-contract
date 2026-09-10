from enum import StrEnum

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field, create_model

from fastapi_contract.application.checker import CheckStatus


class ReadingStatus(StrEnum):
    READING = "reading"
    FINISHED = "finished"


class Detail(BaseModel):
    text: str


def app(model, *, exclude=None, by_alias=True):
    result = FastAPI()

    def endpoint():
        return model.model_validate({"id": 1, "user_id": 1, "notes": "n"}, by_name=True)

    result.get(
        "/books",
        response_model=model,
        response_model_exclude=exclude,
        response_model_by_alias=by_alias,
    )(endpoint)
    return result


def compare(old, new):
    from fastapi_contract.adapters.response import FastApiResponseFactExtractor
    from fastapi_contract.application.response import ResponseFactChecker

    extractor = FastApiResponseFactExtractor()
    return ResponseFactChecker().check(extractor.extract(old), extractor.extract(new))


@pytest.mark.parametrize(
    "sibling,default", [(ReadingStatus, ReadingStatus.READING), (Detail, Detail(text="x"))]
)
def test_notes_loss_with_unrelated_value_shape_is_breaking(sibling, default):
    book = create_model("Book", id=(int, ...), status=(sibling, default), notes=(str | None, None))
    old, new = app(book), app(book, exclude={"notes"})
    result = compare(old, new)
    assert result.status is CheckStatus.BREAKING
    assert next(
        f for f in result.findings if f.evidence.lost_wire_keys
    ).evidence.lost_wire_keys == ("notes",)
    assert old.openapi() == new.openapi()
    with TestClient(old) as client:
        assert client.get("/books").json()["notes"] == "n"
    with TestClient(new) as client:
        assert "notes" not in client.get("/books").json()


def test_route_by_alias_loss():
    model = create_model("User", user_id=(int, Field(serialization_alias="userId")))
    old, new = app(model), app(model, by_alias=False)
    assert old.openapi() == new.openapi()
    result = compare(old, new)
    assert result.status is CheckStatus.BREAKING
    assert result.findings[0].evidence.lost_wire_keys == ("userId",)


@pytest.mark.parametrize("case", ["documented_alias", "excluded_alias", "internal_rename"])
def test_no_false_wire_loss(case):
    old_field = "old_name" if case == "internal_rename" else "user_id"
    new_field = "new_name" if case == "internal_rename" else "user_id"
    old = create_model("User", **{old_field: (int, Field(serialization_alias="id"))})
    new = create_model(
        "User",
        **{
            new_field: (
                int,
                Field(serialization_alias=("id" if case == "internal_rename" else "newId")),
            )
        },
    )
    excluded = {"user_id"} if case == "excluded_alias" else None
    assert (
        compare(app(old, exclude=excluded), app(new, exclude=excluded)).status is CheckStatus.SAFE
    )


def test_shared_model_introspection_once_per_extract(monkeypatch):
    from fastapi_contract.adapters import response

    model = create_model("Book", id=(int, ...))
    application = app(model)
    application.get("/second", response_model=model)(lambda: {"id": 1})
    original = response._model_facts
    calls = []

    def counted(value):
        calls.append(value)
        return original(value)

    monkeypatch.setattr(response, "_model_facts", counted)
    extractor = response.FastApiResponseFactExtractor()
    extractor.extract(application)
    assert calls == [model]
    extractor.extract(application)
    assert calls == [model, model]


def test_nested_selector_blocker_is_local():
    model = create_model("Book", id=(int, ...), notes=(str, ""), detail=(Detail, Detail(text="x")))
    result = compare(app(model), app(model, exclude={"notes": True, "detail": {"text"}}))
    assert result.status is CheckStatus.BREAKING
    assert next(
        f for f in result.findings if f.evidence.lost_wire_keys
    ).evidence.lost_wire_keys == ("notes",)
    assert (
        next(f for f in result.findings if f.evidence.blockers).evidence.blockers[0].code
        == "unsupported_response_selector"
    )


def test_empty_serialization_alias_is_preserved():
    model = create_model("User", user_id=(int, Field(serialization_alias="")))
    result = compare(app(model), app(model, exclude={"user_id"}))
    assert result.status is CheckStatus.BREAKING
    assert result.findings[0].evidence.lost_wire_keys == ("",)


def test_v2_cli_vertical_slice(tmp_path, monkeypatch, capsys):
    from tests.integration.test_public_cli import app_module

    from fastapi_contract.cli import main
    from fastapi_contract.codec.schema_v2 import SnapshotV2Codec

    monkeypatch.chdir(tmp_path)
    old = app_module(tmp_path)
    new = app_module(tmp_path, exclude='{"email"}')
    baseline = tmp_path / "baseline.json"
    assert main(["snapshot", old, "-o", str(baseline), "--schema-version", "2"]) == 0
    assert SnapshotV2Codec().decode(baseline.read_text()).facts.routes
    assert main(["check", new, "--against", str(baseline)]) == 1
    output = capsys.readouterr().out
    assert "BREAKING" in output
    assert (
        'response-wire-surface GET /users: Response wire key "email" is no longer produced; '
        "key remains documented by OpenAPI." in output
    )


def test_unsupported_surface_preserves_relevant_selector_changes():
    assert compare(app(list[int]), app(list[int], exclude={0})).status is CheckStatus.REVIEW


def test_missing_http_methods_fails_closed():
    from fastapi.routing import APIRoute

    from fastapi_contract.adapters.response import FastApiResponseFactExtractor

    model = create_model("User", id=(int, ...))
    application = app(model)
    route = next(r for r in application.routes if isinstance(r, APIRoute))
    route.methods = None
    with pytest.raises(ValueError, match="HTTP methods"):
        FastApiResponseFactExtractor().extract(application)
