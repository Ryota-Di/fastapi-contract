# Test layout

The test suite is organized by contract boundary rather than implementation detail.

- `unit/` — framework-independent domain, rule, codec, checker, reporting, exit-code, and architecture tests.
- `integration/` — FastAPI/Pydantic adapter behavior.
- `acceptance/` — end-to-end product scenarios.
- `property/` — invariant/property-based tests.
- `differential/` — checker predictions compared with real FastAPI/Pydantic runtime behavior.

FAPI001 Slice 1 follows TDD. These tests are intentionally committed before production code and are expected to be RED until the reviewed implementation is added.

Before production implementation starts, `docs/rules/fapi001-test-matrix.md` must contain zero unclassified reviewed viewpoints. Every viewpoint must be covered now, deferred with a concrete trigger, or assigned to an explicit out-of-scope owner.
