"""Stable machine-readable blocker vocabulary shared by canonical fact families."""

from dataclasses import dataclass
from enum import StrEnum


class BlockerCode(StrEnum):
    UNSUPPORTED_SELECTOR = "unsupported_response_selector"
    CONDITIONAL_EXCLUSION = "conditional_field_exclusion"
    MODEL_SERIALIZER = "model_serializer_override"
    UNSUPPORTED_MODEL = "unsupported_response_model"
    DOCUMENTATION_UNKNOWN = "documented_surface_unknown"
    WIRE_COLLISION = "response_wire_collision"
    PARAMETER_BINDING = "parameter_binding_unknown"
    PARAMETER_REQUIREMENT = "parameter_requirement_unknown"
    PARAMETER_VISIBILITY = "parameter_visibility_unknown"
    PARAMETER_MODEL = "parameter_model_container"
    PARAMETER_OVERRIDE = "parameter_dependency_override"
    PARAMETER_HEADER = "parameter_header_name_invalid"
    PARAMETER_RUNTIME = "unsupported_parameter_runtime"
    PARAMETER_UNOBSERVED = "parameter_binding_not_observed"
    PARAMETER_COLLISION = "parameter_wire_collision"
    BODY_ALIAS = "unsupported_body_alias_form"
    BODY_COLLISION = "body_binding_collision"
    BODY_INPUT = "unsupported_body_input"
    BODY_VALIDATION = "unsupported_body_validation"
    BODY_DOCUMENTATION = "body_anchor_unresolved"
    BODY_UNOBSERVED = "body_binding_not_observed"
    BODY_RUNTIME = "unsupported_body_runtime"


@dataclass(frozen=True, order=True)
class FactBlocker:
    code: BlockerCode
    # Opaque discriminator for relevant unsupported structure, never interpreted by rules.
    fingerprint: str = ""
