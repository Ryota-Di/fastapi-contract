"""Import a FastAPI instance without running its lifecycle."""

import importlib
import sys
from pathlib import Path

from fastapi import FastAPI


def load_app(target: str) -> FastAPI:
    parts = target.split(":")
    if (
        len(parts) != 2
        or not all(part.isidentifier() for part in parts[0].split("."))
        or not parts[1].isidentifier()
    ):
        raise ValueError("App target must be module:attribute (for example app.main:app)")
    module_name, attribute = parts
    # Console scripts start with their bin directory on sys.path. Resolve the
    # user's project from the working directory, just as a local Python app does.
    original_path = sys.path[:]
    sys.path.insert(0, str(Path.cwd()))
    try:
        try:
            module = importlib.import_module(module_name)
            app = getattr(module, attribute)
        except (Exception, SystemExit) as exc:
            raise ValueError(f"Cannot load {target}: {type(exc).__name__}: {exc}") from exc
    finally:
        sys.path[:] = original_path
    if not isinstance(app, FastAPI):
        raise ValueError(f"{target} is not a FastAPI instance")
    return app
