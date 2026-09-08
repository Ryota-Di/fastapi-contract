from fastapi import APIRouter, FastAPI
from pydantic import BaseModel, ConfigDict, Field, computed_field

from fastapi_contract.adapters.fastapi import FastApiSnapshotExtractor
from fastapi_contract.domain.model import (
    Completeness,
    NoDefault,
    ObjectSelection,
    ObjectShape,
    ResponseStateKind,
    ScalarShape,
    SchemaVisibility,
    StaticDefault,
)


def _app_routes(app: FastAPI):
    snapshot = FastApiSnapshotExtractor().extract(app)
    return [
        route.contract
        for route in snapshot.application.routes
        if route.contract.key.path.startswith("/")
    ]


def _only_route(app: FastAPI):
    routes = _app_routes(app)
    assert len(routes) == 1
    return routes[0]


def test_extracts_simple_response_model_and_exclude_policy() -> None:
    class User(BaseModel):
        id: int
        email: str

    app = FastAPI()

    @app.get("/users", response_model=User, response_model_exclude={"email"})
    def get_user() -> dict[str, object]:
        return {"id": 1, "email": "a@example.com"}

    route = _only_route(app)

    assert route.response.state is ResponseStateKind.SUPPORTED
    assert isinstance(route.response.shape, ObjectShape)
    assert tuple(field.logical_name for field in route.response.shape.fields) == ("email", "id")
    assert route.response.policy is not None
    assert route.response.policy.exclude is not None
    assert route.response.policy.exclude.completeness is Completeness.COMPLETE
    root = route.response.policy.exclude.root
    assert isinstance(root, ObjectSelection)
    assert tuple(entry.name for entry in root.fields) == ("email",)


def test_extracts_basic_scalar_field_metadata_without_loss() -> None:
    class User(BaseModel):
        id: int
        nickname: str | None = None

    app = FastAPI()

    @app.get("/users", response_model=User)
    def get_user() -> dict[str, object]:
        return {"id": 1, "nickname": None}

    route = _only_route(app)

    assert isinstance(route.response.shape, ObjectShape)
    fields = {field.logical_name: field for field in route.response.shape.fields}

    assert fields["id"].serialization_name == "id"
    assert fields["id"].nullable is False
    assert isinstance(fields["id"].default, NoDefault)
    assert isinstance(fields["id"].shape, ScalarShape)

    assert fields["nickname"].serialization_name == "nickname"
    assert fields["nickname"].nullable is True
    assert isinstance(fields["nickname"].default, StaticDefault)
    assert fields["nickname"].default.is_none is True
    assert isinstance(fields["nickname"].shape, ScalarShape)


def test_no_response_model_is_no_model() -> None:
    app = FastAPI()

    @app.get("/raw", response_model=None)
    def raw() -> dict[str, int]:
        return {"value": 1}

    route = _only_route(app)

    assert route.response.state is ResponseStateKind.NO_MODEL


def test_nested_response_model_is_unsupported_in_slice1() -> None:
    class Profile(BaseModel):
        email: str

    class User(BaseModel):
        id: int
        profile: Profile

    app = FastAPI()

    @app.get("/users", response_model=User)
    def get_user() -> dict[str, object]:
        return {"id": 1, "profile": {"email": "a@example.com"}}

    route = _only_route(app)

    assert route.response.state is ResponseStateKind.UNSUPPORTED
    assert route.response.reason


def test_field_level_exclusion_marks_response_unsupported_in_slice1() -> None:
    class User(BaseModel):
        id: int
        email: str = Field(exclude=True)

    app = FastAPI()

    @app.get("/users", response_model=User)
    def get_user() -> dict[str, object]:
        return {"id": 1, "email": "a@example.com"}

    route = _only_route(app)

    assert route.response.state is ResponseStateKind.UNSUPPORTED
    assert route.response.reason


def test_conditional_field_exclusion_marks_response_unsupported_in_slice1() -> None:
    class User(BaseModel):
        id: int
        score: int = Field(exclude_if=lambda value: value == 0)

    app = FastAPI()

    @app.get("/users", response_model=User)
    def get_user() -> dict[str, int]:
        return {"id": 1, "score": 0}

    route = _only_route(app)

    assert route.response.state is ResponseStateKind.UNSUPPORTED
    assert route.response.reason


