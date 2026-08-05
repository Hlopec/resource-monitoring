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
)
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

ROOT = Path(__file__).resolve().parents[1]
APPLICATION_ROOT = ROOT / "app" / "application"
PORTS_ROOT = APPLICATION_ROOT / "ports"
SQLALCHEMY_PERSISTENCE_ROOT = ROOT / "app" / "persistence" / "sqlalchemy"

SQLALCHEMY_IMPORT_ROOTS = {"sqlalchemy"}
FORBIDDEN_PERSISTENCE_IMPORT_ROOTS = {"fastapi", "pydantic"}
SQLALCHEMY_TYPE_NAMES = {
    "InstrumentedAttribute",
    "Query",
    "Result",
    "Row",
    "Select",
    "Session",
}
FORBIDDEN_REPOSITORY_METHODS = {"commit", "rollback", "filter", "query", "execute"}
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


def test_sqlalchemy_persistence_does_not_import_api_or_schema_frameworks() -> None:
    for path in _python_files(SQLALCHEMY_PERSISTENCE_ROOT):
        imports = _imports_for(path)
        assert not any(
            imported.split(".", 1)[0] in FORBIDDEN_PERSISTENCE_IMPORT_ROOTS
            for imported in imports
        ), path


def test_ports_do_not_import_concrete_persistence_implementations() -> None:
    for path in _python_files(PORTS_ROOT):
        imports = _imports_for(path)
        assert not any(imported.startswith("app.persistence") for imported in imports), path


def test_application_packages_are_importable() -> None:
    import app.application
    import app.application.ports
    import app.persistence
    import app.persistence.sqlalchemy

    assert app.application.ApplicationError is ApplicationError
    assert app.application.ports.UnitOfWork is UnitOfWork
    assert app.application.ports.ResourceRepository is ResourceRepository
    assert app.application.ports.ManagedCatalogRepository is ManagedCatalogRepository
    assert app.persistence.__doc__
    assert app.persistence.sqlalchemy.__doc__


def test_application_error_hierarchy_is_explicit() -> None:
    assert issubclass(EntityNotFoundError, ApplicationError)
    assert issubclass(ConflictError, ApplicationError)
    assert issubclass(ConcurrentModificationError, ConflictError)
    assert issubclass(TenantBoundaryError, ApplicationError)
    assert issubclass(PersistenceError, ApplicationError)


def test_unit_of_work_protocol_declares_lifecycle_methods() -> None:
    expected_methods = {"__enter__", "__exit__", "commit", "rollback"}
    assert expected_methods.issubset(UnitOfWork.__dict__)


def test_unit_of_work_protocol_exposes_technology_neutral_repositories() -> None:
    hints = get_type_hints(UnitOfWork)

    assert hints["tenants"] is TenantRepository
    assert hints["organizations"] is OrganizationRepository
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
        (ResourceOwnershipRepository, "get_current_primary"): ResourceOwnership | None,
        (ResourceClassificationRepository, "get_current_primary"): ResourceClassification | None,
        (ResourceStateRepository, "get_current"): ResourceState | None,
        (ResourceAliasRepository, "find_resource_by_alias"): Resource | None,
        (ResourceMergeRepository, "get_outgoing_merge"): ResourceMerge | None,
    }

    for (protocol, method_name), expected_return in expected_returns.items():
        hints = get_type_hints(getattr(protocol, method_name))
        assert hints["return"] == expected_return

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
