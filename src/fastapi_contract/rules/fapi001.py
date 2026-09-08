"""FAPI001: compare effective top-level response projection."""

from fastapi_contract.domain.finding import (
    CompatibilityImpact,
    FieldPath,
    Finding,
    ProjectionEvidence,
)
from fastapi_contract.domain.model import (
    Completeness,
    FieldSelection,
    ObjectSelection,
    ResponseStateKind,
    RouteContract,
    WholeSelection,
)


def _names(selection: FieldSelection | None) -> set[str] | None:
    if selection is None:
        return set()
    if selection.completeness is not Completeness.COMPLETE:
        return None
    if not isinstance(selection.root, ObjectSelection):
        return None
    if any(
        not isinstance(entry.selection, WholeSelection) or entry.name == "__all__"
        for entry in selection.root.fields
    ):
        return None
    return {entry.name for entry in selection.root.fields}


class Fapi001ResponseProjectionRule:
    def check(self, before: RouteContract, after: RouteContract) -> tuple[Finding, ...]:
        old, new = before.response, after.response
        if old.state is ResponseStateKind.NO_MODEL or new.state is ResponseStateKind.NO_MODEL:
            return ()
        if old.policy is None or new.policy is None:
            raise ValueError("Response with a model must carry projection policy")
        if (old.policy.include, old.policy.exclude) == (new.policy.include, new.policy.exclude):
            return ()
        old_exclude, new_exclude = _names(old.policy.exclude), _names(new.policy.exclude)
        reason = None
        if old.state is ResponseStateKind.UNSUPPORTED or new.state is ResponseStateKind.UNSUPPORTED:
            reason = old.reason or new.reason or "Unsupported response shape"
        elif old.policy.include is not None or new.policy.include is not None:
            reason = "response_model_include is unsupported in Slice 1"
        elif old_exclude is None or new_exclude is None:
            reason = "Unsupported or incomplete response exclude selection"
        if reason:
            return (
                Finding(
                    "FAPI001",
                    CompatibilityImpact.UNKNOWN,
                    after.key,
                    ProjectionEvidence(reason=reason),
                ),
            )
        if old.shape is None or new.shape is None:
            raise ValueError("Supported response must carry an object shape")
        assert old_exclude is not None and new_exclude is not None
        old_fields = {field.logical_name for field in old.shape.fields}
        new_fields = {field.logical_name for field in new.shape.fields}
        # Schema-only removals belong to the OpenAPI checker. Attribute only
        # surviving model fields newly hidden by the projection policy to FAPI001.
        removed = (old_fields - old_exclude) & new_fields & new_exclude
        if not removed:
            return ()
        return (
            Finding(
                "FAPI001",
                CompatibilityImpact.INCOMPATIBLE,
                after.key,
                ProjectionEvidence(tuple(FieldPath((name,)) for name in sorted(removed))),
            ),
        )
