"""Immutable, framework-independent facts transported by snapshot schema v1."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Completeness(StrEnum):
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"


class ShapeOpenness(StrEnum):
    CLOSED = "closed"
    OPEN = "open"


class FieldProjectionPolicy(StrEnum):
    NORMAL = "normal"


class ResponseStateKind(StrEnum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    NO_MODEL = "no_model"


class SchemaVisibility(StrEnum):
    DOCUMENTED = "documented"
    HIDDEN = "hidden"


class JsonBodyStateKind(StrEnum):
    ABSENT = "absent"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class WholeSelection:
    pass


@dataclass(frozen=True)
class UnsupportedSelection:
    # Canonical tagged JSON preserves key types, container types and nested values.
    canonical_value: str


@dataclass(frozen=True)
class SelectionEntry:
    name: str
    selection: WholeSelection | ObjectSelection | UnsupportedSelection


@dataclass(frozen=True)
class ObjectSelection:
    fields: tuple[SelectionEntry, ...]


@dataclass(frozen=True)
class FieldSelection:
    root: ObjectSelection | UnsupportedSelection
    completeness: Completeness
    incomplete_reason: str | None


@dataclass(frozen=True)
class NoDefault:
    pass


@dataclass(frozen=True)
class StaticDefault:
    is_none: bool


@dataclass(frozen=True)
class FactoryDefault:
    pass


@dataclass(frozen=True)
class ScalarShape:
    nullable: bool


@dataclass(frozen=True)
class ObjectField:
    logical_name: str
    serialization_name: str
    nullable: bool
    default: NoDefault | StaticDefault | FactoryDefault
    projection_policy: FieldProjectionPolicy
    shape: ScalarShape


@dataclass(frozen=True)
class ObjectShape:
    fields: tuple[ObjectField, ...]
    openness: ShapeOpenness


@dataclass(frozen=True)
class ResponsePolicy:
    include: FieldSelection | None
    exclude: FieldSelection | None
    by_alias: bool
    exclude_none: bool
    exclude_unset: bool
    exclude_defaults: bool


@dataclass(frozen=True)
class ResponseContract:
    state: ResponseStateKind
    shape: ObjectShape | None
    policy: ResponsePolicy | None
    reason: str | None


@dataclass(frozen=True)
class JsonBodyState:
    kind: JsonBodyStateKind
    contract: None
    reason: str | None


@dataclass(frozen=True)
class RequestContract:
    json_body: JsonBodyState


@dataclass(frozen=True, order=True)
class RouteKey:
    method: str
    path: str


@dataclass(frozen=True, order=True)
class RouteMatchKey:
    method: str
    normalized_path_regex: str


@dataclass(frozen=True)
class RouteContract:
    key: RouteKey
    match_key: RouteMatchKey
    schema_visibility: SchemaVisibility
    parameters: tuple[()]
    request: RequestContract
    response: ResponseContract


@dataclass(frozen=True)
class RouteSnapshot:
    contract: RouteContract
    source: str | None


@dataclass(frozen=True)
class ApplicationContract:
    routes: tuple[RouteSnapshot, ...]


@dataclass(frozen=True)
class EnvironmentSnapshot:
    python_version: str
    fastapi_version: str
    starlette_version: str
    pydantic_version: str


@dataclass(frozen=True)
class SnapshotMetadata:
    schema_version: int
    tool_version: str
    environment: EnvironmentSnapshot


@dataclass(frozen=True)
class ContractSnapshot:
    metadata: SnapshotMetadata
    application: ApplicationContract
