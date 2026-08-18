"""API composition boundary for application handlers and persistence adapters."""

from fastapi import Depends

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
from app.persistence.sqlalchemy import SQLAlchemyUnitOfWork

__all__ = [
    "get_assign_resource_alias_handler",
    "get_assign_resource_classification_handler",
    "get_assign_resource_identifier_handler",
    "get_assign_resource_label_handler",
    "get_assign_resource_ownership_handler",
    "get_assign_resource_relationship_handler",
    "get_create_resource_handler",
    "get_find_resource_by_alias_handler",
    "get_find_resource_by_identifier_handler",
    "get_get_resource_by_canonical_name_handler",
    "get_get_resource_by_id_handler",
    "get_get_resource_details_handler",
    "get_get_resource_history_handler",
    "get_get_resource_relationships_handler",
    "get_list_resources_handler",
    "get_merge_resource_handler",
    "get_resolve_canonical_resource_handler",
    "get_transition_resource_state_handler",
    "get_unit_of_work_factory",
]


def get_unit_of_work_factory() -> UnitOfWorkFactory:
    """Return the concrete Unit of Work factory without opening a session."""
    return SQLAlchemyUnitOfWork


def get_list_resources_handler(
    uow_factory: UnitOfWorkFactory = Depends(get_unit_of_work_factory),
) -> ListResourcesHandler:
    return ListResourcesHandler(uow_factory)


def get_get_resource_by_id_handler(
    uow_factory: UnitOfWorkFactory = Depends(get_unit_of_work_factory),
) -> GetResourceByIdHandler:
    return GetResourceByIdHandler(uow_factory)


def get_get_resource_details_handler(
    uow_factory: UnitOfWorkFactory = Depends(get_unit_of_work_factory),
) -> GetResourceDetailsHandler:
    return GetResourceDetailsHandler(uow_factory)


def get_get_resource_history_handler(
    uow_factory: UnitOfWorkFactory = Depends(get_unit_of_work_factory),
) -> GetResourceHistoryHandler:
    return GetResourceHistoryHandler(uow_factory)


def get_get_resource_relationships_handler(
    uow_factory: UnitOfWorkFactory = Depends(get_unit_of_work_factory),
) -> GetResourceRelationshipsHandler:
    return GetResourceRelationshipsHandler(uow_factory)


def get_get_resource_by_canonical_name_handler(
    uow_factory: UnitOfWorkFactory = Depends(get_unit_of_work_factory),
) -> GetResourceByCanonicalNameHandler:
    return GetResourceByCanonicalNameHandler(uow_factory)


def get_find_resource_by_identifier_handler(
    uow_factory: UnitOfWorkFactory = Depends(get_unit_of_work_factory),
) -> FindResourceByIdentifierHandler:
    return FindResourceByIdentifierHandler(uow_factory)


def get_find_resource_by_alias_handler(
    uow_factory: UnitOfWorkFactory = Depends(get_unit_of_work_factory),
) -> FindResourceByAliasHandler:
    return FindResourceByAliasHandler(uow_factory)


def get_resolve_canonical_resource_handler(
    uow_factory: UnitOfWorkFactory = Depends(get_unit_of_work_factory),
) -> ResolveCanonicalResourceHandler:
    return ResolveCanonicalResourceHandler(uow_factory)


def get_create_resource_handler(
    uow_factory: UnitOfWorkFactory = Depends(get_unit_of_work_factory),
) -> CreateResourceHandler:
    return CreateResourceHandler(uow_factory)


def get_transition_resource_state_handler(
    uow_factory: UnitOfWorkFactory = Depends(get_unit_of_work_factory),
) -> TransitionResourceStateHandler:
    return TransitionResourceStateHandler(uow_factory)


def get_assign_resource_identifier_handler(
    uow_factory: UnitOfWorkFactory = Depends(get_unit_of_work_factory),
) -> AssignResourceIdentifierHandler:
    return AssignResourceIdentifierHandler(uow_factory)


def get_assign_resource_ownership_handler(
    uow_factory: UnitOfWorkFactory = Depends(get_unit_of_work_factory),
) -> AssignResourceOwnershipHandler:
    return AssignResourceOwnershipHandler(uow_factory)


def get_assign_resource_classification_handler(
    uow_factory: UnitOfWorkFactory = Depends(get_unit_of_work_factory),
) -> AssignResourceClassificationHandler:
    return AssignResourceClassificationHandler(uow_factory)


def get_assign_resource_label_handler(
    uow_factory: UnitOfWorkFactory = Depends(get_unit_of_work_factory),
) -> AssignResourceLabelHandler:
    return AssignResourceLabelHandler(uow_factory)


def get_assign_resource_relationship_handler(
    uow_factory: UnitOfWorkFactory = Depends(get_unit_of_work_factory),
) -> AssignResourceRelationshipHandler:
    return AssignResourceRelationshipHandler(uow_factory)


def get_assign_resource_alias_handler(
    uow_factory: UnitOfWorkFactory = Depends(get_unit_of_work_factory),
) -> AssignResourceAliasHandler:
    return AssignResourceAliasHandler(uow_factory)


def get_merge_resource_handler(
    uow_factory: UnitOfWorkFactory = Depends(get_unit_of_work_factory),
) -> MergeResourceHandler:
    return MergeResourceHandler(uow_factory)
