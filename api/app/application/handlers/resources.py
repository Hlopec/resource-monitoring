"""Reference resource handlers for application architecture tests."""

from __future__ import annotations

from decimal import Decimal

from app.application.commands import (
    AssignResourceClassificationCommand,
    AssignResourceIdentifierCommand,
    AssignResourceLabelCommand,
    AssignResourceOwnershipCommand,
    CreateResourceCommand,
    EnsureResourceExistsCommand,
    TransitionResourceStateCommand,
)
from app.application.errors import (
    ConflictError,
    EntityNotFoundError,
    ValidationError,
    ValidationFailure,
)
from app.application.ports import UnitOfWork, UnitOfWorkFactory
from app.application.queries import (
    GetResourceByCanonicalNameQuery,
    GetResourceByIdQuery,
    GetResourceDetailsQuery,
)
from app.application.results import (
    ResourceClassificationAssignedResult,
    ResourceIdentifierAssignedResult,
    ResourceAliasResult,
    ResourceClassificationResult,
    ResourceCreatedResult,
    ResourceDetailsResult,
    ResourceIdentifierResult,
    ResourceLabelAssignedResult,
    ResourceLabelResult,
    ResourceMergeResult,
    ResourceOwnershipAssignedResult,
    ResourceOwnershipResult,
    ResourceReadResult,
    ResourceStateTransitionedResult,
    ResourceStateResult,
)
from app.models import (
    Resource,
    ResourceClassification,
    ResourceIdentifier,
    ResourceLabel,
    ResourceOwnership,
    ResourceState,
)

INITIAL_RESOURCE_RECORD_VERSION = 1


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


class CreateResourceHandler:
    """Command handler for creating one base resource record."""

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    def handle(self, command: CreateResourceCommand) -> ResourceCreatedResult:
        """Create a resource, commit once, and return a materialized result."""
        _validate_create_resource_command(command)
        with self._uow_factory() as uow:
            if uow.tenants.get_by_id(command.tenant_id) is None:
                raise EntityNotFoundError(
                    "Tenant not found",
                    entity_type="Tenant",
                    lookup_field="tenant_id",
                    lookup_value=command.tenant_id,
                )
            _require_active_catalog(
                uow.resource_types,
                command.resource_type_id,
                entity_type="ResourceType",
                lookup_field="resource_type_id",
            )
            _require_active_catalog(
                uow.lifecycle_statuses,
                command.lifecycle_status_id,
                entity_type="LifecycleStatus",
                lookup_field="lifecycle_status_id",
            )
            _require_active_catalog(
                uow.criticalities,
                command.criticality_id,
                entity_type="Criticality",
                lookup_field="criticality_id",
            )
            _require_active_catalog(
                uow.exposure_levels,
                command.exposure_level_id,
                entity_type="ExposureLevel",
                lookup_field="exposure_level_id",
            )
            existing = uow.resources.get_by_canonical_name(
                command.tenant_id,
                command.canonical_name,
            )
            if existing is not None:
                raise ConflictError(
                    "Resource canonical name already exists",
                    entity_type="Resource",
                    conflict_field="canonical_name",
                    conflict_value=command.canonical_name,
                )

            resource = Resource(
                tenant_id=command.tenant_id,
                resource_type_id=command.resource_type_id,
                canonical_name=command.canonical_name,
                display_name=command.display_name,
                lifecycle_status_id=command.lifecycle_status_id,
                criticality_id=command.criticality_id,
                exposure_level_id=command.exposure_level_id,
                source_priority=command.source_priority,
                confidence_score=command.confidence_score,
                first_seen_at=command.first_seen_at,
                last_seen_at=command.last_seen_at,
            )
            uow.resources.add(resource)
            result = ResourceCreatedResult(
                resource_id=resource.id,
                tenant_id=command.tenant_id,
                canonical_name=command.canonical_name,
                record_version=INITIAL_RESOURCE_RECORD_VERSION,
            )
            uow.commit()
            return result


