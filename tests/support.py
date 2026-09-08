from fastapi_contract.domain.model import (
    ApplicationContract,
    Completeness,
    ContractSnapshot,
    EnvironmentSnapshot,
    FieldProjectionPolicy,
    FieldSelection,
    JsonBodyState,
    JsonBodyStateKind,
    NoDefault,
    ObjectField,
    ObjectSelection,
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
    SelectionEntry,
    ShapeOpenness,
    SnapshotMetadata,
    WholeSelection,
)


def selection(
    *names: str,
    completeness: Completeness = Completeness.COMPLETE,
    reason: str | None = None,
) -> FieldSelection:
    entries = tuple(
        SelectionEntry(name=name, selection=WholeSelection()) for name in sorted(set(names))
    )
    return FieldSelection(
        root=ObjectSelection(fields=entries),
        completeness=completeness,
        incomplete_reason=reason,
    )


def simple_object_shape(*fields: str) -> ObjectShape:
    object_fields = tuple(
        ObjectField(
            logical_name=name,
            serialization_name=name,
            nullable=False,
            default=NoDefault(),
            projection_policy=FieldProjectionPolicy.NORMAL,
            shape=ScalarShape(nullable=False),
        )
        for name in sorted(fields)
    )
    return ObjectShape(fields=object_fields, openness=ShapeOpenness.CLOSED)


def route(
    *,
    fields: tuple[str, ...] = ("id", "email"),
    include: FieldSelection | None = None,
    exclude: FieldSelection | None = None,
    path: str = "/users",
    match_regex: str = "^/users$",
    method: str = "GET",
    response_state: ResponseStateKind = ResponseStateKind.SUPPORTED,
    unsupported_reason: str | None = None,
    schema_visibility: SchemaVisibility = SchemaVisibility.DOCUMENTED,
) -> RouteContract:
    policy = ResponsePolicy(
        include=include,
        exclude=exclude,
        by_alias=True,
        exclude_none=False,
        exclude_unset=False,
        exclude_defaults=False,
    )
    if response_state is ResponseStateKind.SUPPORTED:
        response = ResponseContract(
            state=response_state,
            shape=simple_object_shape(*fields),
            policy=policy,
            reason=None,
        )
    elif response_state is ResponseStateKind.UNSUPPORTED:
        response = ResponseContract(
            state=response_state,
            shape=None,
            policy=policy,
            reason=unsupported_reason or "unsupported response shape",
        )
    else:
        response = ResponseContract(
            state=response_state,
            shape=None,
            policy=None,
            reason=None,
        )

    return RouteContract(
        key=RouteKey(method=method, path=path),
        match_key=RouteMatchKey(method=method, normalized_path_regex=match_regex),
        schema_visibility=schema_visibility,
        parameters=(),
        request=RequestContract(
            json_body=JsonBodyState(
                kind=JsonBodyStateKind.ABSENT,
                contract=None,
                reason=None,
            )
        ),
        response=response,
    )


def snapshot(
    *routes: RouteContract,
    python_version: str = "3.12",
    fastapi_version: str = "test",
    starlette_version: str = "test",
    pydantic_version: str = "test",
) -> ContractSnapshot:
    return ContractSnapshot(
        metadata=SnapshotMetadata(
            schema_version=1,
            tool_version="test",
            environment=EnvironmentSnapshot(
                python_version=python_version,
                fastapi_version=fastapi_version,
                starlette_version=starlette_version,
                pydantic_version=pydantic_version,
            ),
        ),
        application=ApplicationContract(
            routes=tuple(RouteSnapshot(contract=item, source=None) for item in routes)
        ),
    )