def test_response_model_include_is_preserved_for_review_logic() -> None:
    class User(BaseModel):
        id: int
        email: str

    app = FastAPI()

    @app.get("/users", response_model=User, response_model_include={"id"})
    def get_user() -> dict[str, object]:
        return {"id": 1, "email": "a@example.com"}

    route = _only_route(app)

    assert route.response.policy is not None
    assert route.response.policy.include is not None
    assert route.response.policy.include.completeness is Completeness.COMPLETE


def test_computed_field_marks_response_unsupported_in_slice1() -> None:
    class User(BaseModel):
        first: str
        last: str

        @computed_field
        @property
        def full_name(self) -> str:
            return f"{self.first} {self.last}"

    app = FastAPI()

    @app.get("/users", response_model=User)
    def get_user() -> dict[str, str]:
        return {"first": "Ada", "last": "Lovelace"}

    route = _only_route(app)

    assert route.response.state is ResponseStateKind.UNSUPPORTED
    assert route.response.reason


def test_open_response_model_marks_response_unsupported_in_slice1() -> None:
    class User(BaseModel):
        model_config = ConfigDict(extra="allow")

        id: int

    app = FastAPI()

    @app.get("/users", response_model=User)
    def get_user() -> dict[str, object]:
        return {"id": 1, "dynamic": "value"}

    route = _only_route(app)

    assert route.response.state is ResponseStateKind.UNSUPPORTED
    assert route.response.reason


def test_array_response_model_marks_response_unsupported_in_slice1() -> None:
    class User(BaseModel):
        id: int

    app = FastAPI()

    @app.get("/users", response_model=list[User])
    def get_users() -> list[dict[str, int]]:
        return [{"id": 1}]

    route = _only_route(app)

    assert route.response.state is ResponseStateKind.UNSUPPORTED
    assert route.response.reason


def test_hidden_route_visibility_is_preserved() -> None:
    class Health(BaseModel):
        ok: bool

    app = FastAPI()

    @app.get("/internal/health", response_model=Health, include_in_schema=False)
    def health() -> dict[str, bool]:
        return {"ok": True}

    route = _only_route(app)

    assert route.schema_visibility is SchemaVisibility.HIDDEN


def test_path_parameter_rename_has_same_runtime_match_key() -> None:
    class User(BaseModel):
        id: int

    before = FastAPI()
    after = FastAPI()

    @before.get("/users/{id}", response_model=User)
    def before_user(id: int) -> dict[str, int]:
        return {"id": id}

    @after.get("/users/{user_id}", response_model=User)
    def after_user(user_id: int) -> dict[str, int]:
        return {"id": user_id}

    before_route = _only_route(before)
    after_route = _only_route(after)

    assert before_route.match_key == after_route.match_key


def test_path_converter_change_has_different_runtime_match_key() -> None:
    class Item(BaseModel):
        value: str

    before = FastAPI()
    after = FastAPI()

    @before.get("/files/{file}", response_model=Item)
    def before_file(file: str) -> dict[str, str]:
        return {"value": file}

    @after.get("/files/{file:path}", response_model=Item)
    def after_file(file: str) -> dict[str, str]:
        return {"value": file}

    before_route = _only_route(before)
    after_route = _only_route(after)

    assert before_route.match_key != after_route.match_key


def test_multi_method_route_is_expanded_to_one_contract_per_method() -> None:
    class Health(BaseModel):
        ok: bool

    app = FastAPI()

    @app.api_route("/health", methods=["GET", "POST"], response_model=Health)
    def health() -> dict[str, bool]:
        return {"ok": True}

    routes = _app_routes(app)

    assert [(route.key.method, route.key.path) for route in routes] == [
        ("GET", "/health"),
        ("POST", "/health"),
    ]


def test_router_prefix_is_reflected_in_effective_route_identity() -> None:
    class User(BaseModel):
        id: int

    router = APIRouter(prefix="/api")

    @router.get("/users", response_model=User)
    def users() -> dict[str, int]:
        return {"id": 1}

    app = FastAPI()
    app.include_router(router)

    route = _only_route(app)

    assert route.key.path == "/api/users"
    assert "/api/users" in route.match_key.normalized_path_regex