class TransitionResourceStateHandler:
    """Command handler for replacing one resource's current state row."""

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    def handle(
        self,
        command: TransitionResourceStateCommand,
    ) -> ResourceStateTransitionedResult:
        """Transition resource state history and commit once."""
        _validate_transition_resource_state_command(command)
        with self._uow_factory() as uow:
            resource = uow.resources.get_for_update(
                command.tenant_id,
                command.resource_id,
            )
            if resource is None:
                raise EntityNotFoundError(
                    "Resource not found",
                    entity_type="Resource",
                    lookup_field="resource_id",
                    lookup_value=command.resource_id,
                )
            _require_active_catalog(
                uow.lifecycle_statuses,
                command.lifecycle_status_id,
                entity_type="LifecycleStatus",
                lookup_field="lifecycle_status_id",
            )
            _require_active_catalog(
                uow.criticalities,
                command.criticality_id,
                entity_type="Criticality",
                lookup_field="criticality_id",
            )
            _require_active_catalog(
                uow.exposure_levels,
                command.exposure_level_id,
                entity_type="ExposureLevel",
                lookup_field="exposure_level_id",
            )
            current_state = uow.resource_states.get_current(
                command.tenant_id,
                command.resource_id,
            )
            if current_state is not None:
                _validate_existing_state_transition(command, current_state)
                current_state.valid_to = command.transitioned_at

            new_state = ResourceState(
                tenant_id=command.tenant_id,
                resource_id=command.resource_id,
                lifecycle_status_id=command.lifecycle_status_id,
                criticality_id=command.criticality_id,
                exposure_level_id=command.exposure_level_id,
                source_priority=command.source_priority,
                confidence_score=command.confidence_score,
                valid_from=command.transitioned_at,
                valid_to=None,
                source=command.source,
            )
            resource.lifecycle_status_id = command.lifecycle_status_id
            resource.criticality_id = command.criticality_id
            resource.exposure_level_id = command.exposure_level_id
            resource.source_priority = command.source_priority
            resource.confidence_score = command.confidence_score
            uow.resource_states.add(new_state)
            result = ResourceStateTransitionedResult(
                resource_id=command.resource_id,
                previous_state_id=(
                    current_state.id if current_state is not None else None
                ),
                new_state_id=new_state.id,
                transitioned_at=command.transitioned_at,
            )
            uow.commit()
            return result


class AssignResourceIdentifierHandler:
    """Command handler for assigning one current identifier to a resource."""

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    def handle(
        self,
        command: AssignResourceIdentifierCommand,
    ) -> ResourceIdentifierAssignedResult:
        """Append one identifier fact, commit once, and return a materialized result."""
        _validate_assign_resource_identifier_command(command)
        with self._uow_factory() as uow:
            resource = uow.resources.get_for_update(
                command.tenant_id,
                command.resource_id,
            )
            if resource is None:
                raise EntityNotFoundError(
                    "Resource not found",
                    entity_type="Resource",
                    lookup_field="resource_id",
                    lookup_value=command.resource_id,
                )
            _require_active_catalog(
                uow.identifier_types,
                command.identifier_type_id,
                entity_type="IdentifierType",
                lookup_field="identifier_type_id",
            )
            current_identifier = uow.resource_identifiers.find_current_by_value(
                command.tenant_id,
                command.identifier_type_id,
                command.normalized_value,
                command.namespace,
            )
            if current_identifier is not None:
                _validate_current_identifier_assignment(command, current_identifier)
            if command.is_primary:
                current_primary = uow.resource_identifiers.get_current_primary(
                    command.tenant_id,
                    command.resource_id,
                    command.identifier_type_id,
                )
                if current_primary is not None:
                    raise ConflictError(
                        "Resource identifier primary already exists",
                        entity_type="ResourceIdentifier",
                        conflict_field="current_primary",
                        conflict_value=command.identifier_type_id,
                    )

            identifier = ResourceIdentifier(
                tenant_id=command.tenant_id,
                resource_id=command.resource_id,
                identifier_type_id=command.identifier_type_id,
                namespace=command.namespace,
                normalized_value=command.normalized_value,
                original_value=command.original_value,
                value_hash=command.value_hash,
                is_primary=command.is_primary,
                valid_from=command.valid_from,
                valid_to=None,
                confidence_score=command.confidence_score,
            )
            uow.resource_identifiers.add(identifier)
            result = ResourceIdentifierAssignedResult(
                resource_id=command.resource_id,
                identifier_id=identifier.id,
                identifier_type_id=command.identifier_type_id,
                original_value=command.original_value,
                normalized_value=command.normalized_value,
                value_hash=command.value_hash,
                namespace=command.namespace,
                is_primary=command.is_primary,
                valid_from=command.valid_from,
            )
            uow.commit()
            return result


