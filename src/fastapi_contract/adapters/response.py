"""Canonical extraction boundary: resolved response facts and delegated body binding facts."""

import hashlib
import json
import platform
import re
from collections.abc import Mapping
from importlib.metadata import version
from typing import Any, cast

from fastapi import FastAPI
from fastapi.routing import APIRoute, iter_route_contexts
from pydantic import BaseModel

from fastapi_contract.adapters.body import extract_body
from fastapi_contract.adapters.parameters import extract_parameters
from fastapi_contract.adapters.selection import _preserve
from fastapi_contract.domain.facts import (
    BlockerCode,
    CanonicalSnapshot,
    FactBlocker,
    ProjectionFact,
    ProjectionState,
    ResponseFacts,
    ResponseSlotFact,
    RouteFacts,
)
from fastapi_contract.domain.model import EnvironmentSnapshot, RouteKey, RouteMatchKey

INCLUDED = ProjectionFact(ProjectionState.INCLUDED)
EXCLUDED = ProjectionFact(ProjectionState.EXCLUDED)


def _unknown(value: object) -> ProjectionFact:
    structural = json.dumps(_preserve(value), ensure_ascii=False, separators=(",", ":"))
    token = hashlib.sha256(structural.encode()).hexdigest()
    return ProjectionFact(
        ProjectionState.UNKNOWN, FactBlocker(BlockerCode.UNSUPPORTED_SELECTOR, token)
    )


def _selection(
    value: object, names: tuple[str, ...], *, include: bool
) -> dict[str, ProjectionFact]:
    default = EXCLUDED if include and value is not None else INCLUDED
    result = dict.fromkeys(names, default)
    if value is None:
        return result
    selected = INCLUDED if include else EXCLUDED
    if isinstance(value, (set, frozenset)) and all(
        type(k) is str and k != "__all__" for k in value
    ):
        for name in names:
            if name in value:
                result[name] = selected
    elif isinstance(value, Mapping) and all(type(k) is str and k != "__all__" for k in value):
        for name in names:
            if name in value:
                item = value[name]
                result[name] = (
                    selected if item is True or item is Ellipsis else _unknown({name: item})
                )
    else:
        unknown = _unknown(value)
        result = dict.fromkeys(names, unknown)
    return result


def _properties(
    document: dict[str, Any], path: str, method: str, status: int | None
) -> set[str] | None:
    try:
        schema = document["paths"][path][method.lower()]["responses"][str(status or 200)][
            "content"
        ]["application/json"]["schema"]
        visited = set()
        while "$ref" in schema:
            ref = schema["$ref"]
            if not isinstance(ref, str) or not ref.startswith("#/") or ref in visited:
                return None
            visited.add(ref)
            schema = document
            for part in ref[2:].split("/"):
                schema = schema[part.replace("~1", "/").replace("~0", "~")]
        properties = schema.get("properties")
        if not isinstance(properties, dict):
            return None
        return set(properties)
    except (KeyError, TypeError, AttributeError):
        return None


# (logical name, resolved serialization alias, always excluded, conditional exclusion)
FieldInfo = tuple[str, str, bool, bool]


def _model_facts(model: type[BaseModel]) -> tuple[tuple[FieldInfo, ...], tuple[FactBlocker, ...]]:
    blockers = []
    if model.__pydantic_root_model__ or model.model_config.get("extra") == "allow":
        blockers.append(FactBlocker(BlockerCode.UNSUPPORTED_MODEL))
    if model.__pydantic_decorators__.model_serializers:
        blockers.append(FactBlocker(BlockerCode.MODEL_SERIALIZER))
    fields = [
        (
            name,
            f.serialization_alias if f.serialization_alias is not None else name,
            f.exclude is True,
            f.exclude_if is not None,
        )
        for name, f in model.model_fields.items()
    ]
    fields.extend(
        (name, f.alias if f.alias is not None else name, False, False)
        for name, f in model.model_computed_fields.items()
    )
    return tuple(sorted(fields)), tuple(sorted(blockers))


