from enum import StrEnum

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import AliasChoices, AliasPath, BaseModel, ConfigDict, Field, create_model
from pydantic.alias_generators import to_camel

from fastapi_contract.adapters.response import FastApiResponseFactExtractor
from fastapi_contract.application.checker import CheckStatus
from fastapi_contract.application.response import ResponseFactChecker


def payload(*, name="user_id", alias="userId", by_name=True, required=False, extra=None):
    fields = {name: (int, Field(... if required else 0, validation_alias=alias))}
    fields.update(extra or {})
    return create_model(
        "Payload", __config__=ConfigDict(validate_by_alias=True, validate_by_name=by_name), **fields
    )


def app(model):
    application = FastAPI()

    def endpoint(body):
        return body.model_dump()

    endpoint.__annotations__ = {"body": model}
    application.post("/users")(endpoint)
    return application


def compare(old, new):
    extractor = FastApiResponseFactExtractor()
    return ResponseFactChecker().check(extractor.extract(old), extractor.extract(new))


@pytest.mark.parametrize("required", [False, True])
def test_body_name_binding_loss_is_breaking_even_when_http_200(required):
    old, new = app(payload(required=required)), app(payload(by_name=False, required=required))
    assert old.openapi() == new.openapi()
    with TestClient(old) as client:
        response = client.post("/users", json={"user_id": 123})
        assert response.status_code == 200
        assert response.json() == {"user_id": 123}
    with TestClient(new) as client:
        response = client.post("/users", json={"user_id": 123})
        assert response.status_code == (422 if required else 200)
        if not required:
            assert response.json() == {"user_id": 0}
        else:
            assert response.json()["detail"][0]["type"] == "missing"
    result = compare(old, new)
    assert result.status is CheckStatus.BREAKING
    assert len(result.findings) == 1
    assert result.findings[0].rule_id == "request-body-binding"
    assert result.findings[0].evidence.lost_bindings[0].wire_key == "user_id"
    assert result.findings[0].evidence.lost_bindings[0].anchor_key == "userId"


def test_stable_alias_internal_rename_has_no_binding_finding():
    old = create_model("Payload", old_name=(int, Field(alias="id")))
    new = create_model("Payload", new_name=(int, Field(alias="id")))
    assert compare(app(old), app(new)).status is CheckStatus.SAFE


def test_explicit_and_generated_alias_construction_invariance():
    old = create_model("Payload", user_id=(int, Field(alias="userId")))
    new = create_model(
        "Payload", __config__=ConfigDict(alias_generator=to_camel), user_id=(int, ...)
    )
    assert compare(app(old), app(new)).status is CheckStatus.SAFE


class Status(StrEnum):
    READING = "reading"


class Nested(BaseModel):
    text: str


@pytest.mark.parametrize(
    "annotation,default", [(Status, Status.READING), (Nested, Nested(text="n"))]
)
def test_sibling_value_shape_does_not_poison_binding(annotation, default):
    sibling = {"sibling": (annotation, default)}
    result = compare(app(payload(extra=sibling)), app(payload(extra=sibling, by_name=False)))
    assert result.status is CheckStatus.BREAKING
    assert len(result.findings) == 1


def test_primary_alias_change_is_openapi_responsibility():
    old, new = app(payload(alias="userId")), app(payload(alias="id"))
    assert old.openapi() != new.openapi()
    assert compare(old, new).status is CheckStatus.SAFE


@pytest.mark.parametrize("alias", [AliasChoices("unrelated", "legacy"), AliasPath("data", "value")])
def test_unrelated_unsupported_alias_is_candidate_local(alias):
    sibling = {"sibling": (int, Field(0, validation_alias=alias))}
    result = compare(app(payload(extra=sibling)), app(payload(extra=sibling, by_name=False)))
    assert result.status is CheckStatus.BREAKING
    assert result.findings[0].evidence.lost_bindings[0].wire_key == "user_id"
    assert all(f.rule_id == "request-body-binding" for f in result.findings)


def test_distinct_anchor_multi_binding_is_proven_without_collapsing_multiplicity():
    from fastapi_contract.domain.finding import CompatibilityImpact
    from fastapi_contract.rules.body_binding import binding_surface

    sibling = {"other": (int, Field(0, validation_alias="user_id"))}
    old, new = app(payload(extra=sibling)), app(payload(extra=sibling, by_name=False))
    with TestClient(old) as client:
        assert client.post("/users", json={"user_id": 123}).json() == {"user_id": 123, "other": 123}
    with TestClient(new) as client:
        assert client.post("/users", json={"user_id": 123}).json() == {"user_id": 0, "other": 123}
    facts = FastApiResponseFactExtractor().extract(old).routes[0].body_binding
    assert len(binding_surface(facts)["user_id"]) == 2
    result = compare(old, new)
    assert result.status is CheckStatus.BREAKING  # independent "other" name binding is also lost
    assert all(f.impact is CompatibilityImpact.INCOMPATIBLE for f in result.findings)
    assert {(r.wire_key, r.anchor_key) for r in result.findings[0].evidence.lost_bindings} == {
        ("user_id", "userId"),
        ("other", "user_id"),
    }
    # The same key remains bound to another slot: a bare accepted-key set would miss this loss.
    assert "user_id" in binding_surface(
        FastApiResponseFactExtractor().extract(new).routes[0].body_binding
    )


def test_related_unsupported_alias_is_review_not_false_breaking():
    sibling = {"sibling": (int, Field(0, validation_alias=AliasChoices("user_id", "legacy")))}
    result = compare(app(payload(extra=sibling)), app(payload(extra=sibling, by_name=False)))
    assert result.status is CheckStatus.REVIEW
    assert result.findings[0].evidence.uncertain_bindings[0].wire_key == "user_id"
    assert result.findings[0].evidence.blockers[0].code == "unsupported_body_alias_form"


