import inspect
import json
from enum import StrEnum
from typing import Annotated

import pytest
from fastapi import Cookie, Depends, FastAPI, Header, Query
from fastapi.testclient import TestClient
from pydantic import BaseModel, BeforeValidator

from fastapi_contract.adapters.response import FastApiResponseFactExtractor
from fastapi_contract.application.checker import CheckStatus
from fastapi_contract.application.response import ContractFactChecker
from fastapi_contract.codec.schema_v2 import SnapshotV2Codec

KINDS = [(Query, "query"), (Header, "header"), (Cookie, "cookie")]


def spec(kind=Query, name="old_name", *, required=False, hidden=True, annotation=str | None, **kw):
    return inspect.Parameter(
        name,
        inspect.Parameter.KEYWORD_ONLY,
        annotation=annotation,
        default=kind(... if required else None, include_in_schema=not hidden, **kw),
    )


def app(*fields, dependency=(), keep=True, hidden_route=False):
    application = FastAPI()

    def endpoint(**values):
        return values

    parameters = list(fields)
    if keep:
        parameters.append(spec(name="other", hidden=False))
    for i, dep in enumerate(dependency):
        parameters.append(
            inspect.Parameter(f"dep{i}", inspect.Parameter.KEYWORD_ONLY, default=Depends(dep))
        )
    endpoint.__signature__ = inspect.Signature(parameters)
    application.get("/probe", include_in_schema=not hidden_route)(endpoint)
    return application


def dep(*fields, children=()):
    def dependency(**values):
        return values

    parameters = list(fields)
    for i, child in enumerate(children):
        parameters.append(
            inspect.Parameter(f"child{i}", inspect.Parameter.KEYWORD_ONLY, default=Depends(child))
        )
    dependency.__signature__ = inspect.Signature(parameters)
    return dependency


def extract(application):
    return FastApiResponseFactExtractor().extract(application)


def compare(before, after):
    return ContractFactChecker().check(extract(before), extract(after))


def signature(result):
    return [
        (f.rule_id, f.impact.value, f.evidence.location.value, f.evidence.wire_name)
        for f in result.findings
    ]


def send(application, location, name=None):
    kw = (
        {}
        if name is None
        else (
            {"params": {name: "value"}}
            if location == "query"
            else {"headers": {name: "value"}}
            if location == "header"
            else {"headers": {"cookie": name + "=value"}}
        )
    )
    with TestClient(application) as client:
        return client.get("/probe", **kw)


@pytest.mark.parametrize("kind,location", KINDS)
@pytest.mark.parametrize("required", [False, True])
def test_hidden_rename_loses_binding(kind, location, required):
    before, after = (
        app(spec(kind, required=required)),
        app(spec(kind, "new_name", required=required)),
    )
    wire = "old-name" if location == "header" else "old_name"
    assert before.openapi() == after.openapi()
    old, new = send(before, location, wire), send(after, location, wire)
    assert old.status_code == 200 and old.json()["old_name"] == "value"
    assert new.status_code == (422 if required else 200)
    if not required:
        assert new.json()["new_name"] is None
    result = compare(before, after)
    assert result.status is CheckStatus.BREAKING
    assert signature(result) == [("hidden-parameter-binding", "incompatible", location, wire)]


@pytest.mark.parametrize("kind,location", KINDS)
def test_stable_explicit_alias_python_rename(kind, location):
    before, after = app(spec(kind, alias="token")), app(spec(kind, "new_name", alias="token"))
    assert send(before, location, "token").json()["old_name"] == "value"
    assert send(after, location, "token").json()["new_name"] == "value"
    assert compare(before, after).status is CheckStatus.SAFE


@pytest.mark.parametrize("kind,location", KINDS)
@pytest.mark.parametrize(
    "old_required,new_required", [(False, True), (True, False), (True, True), (False, False)]
)
def test_requirement_on_matched_binding(kind, location, old_required, new_required):
    before = app(spec(kind, alias="token", required=old_required))
    after = app(spec(kind, alias="token", required=new_required))
    result = compare(before, after)
    assert send(before, location).status_code == (422 if old_required else 200)
    assert send(after, location).status_code == (422 if new_required else 200)
    if not old_required and new_required:
        assert result.status is CheckStatus.BREAKING
        assert signature(result) == [
            ("hidden-parameter-requirement", "incompatible", location, "token")
        ]
        assert result.findings[0].evidence.before_required is False
        assert result.findings[0].evidence.after_required is True
    else:
        assert result.status is CheckStatus.SAFE