class AssignResourceOwnershipHandler:
    """Command handler for assigning one current owner to a resource."""

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    def handle(
        self,
        command: AssignResourceOwnershipCommand,
    ) -> ResourceOwnershipAssignedResult:
        """Append one ownership fact, commit once, and return a materialized result."""
        _validate_assign_resource_ownership_command(command)
        with self._uow_factory() as uow:
            resource = uow.resources.get_for_update(
                command.tenant_id,
                command.resource_id,
            )
            if resource is None:
                raise EntityNotFoundError(
                    "Resource not found",
                    entity_type="Resource",
                    lookup_field="resource_id",
                    lookup_value=command.resource_id,
                )
            organization = uow.organizations.get_by_id(
                command.tenant_id,
                command.organization_id,
            )
            if organization is None:
                raise EntityNotFoundError(
                    "Organization not found",
                    entity_type="Organization",
                    lookup_field="organization_id",
                    lookup_value=command.organization_id,
                )
            _require_active_catalog(
                uow.ownership_roles,
                command.ownership_role_id,
                entity_type="OwnershipRole",
                lookup_field="ownership_role_id",
            )
            current_ownership = uow.resource_ownerships.find_current(
                command.tenant_id,
                command.resource_id,
                command.organization_id,
                command.ownership_role_id,
            )
            if current_ownership is not None:
                raise ConflictError(
                    "Resource ownership is already assigned",
                    entity_type="ResourceOwnership",
                    conflict_field="current",
                    conflict_value=command.organization_id,
                )
            if command.is_primary:
                current_primary = uow.resource_ownerships.get_current_primary(
                    command.tenant_id,
                    command.resource_id,
                    command.ownership_role_id,
                )
                if current_primary is not None:
                    raise ConflictError(
                        "Resource ownership primary already exists",
                        entity_type="ResourceOwnership",
                        conflict_field="current_primary",
                        conflict_value=command.ownership_role_id,
                    )

            ownership = ResourceOwnership(
                tenant_id=command.tenant_id,
                resource_id=command.resource_id,
                organization_id=command.organization_id,
                ownership_role_id=command.ownership_role_id,
                is_primary=command.is_primary,
                confidence_score=command.confidence_score,
                valid_from=command.valid_from,
                valid_to=None,
                source=command.source,
            )
            uow.resource_ownerships.add(ownership)
            result = ResourceOwnershipAssignedResult(
                resource_id=command.resource_id,
                ownership_id=ownership.id,
                organization_id=command.organization_id,
                ownership_role_id=command.ownership_role_id,
                is_primary=command.is_primary,
                valid_from=command.valid_from,
                source=command.source,
            )
            uow.commit()
            return result


