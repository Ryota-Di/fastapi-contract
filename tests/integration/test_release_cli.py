"""Installed console-script release contract; app import happens in a fresh process."""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

NOTICE = (
    "Baseline uses snapshot schema v1.\n"
    "Running legacy checks only.\n"
    "Regenerate the baseline to enable current contract checks.\n"
)
CLI = str(Path(sys.executable).parent / "fastapi-contract")


def run(tmp_path, *args, seed="1"):
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment["PYTHONHASHSEED"] = seed
    return subprocess.run(
        [CLI, *args], cwd=tmp_path, env=environment, capture_output=True, text=True, check=False
    )


def write_app(tmp_path, name, *, changes=(), legacy=False, unknown=False, reverse=False):
    changes = set(changes)
    fields = '    id: int\n    notes: str = ""\n'
    if not legacy:
        fields += "    state: State = State.READY\n    detail: Detail = Detail()\n"
    exclude = {"notes": True} if "response" in changes else {}
    if unknown:
        exclude["detail"] = {"text"}
    query = "credential" if "query" in changes else "token"
    header = "X-Credential" if "header" in changes else "X-Token"
    cookie = "sid" if "cookie" in changes else "session"
    default = "..." if "requirement" in changes else '""'
    arguments = [
        "data: Input",
        f'py_query: str = Query("", alias={query!r}, include_in_schema=False)',
        f'py_header: str = Header("", alias={header!r}, include_in_schema=False)',
        f'py_cookie: str = Cookie("", alias={cookie!r}, include_in_schema=False)',
        f'py_mode: str = Query({default}, alias="mode", include_in_schema=False)',
    ]
    if reverse:
        arguments = arguments[:1] + list(reversed(arguments[1:]))
    source = (
        "from fastapi import FastAPI, Query, Header, Cookie\n"
        "from pydantic import BaseModel, ConfigDict, Field\n"
        "from enum import Enum\n"
        "from contextlib import asynccontextmanager\n"
        "@asynccontextmanager\nasync def lifespan(app):\n"
        '    raise AssertionError("lifespan must not run")\n    yield\n'
        "app = FastAPI(lifespan=lifespan)\n"
        'class State(Enum):\n    READY = "ready"\n'
        'class Detail(BaseModel):\n    text: str = ""\n'
        "class Output(BaseModel):\n" + fields + "class Input(BaseModel):\n"
        f"    model_config = ConfigDict(validate_by_name={'body' not in changes})\n"
        '    user_id: int = Field(1, alias="userId")\n'
        f'@app.post("/items", response_model=Output, response_model_exclude={exclude!r})\n'
        f"def endpoint({', '.join(arguments)}):\n"
        '    raise AssertionError("endpoint must not run")\n'
    )
    (tmp_path / f"{name}.py").write_text(source)
    return f"{name}:app"


def snapshot(tmp_path, target, version=None):
    args = ["snapshot", target, "-o", "baseline.json"]
    if version is not None:
        args.extend(["--schema-version", str(version)])
    result = run(tmp_path, *args)
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")
    return tmp_path / "baseline.json"


@pytest.mark.parametrize("version", [None, 1, 2])
def test_snapshot_default_and_explicit_versions(tmp_path, version):
    target = write_app(tmp_path, "old")
    baseline = snapshot(tmp_path, target, version)
    payload = json.loads(baseline.read_text())
    expected = 2 if version is None else version
    assert payload["metadata"]["schema_version"] == expected
    if expected == 2:
        assert set(payload["metadata"]) == {"schema_version", "tool_version", "environment"}
        assert set(payload["application"]["routes"][0]) == {
            "key",
            "match_key",
            "response",
            "body_binding",
            "parameters",
        }
    checked = run(tmp_path, "check", target, "--against", str(baseline))
    assert checked.returncode == 0
    assert (
        checked.stdout == "SAFE: No incompatibility detected in the supported contract surface.\n"
    )
    assert checked.stderr == (NOTICE if expected == 1 else "")


@pytest.mark.parametrize(
    "case,status,code", [("safe", "SAFE", 0), ("breaking", "BREAKING", 1), ("review", "REVIEW", 1)]
)
def test_legacy_result_and_notice(tmp_path, case, status, code):
    target = write_app(tmp_path, "old", legacy=case != "review")
    current = write_app(
        tmp_path, "new", legacy=case != "review", changes=() if case == "safe" else ("response",)
    )
    baseline = snapshot(tmp_path, target, 1)
    original = baseline.read_bytes()
    checked = run(tmp_path, "check", current, "--against", str(baseline))
    assert checked.returncode == code
    assert checked.stdout.splitlines()[0].split(":")[0] == status
    assert checked.stderr == NOTICE
    if code:
        assert "FAPI001 POST /items:" in checked.stdout
        assert "response-wire-surface" not in checked.stdout
    assert baseline.read_bytes() == original


