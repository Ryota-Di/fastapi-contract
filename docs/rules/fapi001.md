# FAPI001 — Effective Response Projection Changed

## Contract objective

Detect when a response field that could be returned by the old FastAPI application can no longer be returned after a projection-policy change.

The rule compares **effective response projection**, not raw FastAPI configuration values.

## Responsibility boundary

FAPI001 owns whether a response field is projected at all.

- serialized response-key changes belong to FAPI002;
- value-dependent omission (`exclude_none`, `exclude_defaults`, `exclude_unset`) belongs to FAPI003;
- response-model schema additions/removals belong primarily to an OpenAPI checker;
- arbitrary serializer semantics are outside the first implementation scope.

## Classification

- confirmed previously included -> excluded transition: `INCOMPATIBLE` / BREAKING;
- widening or semantic no-op: no finding;
- concrete relevant projection change whose effect cannot be established: `UNKNOWN` / REVIEW.

Unsupported structure alone does not cause REVIEW. There must be a relevant projection change.

## Slice 1 scope

The first vertical slice intentionally supports only:

- a Pydantic `BaseModel` response;
- top-level response fields;
- `response_model_exclude`;
- safely canonicalizable top-level field-name collections and flat mappings whose values are
  exactly `True` or `Ellipsis`;
- before/after matched routes.

The first slice intentionally does not support:

- `response_model_include`;
- nested selectors;
- sequence indexes or `__all__`;
- `Field(exclude=True)` or `exclude_if` as supported projection semantics;
- computed fields;
- dynamic/open response shapes;
- aliases and response omission policies.

Relevant changes involving an unsupported surface must not silently become SAFE.

Unsupported selectors must also not be normalized lossily. If two distinct unsupported selector structures could have different runtime effects, the snapshot must preserve enough structure to distinguish them even though Slice 1 classifies their effect as unknown.

## Effective-projection rule for Slice 1

For a supported top-level object:

```text
base fields - excluded fields = effective fields
```

Then:

```text
before effective fields - after effective fields = confirmed removed fields
```

If confirmed removed fields are non-empty, emit an incompatible FAPI001 finding. If the effective response is unchanged or widened, emit no finding.

`exclude=None` and an explicit empty exclude selection are distinct snapshot facts but are semantically equivalent for this Slice 1 effective projection.

An empty mapping is equivalent to an empty field-name collection. Flat mappings with whole-field
`True` / `Ellipsis` values canonicalize to the corresponding field-name collection. Mapping keys
must be ordinary string field names; `__all__`, indexes, nested values, and other values remain
incomplete with their structure preserved. Equality with `True` is insufficient (`1` is not the
whole-field sentinel).

Scalar fields carrying the standard validation-only metadata `Gt`, `Ge`, `Lt`, `Le`, `MultipleOf`,
`MinLen`, or `MaxLen` remain supported for projection analysis. These constraints do not remove
fields from successfully validated responses. Only these exact metadata types are accepted;
unknown metadata, custom subclasses, and serialization metadata remain unsupported. This does
not classify changes in validation constraints themselves.

Unknown selector names that do not correspond to model fields do not change the effective projection. Reserved/structural selectors such as `__all__`, sequence indexes, and nested selector structures are not treated as harmless unknown field names; they are explicit unsupported/incomplete facts in Slice 1.

## First acceptance scenario

A route has a response model with `id` and `email`.

- baseline: no `response_model_exclude`;
- current: `response_model_exclude={"email"}`;
- OpenAPI: unchanged;
- runtime response: `email` disappears;
- checker result: FAPI001 BREAKING;
- exit status: 1.

This scenario proves the first end-to-end product value: detecting a runtime contract break that an OpenAPI diff cannot see.

## Test traceability

`docs/rules/fapi001-test-matrix.md` is the review gate for Slice 1. Production implementation must not begin while any reviewed test viewpoint is unclassified.
