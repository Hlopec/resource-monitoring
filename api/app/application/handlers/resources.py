"""Reference resource handlers for application architecture tests."""

from __future__ import annotations

from app.application.commands import EnsureResourceExistsCommand
from app.application.errors import EntityNotFoundError
from app.application.ports import UnitOfWork, UnitOfWorkFactory
from app.application.queries import (
    GetResourceByCanonicalNameQuery,
    GetResourceByIdQuery,
    GetResourceDetailsQuery,
)
from app.application.results import (
    ResourceAliasResult,
    ResourceClassificationResult,
    ResourceDetailsResult,
    ResourceIdentifierResult,
    ResourceLabelResult,
    ResourceMergeResult,
    ResourceOwnershipResult,
    ResourceReadResult,
    ResourceStateResult,
)
from app.models import Resource


class GetResourceByIdHandler:
    """Read-only reference handler for tenant-scoped resource lookup."""

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    def handle(self, query: GetResourceByIdQuery) -> ResourceReadResult:
        """Return a resource projection or raise a technology-neutral miss."""
        with self._uow_factory() as uow:
            resource = uow.resources.get_by_id(query.tenant_id, query.resource_id)
            if resource is None:
                raise EntityNotFoundError("Resource not found")
            return ResourceReadResult(
                id=resource.id,
                tenant_id=resource.tenant_id,
                canonical_name=resource.canonical_name,
                display_name=resource.display_name,
            )


class GetResourceDetailsHandler:
    """Read-only handler for tenant-scoped resource details by id."""

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    def handle(self, query: GetResourceDetailsQuery) -> ResourceDetailsResult:
        """Return a fully materialized details projection for one resource."""
        with self._uow_factory() as uow:
            resource = uow.resources.get_by_id(query.tenant_id, query.resource_id)
            if resource is None:
                raise EntityNotFoundError(
                    "Resource not found",
                    entity_type="Resource",
                    lookup_field="resource_id",
                    lookup_value=query.resource_id,
                )
            return _build_resource_details_result(uow, resource)


class GetResourceByCanonicalNameHandler:
    """Read-only handler for tenant-scoped resource details by canonical name."""

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    def handle(
        self,
        query: GetResourceByCanonicalNameQuery,
    ) -> ResourceDetailsResult:
        """Return a fully materialized resource projection by canonical name."""
        with self._uow_factory() as uow:
            resource = uow.resources.get_by_canonical_name(
                query.tenant_id,
                query.canonical_name,
            )
            if resource is None:
                raise EntityNotFoundError(
                    "Resource not found",
                    entity_type="Resource",
                    lookup_field="canonical_name",
                    lookup_value=query.canonical_name,
                )
            return _build_resource_details_result(uow, resource)


class EnsureResourceExistsHandler:
    """Reference command handler that validates resource presence."""

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    def handle(self, command: EnsureResourceExistsCommand) -> None:
        """Validate resource presence and commit the successful command."""
        with self._uow_factory() as uow:
            if not uow.resources.exists(command.tenant_id, command.resource_id):
                raise EntityNotFoundError("Resource not found")
            uow.commit()