@pytest.mark.parametrize("version", [1, 2])
@pytest.mark.parametrize("failure", ["environment", "import", "extraction", "duplicate"])
def test_errors_only_stderr_after_valid_baseline(tmp_path, version, failure):
    target = write_app(tmp_path, "old")
    baseline = snapshot(tmp_path, target, version)
    payload = json.loads(baseline.read_text())
    if failure == "environment":
        payload["metadata"]["environment"]["python_version"] = "different"
    elif failure == "duplicate":
        payload["application"]["routes"] *= 2
    elif failure == "extraction":
        with (tmp_path / "old.py").open("a") as stream:
            stream.write(
                "\nfrom fastapi.routing import APIRoute\nfor r in app.routes:\n"
                "    if isinstance(r, APIRoute): r.methods = None\n"
            )
    else:
        (tmp_path / "broken.py").write_text('raise RuntimeError("import failed")\n')
        target = "broken:app"
    baseline.write_text(json.dumps(payload))
    checked = run(tmp_path, "check", target, "--against", str(baseline))
    assert checked.returncode == 2
    assert checked.stdout == ""
    assert checked.stderr.startswith(NOTICE if version == 1 else "ERROR")
    assert checked.stderr.count(NOTICE) == (1 if version == 1 else 0)
    assert "ERROR" in checked.stderr


@pytest.mark.parametrize(
    "change,owner,wire",
    [
        ("response", "response-wire-surface", "notes"),
        ("body", "request-body-binding", "user_id"),
        ("query", "hidden-parameter-binding", "token"),
        ("header", "hidden-parameter-binding", "x-token"),
        ("cookie", "hidden-parameter-binding", "session"),
        ("requirement", "hidden-parameter-requirement", "mode"),
    ],
)
def test_current_owners(tmp_path, change, owner, wire):
    old = write_app(tmp_path, "old")
    new = write_app(tmp_path, "new", changes=(change,))
    baseline = snapshot(tmp_path, old)
    checked = run(tmp_path, "check", new, "--against", str(baseline))
    assert checked.returncode == 1
    assert checked.stderr == ""
    assert checked.stdout.startswith("BREAKING\n")
    assert f"{owner} POST /items:" in checked.stdout
    assert json.dumps(wire) in checked.stdout
    assert "py_query" not in checked.stdout
    assert "py_header" not in checked.stdout
    assert "py_cookie" not in checked.stdout
    assert "py_mode" not in checked.stdout
    if change == "response":
        assert "key remains documented by OpenAPI" in checked.stdout
    if change == "body":
        assert 'input slot "userId"' in checked.stdout
    if change == "requirement":
        assert "optional to required" in checked.stdout


def test_all_owners_and_review_deterministic(tmp_path):
    old = write_app(tmp_path, "old")
    new = write_app(
        tmp_path,
        "new",
        changes=("response", "body", "query", "header", "cookie", "requirement"),
        unknown=True,
    )
    reversed_app = write_app(
        tmp_path,
        "reordered",
        changes=("response", "body", "query", "header", "cookie", "requirement"),
        unknown=True,
        reverse=True,
    )
    baseline = snapshot(tmp_path, old)
    outputs = [
        run(tmp_path, "check", target, "--against", str(baseline), seed=seed)
        for target in (new, reversed_app)
        for seed in ("1", "17", "123")
    ]
    assert all((r.returncode, r.stderr) == (1, "") for r in outputs)
    assert len({r.stdout for r in outputs}) == 1
    output = outputs[0].stdout
    assert output.startswith("BREAKING\n")
    assert {line.split()[0] for line in output.splitlines()[1:]} == {
        "response-wire-surface",
        "request-body-binding",
        "hidden-parameter-binding",
        "hidden-parameter-requirement",
    }
    assert (
        'Cannot confirm response wire key "detail": unsupported_response_selector (current)'
        in output
    )
    assert 'Response wire key "notes" is no longer produced' in output


@pytest.mark.parametrize(
    "invalid",
    [
        "{",
        "null",
        "[]",
        "{}",
        '{"metadata":{}}',
        '{"metadata":{"schema_version":1,"schema_version":2}}',
        *[
            json.dumps({"metadata": {"schema_version": v}})
            for v in (True, False, "1", "2", 1.0, 2.0, 999)
        ],
        '{"metadata":{"schema_version":1},"application":[]}',
        '{"metadata":{"schema_version":2},"application":[]}',
    ],
)
def test_invalid_baseline_before_app_import(tmp_path, invalid):
    (tmp_path / "side_effect.py").write_text(
        'from pathlib import Path\nPath("imported").touch()\n'
        'raise RuntimeError("must not import")\n'
    )
    baseline = tmp_path / "baseline.json"
    baseline.write_text(invalid)
    result = run(tmp_path, "check", "side_effect:app", "--against", str(baseline))
    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr.startswith("ERROR")
    assert NOTICE not in result.stderr
    assert not (tmp_path / "imported").exists()


