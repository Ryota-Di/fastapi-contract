from dataclasses import replace
from enum import Enum
from hashlib import sha256
from pathlib import Path

import pytest
from fastapi import FastAPI
from pydantic import BaseModel
from tests.support import route, selection, snapshot

from fastapi_contract.application.checker import CheckStatus, ContractChecker
from fastapi_contract.codec.schema_v1 import CanonicalJsonSnapshotCodec
from fastapi_contract.compat.v1.lane import LegacyLane
from fastapi_contract.compat.v1.model import ContractSnapshot, ResponseStateKind
from fastapi_contract.domain.finding import CompatibilityImpact, FieldPath, ProjectionEvidence
from fastapi_contract.reporting.text import TextReporter
from fastapi_contract.rules.fapi001 import Fapi001ResponseProjectionRule


@pytest.fixture
def baseline():
    text = (Path(__file__).parents[1] / "fixtures/schema-v1.json").read_text()
    return CanonicalJsonSnapshotCodec().decode(text)


@pytest.mark.parametrize(
    "current,status,output,evidence",
    [
        (
            snapshot(route()),
            CheckStatus.SAFE,
            "SAFE: No incompatibility detected in the supported contract surface.",
            None,
        ),
        (
            snapshot(route(exclude=selection("email"))),
            CheckStatus.BREAKING,
            "BREAKING\nFAPI001 GET /users: response fields removed by projection: email",
            ProjectionEvidence((FieldPath(("email",)),)),
        ),
        (
            snapshot(route(include=selection("id"))),
            CheckStatus.REVIEW,
            "REVIEW\nFAPI001 GET /users: reason: response_model_include is unsupported in Slice 1",
            ProjectionEvidence(reason="response_model_include is unsupported in Slice 1"),
        ),
        (
            snapshot(route(), python_version="different"),
            CheckStatus.ERROR,
            "ERROR INCOMPATIBLE_ENVIRONMENT: Snapshot framework or Python versions differ",
            None,
        ),
        (
            snapshot(route(), route()),
            CheckStatus.ERROR,
            "ERROR AMBIGUOUS_ROUTE_IDENTITY: Duplicate runtime route identity: "
            "RouteMatchKey(method='GET', normalized_path_regex='^/users$')",
            None,
        ),
    ],
)
def test_frozen_fixture_results_and_output(baseline, current, status, output, evidence):
    result = LegacyLane().check(baseline, current)
    assert result.status is status
    assert TextReporter().render(result) == output
    assert result == ContractChecker((Fapi001ResponseProjectionRule(),)).check(baseline, current)
    if evidence is not None:
        assert len(result.findings) == 1
        finding = result.findings[0]
        assert finding.rule_id == "FAPI001"
        assert finding.evidence == evidence
        assert finding.impact is (
            CompatibilityImpact.INCOMPATIBLE
            if status is CheckStatus.BREAKING
            else CompatibilityImpact.UNKNOWN
        )


def test_duplicate_baseline_is_error(baseline):
    duplicate = replace(
        baseline, application=replace(baseline.application, routes=baseline.application.routes * 2)
    )
    result = LegacyLane().check(duplicate, baseline)
    assert result.status is CheckStatus.ERROR
    assert result.error.code == "AMBIGUOUS_ROUTE_IDENTITY"


def test_facade_extracts_legacy_unsupported_response_without_recovering_facts(capsys):
    class State(Enum):
        READY = "ready"

    class Response(BaseModel):
        state: State
        notes: str

    def app(exclude):
        application = FastAPI()

        @application.get("/books", response_model=Response, response_model_exclude=exclude)
        def endpoint():
            raise AssertionError("Extraction must not execute endpoints")

        return application

    lane = LegacyLane()
    before, after = lane.extract(app(None)), lane.extract(app({"notes"}))
    assert isinstance(before, ContractSnapshot)
    assert before.metadata.schema_version == 1
    response = before.application.routes[0].contract.response
    assert response.state is ResponseStateKind.UNSUPPORTED
    assert response.shape is None
    result = lane.check(before, after)
    assert result.status is CheckStatus.REVIEW
    assert result.findings[0].rule_id == "FAPI001"
    assert result.findings[0].evidence == ProjectionEvidence(
        reason="Nested or custom response field serialization is unsupported"
    )
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize(
    "path,digest",
    [
        ("adapters/fastapi.py", "38d82ba449f7eb6ebbbf949c79243f4e9439b0dcb165cc044df898fefa9360cf"),
        (
            "adapters/selection.py",
            "bbe49d6b94e18761f399686d25c873be80bdd8c3f2fadd60ed9fcf26208f45fa",
        ),
        (
            "application/checker.py",
            "5821b365f9286042dcd4d42d50ba8b314f65bcb1a12855cfed2b18d776d2da7e",
        ),
        ("rules/fapi001.py", "eb4c1748b253456c7c608e1d913de7b2dd6caf646b01c180788b24f193d27966"),
    ],
)
def test_delegated_legacy_algorithms_require_explicit_compatibility_review(path, digest):
    # Pin PR2 base 955ab87. Do not refresh for new current-lane behavior: these
    # modules are legacy-owned. Even a harmless edit requires explicit review.
    source = Path(__file__).parents[2] / "src/fastapi_contract" / path
    assert sha256(source.read_bytes()).hexdigest() == digest, (
        f"Legacy-owned {path} changed; review v1 compatibility before updating this pin"
    )
