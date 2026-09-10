# fastapi-contract

**Catch FastAPI breaking changes before they reach production — including changes OpenAPI diff can miss.**

`fastapi-contract` is a lightweight CI guard for FastAPI applications.

Save the contract of an accepted application revision once, commit that baseline to your repository, and check every pull request against it. If a supported runtime contract becomes incompatible, `fastapi-contract` exits non-zero so CI can stop the change before merge.

```text
accepted main
    ↓
committed baseline
    ↓
pull request
    ↓
fastapi-contract check
    ↓
SAFE / BREAKING / REVIEW / ERROR
```

In the basic workflow, you need only **one baseline file and one CI command**. No FastAPI server needs to be started, and no endpoint needs to be called.

## Why use it?

OpenAPI diff is useful for finding documented API changes, but some FastAPI runtime changes can break clients without producing an equivalent OpenAPI change.

For example, this route:

```python
@app.get("/users", response_model=User)
```

can become:

```python
@app.get(
    "/users",
    response_model=User,
    response_model_exclude={"email"},
)
```

The OpenAPI response schema can still describe `email`, while the actual response no longer contains it.

`fastapi-contract` detects that runtime contract change:

```text
BREAKING
response-wire-surface GET /users: Response wire key "email" is no longer produced; key remains documented by OpenAPI.
```

It also checks supported request-body bindings and hidden Query/Header/Cookie parameters that may not be fully represented in the documented schema.

`fastapi-contract` is designed to **complement, not replace, OpenAPI diff**.

## Quick start

Install `fastapi-contract` into the same dependency environment as your FastAPI application:

```bash
pip install fastapi-contract
```

Suppose your application contains:

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

Create a baseline from an application revision whose behavior you accept:

```bash
fastapi-contract snapshot app.main:app -o fastapi-contract-baseline.json
```

Commit that file to the repository. Then check future changes with:

```bash
fastapi-contract check app.main:app --against fastapi-contract-baseline.json
```

An unchanged compatible application prints:

```text
SAFE: No incompatibility detected in the supported contract surface.
```

and exits with code `0`.

New snapshots use schema v2 and include response, request-body binding, and parameter facts.

## Use it in CI/CD

The intended workflow is to run `check` on every pull request against the committed accepted baseline.

For a project using uv and GitHub Actions:

```yaml
name: FastAPI contract

on:
  pull_request:

jobs:
  contract:
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version-file: .python-version

      - name: Install uv
        run: python -m pip install uv

      - name: Install dependencies
        run: uv sync --locked

      - name: Check FastAPI contract
        run: >-
          uv run --locked fastapi-contract check app.main:app
          --against fastapi-contract-baseline.json
```

Commit an exact Python patch version in `.python-version` and use the same lockfile when generating and checking the baseline.

No custom CI scripting is required: the CLI exit code acts as the compatibility gate.

| Result | Exit code | CI meaning |
| --- | ---: | --- |
| `SAFE` | 0 | Continue |
| `BREAKING` | 1 | Compatibility failure |
| `REVIEW` | 1 | Human compatibility review required |
| `ERROR` | 2 | Analysis, baseline, environment, or app-loading failure |

### Do not regenerate the baseline in normal CI

The committed baseline represents the **previously accepted contract**.

Normal CI should run `check` only. Do not run `snapshot` immediately before `check` against the same revision: that would compare the application with a baseline generated from itself and could silently accept an incompatible change.

When a contract change is intentional:

1. let CI report the change;
2. review the consumer impact;
3. decide whether the new behavior is acceptable;
4. regenerate the baseline from the accepted application revision;
5. commit the application change and baseline update together for review.

For example:

```bash
fastapi-contract snapshot app.main:app -o fastapi-contract-baseline.json
git add fastapi-contract-baseline.json
git commit -m "chore: accept updated FastAPI contract"
```

This keeps intentional contract changes visible in code review instead of approving them automatically.

## What does it catch?

`fastapi-contract` v0.2.0 currently checks four FastAPI runtime contract areas:

| Check | Example |
| --- | --- |
| `response-wire-surface` | A response field stops being produced even though OpenAPI still documents it |
| `request-body-binding` | A previously accepted top-level JSON key stops binding to the intended model field |
| `hidden-parameter-binding` | A hidden Query/Header/Cookie parameter loses or changes its client-facing wire binding |
| `hidden-parameter-requirement` | An existing hidden optional parameter becomes required |

These checks target runtime compatibility information that an OpenAPI-only comparison may not capture.

Parameter identity uses location and the resolved wire name. Header names are canonicalized to ASCII lowercase; Query and Cookie names are case-sensitive. Direct declarations and statically resolved dependencies are supported. Moving a parameter between them or renaming Python fields/arguments while preserving the client-facing binding does not itself cause a finding.

Enum/nested sibling value types and field-local body validators do not automatically block unrelated supported keys. Relevant unresolved selectors, alias forms, model validators, parameter containers, or dependency overrides can produce `REVIEW` for the affected candidate. Confirmed `BREAKING` and independent `REVIEW` findings can remain visible together.

## Requirements and compatibility

`fastapi-contract` v0.2.0 currently supports:

- Python 3.11+
- FastAPI 0.141.1
- Pydantic 2.13.5

FastAPI and Pydantic are pinned to the exact supported versions. Starlette follows FastAPI's dependency.

Baseline generation and checking must use matching recorded Python, FastAPI, Starlette, and Pydantic versions, including the Python patch version. An environment mismatch produces `ERROR` rather than making a potentially unreliable compatibility decision. CI for this project verifies Python 3.11 and 3.12.

App loading imports `module:attribute` in the current process, so module-level side effects execute. Load trusted applications only. Invalid baselines are rejected before the target application is imported. Startup, lifespan, and endpoint execution are not part of extraction.

Successful `snapshot` exits 0. Compatibility results use stdout; `ERROR` and informational migration notices use stderr. Output has no color or TTY-dependent formatting, and consumer wire names use JSON string escaping.

## Upgrading a schema-v1 baseline

Existing schema-v1 baselines continue working and run **legacy checks only**. The result retains legacy FAPI001 meaning and output.

A valid v1 check prints this notice exactly once to stderr before loading the app:

```text
Baseline uses snapshot schema v1.
Running legacy checks only.
Regenerate the baseline to enable current contract checks.
```

V1 does not contain enough information to recover current response facts for models it marked unsupported, request-body binding, hidden parameter binding, or hidden requiredness. A v1 `SAFE` result therefore means only that the legacy checks passed.

To enable current checks, check out the application revision whose contract you accept as the baseline, use its matching environment, and regenerate:

```bash
fastapi-contract snapshot app.main:app -o fastapi-contract-baseline.json
```

Review and commit the result. Regeneration creates a **new accepted baseline**; it does not reconstruct historical v2 facts. There is no automatic migration or `migrate` command. Explicit `--schema-version 1` remains available, and `check` always selects its lane from the saved baseline version. Explicit `--schema-version 2` also works.

## Known limitations

This release does not add conditional response omission (`exclude_none`, `exclude_unset`, `exclude_defaults`), nested projection, full AliasChoices/AliasPath support, request coercion/strictness/validation-constraint checks, missing Content-Type behavior, route/slash resolution, hidden operation availability, Path parameter rules, or new required parameter additions.

Arbitrary serializer, dependency, and user-code behavior is not analyzed. Relevant unsupported structures may require review; unrelated unsupported details do not imply every key is unknown.

Extraction checks declarations, not execution of arbitrary endpoint code. Routes registered only during startup/lifespan are not captured. There is no Git baseline loader, environment reconstruction, or automatic baseline refresh.

OpenAPI diff remains necessary for ordinary documented schema changes.

## Development

```bash
uv sync --locked --group dev
uv run --locked pytest
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy src
uv build --build-constraints tools/release/build-constraints.txt --require-hashes
```

See the [release checklist](docs/release-checklist.md), [release notes](docs/releases/v0.2.0.md), [architecture](docs/architecture.md), and [testing strategy](docs/testing-strategy.md).

## License

Apache License 2.0. See [LICENSE](LICENSE).