def test_regeneration_enables_current_checks(tmp_path):
    old = write_app(tmp_path, "old")
    new = write_app(tmp_path, "new", changes=("response",))
    baseline = snapshot(tmp_path, old, 1)
    legacy_bytes = baseline.read_bytes()
    legacy = run(tmp_path, "check", new, "--against", str(baseline))
    assert (legacy.returncode, legacy.stderr) == (1, NOTICE)
    assert legacy.stdout.startswith("REVIEW\nFAPI001")
    (tmp_path / "legacy.json").write_bytes(legacy_bytes)
    snapshot(tmp_path, old)
    current = run(tmp_path, "check", new, "--against", str(baseline))
    assert (current.returncode, current.stderr) == (1, "")
    assert current.stdout.startswith("BREAKING\nresponse-wire-surface")
    again = run(tmp_path, "check", new, "--against", "legacy.json")
    assert (again.returncode, again.stdout, again.stderr) == (
        legacy.returncode,
        legacy.stdout,
        legacy.stderr,
    )
    assert (tmp_path / "legacy.json").read_bytes() == legacy_bytes
    assert "migrate" not in run(tmp_path, "--help").stdout


def test_published_v1_golden_unchanged():
    # Pin the published transport fixture, including synthetic recorded environment.
    original = Path(__file__).parents[1] / "fixtures/schema-v1.json"
    assert (
        hashlib.sha256(original.read_bytes()).hexdigest()
        == "47e94aec43a2e19230588b5b055dfc8c08b49d4e605a7e706fa2cace24c55e3f"
    )


@pytest.mark.parametrize("wire", ['a"b', "a\\b", "a\nb", "名前", "", "a.b"])
def test_cli_response_wire_escaping(tmp_path, wire):
    for name, exclude in (("before", "None"), ("after", "{'python_field'}")):
        (tmp_path / f"{name}.py").write_text(
            "from fastapi import FastAPI\nfrom pydantic import BaseModel, Field\n"
            "app = FastAPI()\nclass Model(BaseModel):\n"
            f'    python_field: str = Field("", serialization_alias={wire!r})\n'
            f'@app.get("/wire", response_model=Model, response_model_exclude={exclude})\n'
            'def endpoint():\n    raise AssertionError("must not execute")\n'
        )
    baseline = snapshot(tmp_path, "before:app")
    checked = run(tmp_path, "check", "after:app", "--against", str(baseline))
    assert (checked.returncode, checked.stderr) == (1, "")
    assert json.dumps(wire) in checked.stdout
    assert "python_field" not in checked.stdout
    assert len(checked.stdout.splitlines()) == 2


def test_cli_review_only_current_candidate(tmp_path):
    old = write_app(tmp_path, "old")
    new = write_app(tmp_path, "new", unknown=True)
    baseline = snapshot(tmp_path, old)
    checked = run(tmp_path, "check", new, "--against", str(baseline))
    assert checked.returncode == 1
    assert checked.stderr == ""
    assert checked.stdout == (
        'REVIEW\nresponse-wire-surface POST /items: Cannot confirm response wire key "detail": '
        "unsupported_response_selector (current)\n"
    )


def test_cli_unknown_binding_stays_in_bounded_region(tmp_path):
    for name, arguments in (
        (
            "before",
            'python_arg: str = Query("", alias="token", '
            'validation_alias=AliasChoices("token", "alt"), include_in_schema=False)',
        ),
        ("after", ""),
    ):
        (tmp_path / f"{name}.py").write_text(
            "from fastapi import FastAPI, Query\nfrom pydantic import AliasChoices\n"
            'app = FastAPI()\n@app.get("/unknown")\n'
            f"def endpoint({arguments}):\n    return {{}}\n"
        )
    baseline = snapshot(tmp_path, "before:app")
    checked = run(tmp_path, "check", "after:app", "--against", str(baseline))
    assert (checked.returncode, checked.stderr) == (1, "")
    assert checked.stdout.startswith("REVIEW\n")
    assert 'region possibly containing query "alt", query "token"' in checked.stdout
    assert "python_arg" not in checked.stdout
    assert "header" not in checked.stdout and "cookie" not in checked.stdout
    assert "is no longer bound" not in checked.stdout
