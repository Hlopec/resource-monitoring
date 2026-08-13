from __future__ import annotations

import ast
import inspect
from collections.abc import Sequence
from pathlib import Path
from typing import get_args, get_origin, get_type_hints
from uuid import UUID

from app.application.errors import (
    ApplicationError,
    ConcurrentModificationError,
    ConflictError,
    EntityNotFoundError,
    PersistenceError,
    TenantBoundaryError,
    ValidationError,
    ValidationFailure,
)
from app.application.handlers import (
    AssignResourceAliasHandler,
    AssignResourceClassificationHandler,
    AssignResourceIdentifierHandler,
    AssignResourceLabelHandler,
    AssignResourceOwnershipHandler,
    AssignResourceRelationshipHandler,
    CommandHandler,
    CreateResourceHandler,
    EnsureResourceExistsHandler,
    GetResourceByCanonicalNameHandler,
    GetResourceByIdHandler,
    GetResourceDetailsHandler,
    ListResourcesHandler,
    MergeResourceHandler,
    QueryHandler,
    ResolveCanonicalResourceHandler,
    TransitionResourceStateHandler,
)
from app.application.ports import UnitOfWorkFactory
from app.application.ports.catalogs import (
    ClassificationValueRepository,
    ManagedCatalogRepository,
)
from app.application.ports.labels import LabelRepository
from app.application.ports.lineage import (
    ResourceAliasRepository,
    ResourceMergeRepository,
)
from app.application.ports.organizations import OrganizationRepository
from app.application.ports.repositories import (
    GlobalCatalogLookupRepository,
    TenantScopedLookupRepository,
)
from app.application.ports.resources import ResourceRepository
from app.application.ports.resource_queries import (
    ResourceQueryPage,
    ResourceQueryService,
    ResourceSummaryProjection,
)
from app.application.ports.temporal import (
    ResourceClassificationRepository,
    ResourceIdentifierRepository,
    ResourceLabelRepository,
    ResourceOwnershipRepository,
    ResourceRelationshipRepository,
    ResourceStateRepository,
)
from app.application.ports.tenants import TenantRepository
from app.application.ports.unit_of_work import UnitOfWork
from app.models import (
    ClassificationType,
    ClassificationValue,
    Criticality,
    ExposureLevel,
    IdentifierType,
    Label,
    LifecycleStatus,
    Organization,
    OwnershipRole,
    RelationshipType,
    Resource,
    ResourceAlias,
    ResourceClassification,
    ResourceIdentifier,
    ResourceLabel,
    ResourceMerge,
    ResourceOwnership,
    ResourceRelationship,
    ResourceState,
    ResourceType,
    Tenant,
)
from app.persistence.sqlalchemy.repositories import (
    SQLAlchemyClassificationValueRepository,
    SQLAlchemyLabelRepository,
    SQLAlchemyManagedCatalogRepository,
    SQLAlchemyOrganizationRepository,
    SQLAlchemyResourceAliasRepository,
    SQLAlchemyResourceClassificationRepository,
    SQLAlchemyResourceIdentifierRepository,
    SQLAlchemyResourceLabelRepository,
    SQLAlchemyResourceMergeRepository,
    SQLAlchemyResourceOwnershipRepository,
    SQLAlchemyResourceRelationshipRepository,
    SQLAlchemyResourceRepository,
    SQLAlchemyResourceStateRepository,
    SQLAlchemyTenantRepository,
)
from app.persistence.sqlalchemy.queries import SQLAlchemyResourceQueryService

ROOT = Path(__file__).resolve().parents[1]
APPLICATION_ROOT = ROOT / "app" / "application"
PORTS_ROOT = APPLICATION_ROOT / "ports"
SQLALCHEMY_PERSISTENCE_ROOT = ROOT / "app" / "persistence" / "sqlalchemy"
SQLALCHEMY_TRANSLATOR_PATH = SQLALCHEMY_PERSISTENCE_ROOT / "errors.py"

