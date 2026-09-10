"""FastAPI 0.141.1 resolved ordinary-parameter extraction. Never execute dependencies."""

import hashlib
import json
from typing import Any

from fastapi.dependencies.models import Dependant
from fastapi.dependencies.utils import get_validation_alias
from fastapi.routing import APIRoute
from pydantic import AliasChoices, AliasPath, BaseModel

from fastapi_contract.domain.blocker import BlockerCode, FactBlocker
from fastapi_contract.domain.parameters import (
    ParameterCoverage,
    ParameterFacts,
    ParameterKey,
    ParameterLocation,
    ParameterOccurrence,
    ParameterOrigin,
    ParameterRegion,
    ParameterVisibility,
    occurrence_order,
    region_order,
    unavailable_parameters,
)


def _visibility(route: APIRoute, info: Any, standard_docs: bool) -> ParameterVisibility:
    if info.include_in_schema is False or route.include_in_schema is False:
        return ParameterVisibility.HIDDEN
    if standard_docs and info.include_in_schema is True:
        return ParameterVisibility.DOCUMENTED
    return ParameterVisibility.UNKNOWN


def _model_fingerprint(model: type[BaseModel]) -> str:
    # Bounded structural metadata, not field value schemas, defaults or user code.
    structure = sorted(
        (str(info.validation_alias or info.alias or name), info.is_required())
        for name, info in model.model_fields.items()
    )
    return hashlib.sha256(json.dumps(structure).encode()).hexdigest()


def _wire_key(location: ParameterLocation, alias: str) -> ParameterKey:
    wire = (
        alias.translate(str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"))
        if location is ParameterLocation.HEADER
        else alias
    )
    return ParameterKey(location, wire)


def _alias_region(
    location: ParameterLocation, info: Any, visibility: ParameterVisibility
) -> ParameterRegion:
    alias = info.validation_alias
    keys = set()
    if isinstance(alias, (AliasChoices, AliasPath)):
        alternatives = alias.choices if isinstance(alias, AliasChoices) else [alias]
        # Only bound potential contributors; do not admit these forms as known bindings.
        roots = [a.path[0] if isinstance(a, AliasPath) else a for a in alternatives]
        roots.append(info.alias)  # The ordinary-field wrapper may fall back to this name.
        try:
            for root in roots:
                if not isinstance(root, str):
                    raise ValueError("Unbounded alias root")
                keys.add(_wire_key(location, root))
        except ValueError:
            keys.clear()
    possible = tuple(sorted(keys)) if keys else None
    structure = (
        None if possible is None else [(key.location.value, key.wire_name) for key in possible]
    )
    fingerprint = hashlib.sha256(json.dumps(structure, ensure_ascii=True).encode()).hexdigest()
    return ParameterRegion(
        (location,), possible, FactBlocker(BlockerCode.PARAMETER_BINDING, fingerprint), visibility
    )


def extract_parameters(
    route: APIRoute, *, supported_runtime: bool, standard_docs: bool
) -> ParameterFacts:
    if not supported_runtime:
        return unavailable_parameters(BlockerCode.PARAMETER_RUNTIME)
    occurrences = []
    regions = []
    provider = getattr(route, "dependency_overrides_provider", None)
    overrides = getattr(provider, "dependency_overrides", {}) or {}

    def walk(node: Dependant, path: str, ancestors: frozenset[int]) -> None:
        if id(node) in ancestors:
            regions.append(
                ParameterRegion(
                    tuple(ParameterLocation),
                    None,
                    FactBlocker(BlockerCode.PARAMETER_BINDING, "cyclic-tree"),
                )
            )
            return
        if path and node.call in overrides:
            regions.append(
                ParameterRegion(
                    tuple(ParameterLocation), None, FactBlocker(BlockerCode.PARAMETER_OVERRIDE)
                )
            )
            return
        for location in ParameterLocation:
            for field in getattr(node, location.value + "_params"):
                info = field.field_info
                visibility = _visibility(route, info, standard_docs)
                visibility_blocker = (
                    FactBlocker(BlockerCode.PARAMETER_VISIBILITY)
                    if visibility is ParameterVisibility.UNKNOWN
                    else None
                )
                required = info.is_required()
                requirement_blocker = None
                if type(required) is not bool:
                    required = None
                    requirement_blocker = FactBlocker(BlockerCode.PARAMETER_REQUIREMENT)
                binding: ParameterKey | ParameterRegion
                annotation = info.annotation
                if isinstance(annotation, type) and issubclass(annotation, BaseModel):
                    binding = ParameterRegion(
                        (location,),
                        None,
                        FactBlocker(BlockerCode.PARAMETER_MODEL, _model_fingerprint(annotation)),
                        visibility,
                    )
                elif info.validation_alias is not None and not isinstance(
                    info.validation_alias, str
                ):
                    binding = _alias_region(location, info, visibility)
                elif getattr(getattr(info, "in_", None), "value", None) != location.value:
                    binding = ParameterRegion(
                        (location,),
                        None,
                        FactBlocker(BlockerCode.PARAMETER_BINDING, "unresolved-lookup"),
                        visibility,
                    )
                else:
                    alias = get_validation_alias(field)
                    if not isinstance(alias, str):
                        binding = ParameterRegion(
                            (location,),
                            None,
                            FactBlocker(BlockerCode.PARAMETER_BINDING),
                            visibility,
                        )
                    else:
                        try:
                            binding = _wire_key(location, alias)
                        except ValueError:
                            binding = ParameterRegion(
                                (location,),
                                None,
                                FactBlocker(BlockerCode.PARAMETER_HEADER),
                                visibility,
                            )
                occurrences.append(
                    ParameterOccurrence(
                        f"{path}/{location.value}/{field.name}",
                        ParameterOrigin.DEPENDENCY if path else ParameterOrigin.DIRECT,
                        binding,
                        required,
                        visibility,
                        requirement_blocker,
                        visibility_blocker,
                    )
                )
        for index, child in enumerate(node.dependencies):
            walk(child, f"{path}/dependency[{index}]", ancestors | {id(node)})

    walk(route.dependant, "", frozenset())
    partial = regions or any(
        isinstance(o.binding, ParameterRegion)
        or o.required is None
        or o.visibility is ParameterVisibility.UNKNOWN
        for o in occurrences
    )
    return ParameterFacts(
        tuple(sorted(occurrences, key=occurrence_order)),
        tuple(sorted(regions, key=region_order)),
        ParameterCoverage.PARTIAL if partial else ParameterCoverage.COMPLETE,
    )