def _build_resource_details_result(
    uow: UnitOfWork,
    resource: Resource,
) -> ResourceDetailsResult:
    tenant_id = resource.tenant_id
    resource_id = resource.id
    state = uow.resource_states.get_current(tenant_id, resource_id)
    identifiers = uow.resource_identifiers.get_current_for_resource(
        tenant_id,
        resource_id,
    )
    identifiers = sorted(
        identifiers,
        key=lambda identifier: (
            str(identifier.identifier_type_id),
            identifier.namespace or "",
            identifier.normalized_value,
            str(identifier.id),
        ),
    )
    ownership = uow.resource_ownerships.get_current_for_resource(
        tenant_id,
        resource_id,
    )
    ownership = sorted(
        ownership,
        key=lambda ownership_row: (
            str(ownership_row.ownership_role_id),
            not ownership_row.is_primary,
            str(ownership_row.organization_id),
            str(ownership_row.id),
        ),
    )
    classifications = uow.resource_classifications.get_current_for_resource(
        tenant_id,
        resource_id,
    )
    classifications = sorted(
        classifications,
        key=lambda classification: (
            str(classification.classification_type_id),
            str(classification.classification_value_id),
            str(classification.id),
        ),
    )
    labels = uow.resource_labels.get_current_for_resource(tenant_id, resource_id)
    labels = sorted(labels, key=lambda label: (str(label.label_id), str(label.id)))
    aliases = uow.resource_aliases.list_for_resource(tenant_id, resource_id)
    aliases = sorted(
        aliases,
        key=lambda alias: (alias.alias_type, alias.normalized_value, str(alias.id)),
    )
    outgoing_merge = uow.resource_merges.get_outgoing_merge(tenant_id, resource_id)
    primary_ownership = next(
        (ownership_row for ownership_row in ownership if ownership_row.is_primary),
        None,
    )

    return ResourceDetailsResult(
        id=resource.id,
        tenant_id=resource.tenant_id,
        organization_id=(
            primary_ownership.organization_id if primary_ownership is not None else None
        ),
        resource_type_id=resource.resource_type_id,
        canonical_name=resource.canonical_name,
        display_name=resource.display_name,
        record_version=resource.record_version,
        created_at=resource.created_at,
        updated_at=resource.updated_at,
        state=(
            ResourceStateResult(
                id=state.id,
                lifecycle_status_id=state.lifecycle_status_id,
                criticality_id=state.criticality_id,
                exposure_level_id=state.exposure_level_id,
                source_priority=state.source_priority,
                confidence_score=state.confidence_score,
                valid_from=state.valid_from,
                source=state.source,
            )
            if state is not None
            else None
        ),
        identifiers=tuple(
            ResourceIdentifierResult(
                id=identifier.id,
                identifier_type_id=identifier.identifier_type_id,
                namespace=identifier.namespace,
                normalized_value=identifier.normalized_value,
                original_value=identifier.original_value,
                is_primary=identifier.is_primary,
                confidence_score=identifier.confidence_score,
                valid_from=identifier.valid_from,
            )
            for identifier in identifiers
        ),
        ownership=tuple(
            ResourceOwnershipResult(
                id=ownership_row.id,
                organization_id=ownership_row.organization_id,
                ownership_role_id=ownership_row.ownership_role_id,
                is_primary=ownership_row.is_primary,
                confidence_score=ownership_row.confidence_score,
                valid_from=ownership_row.valid_from,
                source=ownership_row.source,
            )
            for ownership_row in ownership
        ),
        classifications=tuple(
            ResourceClassificationResult(
                id=classification.id,
                classification_type_id=classification.classification_type_id,
                classification_value_id=classification.classification_value_id,
                is_primary=classification.is_primary,
                confidence_score=classification.confidence_score,
                valid_from=classification.valid_from,
                source=classification.source,
            )
            for classification in classifications
        ),
        labels=tuple(
            ResourceLabelResult(
                id=label.id,
                label_id=label.label_id,
                valid_from=label.valid_from,
                source=label.source,
            )
            for label in labels
        ),
        aliases=tuple(
            ResourceAliasResult(
                id=alias.id,
                alias_type=alias.alias_type,
                alias_value=alias.alias_value,
                normalized_value=alias.normalized_value,
                source=alias.source,
                first_seen_at=alias.first_seen_at,
                last_seen_at=alias.last_seen_at,
            )
            for alias in aliases
        ),
        outgoing_merge=(
            ResourceMergeResult(
                id=outgoing_merge.id,
                source_resource_id=outgoing_merge.source_resource_id,
                target_resource_id=outgoing_merge.target_resource_id,
                reason=outgoing_merge.reason,
                source=outgoing_merge.source,
                merged_at=outgoing_merge.merged_at,
            )
            if outgoing_merge is not None
            else None
        ),
    )
