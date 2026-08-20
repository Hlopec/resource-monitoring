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
import app.api.routes.resource_lookups as resource_lookup_routes
import app.api.routes.resources as resource_routes
from app.api.composition import get_unit_of_work_factory
from app.api.errors import (
    api_error_response_for,
    application_error_status_code,
)
from app.api.router import api_v1_router
from app.api.schemas import (
    AssignResourceIdentifierRequest,
    ApiError,
    ApiErrorDetail,
    ApiErrorResponse,
    ApiSchema,
    CanonicalResourceResolvedResponse,
    CreateResourceRequest,
    ResourceAliasLookupResponse,
    ResourceCreatedResponse,
    ResourceDetailsResponse,
    ResourceHistoryResponse,
    ResourceIdentifierAssignedResponse,
    ResourceIdentifierLookupResponse,
    ResourcePageResponse,
    ResourceRelationshipsResponse,
    ResourceStateTransitionedResponse,
    TransitionResourceStateRequest,
)
from app.application.errors import ConcurrentModificationError, ConflictError
from app.application.errors import ApplicationError
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
API_ERRORS_PATH = API_ROOT / "errors.py"
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
FORBIDDEN_PUBLIC_ERROR_FIELD_NAMES = {
    "cause",
    "constraint",
    "exception",
    "sql",
    "sqlstate",
    "traceback",
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
FORBIDDEN_RESOURCE_ROUTE_NAMES = {
    "ResourceQueryService",
}
FORBIDDEN_CREATE_ROUTE_NAMES = {
    "GetResourceByIdHandler",
    "GetResourceByIdQuery",
    "get_get_resource_by_id_handler",
    "GetResourceDetailsHandler",
    "GetResourceDetailsQuery",
    "get_get_resource_details_handler",
    "ResolveCanonicalResourceHandler",
    "ResolveCanonicalResourceQuery",
    "get_resolve_canonical_resource_handler",
    "AssignResourceAliasHandler",
    "AssignResourceAliasCommand",
    "AssignResourceClassificationHandler",
    "AssignResourceClassificationCommand",
    "AssignResourceIdentifierHandler",
    "AssignResourceIdentifierCommand",
    "AssignResourceLabelHandler",
    "AssignResourceLabelCommand",
    "AssignResourceOwnershipHandler",
    "AssignResourceOwnershipCommand",
    "AssignResourceRelationshipHandler",
    "AssignResourceRelationshipCommand",
    "MergeResourceHandler",
    "MergeResourceCommand",
    "TransitionResourceStateHandler",
    "TransitionResourceStateCommand",
    "ResourceQueryService",
    "UnitOfWork",
    "SQLAlchemyUnitOfWork",
    "commit",
    "rollback",
    "flush",
}
FORBIDDEN_TRANSITION_ROUTE_NAMES = {
    "CreateResourceHandler",
    "CreateResourceCommand",
    "get_create_resource_handler",
    "GetResourceByIdHandler",
    "GetResourceByIdQuery",
    "get_get_resource_by_id_handler",
    "GetResourceDetailsHandler",
    "GetResourceDetailsQuery",
    "get_get_resource_details_handler",
    "GetResourceHistoryHandler",
    "GetResourceHistoryQuery",
    "get_get_resource_history_handler",
    "ResolveCanonicalResourceHandler",
    "ResolveCanonicalResourceQuery",
    "get_resolve_canonical_resource_handler",
    "AssignResourceAliasHandler",
    "AssignResourceAliasCommand",
    "AssignResourceClassificationHandler",
    "AssignResourceClassificationCommand",
    "AssignResourceIdentifierHandler",
    "AssignResourceIdentifierCommand",
    "AssignResourceLabelHandler",
    "AssignResourceLabelCommand",
    "AssignResourceOwnershipHandler",
    "AssignResourceOwnershipCommand",
    "AssignResourceRelationshipHandler",
    "AssignResourceRelationshipCommand",
    "MergeResourceHandler",
    "MergeResourceCommand",
    "ResourceQueryService",
    "UnitOfWork",
    "SQLAlchemyUnitOfWork",
    "commit",
    "rollback",
    "flush",
}
FORBIDDEN_IDENTIFIER_ROUTE_NAMES = {
    "CreateResourceHandler",
    "CreateResourceCommand",
    "get_create_resource_handler",
    "TransitionResourceStateHandler",
    "TransitionResourceStateCommand",
    "get_transition_resource_state_handler",
    "GetResourceByIdHandler",
    "GetResourceByIdQuery",
    "get_get_resource_by_id_handler",
    "GetResourceDetailsHandler",
    "GetResourceDetailsQuery",
    "get_get_resource_details_handler",
    "FindResourceByIdentifierHandler",
    "FindResourceByIdentifierQuery",
    "get_find_resource_by_identifier_handler",
    "GetResourceHistoryHandler",
    "GetResourceHistoryQuery",
    "get_get_resource_history_handler",
    "ResolveCanonicalResourceHandler",
    "ResolveCanonicalResourceQuery",
    "get_resolve_canonical_resource_handler",
    "AssignResourceAliasHandler",
    "AssignResourceAliasCommand",
    "get_assign_resource_alias_handler",
    "AssignResourceClassificationHandler",
    "AssignResourceClassificationCommand",
    "get_assign_resource_classification_handler",
    "AssignResourceLabelHandler",
    "AssignResourceLabelCommand",
    "get_assign_resource_label_handler",
    "AssignResourceOwnershipHandler",
    "AssignResourceOwnershipCommand",
    "get_assign_resource_ownership_handler",
    "AssignResourceRelationshipHandler",
    "AssignResourceRelationshipCommand",
    "get_assign_resource_relationship_handler",
    "MergeResourceHandler",
    "MergeResourceCommand",
    "get_merge_resource_handler",
    "ResourceQueryService",
    "UnitOfWork",
    "SQLAlchemyUnitOfWork",
    "commit",
    "rollback",
    "flush",
    "hashlib",
}
FORBIDDEN_IDENTIFIER_TRANSFORM_CALL_NAMES = {
    "blake2b",
    "casefold",
    "md5",
    "normalize",
    "sha256",
    "strip",
    "lower",
    "upper",
}
FORBIDDEN_CANONICAL_ROUTE_NAMES = {
    "GetResourceDetailsHandler",
    "GetResourceDetailsQuery",
    "get_get_resource_details_handler",
    "GetResourceHistoryHandler",
    "GetResourceHistoryQuery",
    "get_get_resource_history_handler",
    "GetResourceRelationshipsHandler",
    "GetResourceRelationshipsQuery",
    "get_get_resource_relationships_handler",
    "AssignResourceRelationshipHandler",
    "AssignResourceRelationshipCommand",
    "ResourceQueryService",
}
FORBIDDEN_LOOKUP_ROUTE_NAMES = {
    "ResolveCanonicalResourceHandler",
    "ResolveCanonicalResourceQuery",
    "get_resolve_canonical_resource_handler",
    "AssignResourceRelationshipHandler",
    "AssignResourceRelationshipCommand",
    "ResourceQueryService",
}
FORBIDDEN_HISTORY_ROUTE_NAMES = {
    "GetResourceDetailsHandler",
    "GetResourceDetailsQuery",
    "get_get_resource_details_handler",
    "ResolveCanonicalResourceHandler",
    "ResolveCanonicalResourceQuery",
    "get_resolve_canonical_resource_handler",
    "ResourceQueryService",
}
FORBIDDEN_RELATIONSHIPS_ROUTE_NAMES = {
    "GetResourceDetailsHandler",
    "GetResourceDetailsQuery",
    "get_get_resource_details_handler",
    "GetResourceHistoryHandler",
    "GetResourceHistoryQuery",
    "get_get_resource_history_handler",
    "ResolveCanonicalResourceHandler",
    "ResolveCanonicalResourceQuery",
    "get_resolve_canonical_resource_handler",
    "AssignResourceRelationshipHandler",
    "AssignResourceRelationshipCommand",
    "get_assign_resource_relationship_handler",
    "ResourceQueryService",
}
FORBIDDEN_GRAPH_TRAVERSAL_NAMES = {
    "ancestors",
    "breadth_first",
    "depth_first",
    "descendants",
    "graph_depth",
    "max_depth",
    "recursive",
    "shortest_path",
    "transitive",
    "traversal",
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


def _except_handler_names_for(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(_tree_for(path)):
        if isinstance(node, ast.ExceptHandler):
            if isinstance(node.type, ast.Name):
                names.add(node.type.id)
            elif isinstance(node.type, ast.Tuple):
                names.update(
                    item.id for item in node.type.elts if isinstance(item, ast.Name)
                )
    return names


def _function_def_for(path: Path, function_name: str) -> ast.FunctionDef:
    for node in ast.walk(_tree_for(path)):
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            return node
    raise AssertionError(f"{function_name} not found in {path}")


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


def test_resource_details_route_remains_isolated_from_canonical_resolution() -> None:
    source = inspect.getsource(resource_routes.get_resource_details)
    call_names = _call_names_for(resource_routes.get_resource_details)

    assert "GetResourceDetailsQuery" in call_names
    assert "resource_details_response" in call_names
    assert "ResolveCanonicalResourceQuery" not in source
    assert "get_resolve_canonical_resource_handler" not in source
    assert "ResolveCanonicalResourceHandler" not in source


def test_resource_create_route_is_explicit_handler_owned_transaction() -> None:
    resource_route_path = API_ROUTES_ROOT / "resources.py"
    create_function = _function_def_for(resource_route_path, "create_resource")
    source = inspect.getsource(resource_routes.create_resource)
    call_names = _call_names_for(resource_routes.create_resource)
    signature = inspect.signature(resource_routes.create_resource)
    hints = get_type_hints(resource_routes.create_resource)
    handler_parameter = signature.parameters["handler"]

    decorator = create_function.decorator_list[0]
    assert isinstance(decorator, ast.Call)
    assert isinstance(decorator.func, ast.Attribute)
    assert decorator.func.attr == "post"
    assert isinstance(decorator.args[0], ast.Constant)
    assert decorator.args[0].value == "/tenants/{tenant_id}/resources"
    assert any(
        keyword.arg == "response_model"
        and isinstance(keyword.value, ast.Name)
        and keyword.value.id == "ResourceCreatedResponse"
        for keyword in decorator.keywords
    )
    assert any(keyword.arg == "status_code" for keyword in decorator.keywords)
    assert list(signature.parameters) == ["tenant_id", "request", "handler"]
    assert hints["request"] is CreateResourceRequest
    assert hints["return"] is ResourceCreatedResponse
    assert isinstance(handler_parameter.default, Depends)
    assert handler_parameter.default.dependency is composition.get_create_resource_handler
    assert "CreateResourceCommand" in call_names
    assert "resource_created_response" in call_names
    assert "handle" in call_names
    assert "model_dump" not in source
    assert "**" not in source
    assert not any(name in source for name in FORBIDDEN_CREATE_ROUTE_NAMES)

    command_calls = [
        node
        for node in ast.walk(create_function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "CreateResourceCommand"
    ]
    assert len(command_calls) == 1
    assert [keyword.arg for keyword in command_calls[0].keywords] == [
        "tenant_id",
        "resource_type_id",
        "canonical_name",
        "display_name",
        "lifecycle_status_id",
        "criticality_id",
        "exposure_level_id",
        "source_priority",
        "confidence_score",
        "first_seen_at",
        "last_seen_at",
    ]
    assert command_calls[0].args == []


def test_resource_state_transition_route_is_explicit_handler_owned_transaction() -> None:
    resource_route_path = API_ROUTES_ROOT / "resources.py"
    transition_function = _function_def_for(
        resource_route_path,
        "transition_resource_state",
    )
    source = inspect.getsource(resource_routes.transition_resource_state)
    call_names = _call_names_for(resource_routes.transition_resource_state)
    signature = inspect.signature(resource_routes.transition_resource_state)
    hints = get_type_hints(resource_routes.transition_resource_state)
    handler_parameter = signature.parameters["handler"]

    decorator = transition_function.decorator_list[0]
    assert isinstance(decorator, ast.Call)
    assert isinstance(decorator.func, ast.Attribute)
    assert decorator.func.attr == "post"
    assert isinstance(decorator.args[0], ast.Constant)
    assert decorator.args[0].value == (
        "/tenants/{tenant_id}/resources/{resource_id}/state-transitions"
    )
    assert any(
        keyword.arg == "response_model"
        and isinstance(keyword.value, ast.Name)
        and keyword.value.id == "ResourceStateTransitionedResponse"
        for keyword in decorator.keywords
    )
    assert not any(keyword.arg == "status_code" for keyword in decorator.keywords)
    assert list(signature.parameters) == [
        "tenant_id",
        "resource_id",
        "request",
        "handler",
    ]
    assert hints["request"] is TransitionResourceStateRequest
    assert hints["return"] is ResourceStateTransitionedResponse
    assert isinstance(handler_parameter.default, Depends)
    assert (
        handler_parameter.default.dependency
        is composition.get_transition_resource_state_handler
    )
    assert "TransitionResourceStateCommand" in call_names
    assert "resource_state_transitioned_response" in call_names
    assert "handle" in call_names
    assert "model_dump" not in source
    assert "**" not in source
    assert not any(name in source for name in FORBIDDEN_TRANSITION_ROUTE_NAMES)

    command_calls = [
        node
        for node in ast.walk(transition_function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "TransitionResourceStateCommand"
    ]
    assert len(command_calls) == 1
    assert [keyword.arg for keyword in command_calls[0].keywords] == [
        "tenant_id",
        "resource_id",
        "lifecycle_status_id",
        "criticality_id",
        "exposure_level_id",
        "source_priority",
        "confidence_score",
        "transitioned_at",
        "source",
    ]
    assert command_calls[0].args == []


def test_resource_identifier_assignment_route_is_explicit_handler_owned_transaction() -> None:
    resource_route_path = API_ROUTES_ROOT / "resources.py"
    identifier_function = _function_def_for(
        resource_route_path,
        "assign_resource_identifier",
    )
    source = inspect.getsource(resource_routes.assign_resource_identifier)
    call_names = _call_names_for(resource_routes.assign_resource_identifier)
    signature = inspect.signature(resource_routes.assign_resource_identifier)
    hints = get_type_hints(resource_routes.assign_resource_identifier)
    handler_parameter = signature.parameters["handler"]

    decorator = identifier_function.decorator_list[0]
    assert isinstance(decorator, ast.Call)
    assert isinstance(decorator.func, ast.Attribute)
    assert decorator.func.attr == "post"
    assert isinstance(decorator.args[0], ast.Constant)
    assert decorator.args[0].value == (
        "/tenants/{tenant_id}/resources/{resource_id}/identifiers"
    )
    assert any(
        keyword.arg == "response_model"
        and isinstance(keyword.value, ast.Name)
        and keyword.value.id == "ResourceIdentifierAssignedResponse"
        for keyword in decorator.keywords
    )
    assert any(keyword.arg == "status_code" for keyword in decorator.keywords)
    assert list(signature.parameters) == [
        "tenant_id",
        "resource_id",
        "request",
        "handler",
    ]
    assert hints["request"] is AssignResourceIdentifierRequest
    assert hints["return"] is ResourceIdentifierAssignedResponse
    assert isinstance(handler_parameter.default, Depends)
    assert (
        handler_parameter.default.dependency
        is composition.get_assign_resource_identifier_handler
    )
    assert "AssignResourceIdentifierCommand" in call_names
    assert "resource_identifier_assigned_response" in call_names
    assert "handle" in call_names
    assert "model_dump" not in source
    assert "**" not in source
    assert not any(name in source for name in FORBIDDEN_IDENTIFIER_ROUTE_NAMES)
    assert FORBIDDEN_IDENTIFIER_TRANSFORM_CALL_NAMES.isdisjoint(call_names)

    command_calls = [
        node
        for node in ast.walk(identifier_function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "AssignResourceIdentifierCommand"
    ]
    assert len(command_calls) == 1
    assert [keyword.arg for keyword in command_calls[0].keywords] == [
        "tenant_id",
        "resource_id",
        "identifier_type_id",
        "original_value",
        "normalized_value",
        "value_hash",
        "namespace",
        "is_primary",
        "confidence_score",
        "valid_from",
    ]
    assert command_calls[0].args == []


def test_resource_history_route_is_isolated_from_details_and_canonical_use_cases() -> None:
    resource_route_path = API_ROUTES_ROOT / "resources.py"
    history_function = _function_def_for(resource_route_path, "get_resource_history")
    source = inspect.getsource(resource_routes.get_resource_history)
    call_names = _call_names_for(resource_routes.get_resource_history)
    signature = inspect.signature(resource_routes.get_resource_history)
    handler_parameter = signature.parameters["handler"]

    decorator = history_function.decorator_list[0]
    assert isinstance(decorator, ast.Call)
    assert isinstance(decorator.func, ast.Attribute)
    assert decorator.func.attr == "get"
    assert isinstance(decorator.args[0], ast.Constant)
    assert decorator.args[0].value == (
        "/tenants/{tenant_id}/resources/{resource_id}/history"
    )
    assert any(
        keyword.arg == "response_model"
        and isinstance(keyword.value, ast.Name)
        and keyword.value.id == "ResourceHistoryResponse"
        for keyword in decorator.keywords
    )
    assert list(signature.parameters) == ["tenant_id", "resource_id", "handler"]
    assert isinstance(handler_parameter.default, Depends)
    assert (
        handler_parameter.default.dependency
        is composition.get_get_resource_history_handler
    )
    assert "GetResourceHistoryQuery" in call_names
    assert "resource_history_response" in call_names
    assert "handle" in call_names
    assert not any(name in source for name in FORBIDDEN_HISTORY_ROUTE_NAMES)


def test_resource_relationships_route_is_current_read_only_and_one_hop() -> None:
    resource_route_path = API_ROUTES_ROOT / "resources.py"
    relationships_function = _function_def_for(
        resource_route_path,
        "get_resource_relationships",
    )
    source = inspect.getsource(resource_routes.get_resource_relationships)
    call_names = _call_names_for(resource_routes.get_resource_relationships)
    signature = inspect.signature(resource_routes.get_resource_relationships)
    handler_parameter = signature.parameters["handler"]

    decorator = relationships_function.decorator_list[0]
    assert isinstance(decorator, ast.Call)
    assert isinstance(decorator.func, ast.Attribute)
    assert decorator.func.attr == "get"
    assert isinstance(decorator.args[0], ast.Constant)
    assert decorator.args[0].value == (
        "/tenants/{tenant_id}/resources/{resource_id}/relationships"
    )
    assert any(
        keyword.arg == "response_model"
        and isinstance(keyword.value, ast.Name)
        and keyword.value.id == "ResourceRelationshipsResponse"
        for keyword in decorator.keywords
    )
    assert list(signature.parameters) == ["tenant_id", "resource_id", "handler"]
    assert isinstance(handler_parameter.default, Depends)
    assert (
        handler_parameter.default.dependency
        is composition.get_get_resource_relationships_handler
    )
    assert "GetResourceRelationshipsQuery" in call_names
    assert "resource_relationships_response" in call_names
    assert "handle" in call_names
    assert not any(name in source for name in FORBIDDEN_RELATIONSHIPS_ROUTE_NAMES)
    assert not any(name in source for name in FORBIDDEN_GRAPH_TRAVERSAL_NAMES)


def test_resource_canonical_route_is_explicit_and_does_not_enrich_or_write() -> None:
    resource_route_path = API_ROUTES_ROOT / "resources.py"
    canonical_function = _function_def_for(
        resource_route_path,
        "resolve_resource_canonical",
    )
    source = inspect.getsource(resource_routes.resolve_resource_canonical)
    call_names = _call_names_for(resource_routes.resolve_resource_canonical)
    signature = inspect.signature(resource_routes.resolve_resource_canonical)
    handler_parameter = signature.parameters["handler"]

    decorator = canonical_function.decorator_list[0]
    assert isinstance(decorator, ast.Call)
    assert isinstance(decorator.func, ast.Attribute)
    assert decorator.func.attr == "get"
    assert isinstance(decorator.args[0], ast.Constant)
    assert decorator.args[0].value == (
        "/tenants/{tenant_id}/resources/{resource_id}/canonical"
    )
    assert any(
        keyword.arg == "response_model"
        and isinstance(keyword.value, ast.Name)
        and keyword.value.id == "CanonicalResourceResolvedResponse"
        for keyword in decorator.keywords
    )
    assert list(signature.parameters) == ["tenant_id", "resource_id", "handler"]
    assert isinstance(handler_parameter.default, Depends)
    assert (
        handler_parameter.default.dependency
        is composition.get_resolve_canonical_resource_handler
    )
    assert "ResolveCanonicalResourceQuery" in call_names
    assert "canonical_resource_resolved_response" in call_names
    assert "handle" in call_names
    assert "RedirectResponse" not in source
    assert "HTTPException" not in source
    assert not any(name in source for name in FORBIDDEN_CANONICAL_ROUTE_NAMES)


def test_resource_lookup_routes_are_static_explicit_and_non_canonicalizing() -> None:
    route_path = API_ROUTES_ROOT / "resource_lookups.py"
    cases = [
        (
            resource_lookup_routes.get_resource_by_canonical_name,
            "get_resource_by_canonical_name",
            "/tenants/{tenant_id}/resource-lookups/canonical-name",
            "ResourceDetailsResponse",
            composition.get_get_resource_by_canonical_name_handler,
            "GetResourceByCanonicalNameQuery",
            "resource_details_response",
        ),
        (
            resource_lookup_routes.find_resource_by_identifier,
            "find_resource_by_identifier",
            "/tenants/{tenant_id}/resource-lookups/identifier",
            "ResourceIdentifierLookupResponse",
            composition.get_find_resource_by_identifier_handler,
            "FindResourceByIdentifierQuery",
            "resource_identifier_lookup_response",
        ),
        (
            resource_lookup_routes.find_resource_by_alias,
            "find_resource_by_alias",
            "/tenants/{tenant_id}/resource-lookups/alias",
            "ResourceAliasLookupResponse",
            composition.get_find_resource_by_alias_handler,
            "FindResourceByAliasQuery",
            "resource_alias_lookup_response",
        ),
    ]

    for function, function_name, path, response_model, provider, query, mapper in cases:
        function_def = _function_def_for(route_path, function_name)
        source = inspect.getsource(function)
        call_names = _call_names_for(function)
        signature = inspect.signature(function)
        handler_parameter = signature.parameters["handler"]
        decorator = function_def.decorator_list[0]

        assert isinstance(decorator, ast.Call)
        assert isinstance(decorator.func, ast.Attribute)
        assert decorator.func.attr == "get"
        assert isinstance(decorator.args[0], ast.Constant)
        assert decorator.args[0].value == path
        assert any(
            keyword.arg == "response_model"
            and isinstance(keyword.value, ast.Name)
            and keyword.value.id == response_model
            for keyword in decorator.keywords
        )
        assert isinstance(handler_parameter.default, Depends)
        assert handler_parameter.default.dependency is provider
        assert query in call_names
        assert mapper in call_names
        assert "handle" in call_names
        assert not any(name in source for name in FORBIDDEN_LOOKUP_ROUTE_NAMES)


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


def test_api_error_module_does_not_import_persistence_or_sqlalchemy() -> None:
    imports = _imports_for(API_ERRORS_PATH)

    assert not any(imported.split(".", 1)[0] == "sqlalchemy" for imported in imports)
    assert not any(imported.startswith("app.persistence") for imported in imports)
    assert not any(imported.startswith("app.db") for imported in imports)


def test_api_error_schemas_are_api_owned_and_sanitized() -> None:
    assert issubclass(ApiErrorDetail, ApiSchema)
    assert issubclass(ApiError, ApiSchema)
    assert issubclass(ApiErrorResponse, ApiSchema)
    assert set(ApiErrorDetail.model_fields) == {"field", "message"}
    assert set(ApiError.model_fields) == {"code", "message", "details"}
    assert set(ApiErrorResponse.model_fields) == {"error"}
    assert FORBIDDEN_PUBLIC_ERROR_FIELD_NAMES.isdisjoint(ApiError.model_fields)
    assert FORBIDDEN_PUBLIC_ERROR_FIELD_NAMES.isdisjoint(ApiErrorDetail.model_fields)
    assert FORBIDDEN_PUBLIC_ERROR_FIELD_NAMES.isdisjoint(ApiErrorResponse.model_fields)


def test_routes_do_not_catch_application_errors_locally() -> None:
    for path in _python_files(API_ROUTES_ROOT):
        caught_names = _except_handler_names_for(path)

        assert "ApplicationError" not in caught_names, path


def test_application_error_handlers_are_centrally_registered_from_bootstrap() -> None:
    imports = _imports_for(MAIN_PATH)

    assert "app.api.errors" in imports
    assert ApplicationError in app.exception_handlers
    assert not any(
        "exception_handler" in _call_names_for(getattr(composition, provider_name))
        for provider_name in RESOURCE_HANDLER_PROVIDERS
    )


def test_concurrent_modification_error_has_specific_mapping() -> None:
    conflict = ConflictError("conflict")
    concurrent = ConcurrentModificationError("concurrent")

    assert application_error_status_code(conflict) == 409
    assert application_error_status_code(concurrent) == 409
    assert api_error_response_for(conflict).error.code == "conflict"
    assert api_error_response_for(concurrent).error.code == "concurrent_modification"


def test_tenant_boundary_policy_is_not_more_revealing_than_not_found() -> None:
    from app.application.errors import EntityNotFoundError, TenantBoundaryError

    not_found = api_error_response_for(EntityNotFoundError("missing"))
    tenant_boundary = api_error_response_for(
        TenantBoundaryError("other tenant exists")
    )

    assert tenant_boundary == not_found


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


def test_api_v1_router_contains_only_expected_resource_operations() -> None:
    route_paths = {route.path for route in app.routes}
    api_v1_operations = {
        (method, route.path)
        for route in api_v1_router.routes
        for method in route.methods
        if method in {"GET", "POST", "PUT", "PATCH", "DELETE"}
    }
    resource_operations = [
        route
        for route in app.routes
        if getattr(route, "path", "").startswith("/api/v1/tenants/")
    ]

    assert api_v1_router.prefix == "/api/v1"
    assert api_v1_operations == {
        ("GET", "/api/v1/tenants/{tenant_id}/resource-lookups/alias"),
        ("GET", "/api/v1/tenants/{tenant_id}/resource-lookups/canonical-name"),
        ("GET", "/api/v1/tenants/{tenant_id}/resource-lookups/identifier"),
        ("GET", "/api/v1/tenants/{tenant_id}/resources"),
        ("POST", "/api/v1/tenants/{tenant_id}/resources"),
        ("GET", "/api/v1/tenants/{tenant_id}/resources/{resource_id}"),
        ("GET", "/api/v1/tenants/{tenant_id}/resources/{resource_id}/canonical"),
        ("GET", "/api/v1/tenants/{tenant_id}/resources/{resource_id}/history"),
        (
            "GET",
            "/api/v1/tenants/{tenant_id}/resources/{resource_id}/relationships",
        ),
        (
            "POST",
            "/api/v1/tenants/{tenant_id}/resources/{resource_id}/state-transitions",
        ),
        (
            "POST",
            "/api/v1/tenants/{tenant_id}/resources/{resource_id}/identifiers",
        ),
    }
    assert "/api/v1/resources" not in route_paths
    assert [(sorted(route.methods), route.path) for route in resource_operations] == [
        (
            ["GET"],
            "/api/v1/tenants/{tenant_id}/resource-lookups/canonical-name",
        ),
        (["GET"], "/api/v1/tenants/{tenant_id}/resource-lookups/identifier"),
        (["GET"], "/api/v1/tenants/{tenant_id}/resource-lookups/alias"),
        (["GET"], "/api/v1/tenants/{tenant_id}/resources"),
        (["POST"], "/api/v1/tenants/{tenant_id}/resources"),
        (["GET"], "/api/v1/tenants/{tenant_id}/resources/{resource_id}"),
        (
            ["POST"],
            "/api/v1/tenants/{tenant_id}/resources/{resource_id}/state-transitions",
        ),
        (
            ["POST"],
            "/api/v1/tenants/{tenant_id}/resources/{resource_id}/identifiers",
        ),
        (
            ["GET"],
            "/api/v1/tenants/{tenant_id}/resources/{resource_id}/history",
        ),
        (
            ["GET"],
            "/api/v1/tenants/{tenant_id}/resources/{resource_id}/relationships",
        ),
        (
            ["GET"],
            "/api/v1/tenants/{tenant_id}/resources/{resource_id}/canonical",
        ),
    ]
    assert [route.path for route in resource_operations] == [
        "/api/v1/tenants/{tenant_id}/resource-lookups/canonical-name",
        "/api/v1/tenants/{tenant_id}/resource-lookups/identifier",
        "/api/v1/tenants/{tenant_id}/resource-lookups/alias",
        "/api/v1/tenants/{tenant_id}/resources",
        "/api/v1/tenants/{tenant_id}/resources",
        "/api/v1/tenants/{tenant_id}/resources/{resource_id}",
        "/api/v1/tenants/{tenant_id}/resources/{resource_id}/state-transitions",
        "/api/v1/tenants/{tenant_id}/resources/{resource_id}/identifiers",
        "/api/v1/tenants/{tenant_id}/resources/{resource_id}/history",
        "/api/v1/tenants/{tenant_id}/resources/{resource_id}/relationships",
        "/api/v1/tenants/{tenant_id}/resources/{resource_id}/canonical",
    ]
    assert resource_operations[0].response_model is ResourceDetailsResponse
    assert resource_operations[1].response_model is ResourceIdentifierLookupResponse
    assert resource_operations[2].response_model is ResourceAliasLookupResponse
    assert resource_operations[3].response_model is ResourcePageResponse
    assert resource_operations[4].response_model is ResourceCreatedResponse
    assert resource_operations[5].response_model is ResourceDetailsResponse
    assert resource_operations[6].response_model is ResourceStateTransitionedResponse
    assert resource_operations[7].response_model is ResourceIdentifierAssignedResponse
    assert resource_operations[8].response_model is ResourceHistoryResponse
    assert resource_operations[9].response_model is ResourceRelationshipsResponse
    assert resource_operations[10].response_model is CanonicalResourceResolvedResponse
