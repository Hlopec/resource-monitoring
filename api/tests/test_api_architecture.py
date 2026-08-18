from __future__ import annotations

import ast
import inspect
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.api.composition import get_unit_of_work_factory
from app.api.router import api_v1_router
from app.api.schemas import ApiSchema
from app.main import app
from app.persistence.sqlalchemy import SQLAlchemyUnitOfWork

ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "app"
APPLICATION_ROOT = APP_ROOT / "application"
API_ROOT = APP_ROOT / "api"
API_ROUTES_ROOT = API_ROOT / "routes"
API_COMPOSITION_PATH = API_ROOT / "composition.py"
MAIN_PATH = APP_ROOT / "main.py"

FORBIDDEN_APPLICATION_IMPORT_ROOTS = {"fastapi", "pydantic", "starlette"}
FORBIDDEN_APPLICATION_MODULE_PREFIXES = {"app.api", "app.persistence"}
FORBIDDEN_APPLICATION_NAMES = {
    "HTTPException",
    "Request",
    "Response",
}
FORBIDDEN_ROUTE_IMPORT_ROOTS = {"sqlalchemy"}
FORBIDDEN_ROUTE_MODULE_PREFIXES = {
    "app.db",
    "app.models",
    "app.persistence",
}
FORBIDDEN_ROUTE_SQLALCHEMY_NAMES = {
    "Engine",
    "Query",
    "Result",
    "Row",
    "Select",
    "Session",
    "SessionLocal",
    "create_engine",
    "sessionmaker",
}
FORBIDDEN_FRAMEWORK_NAMES = {
    "CommandBus",
    "HandlerRegistry",
    "Mediator",
    "ServiceLocator",
}


def _python_files(path: Path) -> list[Path]:
    return sorted(candidate for candidate in path.rglob("*.py") if candidate.is_file())


def _tree_for(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imports_for(path: Path) -> set[str]:
    tree = _tree_for(path)
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def _imported_names_for(path: Path) -> set[str]:
    tree = _tree_for(path)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.asname or alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.update(alias.asname or alias.name for alias in node.names)
    return names


def _source_contains(path: Path, values: set[str]) -> set[str]:
    source = path.read_text(encoding="utf-8")
    return {value for value in values if value in source}


def test_application_layer_does_not_import_api_or_transport_frameworks() -> None:
    for path in _python_files(APPLICATION_ROOT):
        imports = _imports_for(path)
        imported_names = _imported_names_for(path)

        assert not any(
            imported.split(".", 1)[0] in FORBIDDEN_APPLICATION_IMPORT_ROOTS
            for imported in imports
        ), path
        assert not any(
            imported.startswith(tuple(FORBIDDEN_APPLICATION_MODULE_PREFIXES))
            for imported in imports
        ), path
        assert FORBIDDEN_APPLICATION_NAMES.isdisjoint(imported_names), path


def test_api_route_modules_do_not_import_sqlalchemy_models_or_persistence() -> None:
    for path in _python_files(API_ROUTES_ROOT):
        imports = _imports_for(path)
        imported_names = _imported_names_for(path)

        assert not any(
            imported.split(".", 1)[0] in FORBIDDEN_ROUTE_IMPORT_ROOTS
            for imported in imports
        ), path
        assert not any(
            imported.startswith(tuple(FORBIDDEN_ROUTE_MODULE_PREFIXES))
            for imported in imports
        ), path
        assert FORBIDDEN_ROUTE_SQLALCHEMY_NAMES.isdisjoint(imported_names), path


def test_api_schemas_are_pydantic_transport_contracts_not_orm_models() -> None:
    import app.api.schemas as schemas

    schema_types = [
        member
        for _, member in inspect.getmembers(schemas, inspect.isclass)
        if issubclass(member, BaseModel) and member.__module__ == schemas.__name__
    ]

    assert schema_types
    assert all(issubclass(schema_type, ApiSchema) for schema_type in schema_types)
    assert all(
        schema_type.model_config.get("from_attributes") is False
        for schema_type in schema_types
    )
    assert not any(
        imported.startswith("app.models") for imported in _imports_for(API_ROOT / "schemas.py")
    )


def test_persistence_wiring_is_confined_to_api_composition_boundary() -> None:
    for path in _python_files(API_ROOT):
        imports = _imports_for(path)
        imports_persistence = any(
            imported.startswith("app.persistence") or imported.startswith("app.db")
            for imported in imports
        )
        if path == API_COMPOSITION_PATH:
            assert imports_persistence, path
        else:
            assert not imports_persistence, path

    assert get_unit_of_work_factory() is SQLAlchemyUnitOfWork


def test_no_bus_mediator_registry_or_service_locator_is_introduced() -> None:
    for path in _python_files(APP_ROOT):
        assert not _source_contains(path, FORBIDDEN_FRAMEWORK_NAMES), path


def test_main_module_is_bootstrap_oriented() -> None:
    imports = _imports_for(MAIN_PATH)
    tree = _tree_for(MAIN_PATH)

    assert "fastapi" in imports
    assert "app.api" in imports
    assert not any(imported.startswith("app.persistence") for imported in imports)
    assert not any(imported.startswith("app.models") for imported in imports)
    assert not any(isinstance(node, ast.FunctionDef) for node in ast.walk(tree))


def test_fastapi_app_imports_and_existing_system_routes_work() -> None:
    client = TestClient(app)

    root_response = client.get("/")
    health_response = client.get("/health")

    assert root_response.status_code == 200
    assert root_response.json() == {
        "service": "resource-monitoring-api",
        "status": "running",
    }
    assert health_response.status_code == 200
    assert health_response.json() == {"status": "healthy"}


def test_api_v1_router_baseline_is_composable_without_resource_endpoints() -> None:
    route_paths = {route.path for route in app.routes}

    assert api_v1_router.prefix == "/api/v1"
    assert api_v1_router.routes == []
    assert "/api/v1/resources" not in route_paths
