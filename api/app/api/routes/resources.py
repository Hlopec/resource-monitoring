"""Resource read routes."""

from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.composition import (
    get_assign_resource_classification_handler,
    get_assign_resource_identifier_handler,
    get_assign_resource_ownership_handler,
    get_create_resource_handler,
    get_get_resource_details_handler,
    get_get_resource_history_handler,
    get_get_resource_relationships_handler,
    get_list_resources_handler,
    get_resolve_canonical_resource_handler,
    get_transition_resource_state_handler,
)
from app.api.mappers import (
    canonical_resource_resolved_response,
    resource_classification_assigned_response,
    resource_identifier_assigned_response,
    resource_ownership_assigned_response,
    resource_created_response,
    resource_details_response,
    resource_history_response,
    resource_page_response,
    resource_relationships_response,
    resource_state_transitioned_response,
)
from app.api.schemas import (
    AssignResourceClassificationRequest,
    AssignResourceIdentifierRequest,
    AssignResourceOwnershipRequest,
    CanonicalResourceResolvedResponse,
    CreateResourceRequest,
    ResourceCreatedResponse,
    ResourceClassificationAssignedResponse,
    ResourceDetailsResponse,
    ResourceHistoryResponse,
    ResourceIdentifierAssignedResponse,
    ResourceOwnershipAssignedResponse,
    ResourcePageResponse,
    ResourceRelationshipsResponse,
    ResourceStateTransitionedResponse,
    TransitionResourceStateRequest,
)
from app.application.commands import (
    AssignResourceClassificationCommand,
    AssignResourceIdentifierCommand,
    AssignResourceOwnershipCommand,
    CreateResourceCommand,
    TransitionResourceStateCommand,
)
from app.application.handlers import (
    AssignResourceClassificationHandler,
    AssignResourceIdentifierHandler,
    AssignResourceOwnershipHandler,
    CreateResourceHandler,
    GetResourceDetailsHandler,
    GetResourceHistoryHandler,
    GetResourceRelationshipsHandler,
    ListResourcesHandler,
    ResolveCanonicalResourceHandler,
    TransitionResourceStateHandler,
)
from app.application.queries import (
    DEFAULT_RESOURCE_PAGE_SIZE,
    GetResourceDetailsQuery,
    GetResourceHistoryQuery,
    GetResourceRelationshipsQuery,
    ListResourcesQuery,
    ResolveCanonicalResourceQuery,
)

router = APIRouter(tags=["resources"])


@router.get(
    "/tenants/{tenant_id}/resources",
    response_model=ResourcePageResponse,
    summary="List tenant resources",
)
def list_resources(
    tenant_id: UUID,
    resource_type_id: UUID | None = None,
    lifecycle_status_id: UUID | None = None,
    organization_id: UUID | None = None,
    label_id: UUID | None = None,
    classification_type_id: UUID | None = None,
    classification_value_id: UUID | None = None,
    page_size: int = DEFAULT_RESOURCE_PAGE_SIZE,
    cursor: str | None = None,
    handler: ListResourcesHandler = Depends(get_list_resources_handler),
) -> ResourcePageResponse:
    query = ListResourcesQuery(
        tenant_id=tenant_id,
        resource_type_id=resource_type_id,
        lifecycle_status_id=lifecycle_status_id,
        organization_id=organization_id,
        label_id=label_id,
        classification_type_id=classification_type_id,
        classification_value_id=classification_value_id,
        page_size=page_size,
        cursor=cursor,
    )
    return resource_page_response(handler.handle(query))


@router.post(
    "/tenants/{tenant_id}/resources",
    response_model=ResourceCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create tenant resource",
)
def create_resource(
    tenant_id: UUID,
    request: CreateResourceRequest,
    handler: CreateResourceHandler = Depends(get_create_resource_handler),
) -> ResourceCreatedResponse:
    command = CreateResourceCommand(
        tenant_id=tenant_id,
        resource_type_id=request.resource_type_id,
        canonical_name=request.canonical_name,
        display_name=request.display_name,
        lifecycle_status_id=request.lifecycle_status_id,
        criticality_id=request.criticality_id,
        exposure_level_id=request.exposure_level_id,
        source_priority=request.source_priority,
        confidence_score=request.confidence_score,
        first_seen_at=request.first_seen_at,
        last_seen_at=request.last_seen_at,
    )
    return resource_created_response(handler.handle(command))


@router.get(
    "/tenants/{tenant_id}/resources/{resource_id}",
    response_model=ResourceDetailsResponse,
    summary="Get tenant resource details",
)
def get_resource_details(
    tenant_id: UUID,
    resource_id: UUID,
    handler: GetResourceDetailsHandler = Depends(get_get_resource_details_handler),
) -> ResourceDetailsResponse:
    query = GetResourceDetailsQuery(
        tenant_id=tenant_id,
        resource_id=resource_id,
    )
    return resource_details_response(handler.handle(query))


