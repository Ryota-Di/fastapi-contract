from collections import UserDict
from types import MappingProxyType
from typing import Annotated

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field, PlainSerializer, create_model

from fastapi_contract.adapters.fastapi import FastApiSnapshotExtractor
from fastapi_contract.application.checker import CheckStatus, ContractChecker
from fastapi_contract.codec.json import CanonicalJsonSnapshotCodec
from fastapi_contract.domain.finding import CompatibilityImpact
from fastapi_contract.domain.model import ResponseStateKind
from fastapi_contract.rules.fapi001 import Fapi001ResponseProjectionRule


class Payload(BaseModel):
    id: int
    email: str


def _app(model, data, exclude):
    app = FastAPI()
    app.add_api_route(
        "/payload", lambda: data, response_model=model, response_model_exclude=exclude
    )
    return app


def _check_runtime_projection(model, data, before_exclude, after_exclude, expected_removed):
    snapshots = []
    runtime_keys = []
    for exclude in (before_exclude, after_exclude):
        app = _app(model, data, exclude)
        with TestClient(app) as client:
            response = client.get("/payload")
        assert response.status_code == 200
        assert response.json() == model(**data).model_dump(mode="json", exclude=exclude)
        runtime_keys.append(set(response.json()))
        codec = CanonicalJsonSnapshotCodec()
        snapshot = codec.decode(codec.encode(FastApiSnapshotExtractor().extract(app)))
        assert snapshot.application.routes[0].contract.response.state is ResponseStateKind.SUPPORTED
        snapshots.append(snapshot)
    result = ContractChecker(rules=(Fapi001ResponseProjectionRule(),)).check(*snapshots)
    assert result.status is (CheckStatus.BREAKING if expected_removed else CheckStatus.SAFE)
    assert all(finding.impact is CompatibilityImpact.INCOMPATIBLE for finding in result.findings)
    actual_removed = {
        path.segments[0] for finding in result.findings for path in finding.evidence.removed_fields
    }
    assert actual_removed == runtime_keys[0] - runtime_keys[1] == expected_removed


@pytest.mark.parametrize("factory", [dict, UserDict, MappingProxyType])
@pytest.mark.parametrize(
    ("before", "after", "removed"),
    [
        (None, {}, set()),
        (None, {"email": True}, {"email"}),
        (None, {"email": Ellipsis}, {"email"}),
        ({"email": True}, {}, set()),
        ({"email": True}, {"email": Ellipsis}, set()),
        ({"email": True}, {"id": Ellipsis}, {"id"}),
        (None, {"unknown": True}, set()),
        (None, {"email": True, "unknown": Ellipsis}, {"email"}),
    ],
)
def test_flat_mapping_agrees_with_pydantic_and_fastapi(factory, before, after, removed) -> None:
    _check_runtime_projection(
        Payload,
        {"id": 1, "email": "a@example.com"},
        None if before is None else factory(before),
        factory(after),
        removed,
    )


@pytest.mark.parametrize(
    ("annotation", "constraints", "value"),
    [
        (int, {"gt": 0}, 1),
        (int, {"ge": 0}, 0),
        (float, {"lt": 2}, 1.5),
        (float, {"le": 2}, 2.0),
        (int, {"multiple_of": 2}, 4),
        (str, {"min_length": 1}, "a"),
        (str, {"max_length": 2}, "ab"),
        (bytes, {"min_length": 1, "max_length": 2}, b"ab"),
        (int | None, {"gt": 0}, None),
        (int, {"gt": 0, "le": 10, "multiple_of": 2}, 4),
    ],
)
@pytest.mark.parametrize("narrowing", [False, True], ids=["widening", "narrowing"])
def test_validation_only_metadata_preserves_runtime_projection(
    annotation, constraints, value, narrowing
) -> None:
    model = create_model(
        "ConstrainedPayload", id=(int, ...), value=(annotation, Field(**constraints))
    )
    before, after = (None, {"value"}) if narrowing else ({"value"}, None)
    _check_runtime_projection(
        model, {"id": 1, "value": value}, before, after, {"value"} if narrowing else set()
    )


@pytest.mark.parametrize(
    "annotation",
    [
        Annotated[int, Field(gt=0), PlainSerializer(lambda value: str(value), return_type=str)],
        Annotated[int, Field(gt=0), object()],
    ],
)
def test_unknown_or_serializing_metadata_remains_unsupported(annotation) -> None:
    model = create_model("CustomPayload", value=(annotation, ...))
    before = _app(model, {"value": 1}, None)
    after = _app(model, {"value": 1}, {"value"})
    for app in (before, after):
        with TestClient(app) as client:
            assert client.get("/payload").status_code == 200
    extractor = FastApiSnapshotExtractor()
    baseline, current = extractor.extract(before), extractor.extract(after)
    assert baseline.application.routes[0].contract.response.state is ResponseStateKind.UNSUPPORTED
    assert current.application.routes[0].contract.response.state is ResponseStateKind.UNSUPPORTED
    result = ContractChecker(rules=(Fapi001ResponseProjectionRule(),)).check(baseline, current)
    assert result.status is CheckStatus.REVIEW
