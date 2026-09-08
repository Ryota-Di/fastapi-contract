"""Extract FastAPI/Pydantic facts once per application run."""

import platform
import re
from importlib.metadata import version
from types import UnionType
from typing import Union, cast, get_args, get_origin

from annotated_types import Ge, Gt, Le, Lt, MaxLen, MinLen, MultipleOf
from fastapi import FastAPI
from fastapi.routing import APIRoute, iter_route_contexts
from pydantic import BaseModel

from fastapi_contract.adapters.selection import normalize_top_level_selection
from fastapi_contract.domain.model import (
    ApplicationContract,
    ContractSnapshot,
    EnvironmentSnapshot,
    FactoryDefault,
    FieldProjectionPolicy,
    JsonBodyState,
    JsonBodyStateKind,
    NoDefault,
    ObjectField,
    ObjectShape,
    RequestContract,
    ResponseContract,
    ResponsePolicy,
    ResponseStateKind,
    RouteContract,
    RouteKey,
    RouteMatchKey,
    RouteSnapshot,
    ScalarShape,
    SchemaVisibility,
    ShapeOpenness,
    SnapshotMetadata,
    StaticDefault,
)

__all__ = ["FastApiSnapshotExtractor", "normalize_top_level_selection"]

# These standard metadata classes constrain validation, not field projection.
# Exact types prevent custom subclasses with schema/serialization hooks from
# being accepted merely because they inherit a familiar validation constraint.
_VALIDATION_ONLY_METADATA = frozenset({Gt, Ge, Lt, Le, MultipleOf, MinLen, MaxLen})


def _scalar_nullable(annotation: object) -> bool | None:
    if annotation in (str, int, float, bool, bytes, type(None)):
        return annotation is type(None)
    if get_origin(annotation) in (Union, UnionType):
        members = [_scalar_nullable(arg) for arg in get_args(annotation)]
        if all(member is not None for member in members):
            return any(members)
    return None


def _extract_shape(model: object) -> tuple[ObjectShape | None, str | None]:
    if not isinstance(model, type) or not issubclass(model, BaseModel):
        return None, "Response is not a top-level BaseModel object"
    if model.__pydantic_root_model__:
        return None, "RootModel response is unsupported"
    if model.model_config.get("extra") == "allow":
        return None, "Open response model is unsupported"
    if model.model_computed_fields:
        return None, "Computed response fields are unsupported"
    decorators = model.__pydantic_decorators__
    if decorators.model_serializers or decorators.field_serializers:
        return None, "Custom response serializers are unsupported"
    fields = []
    for name, field in sorted(model.model_fields.items()):
        if field.exclude or field.exclude_if is not None:
            return None, "Field-level response exclusion is unsupported"
        nullable = _scalar_nullable(field.annotation)
        if nullable is None or any(
            type(metadata) not in _VALIDATION_ONLY_METADATA for metadata in field.metadata
        ):
            return None, "Nested or custom response field serialization is unsupported"
        default: NoDefault | StaticDefault | FactoryDefault
        if field.default_factory is not None:
            default = FactoryDefault()
        elif field.is_required():
            default = NoDefault()
        else:
            default = StaticDefault(is_none=field.default is None)
        fields.append(
            ObjectField(
                logical_name=name,
                serialization_name=field.serialization_alias or name,
                nullable=nullable,
                default=default,
                projection_policy=FieldProjectionPolicy.NORMAL,
                shape=ScalarShape(nullable=nullable),
            )
        )
    return ObjectShape(tuple(fields), ShapeOpenness.CLOSED), None


class FastApiSnapshotExtractor:
    def extract(self, app: FastAPI) -> ContractSnapshot:
        # A fresh cache avoids stale facts if the same extractor is reused after
        # a model rebuild, and avoids repeated introspection for shared models.
        cache: dict[type[BaseModel], tuple[ObjectShape | None, str | None]] = {}
        routes = []
        for context in iter_route_contexts(app.routes):
            if not isinstance(context.original_route, APIRoute):
                continue
            # RouteContext exposes the effective APIRoute attributes, including
            # prefixes and include-time overrides.
            route = cast(APIRoute, context)
            methods = route.methods
            if not methods:
                raise ValueError(f"Cannot extract HTTP methods for route {route.path!r}")
            model = route.response_model
            if model is None:
                response = ResponseContract(ResponseStateKind.NO_MODEL, None, None, None)
            else:
                if isinstance(model, type) and issubclass(model, BaseModel):
                    if model not in cache:
                        cache[model] = _extract_shape(model)
                    shape, reason = cache[model]
                else:
                    shape, reason = _extract_shape(model)
                policy = ResponsePolicy(
                    include=normalize_top_level_selection(route.response_model_include),
                    exclude=normalize_top_level_selection(route.response_model_exclude),
                    by_alias=route.response_model_by_alias,
                    exclude_none=route.response_model_exclude_none,
                    exclude_unset=route.response_model_exclude_unset,
                    exclude_defaults=route.response_model_exclude_defaults,
                )
                response = ResponseContract(
                    ResponseStateKind.SUPPORTED
                    if shape is not None
                    else ResponseStateKind.UNSUPPORTED,
                    shape,
                    policy,
                    reason,
                )
            # Remove only parameter group names, retaining converter regexes.
            regex = re.sub(r"\(\?P<[^>]+>", "(?:", route.path_regex.pattern)
            body = JsonBodyState(
                JsonBodyStateKind.ABSENT
                if route.body_field is None
                else JsonBodyStateKind.UNSUPPORTED,
                None,
                None if route.body_field is None else "Request analysis is outside Slice 1",
            )
            for method in sorted(methods):
                routes.append(
                    RouteSnapshot(
                        RouteContract(
                            key=RouteKey(method, route.path),
                            match_key=RouteMatchKey(method, regex),
                            schema_visibility=(
                                SchemaVisibility.DOCUMENTED
                                if route.include_in_schema
                                else SchemaVisibility.HIDDEN
                            ),
                            parameters=(),
                            request=RequestContract(body),
                            response=response,
                        ),
                        source=None,
                    )
                )
        routes.sort(key=lambda item: (item.contract.match_key, item.contract.key))
        return ContractSnapshot(
            SnapshotMetadata(
                1,
                version("fastapi-contract"),
                EnvironmentSnapshot(
                    platform.python_version(),
                    version("fastapi"),
                    version("starlette"),
                    version("pydantic"),
                ),
            ),
            ApplicationContract(tuple(routes)),
        )
