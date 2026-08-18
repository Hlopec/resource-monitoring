"""Resource read routes."""

from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.composition import get_list_resources_handler
from app.api.mappers import resource_page_response
from app.api.schemas import ResourcePageResponse
from app.application.handlers import ListResourcesHandler
from app.application.queries import DEFAULT_RESOURCE_PAGE_SIZE, ListResourcesQuery

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
