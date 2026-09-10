# Architecture

## Product boundary

`fastapi-contract` detects FastAPI runtime contract compatibility changes that may not be visible to an OpenAPI diff.

Current owners are `response-wire-surface`, `request-body-binding`,
`hidden-parameter-binding`, and `hidden-parameter-requirement`. Legacy schema-v1
checks retain FAPI001. Descriptive current owner names are independent of historical
public numbering; no new numbered rules are assigned.

## Processing model

```text
check: read baseline -> strict version inspection -> full selected-codec decode
  LegacyBaseline  -> load app -> legacy extractor -> legacy checker/FAPI001
  CurrentBaseline -> load app -> current fact extractor -> canonical checker
result -> typed evidence -> text report + CI exit status
```

`application/baseline_loader.py` returns an immutable tagged union without loading
an app. It never falls back to another codec. `compat/v1/lane.py` owns the frozen
legacy composition. A valid v1 selection emits informational stderr text before
app import. V1 snapshots are never converted to current facts.

Snapshot creation defaults to final schema v2. Explicit v1 remains available.
Final v2 has `metadata` (schema_version, tool_version, environment) and
`application.routes` (key, match_key, response, body_binding, parameters). Every
family is explicit; no fact profiles or development-format fallback exist.
Transport mapping is explicit and strict. Duplicate semantic occurrences are
preserved; duplicate JSON keys are rejected.

Current rules consume canonical facts, without transport-schema branching or
framework imports. Reporter evidence carries response ownership, binding anchors,
wire names, requiredness and scoped candidate blockers. The reporter never derives
consumer identity or ownership from diagnostic names or opaque fingerprints.
`domain/finding_order.py` defines canonical current finding order. Legacy text
retains its published ordering and content.

## Core principles

1. **Framework isolation** — domain and rules do not depend on `APIRoute`, `FieldInfo`, `BaseModel`, or other FastAPI/Pydantic runtime objects.
2. **Facts before judgement** — snapshots contain observed contract facts, never `SAFE`, `REVIEW`, or `BREAKING` decisions.
3. **Fail closed** — an analysis failure never falls back to SAFE.
4. **Explicit unsupported states** — unsupported contract surfaces are represented explicitly and are only reported as REVIEW when a relevant contract change exists.
5. **Canonical domain data** — normalization occurs at the adapter boundary; rules consume deterministic domain objects.
6. **No lossy normalization** — information needed to distinguish runtime semantics must not be flattened away.
7. **Effective runtime identity** — client-facing wire names and effective route matching semantics take precedence over Python declaration names.
8. **YAGNI** — derived contracts, caches, and framework metadata are not persisted unless a concrete rule requires them.

## Result model

User-facing classifications:

- `BREAKING` — incompatibility proven; exit 1
- `REVIEW` — relevant change detected but compatibility cannot be established; exit 1
- `SAFE` — no incompatibility detected in the supported contract surface; exit 0
- `ERROR` — analysis cannot be trusted or completed; exit 2

Rules emit structured findings with only two impacts:

- `INCOMPATIBLE` -> BREAKING
- `UNKNOWN` -> REVIEW

No SAFE finding is emitted.

## Snapshot boundary

Baselines are saved JSON documents. The CLI loads the current application in its own process after validating the baseline. Endpoint/startup/lifespan execution is not part of extraction.

A snapshot carries environment metadata for Python, FastAPI, Starlette, and Pydantic versions. Environment changes that make comparison unreliable are analysis errors rather than REVIEW findings.

## Performance constraints

These constraints apply from the beginning even before benchmark thresholds are fixed:

- route correspondence should be approximately O(N), using keyed lookup rather than pairwise route comparison;
- FastAPI/Pydantic introspection happens in the adapter, not independently in each rule;
- canonicalization happens once at the adapter boundary;
- repeated response-model analysis should support run-local memoization when implementation reaches that point;
- snapshots should contain only contract facts needed by rules;
- deterministic output is required for the same effective application contract.

Absolute performance targets will be set from benchmarks after the first vertical slice exists.
