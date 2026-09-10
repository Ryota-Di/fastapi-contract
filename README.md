# fastapi-contract

Catch FastAPI breaking changes that OpenAPI diff can't see.

`fastapi-contract` compares your FastAPI application's declared runtime contracts
with a saved baseline. It complements OpenAPI diff: a response key can disappear,
input can stop reaching a field, or a hidden parameter can become required while
the documented schema stays the same. SAFE means no incompatibility was detected
in the supported contract surface; it is not a guarantee of full API compatibility.

## Installation and supported versions

Requires **Python 3.11+**, **FastAPI 0.141.1**, and **Pydantic 2.13.5**.
Install into the application's dependency environment:

```bash
pip install fastapi-contract
```

For a source checkout, use `pip install .`. FastAPI and Pydantic are pinned to the
exact supported versions. Starlette follows FastAPI's dependency; use the same
locked environment for baseline generation and checking. Baselines record exact
Python, FastAPI, Starlette and Pydantic versions, including the Python patch
version. Mismatches cause ERROR. CI verifies Python 3.11 and 3.12.

## Quickstart

Create `app/__init__.py` and `app/main.py` in your project:

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

Save the accepted application contract, then check proposed changes against it:

```bash
fastapi-contract snapshot app.main:app -o fastapi-contract-baseline.json
fastapi-contract check app.main:app --against fastapi-contract-baseline.json
```

New snapshots use schema v2 and include response, body binding, and parameter
facts. An unchanged app prints:

```text
SAFE: No incompatibility detected in the supported contract surface.
```

For example, add `response_model_exclude={"email"}` to the route decorator. The
OpenAPI response schema still describes `email`, but runtime output loses it:

```text
BREAKING
response-wire-surface GET /users: Response wire key "email" is no longer produced; key remains documented by OpenAPI.
```

The command exits 1. No server, endpoint, startup, or lifespan needs to run.
App loading does execute module-level code; load trusted applications only. An
invalid baseline is rejected before the target application is imported.

## Supported checks

| Owner | Supported contract change |
| --- | --- |
| `response-wire-surface` | Loss of an effective projected top-level response wire key, including `response_model_by_alias` blind spots. Ordinary documented key losses are delegated to OpenAPI diff. |
| `request-body-binding` | Loss of a supported top-level JSON BaseModel input key's binding to a matched documented input slot. A field falling back to its default can be BREAKING even when HTTP stays 200. |
| `hidden-parameter-binding` | Loss of a hidden Query, Header or Cookie wire binding. |
| `hidden-parameter-requirement` | An existing, matched hidden parameter changes from optional to required. New required parameter additions are outside this release. |

Parameter identity uses location and the resolved wire name. Header names are
canonicalized to ASCII lowercase; Query and Cookie names are case-sensitive.
Direct declarations and statically resolved dependencies are supported. Moving
a parameter between them or renaming Python fields/arguments with stable wire
bindings does not itself cause a finding.

Enum/nested sibling value types and field-local body validators do not automatically
block unrelated supported keys. Relevant unresolved selectors, alias forms, model
validators, parameter containers or dependency overrides can produce REVIEW for
the affected candidate. Findings retain independent uncertainty alongside confirmed
losses; BREAKING takes precedence over REVIEW without hiding those findings.

## Results and CI

| Result | Stream | Exit code |
| --- | --- | --- |
| SAFE | stdout | 0 |
| BREAKING | stdout | 1 |
| REVIEW | stdout | 1 |
| ERROR | stderr | 2 |

Successful `snapshot` exits 0. Invalid arguments, invalid snapshots, environment
mismatch, app loading, file and analysis failures exit 2. Informational migration
notices go to stderr and do not affect results or exit codes. Output has no color
or TTY-dependent formatting; consumer wire names use JSON string escaping.

Commit the baseline alongside the application. With locked uv dependencies:

```yaml
- run: uv sync --locked
- run: >-
    uv run --locked fastapi-contract check app.main:app
    --against fastapi-contract-baseline.json
```

Keep the exact Python patch version and lockfile consistent with baseline creation.
Do not refresh baselines during ordinary CI checks. For an intentional contract
change, review consumer impact and commit the accepted new baseline for review.

## Upgrading a schema-v1 baseline

Existing schema-v1 baselines continue working and run **legacy checks only**.
The result retains legacy FAPI001 meaning and output. A valid v1 check prints this
notice exactly once to stderr, before loading the app:

```text
Baseline uses snapshot schema v1.
Running legacy checks only.
Regenerate the baseline to enable current contract checks.
```

V1 does not contain enough information to recover current response facts for
models it marked UNSUPPORTED, body binding, hidden parameter binding, or hidden
requiredness. Legacy REVIEW limitations remain; a v1 SAFE result means only the
legacy checks passed.

To enable current checks, check out the application revision whose contract you
accept as the baseline, use its matching environment, and regenerate:

```bash
fastapi-contract snapshot app.main:app \
  -o fastapi-contract-baseline.json
```

Review and commit the result. Regeneration creates a **new accepted baseline**;
it does not reconstruct historical facts. Generating from an already changed app
accepts that app as the baseline. There is no automatic migration or `migrate`
command. Explicit `--schema-version 1` remains available, and `check` always selects
its lane from the saved baseline version. Explicit `--schema-version 2` also works.

## Known limitations

This release does not add conditional response omission (`exclude_none`,
`exclude_unset`, `exclude_defaults`), nested projection, full AliasChoices/AliasPath
support, request coercion/strictness/validation-constraint checks, missing
Content-Type behavior, route/slash resolution, hidden operation availability,
Path parameter rules, or new required parameter additions. Arbitrary serializer,
dependency, and user-code behavior is not analyzed. Relevant unsupported structures
may require review; unrelated unsupported details do not imply every key is unknown.

Extraction checks declarations, not execution of arbitrary endpoint code. Routes
registered only during startup/lifespan are not captured. There is no Git baseline
loader, environment reconstruction, or automatic baseline refresh.

## Development

```bash
uv sync --locked --group dev
uv run --locked pytest
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy src
uv build --build-constraints tools/release/build-constraints.txt --require-hashes
```

See the [release checklist](docs/release-checklist.md),
[release notes](docs/releases/v0.2.0.md), [architecture](docs/architecture.md),
and [testing strategy](docs/testing-strategy.md).

## License

Apache License 2.0. See [LICENSE](LICENSE).
