from collections import UserDict
from types import MappingProxyType
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict

from fastapi_contract.adapters import fastapi as adapter
from fastapi_contract.domain.model import Completeness, ObjectSelection, ResponseStateKind


class Payload(BaseModel):
    id: int
    email: str


@pytest.mark.parametrize("factory", [dict, UserDict, MappingProxyType])
@pytest.mark.parametrize("mapping", [{}, {"email": True}, {"email": Ellipsis}])
def test_extracts_flat_mapping_as_complete_selection(factory, mapping) -> None:
    app = FastAPI()
    app.add_api_route(
        "/payload",
        lambda: {"id": 1, "email": "a@example.com"},
        response_model=Payload,
        response_model_exclude=factory(mapping),
    )

    snapshot = adapter.FastApiSnapshotExtractor().extract(app)

    assert len(snapshot.application.routes) == 1
    response = snapshot.application.routes[0].contract.response
    assert response.state is ResponseStateKind.SUPPORTED
    assert response.policy is not None
    assert response.policy.exclude is not None
    assert response.policy.exclude.completeness is Completeness.COMPLETE
    assert isinstance(response.policy.exclude.root, ObjectSelection)
    assert tuple(entry.name for entry in response.policy.exclude.root.fields) == tuple(
        sorted(mapping)
    )


@pytest.mark.parametrize("open_model", [False, True], ids=["supported", "unsupported"])
def test_shared_model_shape_is_introspected_once_per_extract(open_model: bool) -> None:
    class Shared(BaseModel):
        model_config = ConfigDict(extra="allow" if open_model else "ignore")
        id: int
        email: str

    app = FastAPI()
    for index in range(5):
        app.add_api_route(
            f"/payload/{index}",
            lambda: {"id": 1, "email": "a@example.com"},
            methods=["GET", "POST"],
            response_model=Shared,
            response_model_exclude={"email"} if index % 2 else None,
        )
    extractor = adapter.FastApiSnapshotExtractor()
    with patch.object(adapter, "_extract_shape", wraps=adapter._extract_shape) as introspect:
        first = extractor.extract(app)
        introspect.assert_called_once_with(Shared)
        assert len(first.application.routes) == 10
        assert all(
            item.contract.response.state
            is (ResponseStateKind.UNSUPPORTED if open_model else ResponseStateKind.SUPPORTED)
            for item in first.application.routes
        )
        assert (
            sum(
                item.contract.response.policy.exclude is not None
                for item in first.application.routes
            )
            == 4
        )

        # A later extraction must not reuse stale framework facts across runs.
        second = extractor.extract(app)
        assert introspect.call_count == 2
        assert second == first