SQLALCHEMY_IMPORT_ROOTS = {"sqlalchemy"}
FORBIDDEN_APPLICATION_IMPORT_ROOTS = {"fastapi", "pydantic", "sqlalchemy"}
FORBIDDEN_PERSISTENCE_IMPORT_ROOTS = {"fastapi", "pydantic"}
FORBIDDEN_APPLICATION_MODULE_PREFIXES = {"app.persistence"}
SQLALCHEMY_TYPE_NAMES = {
    "InstrumentedAttribute",
    "Query",
    "Result",
    "Row",
    "Select",
    "Session",
}
FORBIDDEN_REPOSITORY_METHODS = {"commit", "rollback", "filter", "query", "execute"}
FORBIDDEN_RESOURCE_REPOSITORY_LIST_METHODS = {
    "filter_by_kwargs",
    "list",
    "paginate",
    "query",
    "search",
}
FORBIDDEN_REPLACEMENT_METHODS = {
    "close_current",
    "close_current_and_add",
    "delete_history",
    "merge_resources",
    "move_alias",
    "remove",
    "replace_current",
    "replace_alias",
    "resolve",
    "rewrite_lineage",
    "rewrite_history",
    "unmerge_resources",
    "upsert_current",
}
FORBIDDEN_FRAMEWORK_NAMES = {
    "BaseResourceHandler",
    "CommandBus",
    "CommandDispatcher",
    "GenericAssignmentHandler",
    "GenericTemporalService",
    "GraphService",
    "HandlerRegistry",
    "Mediator",
    "RepositoryRegistry",
    "ServiceLocator",
}
FORBIDDEN_READ_ONLY_CATALOG_METHODS = FORBIDDEN_REPOSITORY_METHODS | {
    "add",
    "delete",
    "remove",
    "update",
    "create",
    "save",
    "flush",
}
CONCRETE_REPOSITORIES = (
    SQLAlchemyTenantRepository,
    SQLAlchemyOrganizationRepository,
    SQLAlchemyLabelRepository,
    SQLAlchemyResourceRepository,
    SQLAlchemyManagedCatalogRepository,
    SQLAlchemyClassificationValueRepository,
    SQLAlchemyResourceIdentifierRepository,
    SQLAlchemyResourceOwnershipRepository,
    SQLAlchemyResourceRelationshipRepository,
    SQLAlchemyResourceClassificationRepository,
    SQLAlchemyResourceLabelRepository,
    SQLAlchemyResourceStateRepository,
    SQLAlchemyResourceAliasRepository,
    SQLAlchemyResourceMergeRepository,
)
TENANT_SCOPED_REPOSITORIES = (
    OrganizationRepository,
    ResourceRepository,
    LabelRepository,
    ResourceIdentifierRepository,
    ResourceOwnershipRepository,
    ResourceRelationshipRepository,
    ResourceClassificationRepository,
    ResourceLabelRepository,
    ResourceStateRepository,
    ResourceAliasRepository,
    ResourceMergeRepository,
)
GLOBAL_CATALOG_REPOSITORIES = (
    ManagedCatalogRepository,
    ClassificationValueRepository,
)
ALL_REPOSITORY_PROTOCOLS = (
    TenantRepository,
    OrganizationRepository,
    ResourceRepository,
    LabelRepository,
    ManagedCatalogRepository,
    ClassificationValueRepository,
    ResourceIdentifierRepository,
    ResourceOwnershipRepository,
    ResourceRelationshipRepository,
    ResourceClassificationRepository,
    ResourceLabelRepository,
    ResourceStateRepository,
    ResourceAliasRepository,
    ResourceMergeRepository,
    ResourceQueryService,
)
READ_HANDLER_TYPES = (
    GetResourceByCanonicalNameHandler,
    GetResourceByIdHandler,
    GetResourceDetailsHandler,
    ListResourcesHandler,
    ResolveCanonicalResourceHandler,
)
WRITE_HANDLER_TYPES = (
    AssignResourceAliasHandler,
    AssignResourceClassificationHandler,
    AssignResourceIdentifierHandler,
    AssignResourceLabelHandler,
    AssignResourceOwnershipHandler,
    AssignResourceRelationshipHandler,
    CreateResourceHandler,
    EnsureResourceExistsHandler,
    MergeResourceHandler,
    TransitionResourceStateHandler,
)