class AssignResourceClassificationHandler:
    """Command handler for assigning one current classification to a resource."""

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    def handle(
        self,
        command: AssignResourceClassificationCommand,
    ) -> ResourceClassificationAssignedResult:
        """Append one classification fact, commit once, and return a result."""
        _validate_assign_resource_classification_command(command)
        with self._uow_factory() as uow:
            resource = uow.resources.get_for_update(
                command.tenant_id,
                command.resource_id,
            )
            if resource is None:
                raise EntityNotFoundError(
                    "Resource not found",
                    entity_type="Resource",
                    lookup_field="resource_id",
                    lookup_value=command.resource_id,
                )
            _require_active_catalog(
                uow.classification_types,
                command.classification_type_id,
                entity_type="ClassificationType",
                lookup_field="classification_type_id",
            )
            classification_value = uow.classification_values.get_by_id(
                command.classification_value_id,
            )
            if classification_value is None:
                raise EntityNotFoundError(
                    "ClassificationValue not found",
                    entity_type="ClassificationValue",
                    lookup_field="classification_value_id",
                    lookup_value=command.classification_value_id,
                )
            if not classification_value.is_active:
                raise ConflictError(
                    "ClassificationValue is inactive",
                    entity_type="ClassificationValue",
                    conflict_field="classification_value_id",
                    conflict_value=command.classification_value_id,
                )
            if classification_value.classification_type_id != command.classification_type_id:
                raise ConflictError(
                    "ClassificationValue does not belong to ClassificationType",
                    entity_type="ClassificationValue",
                    conflict_field="classification_type_id",
                    conflict_value=command.classification_type_id,
                )
            current_classification = uow.resource_classifications.find_current(
                command.tenant_id,
                command.resource_id,
                command.classification_type_id,
                command.classification_value_id,
            )
            if current_classification is not None:
                raise ConflictError(
                    "Resource classification is already assigned",
                    entity_type="ResourceClassification",
                    conflict_field="current",
                    conflict_value=command.classification_value_id,
                )
            if command.is_primary:
                current_primary = uow.resource_classifications.get_current_primary(
                    command.tenant_id,
                    command.resource_id,
                    command.classification_type_id,
                )
                if current_primary is not None:
                    raise ConflictError(
                        "Resource classification primary already exists",
                        entity_type="ResourceClassification",
                        conflict_field="current_primary",
                        conflict_value=command.classification_type_id,
                    )

            classification = ResourceClassification(
                tenant_id=command.tenant_id,
                resource_id=command.resource_id,
                classification_type_id=command.classification_type_id,
                classification_value_id=command.classification_value_id,
                is_primary=command.is_primary,
                confidence_score=command.confidence_score,
                valid_from=command.valid_from,
                valid_to=None,
                source=command.source,
            )
            uow.resource_classifications.add(classification)
            result = ResourceClassificationAssignedResult(
                resource_id=command.resource_id,
                classification_id=classification.id,
                classification_type_id=command.classification_type_id,
                classification_value_id=command.classification_value_id,
                is_primary=command.is_primary,
                valid_from=command.valid_from,
                source=command.source,
            )
            uow.commit()
            return result


class AssignResourceLabelHandler:
    """Command handler for assigning one current label to a resource."""

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    def handle(
        self,
        command: AssignResourceLabelCommand,
    ) -> ResourceLabelAssignedResult:
        """Append one label assignment fact, commit once, and return a result."""
        _validate_assign_resource_label_command(command)
        with self._uow_factory() as uow:
            resource = uow.resources.get_for_update(
                command.tenant_id,
                command.resource_id,
            )
            if resource is None:
                raise EntityNotFoundError(
                    "Resource not found",
                    entity_type="Resource",
                    lookup_field="resource_id",
                    lookup_value=command.resource_id,
                )
            label = uow.labels.get_by_id(command.tenant_id, command.label_id)
            if label is None:
                raise EntityNotFoundError(
                    "Label not found",
                    entity_type="Label",
                    lookup_field="label_id",
                    lookup_value=command.label_id,
                )
            if not label.is_active:
                raise ConflictError(
                    "Label is inactive",
                    entity_type="Label",
                    conflict_field="label_id",
                    conflict_value=command.label_id,
                )
            current_label = uow.resource_labels.find_current(
                command.tenant_id,
                command.resource_id,
                command.label_id,
            )
            if current_label is not None:
                raise ConflictError(
                    "Resource label is already assigned",
                    entity_type="ResourceLabel",
                    conflict_field="current",
                    conflict_value=command.label_id,
                )

            resource_label = ResourceLabel(
                tenant_id=command.tenant_id,
                resource_id=command.resource_id,
                label_id=command.label_id,
                valid_from=command.valid_from,
                valid_to=None,
                source=command.source,
            )
            uow.resource_labels.add(resource_label)
            result = ResourceLabelAssignedResult(
                resource_id=command.resource_id,
                resource_label_id=resource_label.id,
                label_id=command.label_id,
                valid_from=command.valid_from,
                source=command.source,
            )
            uow.commit()
            return result