@pytest.mark.parametrize(
    "old_opts,new_opts,safe,wire",
    [
        ({}, {"alias": "X-Token"}, True, "x-token"),
        ({"alias": "X-Token"}, {"alias": "x-token"}, True, "x-token"),
        ({"alias": "x_token"}, {"alias": "X_TOKEN"}, True, "x_token"),
        ({}, {"convert_underscores": False}, False, "x-token"),
        ({"alias": ""}, {}, True, "x-token"),
        (
            {"alias": "advertised", "validation_alias": "x_token"},
            {"alias": "x_token"},
            True,
            "x_token",
        ),
    ],
)
def test_header_lookup_resolution(old_opts, new_opts, safe, wire):
    before, after = (
        app(spec(Header, "x_token", **old_opts)),
        app(spec(Header, "x_token", **new_opts)),
    )
    assert send(before, "header", wire).json()["x_token"] == "value"
    if safe:
        assert send(after, "header", wire).json()["x_token"] == "value"
    assert compare(before, after).status is (CheckStatus.SAFE if safe else CheckStatus.BREAKING)


@pytest.mark.parametrize("kind,location", KINDS)
def test_validation_alias_is_lookup_identity(kind, location):
    before = app(spec(kind, alias="schema", validation_alias="wire"))
    after = app(spec(kind, alias="schema", validation_alias="next"))
    assert send(before, location, "wire").json()["old_name"] == "value"
    assert send(after, location, "wire").json()["old_name"] is None
    assert signature(compare(before, after)) == [
        ("hidden-parameter-binding", "incompatible", location, "wire")
    ]


@pytest.mark.parametrize(
    "old_hidden,new_hidden,tighten,expected",
    [
        (True, False, False, False),
        (False, True, False, False),
        (True, False, True, True),
        (False, True, True, True),
        (False, False, True, False),
    ],
)
def test_visibility_requirement_ownership(old_hidden, new_hidden, tighten, expected):
    result = compare(app(spec(hidden=old_hidden)), app(spec(hidden=new_hidden, required=tighten)))
    assert result.status is (CheckStatus.BREAKING if expected else CheckStatus.SAFE)
    assert all(f.rule_id == "hidden-parameter-requirement" for f in result.findings)


@pytest.mark.parametrize("keep", [False, True])
def test_removal_ownership_independent_of_incidental_openapi(keep):
    before, after = app(spec(alias="token"), keep=keep), app(keep=keep)
    assert (before.openapi() == after.openapi()) is keep
    assert signature(compare(before, after)) == [
        ("hidden-parameter-binding", "incompatible", "query", "token")
    ]
    assert send(before, "query", "token").json()["old_name"] == "value"
    assert "old_name" not in send(after, "query", "token").json()


@pytest.mark.parametrize("direction", [False, True])
def test_move_between_direct_and_dependency(direction):
    before, after = app(spec(alias="token")), app(dependency=(dep(spec(alias="token")),))
    if direction:
        before, after = after, before
    assert compare(before, after).status is CheckStatus.SAFE


def test_nested_dependency_binding_and_requirement():
    before = app(dependency=(dep(children=(dep(spec(Header, alias="token")),)),))
    after = app(dependency=(dep(children=(dep(spec(Header, alias="token", required=True)),)),))
    assert signature(compare(before, after)) == [
        ("hidden-parameter-requirement", "incompatible", "header", "token")
    ]


class State(StrEnum):
    READING = "reading"


class Container(BaseModel):
    complex: str | None = None


@pytest.mark.parametrize(
    "annotation",
    [State | None, Annotated[str | None, BeforeValidator(lambda v: v)], list[str] | None],
)
def test_value_metadata_does_not_poison_binding(annotation):
    result = compare(
        app(spec(annotation=annotation)), app(spec(name="new_name", annotation=annotation))
    )
    assert result.status is CheckStatus.BREAKING
    assert len(result.findings) == 1


def test_model_region_is_local_to_location():
    extra = dep(spec(Header, "model", annotation=Container))
    before, after = app(spec(alias="token"), dependency=(extra,)), app(dependency=(extra,))
    result = compare(before, after)
    assert signature(result) == [("hidden-parameter-binding", "incompatible", "query", "token")]
    assert extract(before).routes[0].parameters.coverage.value == "partial"


