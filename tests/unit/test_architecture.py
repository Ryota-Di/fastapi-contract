import ast
from pathlib import Path

import pytest

_SRC_ROOT = Path(__file__).parents[2] / "src" / "fastapi_contract"
_FORBIDDEN_FRAMEWORK_ROOTS = {"fastapi", "pydantic", "starlette"}


@pytest.mark.parametrize("package", ["domain", "rules"])
def test_domain_and_rules_do_not_import_framework_packages(package: str) -> None:
    violations: list[str] = []

    for path in (_SRC_ROOT / package).rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            imported_roots: set[str] = set()
            if isinstance(node, ast.Import):
                imported_roots = {alias.name.split(".", 1)[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_roots = {node.module.split(".", 1)[0]}

            forbidden = imported_roots & _FORBIDDEN_FRAMEWORK_ROOTS
            if forbidden:
                violations.append(f"{path.relative_to(_SRC_ROOT)}: {sorted(forbidden)}")

    assert violations == []
