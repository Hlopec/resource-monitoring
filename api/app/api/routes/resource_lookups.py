"""Resource identity lookup routes."""

from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.composition import (
    get_find_resource_by_alias_handler,
    get_find_resource_by_identifier_handler,
    get_get_resource_by_canonical_name_handler,
)
from app.api.mappers import (
    resource_alias_lookup_response,
    resource_details_response,
    resource_identifier_lookup_response,
)
from app.api.schemas import (
    ResourceAliasLookupResponse,
    ResourceDetailsResponse,
    ResourceIdentifierLookupResponse,
)
from app.application.handlers import (
    FindResourceByAliasHandler,
    FindResourceByIdentifierHandler,
    GetResourceByCanonicalNameHandler,
)
from app.application.queries import (
    FindResourceByAliasQuery,
    FindResourceByIdentifierQuery,
    GetResourceByCanonicalNameQuery,
)

router = APIRouter(tags=["resources"])


@router.get(
    "/tenants/{tenant_id}/resource-lookups/canonical-name",
    response_model=ResourceDetailsResponse,
    summary="Find tenant resource by canonical name",
)
def get_resource_by_canonical_name(
    tenant_id: UUID,
    canonical_name: str,
    handler: GetResourceByCanonicalNameHandler = Depends(
        get_get_resource_by_canonical_name_handler
    ),
) -> ResourceDetailsResponse:
    query = GetResourceByCanonicalNameQuery(
        tenant_id=tenant_id,
        canonical_name=canonical_name,
    )
    return resource_details_response(handler.handle(query))


@router.get(
    "/tenants/{tenant_id}/resource-lookups/identifier",
    response_model=ResourceIdentifierLookupResponse,
    summary="Find tenant resource by identifier",
)
def find_resource_by_identifier(
    tenant_id: UUID,
    identifier_type_id: UUID,
    normalized_value: str,
    namespace: str | None = None,
    handler: FindResourceByIdentifierHandler = Depends(
        get_find_resource_by_identifier_handler
    ),
) -> ResourceIdentifierLookupResponse:
    query = FindResourceByIdentifierQuery(
        tenant_id=tenant_id,
        identifier_type_id=identifier_type_id,
        namespace=namespace,
        normalized_value=normalized_value,
    )
    return resource_identifier_lookup_response(handler.handle(query))


@router.get(
    "/tenants/{tenant_id}/resource-lookups/alias",
    response_model=ResourceAliasLookupResponse,
    summary="Find tenant resource by alias",
)
def find_resource_by_alias(
    tenant_id: UUID,
    alias_type: str,
    normalized_value: str,
    handler: FindResourceByAliasHandler = Depends(get_find_resource_by_alias_handler),
) -> ResourceAliasLookupResponse:
    query = FindResourceByAliasQuery(
        tenant_id=tenant_id,
        alias_type=alias_type,
        normalized_value=normalized_value,
    )
    return resource_alias_lookup_response(handler.handle(query))
