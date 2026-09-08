from unittest.mock import patch

from fastapi import FastAPI
from pydantic import BaseModel

from fastapi_contract.adapters import fastapi as adapter
from fastapi_contract.adapters import selection as selection_adapter
from fastapi_contract.application.checker import CheckStatus, ContractChecker
from fastapi_contract.codec.json import CanonicalJsonSnapshotCodec
from fastapi_contract.rules.fapi001 import Fapi001ResponseProjectionRule


def test_selection_canonicalization_occurs_once_per_policy_at_adapter_boundary() -> None:
    class Shared(BaseModel):
        id: int
        email: str

    def app(exclude):
        value = FastAPI()
        for index in range(3):
            value.add_api_route(
                f"/payload/{index}",
                lambda: {"id": 1, "email": "a@example.com"},
                methods=["GET", "POST"],
                response_model=Shared,
                response_model_exclude=exclude,
            )
        return value

    extractor = adapter.FastApiSnapshotExtractor()
    with patch.object(
        adapter, "normalize_top_level_selection", wraps=adapter.normalize_top_level_selection
    ) as normalize:
        baseline = extractor.extract(app(None))
        assert len(baseline.application.routes) == 6
        assert normalize.call_count == 6  # include + exclude per route, before method expansion
        normalize.reset_mock()
        current = extractor.extract(app({"email": True}))
        assert normalize.call_count == 6
        assert sum(call.args == ({"email": True},) for call in normalize.call_args_list) == 3

    # Guard both the exported adapter alias and the defining module. Codec and
    # rules must consume canonical facts, even for a second comparison.
    with (
        patch.object(
            adapter,
            "normalize_top_level_selection",
            side_effect=AssertionError("Repeated adapter canonicalization"),
        ),
        patch.object(
            selection_adapter,
            "normalize_top_level_selection",
            side_effect=AssertionError("Canonicalization outside adapter boundary"),
        ),
    ):
        codec = CanonicalJsonSnapshotCodec()
        baseline = codec.decode(codec.encode(baseline))
        current = codec.decode(codec.encode(current))
        checker = ContractChecker(rules=(Fapi001ResponseProjectionRule(),))
        for _ in range(2):
            result = checker.check(baseline, current)
            assert result.status is CheckStatus.BREAKING
            assert len(result.findings) == 6
