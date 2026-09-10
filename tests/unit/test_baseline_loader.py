import ast
import json
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch

import pytest

from fastapi_contract.application.baseline_loader import (
    CurrentBaseline,
    LegacyBaseline,
    load_baseline,
)
from fastapi_contract.codec.schema_v1 import CanonicalJsonSnapshotCodec, SnapshotCodecError
from fastapi_contract.codec.schema_v2 import SnapshotV2Codec

FIXTURES = Path(__file__).parents[1] / "fixtures"


@pytest.mark.parametrize(
    "filename,tag,kind,codec",
    [
        ("schema-v1.json", "legacy", LegacyBaseline, CanonicalJsonSnapshotCodec),
        ("schema-v2.json", "current", CurrentBaseline, SnapshotV2Codec),
        ("schema-v2-body.json", "current", CurrentBaseline, SnapshotV2Codec),
    ],
)
def test_loads_full_document_without_conversion(filename, tag, kind, codec):
    text = (FIXTURES / filename).read_text()
    baseline = load_baseline(text)
    assert isinstance(baseline, kind)
    assert baseline.kind == tag
    assert baseline.document == codec().decode(text)
    with pytest.raises(FrozenInstanceError):
        baseline.kind = "other"


@pytest.mark.parametrize(
    "text",
    [
        "{",
        "not JSON",
        "null",
        "[]",
        "{}",
        '{"metadata":{}}',
        '{"metadata":{"schema_version":1,"schema_version":2}}',
        '{"metadata":{"schema_version":1},"application":{"x":1,"x":2}}',
        '{"metadata":{"schema_version":1},"value":NaN}',
        *[
            json.dumps({"metadata": {"schema_version": v}})
            for v in [None, True, False, 1.0, 2.0, "1", "2", 0, -1, 3, 999]
        ],
    ],
)
def test_invalid_envelope_never_reaches_either_decoder(text):
    with (
        patch.object(CanonicalJsonSnapshotCodec, "decode") as v1,
        patch.object(SnapshotV2Codec, "decode") as v2,
        pytest.raises(SnapshotCodecError),
    ):
        load_baseline(text)
    v1.assert_not_called()
    v2.assert_not_called()


@pytest.mark.parametrize("version", [1, 2])
def test_known_version_invalid_body_uses_only_selected_codec(version):
    text = json.dumps({"metadata": {"schema_version": version}, "application": []})
    selected, other = (
        (CanonicalJsonSnapshotCodec, SnapshotV2Codec)
        if version == 1
        else (SnapshotV2Codec, CanonicalJsonSnapshotCodec)
    )
    with pytest.raises(SnapshotCodecError) as direct:
        selected().decode(text)
    with patch.object(other, "decode") as fallback, pytest.raises(SnapshotCodecError) as loaded:
        load_baseline(text)
    assert str(loaded.value) == str(direct.value)
    fallback.assert_not_called()


def test_loader_dependencies_exclude_app_loading_and_lane_execution():
    source = Path(__file__).parents[2] / "src/fastapi_contract/application/baseline_loader.py"
    modules = set()
    for node in ast.walk(ast.parse(source.read_text())):
        if isinstance(node, ast.ImportFrom):
            modules.add(node.module)
        elif isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
    assert modules <= {
        "dataclasses",
        "typing",
        "fastapi_contract.codec.json",
        "fastapi_contract.codec.schema_v1",
        "fastapi_contract.codec.schema_v2",
        "fastapi_contract.compat.v1.model",
    }


@pytest.mark.parametrize("version", [1, 2])
def test_valid_document_does_not_call_other_codec_or_dispatch_on_tool_version(version):
    text = (FIXTURES / f"schema-v{version}.json").read_text()
    payload = json.loads(text)
    payload["metadata"]["tool_version"] = "999.0-future-tool"
    other = SnapshotV2Codec if version == 1 else CanonicalJsonSnapshotCodec
    with patch.object(other, "decode") as fallback:
        result = load_baseline(json.dumps(payload))
    assert isinstance(result, LegacyBaseline if version == 1 else CurrentBaseline)
    fallback.assert_not_called()


def test_future_inspector_support_cannot_create_implicit_lane():
    with (
        patch(
            "fastapi_contract.application.baseline_loader.snapshot_schema_version", return_value=3
        ),
        pytest.raises(SnapshotCodecError, match="Unsupported snapshot schema version"),
    ):
        load_baseline("unused")


@pytest.mark.parametrize("version", [1, 2])
def test_selected_codec_error_is_propagated_without_fallback(version):
    selected, other = (
        (CanonicalJsonSnapshotCodec, SnapshotV2Codec)
        if version == 1
        else (SnapshotV2Codec, CanonicalJsonSnapshotCodec)
    )
    error = SnapshotCodecError("selected transport failure")
    with (
        patch.object(selected, "decode", side_effect=error) as decode,
        patch.object(other, "decode") as fallback,
        pytest.raises(SnapshotCodecError) as caught,
    ):
        load_baseline(json.dumps({"metadata": {"schema_version": version}}))
    assert caught.value is error
    decode.assert_called_once()
    fallback.assert_not_called()
