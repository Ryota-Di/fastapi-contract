# fastapi-contract

Catch FastAPI breaking changes that OpenAPI diff can't see.

**v0.1 Technical Preview:** the CLI currently checks FAPI001 response projection
compatibility only. The public API and snapshot format are not yet stable.

## Why

A FastAPI route can keep the same OpenAPI response schema while returning fewer
fields. `fastapi-contract` compares extracted runtime configuration to a saved
baseline and reports changes in the supported contract surface. It complements
OpenAPI diff tools; a SAFE result is not a guarantee of full API compatibility.

## Installation

Requires Python 3.11+. Install into your application's dependency environment.

```bash
pip install fastapi-contract
```

To try it from source, run
`pip install .` in this repository, or use `uv sync --group dev` and prefix the
commands below with `uv run`.

## Quickstart

From your application project directory, create `app/__init__.py` and
`app/main.py`. Put this in `app/main.py`:

```python
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()


class User(BaseModel):
    id: int
    email: str


@app.get("/users", response_model=User)
def users():
    return {"id": 1, "email": "alice@example.com"}
```

Save the accepted contract:

```bash
fastapi-contract snapshot app.main:app \
  -o fastapi-contract-baseline.json
```

After editing the application, compare it with that file:

```bash
fastapi-contract check app.main:app \
  --against fastapi-contract-baseline.json
```

An unchanged app prints `SAFE: No incompatibility detected in the supported
contract surface.` and exits 0. `snapshot` also accepts `--output` instead of `-o`.
No server needs to run.

## Example breaking change

Before:

```python
@app.get("/users", response_model=User)
```

After (replace only the decorator in the example):

```python
@app.get(
    "/users",
    response_model=User,
    response_model_exclude={"email"},
)
```

The OpenAPI response schema still describes `User`, but the runtime response
loses `email`. Running `check` against the original snapshot prints:

```text
BREAKING
FAPI001 GET /users: response fields removed by projection: email
```

The command exits 1.

## Exit codes

| Code | Result | Meaning |
| --- | --- | --- |
| 0 | SAFE | No incompatibility detected in the supported surface; snapshot saved successfully for `snapshot`. |
| 1 | BREAKING / REVIEW | A breaking projection change or a relevant change requiring human review. |
| 2 | ERROR | Invalid arguments, app loading/file/analysis failure, invalid snapshot, or incompatible environment. |

## Supported rules

**FAPI001 — Effective Response Projection Changed** is the only enabled rule.
Slice 1 supports static top-level projection of supported flat response models.
Unsupported relevant changes can produce REVIEW rather than a definite finding.
See the [FAPI001 specification](docs/rules/fapi001.md) for the precise boundary.

## Current limitations

- Technical Preview, FAPI001 only; no alias, omission, or request-side checks.
- Analysis is limited to the supported top-level Slice 1 surface. It does not
  exercise endpoints or prove their returned values match their declarations.
- Baselines are snapshot files using the existing schema v1. There is no Git
  baseline loading, environment reconstruction, or automatic baseline refresh.
- Baseline and current must use the same runtime/dependency environment. The
  checker requires matching recorded Python, FastAPI, Starlette, and Pydantic versions;
  keep exact versions consistent, including Python patch versions.
- App loading imports `module:attribute` in the current process. Module-level
  side effects execute; only load trusted application code. No subprocess
  isolation is provided. Run from the project directory or install its modules.
- Startup, lifespan, and the server are not run. Routes registered only during
  startup or lifespan are therefore not included.

## CI usage

Commit `fastapi-contract-baseline.json` alongside your application. For a project
that has `fastapi-contract` in its locked uv dependencies, a minimal GitHub Actions
job is:

```yaml
name: Contract check
on: [push, pull_request]
jobs:
  contract:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version-file: .python-version
      - run: python -m pip install uv
      - run: uv sync --frozen
      - run: >-
          uv run fastapi-contract check app.main:app
          --against fastapi-contract-baseline.json
```

Commit an exact Python patch version in `.python-version` and use that version
and the same lockfile when generating the baseline. Keep the committed baseline
unchanged during ordinary CI checks. For an intentional contract change, review
its consumer impact, rerun `snapshot` in the matching environment, and commit
the updated baseline with the application change for review.

## Roadmap

- Response serialized alias compatibility
- Response omission behavior
- Request-side runtime contracts
- Other hidden runtime contracts
- Git baseline workflow

## Development

```bash
uv sync --group dev
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv build
```

## License

Apache License 2.0. See [LICENSE](LICENSE).