@router.post(
    "/tenants/{tenant_id}/resources/{resource_id}/state-transitions",
    response_model=ResourceStateTransitionedResponse,
    summary="Transition tenant resource state",
)
def transition_resource_state(
    tenant_id: UUID,
    resource_id: UUID,
    request: TransitionResourceStateRequest,
    handler: TransitionResourceStateHandler = Depends(
        get_transition_resource_state_handler
    ),
) -> ResourceStateTransitionedResponse:
    command = TransitionResourceStateCommand(
        tenant_id=tenant_id,
        resource_id=resource_id,
        lifecycle_status_id=request.lifecycle_status_id,
        criticality_id=request.criticality_id,
        exposure_level_id=request.exposure_level_id,
        source_priority=request.source_priority,
        confidence_score=request.confidence_score,
        transitioned_at=request.transitioned_at,
        source=request.source,
    )
    return resource_state_transitioned_response(handler.handle(command))


@router.post(
    "/tenants/{tenant_id}/resources/{resource_id}/identifiers",
    response_model=ResourceIdentifierAssignedResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Assign tenant resource identifier",
)
def assign_resource_identifier(
    tenant_id: UUID,
    resource_id: UUID,
    request: AssignResourceIdentifierRequest,
    handler: AssignResourceIdentifierHandler = Depends(
        get_assign_resource_identifier_handler
    ),
) -> ResourceIdentifierAssignedResponse:
    command = AssignResourceIdentifierCommand(
        tenant_id=tenant_id,
        resource_id=resource_id,
        identifier_type_id=request.identifier_type_id,
        original_value=request.original_value,
        normalized_value=request.normalized_value,
        value_hash=request.value_hash,
        namespace=request.namespace,
        is_primary=request.is_primary,
        confidence_score=request.confidence_score,
        valid_from=request.valid_from,
    )
    return resource_identifier_assigned_response(handler.handle(command))


@router.post(
    "/tenants/{tenant_id}/resources/{resource_id}/ownership",
    response_model=ResourceOwnershipAssignedResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Assign tenant resource ownership",
)
def assign_resource_ownership(
    tenant_id: UUID,
    resource_id: UUID,
    request: AssignResourceOwnershipRequest,
    handler: AssignResourceOwnershipHandler = Depends(
        get_assign_resource_ownership_handler
    ),
) -> ResourceOwnershipAssignedResponse:
    command = AssignResourceOwnershipCommand(
        tenant_id=tenant_id,
        resource_id=resource_id,
        organization_id=request.organization_id,
        ownership_role_id=request.ownership_role_id,
        is_primary=request.is_primary,
        confidence_score=request.confidence_score,
        valid_from=request.valid_from,
        source=request.source,
    )
    return resource_ownership_assigned_response(handler.handle(command))


@router.post(
    "/tenants/{tenant_id}/resources/{resource_id}/classifications",
    response_model=ResourceClassificationAssignedResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Assign tenant resource classification",
)
def assign_resource_classification(
    tenant_id: UUID,
    resource_id: UUID,
    request: AssignResourceClassificationRequest,
    handler: AssignResourceClassificationHandler = Depends(
        get_assign_resource_classification_handler
    ),
) -> ResourceClassificationAssignedResponse:
    command = AssignResourceClassificationCommand(
        tenant_id=tenant_id,
        resource_id=resource_id,
        classification_type_id=request.classification_type_id,
        classification_value_id=request.classification_value_id,
        is_primary=request.is_primary,
        confidence_score=request.confidence_score,
        valid_from=request.valid_from,
        source=request.source,
    )
    return resource_classification_assigned_response(handler.handle(command))


@router.get(
    "/tenants/{tenant_id}/resources/{resource_id}/history",
    response_model=ResourceHistoryResponse,
    summary="Get tenant resource history",
)
def get_resource_history(
    tenant_id: UUID,
    resource_id: UUID,
    handler: GetResourceHistoryHandler = Depends(get_get_resource_history_handler),
) -> ResourceHistoryResponse:
    query = GetResourceHistoryQuery(
        tenant_id=tenant_id,
        resource_id=resource_id,
    )
    return resource_history_response(handler.handle(query))


@router.get(
    "/tenants/{tenant_id}/resources/{resource_id}/relationships",
    response_model=ResourceRelationshipsResponse,
    summary="Get tenant resource relationships",
)
def get_resource_relationships(
    tenant_id: UUID,
    resource_id: UUID,
    handler: GetResourceRelationshipsHandler = Depends(
        get_get_resource_relationships_handler
    ),
) -> ResourceRelationshipsResponse:
    query = GetResourceRelationshipsQuery(
        tenant_id=tenant_id,
        resource_id=resource_id,
    )
    return resource_relationships_response(handler.handle(query))


@router.get(
    "/tenants/{tenant_id}/resources/{resource_id}/canonical",
    response_model=CanonicalResourceResolvedResponse,
    summary="Resolve tenant resource canonical target",
)
def resolve_resource_canonical(
    tenant_id: UUID,
    resource_id: UUID,
    handler: ResolveCanonicalResourceHandler = Depends(
        get_resolve_canonical_resource_handler
    ),
) -> CanonicalResourceResolvedResponse:
    query = ResolveCanonicalResourceQuery(
        tenant_id=tenant_id,
        resource_id=resource_id,
    )
    return canonical_resource_resolved_response(handler.handle(query))