class FastApiFactExtractor:
    def extract(self, app: FastAPI) -> CanonicalSnapshot:
        # Only use the standard OpenAPI generation path. Unknown custom documentation
        # cannot establish OpenAPI ownership of a runtime loss.
        effective_routes = [
            cast(APIRoute, context)
            for context in iter_route_contexts(app.routes)
            if isinstance(context.original_route, APIRoute)
        ]
        for route in effective_routes:
            if not route.methods:
                raise ValueError(f"Cannot extract HTTP methods for route {route.path!r}")
            if type(route.response_model_by_alias) is not bool:
                raise ValueError("Cannot resolve response by_alias policy")
        standard_docs = getattr(app.openapi, "__func__", None) is FastAPI.openapi
        document = app.openapi() if standard_docs else {}
        cache: dict[type[BaseModel], tuple[tuple[FieldInfo, ...], tuple[FactBlocker, ...]]] = {}
        routes = []
        supported_runtime = version("fastapi") == "0.141.1" and version("pydantic") == "2.13.5"
        for route in effective_routes:
            if not route.methods:
                raise ValueError(f"Cannot extract HTTP methods for route {route.path!r}")
            model = route.response_model
            fields: tuple[FieldInfo, ...] = ()
            if isinstance(model, type) and issubclass(model, BaseModel):
                if model not in cache:
                    cache[model] = _model_facts(model)
                fields, wide = cache[model]
            else:
                wide = (
                    FactBlocker(
                        BlockerCode.UNSUPPORTED_MODEL, "no_model" if model is None else "non_object"
                    ),
                )
            names = tuple(f[0] for f in fields)
            include = _selection(route.response_model_include, names, include=True)
            exclude = _selection(route.response_model_exclude, names, include=False)
            conditional = (
                route.response_model_exclude_none
                or route.response_model_exclude_unset
                or route.response_model_exclude_defaults
            )
            conditional_token = json.dumps(
                [
                    route.response_model_exclude_none,
                    route.response_model_exclude_unset,
                    route.response_model_exclude_defaults,
                ]
            )
            if wide:
                policy_token = hashlib.sha256(
                    json.dumps(
                        [
                            _preserve(route.response_model_include),
                            _preserve(route.response_model_exclude),
                            route.response_model_by_alias,
                            conditional_token,
                        ],
                        sort_keys=True,
                        ensure_ascii=False,
                    ).encode()
                ).hexdigest()
                wide = tuple(FactBlocker(b.code, b.fingerprint + ":" + policy_token) for b in wide)
            regex = re.sub(r"\(\?P<[^>]+>", "(?:", route.path_regex.pattern)
            for method in sorted(route.methods):
                properties = (
                    _properties(document, route.path_format, method, route.status_code)
                    if standard_docs and route.include_in_schema
                    else set()
                )
                blockers = list(wide)
                if not standard_docs or properties is None:
                    blockers.append(FactBlocker(BlockerCode.DOCUMENTATION_UNKNOWN))
                slots = []
                for name, alias, excluded, field_conditional in fields:
                    choices = (include[name], exclude[name])
                    if excluded or EXCLUDED in choices:
                        projection = EXCLUDED
                    elif any(p.state is ProjectionState.UNKNOWN for p in choices):
                        projection = next(p for p in choices if p.state is ProjectionState.UNKNOWN)
                    elif conditional or field_conditional:
                        projection = ProjectionFact(
                            ProjectionState.UNKNOWN,
                            FactBlocker(
                                BlockerCode.CONDITIONAL_EXCLUSION,
                                hashlib.sha256(
                                    (conditional_token + str(field_conditional)).encode()
                                ).hexdigest(),
                            ),
                        )
                    else:
                        projection = INCLUDED
                    documented = alias if properties is not None and alias in properties else None
                    if (
                        route.include_in_schema
                        and properties is not None
                        and alias not in properties
                        and not excluded
                    ):
                        blockers.append(FactBlocker(BlockerCode.DOCUMENTATION_UNKNOWN))
                    slots.append(
                        ResponseSlotFact(
                            name,
                            documented,
                            alias if route.response_model_by_alias else name,
                            projection,
                        )
                    )
                routes.append(
                    RouteFacts(
                        RouteKey(method, route.path),
                        RouteMatchKey(method, regex),
                        ResponseFacts(tuple(slots), tuple(sorted(set(blockers)))),
                        extract_body(route, method, document, supported_runtime=supported_runtime),
                        extract_parameters(
                            route,
                            supported_runtime=supported_runtime,
                            standard_docs=standard_docs,
                        ),
                    )
                )
        routes.sort(key=lambda r: (r.match_key, r.key))
        return CanonicalSnapshot(
            EnvironmentSnapshot(
                platform.python_version(),
                version("fastapi"),
                version("starlette"),
                version("pydantic"),
            ),
            tuple(routes),
        )


# Retain the PR1 public import while the canonical extractor gains the body family.
FastApiResponseFactExtractor = FastApiFactExtractor
