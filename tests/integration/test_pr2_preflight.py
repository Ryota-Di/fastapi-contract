import tomllib
from pathlib import Path
from typing import Annotated

import pytest
from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainValidator,
    WrapValidator,
    create_model,
    field_validator,
)
from tests.integration.test_body_binding import app, compare

from fastapi_contract.application.checker import CheckStatus


@pytest.mark.parametrize("mode", ["before", "after", "plain", "wrap"])
def test_candidate_field_validator_does_not_own_binding(mode):
    class Payload(BaseModel):
        model_config = ConfigDict(validate_by_name=True)
        user_id: int = Field(0, validation_alias="userId")

        if mode == "wrap":

            @field_validator("user_id", mode="wrap")
            @classmethod
            def normalize(cls, value, handler):
                return handler(value)
        else:

            @field_validator("user_id", mode=mode)
            @classmethod
            def normalize(cls, value):
                return value

    new = create_model("Payload", __base__=Payload, __config__=ConfigDict(validate_by_name=False))
    result = compare(app(Payload), app(new))
    assert result.status is CheckStatus.BREAKING
    assert result.findings[0].evidence.lost_bindings[0].wire_key == "user_id"


@pytest.mark.parametrize(
    "validator",
    [
        BeforeValidator(lambda v: v),
        AfterValidator(lambda v: v),
        PlainValidator(lambda v: v),
        WrapValidator(lambda v, handler: handler(v)),
    ],
)
def test_field_local_annotated_validator_does_not_own_binding(validator):
    def model(by_name):
        return create_model(
            "Payload",
            __config__=ConfigDict(validate_by_name=by_name),
            user_id=(Annotated[int, validator], Field(0, alias="userId")),
        )

    assert compare(app(model(True)), app(model(False))).status is CheckStatus.BREAKING


def test_declared_framework_versions_match_proven_runtime_gate():
    config = tomllib.loads(Path("pyproject.toml").read_text())
    assert "fastapi==0.141.1" in config["project"]["dependencies"]
    assert "pydantic==2.13.5" in config["project"]["dependencies"]
