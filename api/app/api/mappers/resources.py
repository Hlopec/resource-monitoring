"""Explicit Resource application-result to API-schema mappers."""

from app.api.schemas import (
    CanonicalResourceResolvedResponse,
    ResourceCreatedResponse,
    ResourceAliasResponse,
    ResourceAliasLookupResponse,
    ResourceClassificationResponse,
    ResourceDetailsResponse,
    ResourceHistoryResponse,
    ResourceIdentifierAssignedResponse,
    ResourceIdentifierResponse,
    ResourceIdentifierLookupResponse,
    ResourceLabelResponse,
    ResourceMergeResponse,
    ResourceOwnershipResponse,
    ResourcePageResponse,
    ResourceReadResponse,
    ResourceRelationshipResponse,
    ResourceRelationshipsResponse,
    ResourceClassificationHistoryResponse,
    ResourceIdentifierHistoryResponse,
    ResourceLabelHistoryResponse,
    ResourceOwnershipHistoryResponse,
    ResourceStateHistoryResponse,
    ResourceStateTransitionedResponse,
    ResourceStateResponse,
    ResourceSummaryResponse,
)
from app.application.results import (
    CanonicalResourceResolvedResult,
    ResourceCreatedResult,
    ResourceAliasLookupResult,
    ResourceAliasResult,
    ResourceClassificationHistoryResult,
    ResourceClassificationResult,
    ResourceDetailsResult,
    ResourceHistoryResult,
    ResourceIdentifierAssignedResult,
    ResourceIdentifierHistoryResult,
    ResourceIdentifierLookupResult,
    ResourceIdentifierResult,
    ResourceLabelHistoryResult,
    ResourceLabelResult,
    ResourceMergeResult,
    ResourceOwnershipHistoryResult,
    ResourceOwnershipResult,
    ResourcePageResult,
    ResourceReadResult,
    ResourceRelationshipResult,
    ResourceRelationshipsResult,
    ResourceStateHistoryResult,
    ResourceStateTransitionedResult,
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


def resource_created_response(
    result: ResourceCreatedResult,
) -> ResourceCreatedResponse:
    return ResourceCreatedResponse(
        resource_id=result.resource_id,
        tenant_id=result.tenant_id,
        canonical_name=result.canonical_name,
        record_version=result.record_version,
    )


def resource_state_transitioned_response(
    result: ResourceStateTransitionedResult,
) -> ResourceStateTransitionedResponse:
    return ResourceStateTransitionedResponse(
        resource_id=result.resource_id,
        previous_state_id=result.previous_state_id,
        new_state_id=result.new_state_id,
        transitioned_at=result.transitioned_at,
    )


def resource_identifier_assigned_response(
    result: ResourceIdentifierAssignedResult,
) -> ResourceIdentifierAssignedResponse:
    return ResourceIdentifierAssignedResponse(
        resource_id=result.resource_id,
        identifier_id=result.identifier_id,
        identifier_type_id=result.identifier_type_id,
        original_value=result.original_value,
        normalized_value=result.normalized_value,
        value_hash=result.value_hash,
        namespace=result.namespace,
        is_primary=result.is_primary,
        valid_from=result.valid_from,
    )


def resource_read_response(result: ResourceReadResult) -> ResourceReadResponse:
    return ResourceReadResponse(
        id=result.id,
        tenant_id=result.tenant_id,
        canonical_name=result.canonical_name,
        display_name=result.display_name,
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


def resource_state_history_response(
    result: ResourceStateHistoryResult,
) -> ResourceStateHistoryResponse:
    return ResourceStateHistoryResponse(
        id=result.id,
        lifecycle_status_id=result.lifecycle_status_id,
        criticality_id=result.criticality_id,
        exposure_level_id=result.exposure_level_id,
        source_priority=result.source_priority,
        confidence_score=result.confidence_score,
        valid_from=result.valid_from,
        valid_to=result.valid_to,
        source=result.source,
    )


def resource_ownership_history_response(
    result: ResourceOwnershipHistoryResult,
) -> ResourceOwnershipHistoryResponse:
    return ResourceOwnershipHistoryResponse(
        id=result.id,
        organization_id=result.organization_id,
        ownership_role_id=result.ownership_role_id,
        is_primary=result.is_primary,
        confidence_score=result.confidence_score,
        valid_from=result.valid_from,
        valid_to=result.valid_to,
        source=result.source,
    )


def resource_label_history_response(
    result: ResourceLabelHistoryResult,
) -> ResourceLabelHistoryResponse:
    return ResourceLabelHistoryResponse(
        id=result.id,
        label_id=result.label_id,
        valid_from=result.valid_from,
        valid_to=result.valid_to,
        source=result.source,
    )


def resource_classification_history_response(
    result: ResourceClassificationHistoryResult,
) -> ResourceClassificationHistoryResponse:
    return ResourceClassificationHistoryResponse(
        id=result.id,
        classification_type_id=result.classification_type_id,
        classification_value_id=result.classification_value_id,
        is_primary=result.is_primary,
        confidence_score=result.confidence_score,
        valid_from=result.valid_from,
        valid_to=result.valid_to,
        source=result.source,
    )


def resource_identifier_history_response(
    result: ResourceIdentifierHistoryResult,
) -> ResourceIdentifierHistoryResponse:
    return ResourceIdentifierHistoryResponse(
        id=result.id,
        identifier_type_id=result.identifier_type_id,
        namespace=result.namespace,
        normalized_value=result.normalized_value,
        original_value=result.original_value,
        is_primary=result.is_primary,
        confidence_score=result.confidence_score,
        valid_from=result.valid_from,
        valid_to=result.valid_to,
    )


def resource_history_response(result: ResourceHistoryResult) -> ResourceHistoryResponse:
    return ResourceHistoryResponse(
        id=result.id,
        tenant_id=result.tenant_id,
        resource_type_id=result.resource_type_id,
        canonical_name=result.canonical_name,
        display_name=result.display_name,
        states=[resource_state_history_response(state) for state in result.states],
        ownership=[
            resource_ownership_history_response(ownership)
            for ownership in result.ownership
        ],
        labels=[resource_label_history_response(label) for label in result.labels],
        classifications=[
            resource_classification_history_response(classification)
            for classification in result.classifications
        ],
        identifiers=[
            resource_identifier_history_response(identifier)
            for identifier in result.identifiers
        ],
    )


def resource_relationship_response(
    result: ResourceRelationshipResult,
) -> ResourceRelationshipResponse:
    return ResourceRelationshipResponse(
        id=result.id,
        relationship_type_id=result.relationship_type_id,
        source_resource_id=result.source_resource_id,
        target_resource_id=result.target_resource_id,
        direction=result.direction,
        confidence_score=result.confidence_score,
        valid_from=result.valid_from,
        source=result.source,
        created_at=result.created_at,
    )


def resource_relationships_response(
    result: ResourceRelationshipsResult,
) -> ResourceRelationshipsResponse:
    return ResourceRelationshipsResponse(
        resource_id=result.resource_id,
        tenant_id=result.tenant_id,
        relationships=[
            resource_relationship_response(relationship)
            for relationship in result.relationships
        ],
    )


def resource_identifier_lookup_response(
    result: ResourceIdentifierLookupResult,
) -> ResourceIdentifierLookupResponse:
    return ResourceIdentifierLookupResponse(
        resource=resource_read_response(result.resource),
        identifier_id=result.identifier_id,
        identifier_type_id=result.identifier_type_id,
        namespace=result.namespace,
        normalized_value=result.normalized_value,
        original_value=result.original_value,
        is_primary=result.is_primary,
    )


def resource_alias_lookup_response(
    result: ResourceAliasLookupResult,
) -> ResourceAliasLookupResponse:
    return ResourceAliasLookupResponse(
        resource=resource_read_response(result.resource),
        alias_id=result.alias_id,
        alias_type=result.alias_type,
        normalized_value=result.normalized_value,
        alias_value=result.alias_value,
    )


def canonical_resource_resolved_response(
    result: CanonicalResourceResolvedResult,
) -> CanonicalResourceResolvedResponse:
    return CanonicalResourceResolvedResponse(
        requested_resource_id=result.requested_resource_id,
        canonical_resource_id=result.canonical_resource_id,
        immediate_target_resource_id=result.immediate_target_resource_id,
        merge_depth=result.merge_depth,
        is_canonical=result.is_canonical,
        canonical_resource=resource_read_response(result.canonical_resource),
    )