def test_changed_collision_is_local_and_preserves_breaking():
    a, b = spec(Header, "a", alias="X-Token"), spec(Header, "b", alias="x-token")
    before, after = app(a, spec(alias="ok")), app(a, b)
    result = compare(before, after)
    assert result.status is CheckStatus.BREAKING
    assert set(signature(result)) == {
        ("hidden-parameter-binding", "unknown", "header", "x-token"),
        ("hidden-parameter-binding", "incompatible", "query", "ok"),
    }
    assert compare(app(a, b), app(b, a)).status is CheckStatus.SAFE


def test_repeated_dependencies_preserve_multiplicity():
    dependency = dep(spec(alias="token"))
    facts = extract(app(dependency=(dependency, dependency))).routes[0].parameters
    assert len([o for o in facts.occurrences if o.binding.wire_name == "token"]) == 2


def test_canonical_order_does_not_depend_on_declaration_order():
    fields = [spec(name="a", alias="z"), spec(Header, "b", alias="A"), spec(Cookie, "c", alias="c")]
    a, b = app(*fields), app(*reversed(fields))
    assert SnapshotV2Codec().encode(extract(a)) == SnapshotV2Codec().encode(extract(b))
    assert signature(compare(a, app())) == signature(compare(b, app()))


def test_parameters_v2_roundtrip_and_strict_fields():
    codec = SnapshotV2Codec()
    facts = extract(app(spec(alias="token")))
    text = codec.encode(facts)
    assert codec.decode(text).facts == facts
    payload = json.loads(text)
    assert payload["application"]["routes"][0]["parameters"]["coverage"] == "complete"
    payload["application"]["routes"][0]["parameters"]["surprise"] = True
    from fastapi_contract.codec.json import SnapshotCodecError

    with pytest.raises(SnapshotCodecError):
        codec.decode(json.dumps(payload))


def test_cli_v2_parameter_breaking(tmp_path, monkeypatch, capsys):
    from fastapi_contract.cli import main

    code = """from fastapi import FastAPI, Query
app = FastAPI()
@app.get('/probe')
def endpoint({name}: str | None = Query(None, include_in_schema=False)):
    return {{'value': {name}}}
"""
    for name in ("old_name", "new_name"):
        (tmp_path / f"pr3_{name}.py").write_text(code.format(name=name))
    monkeypatch.chdir(tmp_path)
    baseline = str(tmp_path / "baseline.json")
    assert main(["snapshot", "pr3_old_name:app", "--schema-version", "2", "-o", baseline]) == 0
    assert main(["check", "pr3_new_name:app", "--against", baseline]) == 1
    output = capsys.readouterr().out
    assert "hidden-parameter-binding" in output and "old_name" in output and "BREAKING" in output


def test_dependency_is_never_executed_by_extraction():
    def dependency(token: str | None = Query(None, include_in_schema=False)):
        raise AssertionError("extraction must not execute dependencies")

    facts = extract(app(dependency=(dependency,))).routes[0].parameters
    assert facts.coverage.value == "complete"
    assert any(o.binding.wire_name == "token" for o in facts.occurrences)


def test_default_factory_is_not_called_by_extraction():
    calls = []

    def factory():
        calls.append(True)
        raise AssertionError("extraction must not evaluate default values")

    field = inspect.Parameter(
        "token",
        inspect.Parameter.KEYWORD_ONLY,
        annotation=str,
        default=Query(default_factory=factory, include_in_schema=False),
    )
    facts = extract(app(field)).routes[0].parameters
    token = next(o for o in facts.occurrences if o.binding.wire_name == "token")
    assert token.required is False
    assert calls == []


def test_reachable_dependency_override_does_not_trust_original_tree():
    dependency = dep(spec(alias="token"))
    before = app(spec(Header, alias="independent"), dependency=(dependency,))
    after = app(dependency=(dependency,))
    after.dependency_overrides[dependency] = dep(spec(Header, alias="independent"))
    facts = extract(after).routes[0].parameters
    assert facts.coverage.value == "partial"
    assert facts.unresolved_regions[0].blocker.code.value == "parameter_dependency_override"
    result = compare(before, after)
    assert result.status is CheckStatus.REVIEW
    assert all(f.impact.value == "unknown" for f in result.findings)


def test_unreachable_override_does_not_poison_direct_inputs():
    before, after = app(spec(alias="token")), app()
    after.dependency_overrides[dep(spec())] = dep(spec())
    assert compare(before, after).status is CheckStatus.BREAKING


