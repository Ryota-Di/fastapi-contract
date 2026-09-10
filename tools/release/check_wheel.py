"""Check built metadata and exercise a wheel outside the repository (stdlib only)."""

import argparse
import configparser
import email.policy
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import zipfile
from email.parser import BytesParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def check_metadata(raw: bytes, project: dict) -> None:
    metadata = BytesParser(policy=email.policy.default).parsebytes(raw)
    require(metadata["Name"] == "fastapi-contract", "Incorrect distribution name")
    require(metadata["Version"] == project["version"], "Version differs from pyproject.toml")
    require(
        metadata["Requires-Python"] == project["requires-python"],
        "Requires-Python missing or differs from pyproject.toml",
    )
    require(
        "Repository, https://github.com/Ryota-Di/fastapi-contract"
        in metadata.get_all("Project-URL", []),
        "Production repository URL missing",
    )
    require(b"fastapi-contract-dev" not in raw.lower(), "Dev repository leaked into metadata")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist-dir", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    wheels = list(args.dist_dir.glob("*.whl"))
    sdists = list(args.dist_dir.glob("*.tar.gz"))
    require(len(wheels) == len(sdists) == 1, "Expected exactly one wheel and one sdist")
    wheel = wheels[0].resolve()
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    with zipfile.ZipFile(wheel) as archive:
        names = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
        require(len(names) == 1, "Wheel must contain one METADATA file")
        check_metadata(archive.read(names[0]), project)
        entry_points = configparser.ConfigParser()
        entry_points.read_string(
            archive.read(names[0].removesuffix("METADATA") + "entry_points.txt").decode()
        )
        require(
            entry_points["console_scripts"]["fastapi-contract"]
            == project["scripts"]["fastapi-contract"],
            "Console entry point differs from pyproject.toml",
        )
    with tarfile.open(sdists[0]) as archive:
        metadata_files = [
            member
            for member in archive.getmembers()
            if len(Path(member.name).parts) == 2 and member.name.endswith("/PKG-INFO")
        ]
        require(len(metadata_files) == 1, "Sdist must contain one root PKG-INFO")
        metadata_file = archive.extractfile(metadata_files[0])
        require(metadata_file is not None, "Cannot read sdist metadata")
        check_metadata(metadata_file.read(), project)
    print("Wheel and sdist metadata OK", flush=True)

    environment = os.environ.copy()
    for key in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"):
        environment.pop(key, None)
    environment["PYTHONNOUSERSITE"] = "1"

    # Explicitly use the system temporary area, even if TMPDIR points into the repo.
    with tempfile.TemporaryDirectory(prefix="fastapi-contract-wheel-", dir="/tmp") as directory:
        work = Path(directory).resolve()
        require(not work.is_relative_to(ROOT), "Smoke directory must be outside the repository")

        def run(*command: str, cwd: Path = work) -> None:
            subprocess.run(command, cwd=cwd, env=environment, check=True)

        requirements = work / "runtime.txt"
        run(
            "uv",
            "export",
            "--quiet",
            "--python",
            sys.executable,
            "--locked",
            "--no-dev",
            "--no-default-groups",
            "--no-emit-project",
            "--output-file",
            str(requirements),
            cwd=ROOT,
        )
        venv = work / "venv"
        run("uv", "venv", "--python", sys.executable, str(venv))
        python = str(venv / "bin/python")
        run(
            "uv",
            "pip",
            "install",
            "--python",
            python,
            "--require-hashes",
            "--only-binary",
            ":all:",
            "-r",
            str(requirements),
        )
        run("uv", "pip", "install", "--python", python, "--no-deps", str(wheel))
        run("uv", "pip", "check", "--python", python)
        # -I ignores user site and Python environment overrides. Check the actual package path
        # as well as distribution provenance, so an editable install cannot masquerade as a wheel.
        run(
            python,
            "-I",
            "-c",
            """
import importlib.metadata
import json
import pathlib
import sys
import fastapi_contract

prefix = pathlib.Path(sys.prefix).resolve()
origin = pathlib.Path(fastapi_contract.__file__).resolve()
if not origin.is_relative_to(prefix):
    raise RuntimeError(f"Package imported outside clean venv: {origin}")
dist = importlib.metadata.distribution("fastapi-contract")
direct = json.loads(dist.read_text("direct_url.json"))
if direct.get("dir_info", {}).get("editable") or not direct["url"].endswith(".whl"):
    raise RuntimeError(f"Expected a wheel installation: {direct}")
print(f"Isolated wheel import OK: {origin}")
""",
        )
        (work / "smoke_app.py").write_text(
            "from fastapi import FastAPI\n"
            "from pydantic import BaseModel\n"
            "app = FastAPI()\n"
            "class Item(BaseModel):\n    id: int\n"
            '@app.get("/items", response_model=Item)\n'
            "def item():\n    return Item(id=1)\n",
            encoding="utf-8",
        )
        cli = str(venv / "bin/fastapi-contract")
        run(cli, "--help")
        run(cli, "snapshot", "smoke_app:app", "--output", "snapshot.json")
        payload = json.loads((work / "snapshot.json").read_text())
        require(
            isinstance(payload, dict) and bool(payload), "Snapshot must be a nonempty JSON object"
        )
        run(cli, "check", "smoke_app:app", "--against", "snapshot.json")
        print("Clean-wheel CLI help, snapshot and self-check OK", flush=True)


if __name__ == "__main__":
    main()
