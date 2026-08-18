"""Explicit Resource application-result to API-schema mappers."""

from app.api.schemas import (
    ResourceAliasResponse,
    ResourceClassificationResponse,
    ResourceDetailsResponse,
    ResourceIdentifierResponse,
    ResourceLabelResponse,
    ResourceMergeResponse,
    ResourceOwnershipResponse,
    ResourcePageResponse,
    ResourceStateResponse,
    ResourceSummaryResponse,
)
from app.application.results import (
    ResourceAliasResult,
    ResourceClassificationResult,
    ResourceDetailsResult,
    ResourceIdentifierResult,
    ResourceLabelResult,
    ResourceMergeResult,
    ResourceOwnershipResult,
    ResourcePageResult,
    ResourceStateResult,
    ResourceSummaryResult,
)


def resource_summary_response(
    result: ResourceSummaryResult,
) -> ResourceSummaryResponse:
    return ResourceSummaryResponse(
        resource_id=result.resource_id,
        tenant_id=result.tenant_id,
        resource_type_id=result.resource_type_id,
        lifecycle_status_id=result.lifecycle_status_id,
        canonical_name=result.canonical_name,
        display_name=result.display_name,
        primary_organization_id=result.primary_organization_id,
        primary_ownership_role_id=result.primary_ownership_role_id,
        record_version=result.record_version,
        first_seen_at=result.first_seen_at,
        last_seen_at=result.last_seen_at,
        created_at=result.created_at,
        updated_at=result.updated_at,
    )


def resource_page_response(result: ResourcePageResult) -> ResourcePageResponse:
    return ResourcePageResponse(
        items=[resource_summary_response(item) for item in result.items],
        next_cursor=result.next_cursor,
    )


def resource_state_response(result: ResourceStateResult) -> ResourceStateResponse:
    return ResourceStateResponse(
        id=result.id,
        lifecycle_status_id=result.lifecycle_status_id,
        criticality_id=result.criticality_id,
        exposure_level_id=result.exposure_level_id,
        source_priority=result.source_priority,
        confidence_score=result.confidence_score,
        valid_from=result.valid_from,
        source=result.source,
    )


def resource_identifier_response(
    result: ResourceIdentifierResult,
) -> ResourceIdentifierResponse:
    return ResourceIdentifierResponse(
        id=result.id,
        identifier_type_id=result.identifier_type_id,
        namespace=result.namespace,
        normalized_value=result.normalized_value,
        original_value=result.original_value,
        is_primary=result.is_primary,
        confidence_score=result.confidence_score,
        valid_from=result.valid_from,
    )


def resource_ownership_response(
    result: ResourceOwnershipResult,
) -> ResourceOwnershipResponse:
    return ResourceOwnershipResponse(
        id=result.id,
        organization_id=result.organization_id,
        ownership_role_id=result.ownership_role_id,
        is_primary=result.is_primary,
        confidence_score=result.confidence_score,
        valid_from=result.valid_from,
        source=result.source,
    )


def resource_classification_response(
    result: ResourceClassificationResult,
) -> ResourceClassificationResponse:
    return ResourceClassificationResponse(
        id=result.id,
        classification_type_id=result.classification_type_id,
        classification_value_id=result.classification_value_id,
        is_primary=result.is_primary,
        confidence_score=result.confidence_score,
        valid_from=result.valid_from,
        source=result.source,
    )


def resource_label_response(result: ResourceLabelResult) -> ResourceLabelResponse:
    return ResourceLabelResponse(
        id=result.id,
        label_id=result.label_id,
        valid_from=result.valid_from,
        source=result.source,
    )


def resource_alias_response(result: ResourceAliasResult) -> ResourceAliasResponse:
    return ResourceAliasResponse(
        id=result.id,
        alias_type=result.alias_type,
        alias_value=result.alias_value,
        normalized_value=result.normalized_value,
        source=result.source,
        first_seen_at=result.first_seen_at,
        last_seen_at=result.last_seen_at,
    )


def resource_merge_response(result: ResourceMergeResult) -> ResourceMergeResponse:
    return ResourceMergeResponse(
        id=result.id,
        source_resource_id=result.source_resource_id,
        target_resource_id=result.target_resource_id,
        reason=result.reason,
        source=result.source,
        merged_at=result.merged_at,
    )


def resource_details_response(result: ResourceDetailsResult) -> ResourceDetailsResponse:
    return ResourceDetailsResponse(
        id=result.id,
        tenant_id=result.tenant_id,
        organization_id=result.organization_id,
        resource_type_id=result.resource_type_id,
        canonical_name=result.canonical_name,
        display_name=result.display_name,
        record_version=result.record_version,
        created_at=result.created_at,
        updated_at=result.updated_at,
        state=(
            resource_state_response(result.state)
            if result.state is not None
            else None
        ),
        identifiers=[
            resource_identifier_response(identifier)
            for identifier in result.identifiers
        ],
        ownership=[
            resource_ownership_response(ownership)
            for ownership in result.ownership
        ],
        classifications=[
            resource_classification_response(classification)
            for classification in result.classifications
        ],
        labels=[resource_label_response(label) for label in result.labels],
        aliases=[resource_alias_response(alias) for alias in result.aliases],
        outgoing_merge=(
            resource_merge_response(result.outgoing_merge)
            if result.outgoing_merge is not None
            else None
        ),
    )
