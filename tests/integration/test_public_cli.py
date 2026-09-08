import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from fastapi_contract import cli
from fastapi_contract.codec.json import CanonicalJsonSnapshotCodec


def app_module(tmp_path, *, exclude="None", extra="", object_name="app"):
    name = f"cli_app_{uuid.uuid4().hex}"
    (tmp_path / f"{name}.py").write_text(
        "from fastapi import FastAPI\nfrom pydantic import BaseModel\n"
        "from contextlib import asynccontextmanager\n"
        "@asynccontextmanager\nasync def lifespan(app):\n"
        '    raise RuntimeError("lifespan must not run")\n    yield\n'
        "app = FastAPI(lifespan=lifespan)\n"
        "class User(BaseModel):\n    id: int\n    email: str\n"
        f'@app.get("/users", response_model=User, response_model_exclude={exclude})\n'
        'def users():\n    return {"id": 1, "email": "a@example.com"}\n' + extra,
        encoding="utf-8",
    )
    return f"{name}:{object_name}"


def run(*args):
    return cli.main(list(args))


def test_snapshot_success_loads_from_cwd_without_lifespan(tmp_path, monkeypatch):
    target = app_module(tmp_path)
    monkeypatch.chdir(tmp_path)
    output = tmp_path / "baseline.json"
    assert run("snapshot", target, "--output", str(output)) == 0
    value = CanonicalJsonSnapshotCodec().decode(output.read_text(encoding="utf-8"))
    assert value.metadata.schema_version == 1
    assert [(r.contract.key.method, r.contract.key.path) for r in value.application.routes] == [
        ("GET", "/users")
    ]


@pytest.mark.parametrize(
    "exclude,status,code",
    [("None", "SAFE", 0), ('{"email"}', "BREAKING", 1), ('{"email": {"nested"}}', "REVIEW", 1)],
)
def test_check_uses_fapi001_and_reports_exit(tmp_path, monkeypatch, capsys, exclude, status, code):
    monkeypatch.chdir(tmp_path)
    baseline = app_module(tmp_path)
    current = app_module(tmp_path, exclude=exclude)
    path = tmp_path / "baseline.json"
    assert run("snapshot", baseline, "-o", str(path)) == 0
    capsys.readouterr()
    assert run("check", current, "--against", str(path)) == code
    text = capsys.readouterr().out
    assert status in text
    if code:
        assert "FAPI001 GET /users" in text
        if status == "BREAKING":
            assert "response fields removed by projection: email" in text
    else:
        assert "supported contract surface" in text
    assert "FAPI002" not in text


@pytest.mark.parametrize(
    "target",
    ["malformed", ":app", "module:", "a:b:c", "bad-name:app", "missing_cli_module_xyz:app"],
)
def test_invalid_target_or_missing_module_is_error(target, tmp_path, capsys):
    output = tmp_path / "snapshot.json"
    assert run("snapshot", target, "-o", str(output)) == 2
    assert "ERROR" in capsys.readouterr().err
    assert not output.exists()


@pytest.mark.parametrize(
    "extra,attribute",
    [
        ("other = 42\n", "other"),
        ("", "missing"),
        ('raise RuntimeError("import failed")\n', "app"),
        ("raise SystemExit(0)\n", "app"),
    ],
)
def test_bad_import_or_object_is_error(tmp_path, monkeypatch, capsys, extra, attribute):
    target = app_module(tmp_path, extra=extra, object_name=attribute)
    monkeypatch.chdir(tmp_path)
    assert run("snapshot", target, "-o", str(tmp_path / "out.json")) == 2
    assert "ERROR" in capsys.readouterr().err


@pytest.mark.parametrize("baseline", ["invalid", "missing", "environment"])
def test_baseline_failure_is_error(tmp_path, monkeypatch, capsys, baseline):
    monkeypatch.chdir(tmp_path)
    target = app_module(tmp_path)
    path = tmp_path / "baseline.json"
    if baseline == "invalid":
        path.write_text("not JSON", encoding="utf-8")
    elif baseline == "environment":
        assert run("snapshot", target, "-o", str(path)) == 0
        payload = json.loads(path.read_text())
        payload["metadata"]["environment"]["python_version"] = "different"
        path.write_text(json.dumps(payload))
    capsys.readouterr()
    assert run("check", target, "--against", str(path)) == 2
    captured = capsys.readouterr()
    assert "ERROR" in captured.out + captured.err


def test_output_write_failure_is_error(tmp_path, monkeypatch, capsys):
    target = app_module(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert run("snapshot", target, "-o", str(tmp_path / "missing" / "out.json")) == 2
    assert "ERROR" in capsys.readouterr().err


def test_invalid_baseline_is_rejected_before_app_import(tmp_path, monkeypatch, capsys):
    target = app_module(tmp_path, extra='raise AssertionError("app must not be imported")\n')
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "baseline.json"
    path.write_text("not JSON", encoding="utf-8")
    assert run("check", target, "--against", str(path)) == 2
    assert target.split(":")[0] not in sys.modules
    error = capsys.readouterr().err
    assert "ERROR" in error
    assert "app must not be imported" not in error


def test_console_script_snapshot_and_check_from_app_directory(tmp_path):
    target = app_module(tmp_path)
    executable = str(Path(sys.executable).parent / "fastapi-contract")
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    first = subprocess.run(
        [executable, "snapshot", target, "-o", "baseline.json"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
    )
    assert first.returncode == 0, first.stderr
    second = subprocess.run(
        [executable, "check", target, "--against", "baseline.json"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
    )
    assert second.returncode == 0, second.stderr
    assert "SAFE" in second.stdout
