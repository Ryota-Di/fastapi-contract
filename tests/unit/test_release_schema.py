import json
from pathlib import Path

import pytest

from fastapi_contract.codec.schema_v1 import SnapshotCodecError
from fastapi_contract.codec.schema_v2 import SnapshotV2Codec


@pytest.mark.parametrize(
    "fixture", ["schema-v2.json", "schema-v2-body.json", "schema-v2-parameters.json"]
)
@pytest.mark.parametrize(
    "mutation",
    ["profile", "response", "body_binding", "parameters", "body_null", "parameters_null"],
)
def test_final_v2_requires_one_complete_representation(fixture, mutation):
    original = (Path(__file__).parents[1] / "fixtures" / fixture).read_text()
    payload = json.loads(original)
    route = payload["application"]["routes"][0]
    if mutation == "profile":
        payload["metadata"]["fact_profile"] = "response-and-body-binding"
    elif mutation.endswith("_null"):
        route["body_binding" if mutation == "body_null" else "parameters"] = None
    else:
        route.pop(mutation)
    with pytest.raises(SnapshotCodecError):
        SnapshotV2Codec().decode(json.dumps(payload))


def test_duplicate_route_occurrences_preserved_for_analysis_error():
    original = (Path(__file__).parents[1] / "fixtures/schema-v2-parameters.json").read_text()
    payload = json.loads(original)
    payload["application"]["routes"] *= 2
    document = SnapshotV2Codec().decode(json.dumps(payload))
    assert len(document.facts.routes) == 2
    assert len(document.facts.routes[0].parameters.occurrences) == 2
    encoded = SnapshotV2Codec().encode(document)
    assert SnapshotV2Codec().encode(SnapshotV2Codec().decode(encoded)) == encoded