def _validate_create_resource_command(command: CreateResourceCommand) -> None:
    failures: list[ValidationFailure] = []
    if command.canonical_name.strip() == "":
        failures.append(ValidationFailure("canonical_name", "must not be blank"))
    if command.display_name.strip() == "":
        failures.append(ValidationFailure("display_name", "must not be blank"))
    if command.source_priority < 0 or command.source_priority > 1000:
        failures.append(
            ValidationFailure("source_priority", "must be between 0 and 1000")
        )
    if command.confidence_score < Decimal("0") or command.confidence_score > Decimal(
        "1"
    ):
        failures.append(
            ValidationFailure("confidence_score", "must be between 0 and 1")
        )
    first_seen_at_is_aware = (
        command.first_seen_at.tzinfo is not None
        and command.first_seen_at.utcoffset() is not None
    )
    last_seen_at_is_aware = (
        command.last_seen_at.tzinfo is not None
        and command.last_seen_at.utcoffset() is not None
    )
    if not first_seen_at_is_aware:
        failures.append(ValidationFailure("first_seen_at", "must be timezone-aware"))
    if not last_seen_at_is_aware:
        failures.append(ValidationFailure("last_seen_at", "must be timezone-aware"))
    if (
        first_seen_at_is_aware
        and last_seen_at_is_aware
        and command.last_seen_at < command.first_seen_at
    ):
        failures.append(
            ValidationFailure(
                "last_seen_at",
                "must not be earlier than first_seen_at",
            )
        )
    if failures:
        raise ValidationError(
            "Invalid resource creation command",
            failures=tuple(failures),
        )


def _validate_assign_resource_label_command(
    command: AssignResourceLabelCommand,
) -> None:
    failures: list[ValidationFailure] = []
    valid_from_is_aware = (
        command.valid_from.tzinfo is not None
        and command.valid_from.utcoffset() is not None
    )
    if not valid_from_is_aware:
        failures.append(ValidationFailure("valid_from", "must be timezone-aware"))
    if command.source is not None and command.source.strip() == "":
        failures.append(ValidationFailure("source", "must not be blank when provided"))
    if failures:
        raise ValidationError(
            "Invalid resource label assignment command",
            failures=tuple(failures),
        )


def _validate_assign_resource_classification_command(
    command: AssignResourceClassificationCommand,
) -> None:
    failures: list[ValidationFailure] = []
    if command.confidence_score < Decimal("0") or command.confidence_score > Decimal(
        "1"
    ):
        failures.append(
            ValidationFailure("confidence_score", "must be between 0 and 1")
        )
    valid_from_is_aware = (
        command.valid_from.tzinfo is not None
        and command.valid_from.utcoffset() is not None
    )
    if not valid_from_is_aware:
        failures.append(ValidationFailure("valid_from", "must be timezone-aware"))
    if command.source is not None and command.source.strip() == "":
        failures.append(ValidationFailure("source", "must not be blank when provided"))
    if failures:
        raise ValidationError(
            "Invalid resource classification assignment command",
            failures=tuple(failures),
        )


def _validate_assign_resource_ownership_command(
    command: AssignResourceOwnershipCommand,
) -> None:
    failures: list[ValidationFailure] = []
    if command.confidence_score < Decimal("0") or command.confidence_score > Decimal(
        "1"
    ):
        failures.append(
            ValidationFailure("confidence_score", "must be between 0 and 1")
        )
    valid_from_is_aware = (
        command.valid_from.tzinfo is not None
        and command.valid_from.utcoffset() is not None
    )
    if not valid_from_is_aware:
        failures.append(ValidationFailure("valid_from", "must be timezone-aware"))
    if command.source is not None and command.source.strip() == "":
        failures.append(ValidationFailure("source", "must not be blank when provided"))
    if failures:
        raise ValidationError(
            "Invalid resource ownership assignment command",
            failures=tuple(failures),
        )