def _python_files(path: Path) -> list[Path]:
    return sorted(candidate for candidate in path.rglob("*.py") if candidate.is_file())


def _imports_for(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def _public_methods(protocol: type) -> list[tuple[str, object]]:
    return [
        (name, member)
        for name, member in inspect.getmembers(protocol, inspect.isfunction)
        if not name.startswith("_")
    ]


def _function_names_for(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}


def _called_attribute_names_for(handler_type: type) -> set[str]:
    source = inspect.getsource(handler_type)
    tree = ast.parse(source)
    return {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }


def _attribute_call_count(handler_type: type, attribute_name: str) -> int:
    source = inspect.getsource(handler_type)
    tree = ast.parse(source)
    return sum(
        1
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == attribute_name
    )


def _contains_optional_none(annotation: object) -> bool:
    return type(None) in get_args(annotation)


def _contains_sqlalchemy_type(annotation: object) -> bool:
    if getattr(annotation, "__name__", None) in SQLALCHEMY_TYPE_NAMES:
        return True
    if annotation.__class__.__name__ in SQLALCHEMY_TYPE_NAMES:
        return True
    return any(_contains_sqlalchemy_type(arg) for arg in get_args(annotation))


def test_application_modules_do_not_import_sqlalchemy() -> None:
    for path in _python_files(APPLICATION_ROOT):
        imports = _imports_for(path)
        assert not any(
            imported.split(".", 1)[0] in SQLALCHEMY_IMPORT_ROOTS for imported in imports
        ), path


def test_application_modules_do_not_import_transport_or_persistence_frameworks() -> None:
    for path in _python_files(APPLICATION_ROOT):
        imports = _imports_for(path)
        assert not any(
            imported.split(".", 1)[0] in FORBIDDEN_APPLICATION_IMPORT_ROOTS
            for imported in imports
        ), path
        assert not any(
            imported.startswith(tuple(FORBIDDEN_APPLICATION_MODULE_PREFIXES))
            for imported in imports
        ), path


def test_sqlalchemy_persistence_does_not_import_api_or_schema_frameworks() -> None:
    for path in _python_files(SQLALCHEMY_PERSISTENCE_ROOT):
        imports = _imports_for(path)
        assert not any(
            imported.split(".", 1)[0] in FORBIDDEN_PERSISTENCE_IMPORT_ROOTS
            for imported in imports
        ), path


def test_persistence_error_translator_stays_in_sqlalchemy_boundary() -> None:
    assert SQLALCHEMY_TRANSLATOR_PATH.exists()
    imports = _imports_for(SQLALCHEMY_TRANSLATOR_PATH)

    assert SQLALCHEMY_TRANSLATOR_PATH.parent == SQLALCHEMY_PERSISTENCE_ROOT
    assert "sqlalchemy.exc" in imports
    assert "sqlalchemy.orm.exc" in imports
    assert not any(imported.startswith("app.application.handlers") for imported in imports)
    assert not any(
        imported.split(".", 1)[0] in FORBIDDEN_PERSISTENCE_IMPORT_ROOTS
        for imported in imports
    )


def test_sqlalchemy_persistence_does_not_introduce_retry_framework() -> None:
    retry_import_roots = {"retry", "tenacity", "backoff"}
    retry_function_names = {"retry", "retry_on_exception", "with_retry"}
    for path in _python_files(SQLALCHEMY_PERSISTENCE_ROOT):
        imports = _imports_for(path)
        assert retry_import_roots.isdisjoint(
            imported.split(".", 1)[0].lower() for imported in imports
        ), path
        assert retry_function_names.isdisjoint(_function_names_for(path)), path


def test_ports_do_not_import_concrete_persistence_implementations() -> None:
    for path in _python_files(PORTS_ROOT):
        imports = _imports_for(path)
        assert not any(imported.startswith("app.persistence") for imported in imports), path


def test_application_packages_are_importable() -> None:
    import app.application
    import app.application.commands
    import app.application.handlers
    import app.application.ports
    import app.application.queries
    import app.application.results
    import app.persistence
    import app.persistence.sqlalchemy

    assert app.application.ApplicationError is ApplicationError
    assert app.application.ValidationError is ValidationError
    assert app.application.ports.UnitOfWork is UnitOfWork
    assert app.application.ports.UnitOfWorkFactory is UnitOfWorkFactory
    assert app.application.handlers.CommandHandler is CommandHandler
    assert app.application.handlers.QueryHandler is QueryHandler
    assert app.application.ports.ResourceRepository is ResourceRepository
    assert app.application.ports.ManagedCatalogRepository is ManagedCatalogRepository
    assert app.persistence.__doc__
    assert app.persistence.sqlalchemy.__doc__


def test_application_error_hierarchy_is_explicit() -> None:
    assert issubclass(EntityNotFoundError, ApplicationError)
    assert issubclass(ConflictError, ApplicationError)
    assert issubclass(ValidationError, ApplicationError)
    assert issubclass(ConcurrentModificationError, ConflictError)
    assert issubclass(TenantBoundaryError, ApplicationError)
    assert issubclass(PersistenceError, ApplicationError)
    failure = ValidationFailure("field", "message")
    error = ValidationError("Invalid input", failures=(failure,))
    assert error.failures == (failure,)
    conflict = ConflictError(
        "Conflict",
        entity_type="ResourceState",
        conflict_field="current",
        conflict_value=None,
        constraint="uq_resource_state_current",
    )
    assert conflict.constraint == "uq_resource_state_current"
    assert not hasattr(conflict, "sql")
    assert not hasattr(conflict, "driver_error")


def test_unit_of_work_protocol_declares_lifecycle_methods() -> None:
    expected_methods = {"__enter__", "__exit__", "commit", "rollback"}
    assert expected_methods.issubset(UnitOfWork.__dict__)


def test_unit_of_work_protocol_exposes_technology_neutral_repositories() -> None:
    hints = get_type_hints(UnitOfWork)

    assert hints["tenants"] is TenantRepository
    assert hints["organizations"] is OrganizationRepository
    assert hints["labels"] is LabelRepository
    assert hints["resources"] is ResourceRepository
    assert hints["resource_types"] == ManagedCatalogRepository[ResourceType]
    assert hints["identifier_types"] == ManagedCatalogRepository[IdentifierType]
    assert hints["relationship_types"] == ManagedCatalogRepository[RelationshipType]
    assert hints["ownership_roles"] == ManagedCatalogRepository[OwnershipRole]
    assert hints["classification_types"] == ManagedCatalogRepository[ClassificationType]
    assert hints["classification_values"] is ClassificationValueRepository
    assert hints["lifecycle_statuses"] == ManagedCatalogRepository[LifecycleStatus]
    assert hints["criticalities"] == ManagedCatalogRepository[Criticality]
    assert hints["exposure_levels"] == ManagedCatalogRepository[ExposureLevel]
    assert hints["resource_identifiers"] is ResourceIdentifierRepository
    assert hints["resource_ownerships"] is ResourceOwnershipRepository
    assert hints["resource_relationships"] is ResourceRelationshipRepository
    assert hints["resource_classifications"] is ResourceClassificationRepository
    assert hints["resource_labels"] is ResourceLabelRepository
    assert hints["resource_states"] is ResourceStateRepository
    assert hints["resource_aliases"] is ResourceAliasRepository
    assert hints["resource_merges"] is ResourceMergeRepository
    assert hints["resource_queries"] is ResourceQueryService


def test_unit_of_work_factory_protocol_returns_unit_of_work() -> None:
    hints = get_type_hints(UnitOfWorkFactory.__call__)

    assert hints["return"] is UnitOfWork


def test_repository_protocols_do_not_expose_optional_tenant_scope() -> None:
    for protocol in (TenantScopedLookupRepository, *TENANT_SCOPED_REPOSITORIES):
        for name, member in inspect.getmembers(protocol, inspect.isfunction):
            if name.startswith("_") or name == "add":
                continue
            hints = get_type_hints(member)
            assert hints["tenant_id"] is not None
            assert hints["tenant_id"] is UUID
            assert not _contains_optional_none(hints["tenant_id"])


def test_global_catalog_repository_protocols_do_not_require_tenant_scope() -> None:
    for protocol in GLOBAL_CATALOG_REPOSITORIES:
        for name, member in _public_methods(protocol):
            hints = get_type_hints(member)
            assert "tenant_id" not in hints, (protocol, name)


def test_repository_contracts_do_not_expose_transaction_or_generic_query_methods() -> None:
    for protocol in ALL_REPOSITORY_PROTOCOLS:
        public_method_names = {name for name, _ in _public_methods(protocol)}
        assert FORBIDDEN_REPOSITORY_METHODS.isdisjoint(public_method_names), protocol
        assert FORBIDDEN_REPLACEMENT_METHODS.isdisjoint(public_method_names), protocol

        for name, member in _public_methods(protocol):
            signature = inspect.signature(member)
            assert not any(
                parameter.kind is inspect.Parameter.VAR_KEYWORD
                for parameter in signature.parameters.values()
            ), (protocol, name)


def test_resource_repository_remains_transactional_not_collection_query_service() -> None:
    public_method_names = {name for name, _ in _public_methods(ResourceRepository)}

    assert FORBIDDEN_RESOURCE_REPOSITORY_LIST_METHODS.isdisjoint(public_method_names)


def test_concrete_repositories_stay_in_persistence_and_do_not_expose_transactions() -> None:
    for repository_type in CONCRETE_REPOSITORIES:
        assert repository_type.__module__.startswith("app.persistence.sqlalchemy")
        public_method_names = {name for name, _ in _public_methods(repository_type)}
        assert {"commit", "rollback"}.isdisjoint(public_method_names)


def test_concrete_catalog_adapters_keep_read_only_public_surface() -> None:
    for repository_type in (
        SQLAlchemyManagedCatalogRepository,
        SQLAlchemyClassificationValueRepository,
    ):
        assert repository_type.__module__.startswith("app.persistence.sqlalchemy")
        public_method_names = {name for name, _ in _public_methods(repository_type)}
        assert FORBIDDEN_READ_ONLY_CATALOG_METHODS.isdisjoint(public_method_names)


def test_application_facing_ports_do_not_reference_sqlalchemy_types() -> None:
    for protocol in (
        TenantScopedLookupRepository,
        GlobalCatalogLookupRepository,
        UnitOfWork,
        UnitOfWorkFactory,
        *ALL_REPOSITORY_PROTOCOLS,
    ):
        for name, member in inspect.getmembers(protocol, inspect.isfunction):
            if name.startswith("_") and name not in {"__enter__", "__exit__"}:
                continue
            hints = get_type_hints(member)
            assert not any(_contains_sqlalchemy_type(value) for value in hints.values()), (
                protocol,
                name,
            )


def test_handler_protocols_define_direct_handle_contracts() -> None:
    command_hints = get_type_hints(CommandHandler.handle)
    query_hints = get_type_hints(QueryHandler.handle)

    assert list(inspect.signature(CommandHandler.handle).parameters) == [
        "self",
        "command",
    ]
    assert list(inspect.signature(QueryHandler.handle).parameters) == [
        "self",
        "query",
    ]
    assert "return" in command_hints
    assert "return" in query_hints


def test_reference_handlers_depend_on_unit_of_work_factory_only() -> None:
    for handler_type in (*READ_HANDLER_TYPES, *WRITE_HANDLER_TYPES):
        hints = get_type_hints(handler_type.__init__)
        assert hints["uow_factory"] is UnitOfWorkFactory
        assert list(inspect.signature(handler_type.__init__).parameters) == [
            "self",
            "uow_factory",
        ]


def test_read_handlers_never_commit_or_mutate() -> None:
    for handler_type in READ_HANDLER_TYPES:
        called_methods = _called_attribute_names_for(handler_type)
        source = inspect.getsource(handler_type)
        assert "commit" not in called_methods, handler_type
        assert "rollback" not in called_methods, handler_type
        assert "get_for_update" not in called_methods, handler_type
        assert ".add(" not in source.replace("visited.add(", ""), handler_type
        assert "flush" not in called_methods, handler_type


def test_list_resources_handler_uses_query_service_boundary_only() -> None:
    called_methods = _called_attribute_names_for(ListResourcesHandler)

    assert "list_resources" in called_methods
    assert "commit" not in called_methods
    assert "rollback" not in called_methods
    assert "get_for_update" not in called_methods
    assert "add" not in called_methods
    assert "flush" not in called_methods


def test_write_handlers_commit_once_and_do_not_rollback() -> None:
    for handler_type in WRITE_HANDLER_TYPES:
        assert _attribute_call_count(handler_type, "commit") == 1, handler_type
        assert _attribute_call_count(handler_type, "rollback") == 0, handler_type


def test_canonical_resolution_handler_is_read_only() -> None:
    source = inspect.getsource(ResolveCanonicalResourceHandler)
    tree = ast.parse(source)
    called_methods = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }

    assert "commit" not in called_methods
    assert "get_for_update" not in called_methods
    assert ".add(" not in source.replace("visited.add(", "")
    assert "path_compression" not in source
    assert "canonical_resource_id =" not in source