@pytest.mark.parametrize("kind,location", [(Query, "query"), (Cookie, "cookie")])
def test_query_and_cookie_names_are_case_sensitive(kind, location):
    before, after = app(spec(kind, alias="Token")), app(spec(kind, alias="token"))
    assert send(before, location, "Token").json()["old_name"] == "value"
    assert send(after, location, "Token").json()["old_name"] is None
    assert signature(compare(before, after)) == [
        ("hidden-parameter-binding", "incompatible", location, "Token")
    ]


def test_location_change_is_loss_not_same_binding_requirement():
    result = compare(app(spec(alias="token")), app(spec(Cookie, alias="token", required=True)))
    assert signature(result) == [("hidden-parameter-binding", "incompatible", "query", "token")]


def test_added_required_parameter_is_deferred():
    assert compare(app(), app(spec(required=True))).status is CheckStatus.SAFE


def test_matched_hidden_operation_parameters_are_hidden():
    result = compare(app(spec(hidden=False), hidden_route=True), app(hidden_route=True))
    assert result.status is CheckStatus.BREAKING


def test_custom_documentation_does_not_execute_or_invent_ownership():
    before, after = app(spec(alias="token")), app()

    def custom():
        raise AssertionError("custom documentation must not execute")

    before.openapi = custom
    after.openapi = custom
    assert compare(before, after).status is CheckStatus.BREAKING
    documented = app(spec(alias="token", hidden=False))
    documented.openapi = custom
    assert compare(documented, after).status is CheckStatus.REVIEW


def test_nonstring_validation_alias_region_has_bounded_candidate_keys():
    from pydantic import AliasChoices

    unknown = spec(
        name="complex", alias="complex", validation_alias=AliasChoices("complex", "legacy")
    )
    before, after = app(spec(alias="token"), unknown), app(unknown)
    assert signature(compare(before, after)) == [
        ("hidden-parameter-binding", "incompatible", "query", "token")
    ]


def test_changed_unsupported_alias_structure_is_observable_without_code_analysis():
    from pydantic import AliasChoices

    before = app(spec(alias="complex", validation_alias=AliasChoices("complex", "legacy")))
    after = app(spec(alias="complex", validation_alias=AliasChoices("complex", "next")))
    assert compare(before, after).status is CheckStatus.REVIEW


def test_path_and_route_lifecycle_do_not_create_parameter_findings():
    from fastapi import Path

    before = FastAPI()

    @before.get("/probe/{item_id}")
    def endpoint(item_id: str = Path(include_in_schema=False)):
        return item_id

    assert compare(before, FastAPI()).status is CheckStatus.SAFE


def test_parameter_runtime_gate_is_explicit(monkeypatch):
    import fastapi_contract.adapters.response as module

    original = module.version
    monkeypatch.setattr(
        module, "version", lambda name: "2.13.6" if name == "pydantic" else original(name)
    )
    facts = extract(app(spec())).routes[0].parameters
    assert facts.coverage.value == "unavailable"
    assert facts.unresolved_regions[0].blocker.code.value == "unsupported_parameter_runtime"


def test_current_checker_runs_all_four_owners_together():
    from pydantic import ConfigDict, Field, create_model

    def build(changed):
        application = FastAPI()
        payload = create_model(
            "Payload",
            __config__=ConfigDict(validate_by_name=not changed),
            user_id=(int, Field(0, alias="userId")),
        )
        response = create_model("Response", notes=(str, "notes"), id=(int, 1))

        def endpoint(**values):
            return response()

        fields = [
            inspect.Parameter("body", inspect.Parameter.KEYWORD_ONLY, annotation=payload),
            spec(Header, "mode", required=changed),
        ]
        if not changed:
            fields.append(spec(alias="token"))
        endpoint.__signature__ = inspect.Signature(fields)
        application.post(
            "/probe", response_model=response, response_model_exclude={"notes"} if changed else None
        )(endpoint)
        return application

    result = compare(build(False), build(True))
    assert result.status is CheckStatus.BREAKING
    assert {f.rule_id for f in result.findings} == {
        "response-wire-surface",
        "request-body-binding",
        "hidden-parameter-binding",
        "hidden-parameter-requirement",
    }
    assert len(result.findings) == 4


def test_requirement_report_uses_wire_key_not_python_argument():
    from fastapi_contract.reporting.text import TextReporter

    result = compare(app(spec(alias="wire-token")), app(spec(alias="wire-token", required=True)))
    report = TextReporter().render(result)
    assert "optional to required" in report and "wire-token" in report
    assert "old_name" not in report