def _validate_assign_resource_identifier_command(
    command: AssignResourceIdentifierCommand,
) -> None:
    failures: list[ValidationFailure] = []
    if command.original_value.strip() == "":
        failures.append(ValidationFailure("original_value", "must not be blank"))
    if command.normalized_value.strip() == "":
        failures.append(ValidationFailure("normalized_value", "must not be blank"))
    if command.value_hash.strip() == "":
        failures.append(ValidationFailure("value_hash", "must not be blank"))
    if command.namespace is not None and command.namespace.strip() == "":
        failures.append(ValidationFailure("namespace", "must not be blank when provided"))
    if command.confidence_score < Decimal("0") or command.confidence_score > Decimal(
        "1"
    ):
        failures.append(
            ValidationFailure("confidence_score", "must be between 0 and 1")
        )
    valid_from_is_aware = (
        command.valid_from.tzinfo is not None
        and command.valid_from.utcoffset() is not None
    )
    if not valid_from_is_aware:
        failures.append(ValidationFailure("valid_from", "must be timezone-aware"))
    if failures:
        raise ValidationError(
            "Invalid resource identifier assignment command",
            failures=tuple(failures),
        )


def _validate_transition_resource_state_command(
    command: TransitionResourceStateCommand,
) -> None:
    failures: list[ValidationFailure] = []
    if command.source_priority < 0 or command.source_priority > 1000:
        failures.append(
            ValidationFailure("source_priority", "must be between 0 and 1000")
        )
    if command.confidence_score < Decimal("0") or command.confidence_score > Decimal(
        "1"
    ):
        failures.append(
            ValidationFailure("confidence_score", "must be between 0 and 1")
        )
    transitioned_at_is_aware = (
        command.transitioned_at.tzinfo is not None
        and command.transitioned_at.utcoffset() is not None
    )
    if not transitioned_at_is_aware:
        failures.append(ValidationFailure("transitioned_at", "must be timezone-aware"))
    if command.source is not None and command.source.strip() == "":
        failures.append(ValidationFailure("source", "must not be blank when provided"))
    if failures:
        raise ValidationError(
            "Invalid resource state transition command",
            failures=tuple(failures),
        )


def _validate_current_identifier_assignment(
    command: AssignResourceIdentifierCommand,
    current_identifier: ResourceIdentifier,
) -> None:
    if current_identifier.resource_id == command.resource_id:
        raise ConflictError(
            "Resource identifier is already assigned",
            entity_type="ResourceIdentifier",
            conflict_field="current_value",
            conflict_value=command.normalized_value,
        )


def _validate_existing_state_transition(
    command: TransitionResourceStateCommand,
    current_state: ResourceState,
) -> None:
    if command.transitioned_at <= current_state.valid_from:
        raise ValidationError(
            "Invalid resource state transition command",
            failures=(
                ValidationFailure(
                    "transitioned_at",
                    "must be later than the current state's valid_from",
                ),
            ),
        )
    if (
        command.lifecycle_status_id == current_state.lifecycle_status_id
        and command.criticality_id == current_state.criticality_id
        and command.exposure_level_id == current_state.exposure_level_id
        and command.source_priority == current_state.source_priority
        and command.confidence_score == current_state.confidence_score
        and command.source == current_state.source
    ):
        raise ConflictError(
            "Resource state is unchanged",
            entity_type="ResourceState",
            conflict_field="state",
            conflict_value=command.resource_id,
        )


def _require_active_catalog(
    repository: object,
    catalog_id: object,
    *,
    entity_type: str,
    lookup_field: str,
) -> None:
    catalog = repository.get_by_id(catalog_id)
    if catalog is None:
        raise EntityNotFoundError(
            f"{entity_type} not found",
            entity_type=entity_type,
            lookup_field=lookup_field,
            lookup_value=catalog_id,
        )
    if not catalog.is_active:
        raise ConflictError(
            f"{entity_type} is inactive",
            entity_type=entity_type,
            conflict_field=lookup_field,
            conflict_value=catalog_id,
        )


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