def test_merge_handler_remains_lineage_only() -> None:
    source = inspect.getsource(MergeResourceHandler)
    assert "ResourceMerge(" in source
    assert "ResourceAlias(" not in source
    assert "ResourceIdentifier(" not in source
    assert "ResourceOwnership(" not in source
    assert "ResourceClassification(" not in source
    assert "ResourceLabel(" not in source
    assert "ResourceRelationship(" not in source
    assert "current_resource_id" not in source


def test_no_hidden_application_frameworks_are_introduced() -> None:
    for path in _python_files(APPLICATION_ROOT):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        defined_names = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef | ast.FunctionDef)
        }
        assert FORBIDDEN_FRAMEWORK_NAMES.isdisjoint(defined_names), path


def test_sqlalchemy_resource_query_service_lives_below_persistence_boundary() -> None:
    assert SQLAlchemyResourceQueryService.__module__.startswith(
        "app.persistence.sqlalchemy.queries"
    )
    public_method_names = {
        name for name, _ in _public_methods(SQLAlchemyResourceQueryService)
    }
    assert {"commit", "rollback", "get_for_update", "add", "flush"}.isdisjoint(
        public_method_names
    )


def test_multi_resource_handlers_share_deterministic_lock_order_helper() -> None:
    relationship_source = inspect.getsource(AssignResourceRelationshipHandler)
    merge_source = inspect.getsource(MergeResourceHandler)

    assert "_ordered_resource_ids(" in relationship_source
    assert "_ordered_resource_ids(" in merge_source


