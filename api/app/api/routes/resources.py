"""Resource read routes."""

from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.composition import (
    get_get_resource_details_handler,
    get_get_resource_history_handler,
    get_get_resource_relationships_handler,
    get_list_resources_handler,
)
from app.api.mappers import (
    resource_details_response,
    resource_history_response,
    resource_page_response,
    resource_relationships_response,
)
from app.api.schemas import (
    ResourceDetailsResponse,
    ResourceHistoryResponse,
    ResourcePageResponse,
    ResourceRelationshipsResponse,
)
from app.application.handlers import (
    GetResourceDetailsHandler,
    GetResourceHistoryHandler,
    GetResourceRelationshipsHandler,
    ListResourcesHandler,
)
from app.application.queries import (
    DEFAULT_RESOURCE_PAGE_SIZE,
    GetResourceDetailsQuery,
    GetResourceHistoryQuery,
    GetResourceRelationshipsQuery,
    ListResourcesQuery,
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
