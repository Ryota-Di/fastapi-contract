"""Version-bounded extraction of single, unembedded JSON BaseModel binding facts."""

import hashlib
import json
from typing import Any

from fastapi import params
from fastapi.routing import APIRoute
from pydantic import (
    AfterValidator,
    AliasChoices,
    AliasPath,
    BaseModel,
    BeforeValidator,
    PlainValidator,
    WrapValidator,
)

from fastapi_contract.domain.blocker import BlockerCode, FactBlocker
from fastapi_contract.domain.body import (
    BodyBindingFacts,
    BodyBindingKind,
    BodyInputSlotFact,
    KnownBindingKeys,
    UnknownBindingKeys,
)


def _outside(code: BlockerCode, scope: str) -> BodyBindingFacts:
    return BodyBindingFacts(BodyBindingKind.OUTSIDE_SLICE, blockers=(FactBlocker(code, scope),))


def _properties(document: dict[str, Any], route: APIRoute, method: str) -> set[str] | None:
    try:
        schema = document["paths"][route.path_format][method.lower()]["requestBody"]["content"][
            "application/json"
        ]["schema"]
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
        return set(properties) if isinstance(properties, dict) else None
    except (KeyError, TypeError, AttributeError):
        return None


def _possible_keys(
    alias: AliasChoices | AliasPath, name: str, by_alias: bool, by_name: bool
) -> tuple[str, ...] | None:
    # Only dependency scoping, not AliasChoices/Path binding support.
    roots = {name} if by_name else set()
    if by_alias:
        alternatives = alias.choices if isinstance(alias, AliasChoices) else [alias]
        for alternative in alternatives:
            root = alternative.path[0] if isinstance(alternative, AliasPath) else alternative
            if not isinstance(root, str):
                return None
            roots.add(root)
    return tuple(sorted(roots))


def extract_body(
    route: APIRoute, method: str, document: dict[str, Any], *, supported_runtime: bool
) -> BodyBindingFacts:
    direct = route.dependant.body_params
    # Dependency body extraction is outside this PR. Never mistake a dependency body for ABSENT.
    if route.body_field is None and not direct:
        return BodyBindingFacts(BodyBindingKind.ABSENT)
    if not supported_runtime:
        return _outside(BlockerCode.BODY_RUNTIME, "requires-fastapi-0.141.1-pydantic-2.13.5")
    dependencies = list(route.dependant.dependencies)
    seen: set[int] = set()
    while dependencies:
        dependency = dependencies.pop()
        if id(dependency) in seen:
            continue
        seen.add(id(dependency))
        if dependency.body_params:
            return _outside(BlockerCode.BODY_INPUT, "dependency-body")
        dependencies.extend(dependency.dependencies)
    if len(direct) != 1 or route._embed_body_fields:
        return _outside(BlockerCode.BODY_INPUT, "multiple-embedded-or-dependency-body")
    field = direct[0].field_info
    if (
        not isinstance(field, params.Body)
        or isinstance(field, params.Form)
        or field.media_type != "application/json"
    ):
        return _outside(BlockerCode.BODY_INPUT, "non-json-body")
    if any(
        isinstance(m, (BeforeValidator, AfterValidator, PlainValidator, WrapValidator))
        or hasattr(m, "__get_pydantic_core_schema__")
        for m in field.metadata
    ):
        return _outside(BlockerCode.BODY_VALIDATION, "body-parameter-validator")
    model = field.annotation
    if (
        not isinstance(model, type)
        or not issubclass(model, BaseModel)
        or model.__pydantic_root_model__
    ):
        return _outside(BlockerCode.BODY_INPUT, "non-top-level-basemodel")
    decorators = model.__pydantic_decorators__
    if decorators.model_validators or decorators.root_validators:
        return _outside(BlockerCode.BODY_VALIDATION, "model-validator")
    if getattr(model.__get_pydantic_core_schema__, "__func__", None) is not getattr(
        BaseModel.__get_pydantic_core_schema__, "__func__", None
    ):
        return _outside(BlockerCode.BODY_VALIDATION, "custom-model-schema")
    config = model.model_config
    by_alias = config.get("validate_by_alias", True)
    by_name = config.get("validate_by_name", not by_alias)
    if type(by_alias) is not bool or type(by_name) is not bool:
        return _outside(BlockerCode.BODY_INPUT, "unresolved-validation-policy")
    properties = _properties(document, route, method)
    if properties is None:
        return _outside(BlockerCode.BODY_DOCUMENTATION, "request-schema-unavailable")
    slots = []
    for name, info in sorted(model.model_fields.items()):
        alias = info.validation_alias
        known: KnownBindingKeys | UnknownBindingKeys
        anchor: str | None
        if alias is None or isinstance(alias, str):
            anchor = name if alias is None else alias
            keys = (
                (name,)
                if alias is None
                else tuple(
                    sorted(({alias} if by_alias else set()) | ({name} if by_name else set()))
                )
            )
            known = KnownBindingKeys(keys)
            if anchor not in properties:
                anchor = None
                known = UnknownBindingKeys(FactBlocker(BlockerCode.BODY_DOCUMENTATION), keys)
        elif isinstance(alias, (AliasChoices, AliasPath)):
            anchor = None
            structure = json.dumps(alias.convert_to_aliases(), ensure_ascii=False)
            fingerprint = hashlib.sha256(structure.encode()).hexdigest()
            known = UnknownBindingKeys(
                FactBlocker(BlockerCode.BODY_ALIAS, fingerprint),
                _possible_keys(alias, name, by_alias, by_name),
            )
        else:
            anchor = None
            known = UnknownBindingKeys(FactBlocker(BlockerCode.BODY_ALIAS), None)
        slots.append(BodyInputSlotFact(name, anchor, known))
    return BodyBindingFacts(BodyBindingKind.MODEL, tuple(slots))