def test_collection_repository_methods_return_sequence() -> None:
    collection_methods = {
        (OrganizationRepository, "list_children"),
        (LabelRepository, "list_active"),
        (ManagedCatalogRepository, "list_active"),
        (ClassificationValueRepository, "list_active_for_type"),
        (ResourceIdentifierRepository, "get_current_for_resource"),
        (ResourceOwnershipRepository, "get_current_for_resource"),
        (ResourceRelationshipRepository, "list_current_outgoing"),
        (ResourceRelationshipRepository, "list_current_incoming"),
        (ResourceClassificationRepository, "get_current_for_resource"),
        (ResourceLabelRepository, "get_current_for_resource"),
        (ResourceStateRepository, "list_history"),
        (ResourceAliasRepository, "list_for_resource"),
        (ResourceMergeRepository, "list_incoming_merges"),
    }

    for protocol, method_name in collection_methods:
        hints = get_type_hints(getattr(protocol, method_name))
        assert get_origin(hints["return"]) is Sequence, (protocol, method_name)


def test_repository_protocols_define_expected_signatures() -> None:
    expected_returns = {
        (TenantRepository, "get_by_id"): Tenant | None,
        (TenantRepository, "get_by_slug"): Tenant | None,
        (ClassificationValueRepository, "get_by_id"): ClassificationValue | None,
        (
            ClassificationValueRepository,
            "get_by_type_and_code",
        ): ClassificationValue | None,
        (OrganizationRepository, "get_by_id"): Organization | None,
        (ResourceRepository, "get_by_id"): Resource | None,
        (ResourceRepository, "get_for_update"): Resource | None,
        (LabelRepository, "get_by_id"): Label | None,
        (ResourceIdentifierRepository, "find_current_by_value"): ResourceIdentifier | None,
        (ResourceIdentifierRepository, "get_current_primary"): ResourceIdentifier | None,
        (ResourceOwnershipRepository, "find_current"): ResourceOwnership | None,
        (ResourceOwnershipRepository, "get_current_primary"): ResourceOwnership | None,
        (ResourceRelationshipRepository, "find_current"): ResourceRelationship | None,
        (ResourceClassificationRepository, "find_current"): ResourceClassification
        | None,
        (ResourceClassificationRepository, "get_current_primary"): ResourceClassification | None,
        (ResourceLabelRepository, "find_current"): ResourceLabel | None,
        (ResourceStateRepository, "get_current"): ResourceState | None,
        (ResourceAliasRepository, "find_resource_by_alias"): Resource | None,
        (ResourceMergeRepository, "get_outgoing_merge"): ResourceMerge | None,
    }

    for (protocol, method_name), expected_return in expected_returns.items():
        hints = get_type_hints(getattr(protocol, method_name))
        assert hints["return"] == expected_return

    query_hints = get_type_hints(ResourceQueryService.list_resources)
    assert query_hints["tenant_id"] is UUID
    assert query_hints["return"] is ResourceQueryPage

    mutation_methods = (
        (TenantRepository, "add", Tenant),
        (OrganizationRepository, "add", Organization),
        (ResourceRepository, "add", Resource),
        (LabelRepository, "add", Label),
        (ResourceIdentifierRepository, "add", ResourceIdentifier),
        (ResourceOwnershipRepository, "add", ResourceOwnership),
        (ResourceRelationshipRepository, "add", ResourceRelationship),
        (ResourceClassificationRepository, "add", ResourceClassification),
        (ResourceLabelRepository, "add", ResourceLabel),
        (ResourceStateRepository, "add", ResourceState),
        (ResourceAliasRepository, "add", ResourceAlias),
        (ResourceMergeRepository, "add", ResourceMerge),
    )

    for protocol, method_name, entity_type in mutation_methods:
        hints = get_type_hints(getattr(protocol, method_name))
        parameter_names = [
            name
            for name in inspect.signature(getattr(protocol, method_name)).parameters
            if name != "self"
        ]
        assert hints[parameter_names[0]] is entity_type
        assert hints["return"] is type(None)
