from __future__ import annotations

import ast
import inspect
import re
from pathlib import Path
from typing import get_type_hints

from fastapi.params import Depends
from fastapi.testclient import TestClient
from pydantic import BaseModel

import app.api.composition as composition
from app.api.composition import get_unit_of_work_factory
from app.api.router import api_v1_router
from app.api.schemas import ApiSchema
from app.application.handlers import (
    AssignResourceAliasHandler,
    AssignResourceClassificationHandler,
    AssignResourceIdentifierHandler,
    AssignResourceLabelHandler,
    AssignResourceOwnershipHandler,
    AssignResourceRelationshipHandler,
    CreateResourceHandler,
    FindResourceByAliasHandler,
    FindResourceByIdentifierHandler,
    GetResourceByCanonicalNameHandler,
    GetResourceByIdHandler,
    GetResourceDetailsHandler,
    GetResourceHistoryHandler,
    GetResourceRelationshipsHandler,
    ListResourcesHandler,
    MergeResourceHandler,
    ResolveCanonicalResourceHandler,
    TransitionResourceStateHandler,
)
from app.application.ports import UnitOfWorkFactory
from app.main import app
from app.persistence.sqlalchemy import SQLAlchemyUnitOfWork

ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "app"
APPLICATION_ROOT = APP_ROOT / "application"
API_ROOT = APP_ROOT / "api"
API_MAPPERS_ROOT = API_ROOT / "mappers"
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
FORBIDDEN_SCHEMA_MODULE_PREFIXES = {
    "app.db",
    "app.models",
    "app.persistence",
    "sqlalchemy",
}
FORBIDDEN_GENERIC_SERIALIZER_NAMES = {
    "SerializerRegistry",
    "serializer_registry",
    "serialize",
}
FORBIDDEN_OFFSET_PAGINATION_NAMES = {
    "limit",
    "offset",
    "page_number",
    "total_count",
    "total_pages",
}
FORBIDDEN_PROVIDER_CALL_NAMES = {
    "Session",
    "SessionLocal",
    "begin",
    "commit",
    "connect",
    "execute",
    "flush",
    "rollback",
    "sessionmaker",
}
FORBIDDEN_FRAMEWORK_NAMES = {
    "CommandBus",
    "HandlerRegistry",
    "Mediator",
    "ServiceLocator",
}
RESOURCE_HANDLER_PROVIDERS = {
    "get_list_resources_handler": ListResourcesHandler,
    "get_get_resource_by_id_handler": GetResourceByIdHandler,
    "get_get_resource_details_handler": GetResourceDetailsHandler,
    "get_get_resource_history_handler": GetResourceHistoryHandler,
    "get_get_resource_relationships_handler": GetResourceRelationshipsHandler,
    "get_get_resource_by_canonical_name_handler": GetResourceByCanonicalNameHandler,
    "get_find_resource_by_identifier_handler": FindResourceByIdentifierHandler,
    "get_find_resource_by_alias_handler": FindResourceByAliasHandler,
    "get_resolve_canonical_resource_handler": ResolveCanonicalResourceHandler,
    "get_create_resource_handler": CreateResourceHandler,
    "get_transition_resource_state_handler": TransitionResourceStateHandler,
    "get_assign_resource_identifier_handler": AssignResourceIdentifierHandler,
    "get_assign_resource_ownership_handler": AssignResourceOwnershipHandler,
    "get_assign_resource_classification_handler": AssignResourceClassificationHandler,
    "get_assign_resource_label_handler": AssignResourceLabelHandler,
    "get_assign_resource_relationship_handler": AssignResourceRelationshipHandler,
    "get_assign_resource_alias_handler": AssignResourceAliasHandler,
    "get_merge_resource_handler": MergeResourceHandler,
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


def _source_contains_word(path: Path, values: set[str]) -> set[str]:
    source = path.read_text(encoding="utf-8")
    return {
        value
        for value in values
        if re.search(rf"\b{re.escape(value)}\b", source) is not None
    }


def _call_names_for(function: object) -> set[str]:
    source = inspect.getsource(function)
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                names.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                names.add(node.func.attr)
    return names


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


def test_api_schema_modules_do_not_import_persistence_or_orm_models() -> None:
    for path in [API_ROOT / "schemas.py", *_python_files(API_MAPPERS_ROOT)]:
        imports = _imports_for(path)

        assert not any(
            imported == forbidden_prefix
            or imported.startswith(f"{forbidden_prefix}.")
            for imported in imports
            for forbidden_prefix in FORBIDDEN_SCHEMA_MODULE_PREFIXES
        ), path


def test_api_mapping_helpers_are_api_owned_and_explicit() -> None:
    for path in _python_files(API_MAPPERS_ROOT):
        imports = _imports_for(path)
        function_names = {
            node.name
            for node in ast.walk(_tree_for(path))
            if isinstance(node, ast.FunctionDef)
        }

        assert path.relative_to(API_ROOT).parts[0] == "mappers"
        if function_names:
            assert any(
                imported.startswith("app.application.results") for imported in imports
            )
            assert any(imported.startswith("app.api.schemas") for imported in imports)
        assert "serialize" not in function_names


def test_api_layer_does_not_enable_orm_auto_serialization_strategy() -> None:
    for path in _python_files(API_ROOT):
        source = path.read_text(encoding="utf-8")

        assert "from_attributes=True" not in source
        assert "from_attributes = True" not in source
        assert ".model_validate(" not in source


def test_api_layer_does_not_introduce_generic_serializer_registry() -> None:
    for path in _python_files(API_ROOT):
        assert not _source_contains(path, FORBIDDEN_GENERIC_SERIALIZER_NAMES), path


def test_api_layer_does_not_introduce_offset_or_page_number_pagination() -> None:
    for path in _python_files(API_ROOT):
        assert not _source_contains_word(path, FORBIDDEN_OFFSET_PAGINATION_NAMES), path


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


def test_resource_handler_providers_are_explicit_and_typed() -> None:
    for provider_name, handler_type in RESOURCE_HANDLER_PROVIDERS.items():
        provider = getattr(composition, provider_name)
        signature = inspect.signature(provider)
        hints = get_type_hints(provider)

        assert hints["return"] is handler_type
        assert list(signature.parameters) == ["uow_factory"]
        parameter = signature.parameters["uow_factory"]
        assert hints["uow_factory"] is UnitOfWorkFactory
        assert isinstance(parameter.default, Depends)
        assert parameter.default.dependency is get_unit_of_work_factory


def test_resource_handler_providers_do_not_own_session_or_transaction_lifecycle() -> None:
    for provider_name in RESOURCE_HANDLER_PROVIDERS:
        provider = getattr(composition, provider_name)
        called_names = _call_names_for(provider)

        assert FORBIDDEN_PROVIDER_CALL_NAMES.isdisjoint(called_names), provider_name


def test_resource_handler_providers_are_not_global_singletons() -> None:
    handler_types = tuple(RESOURCE_HANDLER_PROVIDERS.values())

    assert not any(
        isinstance(value, handler_types)
        for value in vars(composition).values()
    )


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
    assert not any(path.startswith("/api/v1/tenants/") for path in route_paths)