@pytest.mark.parametrize(
    "by_alias,by_name,expected",
    [(True, False, ("userId",)), (True, True, ("userId", "user_id")), (False, True, ("user_id",))],
)
def test_resolved_flag_semantics(by_alias, by_name, expected):
    model = create_model(
        "Payload",
        __config__=ConfigDict(validate_by_alias=by_alias, validate_by_name=by_name),
        user_id=(int, Field(alias="userId")),
    )
    slot = FastApiResponseFactExtractor().extract(app(model)).routes[0].body_binding.slots[0]
    assert slot.anchor_key == "userId"
    assert slot.accepted_binding_keys.keys == expected


def test_alias_disabled_removes_alias_binding_with_same_documented_anchor():
    old = create_model(
        "Payload",
        __config__=ConfigDict(validate_by_name=True),
        user_id=(int, Field(default=0, alias="userId")),
    )
    new = create_model(
        "Payload",
        __config__=ConfigDict(validate_by_alias=False),
        user_id=(int, Field(default=0, alias="userId")),
    )
    old_app, new_app = app(old), app(new)
    assert old_app.openapi() == new_app.openapi()
    result = compare(old_app, new_app)
    assert result.status is CheckStatus.BREAKING
    assert result.findings[0].evidence.lost_bindings[0].wire_key == "userId"


def test_no_alias_ignores_name_flag_and_empty_alias_is_preserved():
    old = create_model("Payload", __config__=ConfigDict(validate_by_name=True), user_id=(int, 0))
    new = create_model("Payload", __config__=ConfigDict(validate_by_name=False), user_id=(int, 0))
    assert compare(app(old), app(new)).status is CheckStatus.SAFE
    result = compare(app(payload(alias="")), app(payload(alias="", by_name=False)))
    assert result.status is CheckStatus.BREAKING
    assert result.findings[0].evidence.lost_bindings[0].anchor_key == ""


@pytest.mark.parametrize(
    "shape", ["embedded", "multiple", "root", "primitive", "non_json", "dependency"]
)
def test_outside_slice_inputs_are_not_absent(shape):
    from fastapi import Body, Depends
    from pydantic import RootModel

    application = FastAPI()
    model = payload()
    if shape == "root":
        application = app(RootModel[int])
    elif shape == "primitive":

        def endpoint(value: int = Body()):
            return value

        application.post("/users")(endpoint)
    elif shape == "dependency":

        def dependency(body):
            return body

        dependency.__annotations__ = {"body": model}

        dependency_marker = Depends(dependency)

        def endpoint(body=dependency_marker):
            return body

        application.post("/users")(endpoint)
    else:
        body_marker = Body(
            embed=shape == "embedded",
            media_type="text/plain" if shape == "non_json" else "application/json",
        )

        def endpoint(body=body_marker):
            return body

        endpoint.__annotations__ = {"body": model}
        if shape == "multiple":

            def endpoint(body, other: int = Body()):
                return body

            endpoint.__annotations__["body"] = model
        application.post("/users")(endpoint)
    body = FastApiResponseFactExtractor().extract(application).routes[0].body_binding
    assert body.kind == "outside_slice"
    assert body.slots == ()
    assert body.blockers
    assert compare(app(payload()), application).status is CheckStatus.REVIEW


def test_field_validator_is_local_and_model_validator_is_outside_slice():
    from pydantic import field_validator, model_validator

    class Local(BaseModel):
        sibling: int = 0

        @field_validator("sibling", mode="before")
        @classmethod
        def normalize(cls, value):
            return value

    def build(by_name):
        return create_model(
            "Payload",
            __base__=Local,
            __config__=ConfigDict(validate_by_name=by_name),
            user_id=(int, Field(0, validation_alias="userId")),
        )

    assert compare(app(build(True)), app(build(False))).status is CheckStatus.BREAKING

    class Global(BaseModel):
        user_id: int = 0

        @model_validator(mode="before")
        @classmethod
        def transform(cls, value):
            return value

    body = FastApiResponseFactExtractor().extract(app(Global)).routes[0].body_binding
    assert body.kind == "outside_slice"
    assert body.blockers[0].code == "unsupported_body_validation"


def test_version_mismatch_is_explicitly_outside_supported_body_runtime(monkeypatch):
    import fastapi_contract.adapters.response as module

    original = module.version
    monkeypatch.setattr(
        module, "version", lambda name: "2.99" if name == "pydantic" else original(name)
    )
    body = module.FastApiResponseFactExtractor().extract(app(payload())).routes[0].body_binding
    assert body.kind == "outside_slice"
    assert body.blockers[0].code == "unsupported_body_runtime"


def test_v2_cli_reports_defaulted_body_binding_loss(tmp_path, monkeypatch, capsys):
    from fastapi_contract.cli import main

    code = """from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict, Field
app = FastAPI()
class Payload(BaseModel):
    model_config = ConfigDict(validate_by_name={by_name})
    user_id: int = Field(0, validation_alias="userId")
@app.post("/users")
def users(body: Payload):
    return body.model_dump()
"""
    (tmp_path / "pr2_old.py").write_text(code.format(by_name=True))
    (tmp_path / "pr2_new.py").write_text(code.format(by_name=False))
    monkeypatch.chdir(tmp_path)
    baseline = str(tmp_path / "baseline.json")
    assert main(["snapshot", "pr2_old:app", "-o", baseline, "--schema-version", "2"]) == 0
    assert main(["check", "pr2_new:app", "--against", baseline]) == 1
    output = capsys.readouterr().out
    assert (
        'POST /users: Request body key "user_id" is no longer bound to input slot "userId".'
        in output
    )
    assert "BREAKING" in output
