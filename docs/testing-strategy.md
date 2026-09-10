# Testing Strategy

## Quality objective

The highest-risk defect is a real backward-incompatible runtime change being classified as SAFE. False positives are also important because excessive CI noise makes the checker unusable.

Priority:

1. false-negative prevention;
2. false-positive prevention;
3. REVIEW-boundary correctness;
4. deterministic behavior;
5. agreement with FastAPI/Pydantic runtime semantics.

## Development workflow

Each small implementation slice follows this review-gated flow:

1. GPT proposes implementation specification, concrete design, and test viewpoints.
2. Human reviews and approves the specification.
3. GPT writes tests before production implementation.
4. The slice traceability matrix is reconciled: every approved viewpoint is classified as **covered now**, **deferred with an explicit trigger**, or **out of scope with an owner**.
5. An omission audit checks decision outcomes, public CI behavior, error paths, framework boundaries, and non-functional requirements.
6. Human reviews the tests and expected outcomes.
7. GPT implements with RED -> GREEN -> REFACTOR and runs all quality checks.
8. Implementation and test quality are evaluated; defects become regression tests.

Production implementation does not start while an approved viewpoint is unclassified.

If implementation reveals that an approved expectation is wrong, the test is not silently changed to make the build pass. The specification is reviewed again first.

## Test-design techniques

Every rule uses the techniques that are relevant to its input space:

- requirement traceability;
- equivalence partitioning;
- boundary-value analysis;
- decision tables;
- interaction/combinatorial testing;
- adversarial false-negative and false-positive challenges;
- unsupported-state testing;
- property-based testing;
- differential testing against actual FastAPI/Pydantic behavior;
- regression testing;
- mutation testing for critical rule logic before release.

## Mandatory omission audit

The following checks are mandatory before a test slice is declared review-ready.

### Classification decision table

Exercise every externally observable outcome that the slice can produce:

- BREAKING;
- REVIEW;
- SAFE;
- ERROR;
- precedence when more than one finding/condition exists.

This prevents a rule-focused test suite from forgetting application-level status aggregation.

### Public CI contract

Test both human-readable and machine-observable behavior:

- reporter content for every status;
- exit code for every status;
- SAFE wording must remain scoped to the supported contract surface.

### Fail-closed paths

For every serialization, matching, extraction, or environment boundary, identify how corruption or ambiguity fails. Analysis failures must become ERROR rather than SAFE.

### Representation-preservation challenge

Unsupported input is not allowed to become lossy input. Two distinct unsupported contract facts must remain distinguishable in the snapshot when collapsing them could hide a relevant change.

### Framework differential check

At least one supported semantic slice is compared with real FastAPI/Pydantic runtime behavior. Unit tests alone cannot be the oracle for framework semantics.

### Non-functional checklist

For each slice, explicitly classify:

- expected algorithmic complexity;
- repeated framework introspection;
- cache opportunities;
- snapshot-size impact;
- new I/O/process boundaries;
- determinism;
- portability;
- framework isolation.

A non-functional item may be deferred only with a concrete implementation trigger in the traceability matrix.

## Test layers

### Unit

Framework-independent domain logic, canonicalization, rule logic, codec logic, application orchestration, reporting, exit-code behavior, and architecture boundaries.

### Integration

FastAPI/Pydantic adapter extraction and framework-boundary behavior.

### Acceptance

A complete vertical slice from FastAPI application to snapshot, comparison, finding, report, and CI status.

### Property-based

General invariants such as canonical order independence, monotonicity, and identical-input idempotence.

### Differential

Checker predictions are compared with real FastAPI/Pydantic runtime behavior. This protects against a shared misunderstanding in both unit-test expectations and implementation.

## Performance testing

Performance is treated as a non-functional requirement, but wall-clock thresholds are not asserted in ordinary unit tests because CI machines vary.

Early implementation review protects structural properties such as keyed route matching and bounded repeated model introspection. Once stable seams exist, dedicated tests/benchmarks measure:

- route scaling;
- shared-model extraction cache effectiveness;
- comparison scaling;
- snapshot size.

The FAPI001 Slice 1 traceability matrix records exactly when each deferred performance guard becomes mandatory.

## Mutation testing

Mutation testing is deferred until the first production implementation is GREEN. Before FAPI001 is considered release-ready, mutation testing must target at least:

- removed-field set direction;
- UNKNOWN versus INCOMPATIBLE classification;
- unsupported-relevant-change guards;
- status precedence;
- route-match key use;
- codec discriminator/schema validation.

Surviving critical mutants require either a new test or an explicit design review.

## Quality gate

The initial PR gate is:

```text
pytest       PASS
ruff check   PASS
ruff format  PASS
mypy         PASS
```

Line coverage is reported but is not by itself the release criterion. Requirement, decision, boundary, differential, regression, and mutation strength matter more.
