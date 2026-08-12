"""Concrete synchronous SQLAlchemy Unit of Work."""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum
from types import TracebackType

from sqlalchemy.orm import Session

from app.models import (
    ClassificationType,
    Criticality,
    ExposureLevel,
    IdentifierType,
    LifecycleStatus,
    OwnershipRole,
    RelationshipType,
    ResourceType,
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
from app.persistence.sqlalchemy.errors import translate_sqlalchemy_error

SessionFactory = Callable[[], Session]


class UnitOfWorkError(RuntimeError):
    """Base class for SQLAlchemy Unit of Work lifecycle misuse."""


class UnitOfWorkNotActiveError(UnitOfWorkError):
    """The Unit of Work has no active session."""


class UnitOfWorkStateError(UnitOfWorkError):
    """The Unit of Work is in a state that rejects the requested operation."""


class _UnitOfWorkState(str, Enum):
    NEW = "new"
    ACTIVE = "active"
    COMMITTED = "committed"
    ROLLED_BACK = "rolled_back"
    FAILED = "failed"
    CLOSED = "closed"


class SQLAlchemyUnitOfWork:
    """Single-use synchronous SQLAlchemy Unit of Work.

    The ``session`` property is a concrete persistence-facing escape hatch for
    SQLAlchemy repositories. It is intentionally not part of the
    application-facing Unit of Work protocol.
    """

    def __init__(self, session_factory: SessionFactory | None = None) -> None:
        if session_factory is None:
            from app.db.session import SessionLocal

            session_factory = SessionLocal

        self._session_factory = session_factory
        self._session: Session | None = None
        self._tenants: SQLAlchemyTenantRepository | None = None
        self._organizations: SQLAlchemyOrganizationRepository | None = None
        self._resources: SQLAlchemyResourceRepository | None = None
        self._resource_types: SQLAlchemyManagedCatalogRepository[ResourceType] | None = None
        self._identifier_types: (
            SQLAlchemyManagedCatalogRepository[IdentifierType] | None
        ) = None
        self._relationship_types: (
            SQLAlchemyManagedCatalogRepository[RelationshipType] | None
        ) = None
        self._ownership_roles: (
            SQLAlchemyManagedCatalogRepository[OwnershipRole] | None
        ) = None
        self._classification_types: (
            SQLAlchemyManagedCatalogRepository[ClassificationType] | None
        ) = None
        self._classification_values: SQLAlchemyClassificationValueRepository | None = None
        self._lifecycle_statuses: (
            SQLAlchemyManagedCatalogRepository[LifecycleStatus] | None
        ) = None
        self._criticalities: SQLAlchemyManagedCatalogRepository[Criticality] | None = None
        self._exposure_levels: (
            SQLAlchemyManagedCatalogRepository[ExposureLevel] | None
        ) = None
        self._resource_identifiers: SQLAlchemyResourceIdentifierRepository | None = None
        self._resource_ownerships: SQLAlchemyResourceOwnershipRepository | None = None
        self._resource_relationships: SQLAlchemyResourceRelationshipRepository | None = None
        self._resource_classifications: (
            SQLAlchemyResourceClassificationRepository | None
        ) = None
        self._resource_labels: SQLAlchemyResourceLabelRepository | None = None
        self._resource_states: SQLAlchemyResourceStateRepository | None = None
        self._resource_aliases: SQLAlchemyResourceAliasRepository | None = None
        self._resource_merges: SQLAlchemyResourceMergeRepository | None = None
        self._state = _UnitOfWorkState.NEW

    def __enter__(self) -> SQLAlchemyUnitOfWork:
        if self._state is _UnitOfWorkState.ACTIVE:
            raise UnitOfWorkStateError("Unit of Work is already active")
        if self._state is not _UnitOfWorkState.NEW:
            raise UnitOfWorkStateError("Unit of Work instances are single-use")

        self._session = self._session_factory()
        self._state = _UnitOfWorkState.ACTIVE
        self._tenants = SQLAlchemyTenantRepository(self.session)
        self._organizations = SQLAlchemyOrganizationRepository(self.session)
        self._resources = SQLAlchemyResourceRepository(self.session)
        self._resource_types = SQLAlchemyManagedCatalogRepository(
            self.session,
            ResourceType,
        )
        self._identifier_types = SQLAlchemyManagedCatalogRepository(
            self.session,
            IdentifierType,
        )
        self._relationship_types = SQLAlchemyManagedCatalogRepository(
            self.session,
            RelationshipType,
        )
        self._ownership_roles = SQLAlchemyManagedCatalogRepository(
            self.session,
            OwnershipRole,
        )
        self._classification_types = SQLAlchemyManagedCatalogRepository(
            self.session,
            ClassificationType,
        )
        self._classification_values = SQLAlchemyClassificationValueRepository(
            self.session
        )
        self._lifecycle_statuses = SQLAlchemyManagedCatalogRepository(
            self.session,
            LifecycleStatus,
        )
        self._criticalities = SQLAlchemyManagedCatalogRepository(
            self.session,
            Criticality,
        )
        self._exposure_levels = SQLAlchemyManagedCatalogRepository(
            self.session,
            ExposureLevel,
        )
        self._resource_identifiers = SQLAlchemyResourceIdentifierRepository(self.session)
        self._resource_ownerships = SQLAlchemyResourceOwnershipRepository(self.session)
        self._resource_relationships = SQLAlchemyResourceRelationshipRepository(
            self.session
        )
        self._resource_classifications = SQLAlchemyResourceClassificationRepository(
            self.session
        )
        self._resource_labels = SQLAlchemyResourceLabelRepository(self.session)
        self._resource_states = SQLAlchemyResourceStateRepository(self.session)
        self._resource_aliases = SQLAlchemyResourceAliasRepository(self.session)
        self._resource_merges = SQLAlchemyResourceMergeRepository(self.session)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        session = self._session
        if session is not None:
            try:
                if exc_type is not None:
                    self._rollback_for_cleanup()
                elif self._state is not _UnitOfWorkState.COMMITTED:
                    self._rollback_for_cleanup()
            finally:
                session.close()
                self._session = None
                self._tenants = None
                self._organizations = None
                self._resources = None
                self._resource_types = None
                self._identifier_types = None
                self._relationship_types = None
                self._ownership_roles = None
                self._classification_types = None
                self._classification_values = None
                self._lifecycle_statuses = None
                self._criticalities = None
                self._exposure_levels = None
                self._resource_identifiers = None
                self._resource_ownerships = None
                self._resource_relationships = None
                self._resource_classifications = None
                self._resource_labels = None
                self._resource_states = None
                self._resource_aliases = None
                self._resource_merges = None
                self._state = _UnitOfWorkState.CLOSED

        return False

    @property
    def tenants(self) -> SQLAlchemyTenantRepository:
        """Return the active tenant repository."""
        self.session
        if self._tenants is None:
            raise UnitOfWorkNotActiveError("Tenant repository is not active")
        return self._tenants

    @property
    def organizations(self) -> SQLAlchemyOrganizationRepository:
        """Return the active organization repository."""
        self.session
        if self._organizations is None:
            raise UnitOfWorkNotActiveError("Organization repository is not active")
        return self._organizations

    @property
    def resources(self) -> SQLAlchemyResourceRepository:
        """Return the active resource repository."""
        self.session
        if self._resources is None:
            raise UnitOfWorkNotActiveError("Resource repository is not active")
        return self._resources

    @property
    def resource_types(self) -> SQLAlchemyManagedCatalogRepository[ResourceType]:
        """Return the active resource type catalog repository."""
        self.session
        if self._resource_types is None:
            raise UnitOfWorkNotActiveError("Resource type repository is not active")
        return self._resource_types

    @property
    def identifier_types(self) -> SQLAlchemyManagedCatalogRepository[IdentifierType]:
        """Return the active identifier type catalog repository."""
        self.session
        if self._identifier_types is None:
            raise UnitOfWorkNotActiveError("Identifier type repository is not active")
        return self._identifier_types

    @property
    def relationship_types(
        self,
    ) -> SQLAlchemyManagedCatalogRepository[RelationshipType]:
        """Return the active relationship type catalog repository."""
        self.session
        if self._relationship_types is None:
            raise UnitOfWorkNotActiveError("Relationship type repository is not active")
        return self._relationship_types

    @property
    def ownership_roles(self) -> SQLAlchemyManagedCatalogRepository[OwnershipRole]:
        """Return the active ownership role catalog repository."""
        self.session
        if self._ownership_roles is None:
            raise UnitOfWorkNotActiveError("Ownership role repository is not active")
        return self._ownership_roles

    @property
    def classification_types(
        self,
    ) -> SQLAlchemyManagedCatalogRepository[ClassificationType]:
        """Return the active classification type catalog repository."""
        self.session
        if self._classification_types is None:
            raise UnitOfWorkNotActiveError("Classification type repository is not active")
        return self._classification_types

    @property
    def classification_values(self) -> SQLAlchemyClassificationValueRepository:
        """Return the active classification value repository."""
        self.session
        if self._classification_values is None:
            raise UnitOfWorkNotActiveError("Classification value repository is not active")
        return self._classification_values

    @property
    def lifecycle_statuses(
        self,
    ) -> SQLAlchemyManagedCatalogRepository[LifecycleStatus]:
        """Return the active lifecycle status catalog repository."""
        self.session
        if self._lifecycle_statuses is None:
            raise UnitOfWorkNotActiveError("Lifecycle status repository is not active")
        return self._lifecycle_statuses

    @property
    def criticalities(self) -> SQLAlchemyManagedCatalogRepository[Criticality]:
        """Return the active criticality catalog repository."""
        self.session
        if self._criticalities is None:
            raise UnitOfWorkNotActiveError("Criticality repository is not active")
        return self._criticalities

    @property
    def exposure_levels(self) -> SQLAlchemyManagedCatalogRepository[ExposureLevel]:
        """Return the active exposure level catalog repository."""
        self.session
        if self._exposure_levels is None:
            raise UnitOfWorkNotActiveError("Exposure level repository is not active")
        return self._exposure_levels

    @property
    def resource_identifiers(self) -> SQLAlchemyResourceIdentifierRepository:
        """Return the active resource identifier repository."""
        self.session
        if self._resource_identifiers is None:
            raise UnitOfWorkNotActiveError("Resource identifier repository is not active")
        return self._resource_identifiers

    @property
    def resource_ownerships(self) -> SQLAlchemyResourceOwnershipRepository:
        """Return the active resource ownership repository."""
        self.session
        if self._resource_ownerships is None:
            raise UnitOfWorkNotActiveError("Resource ownership repository is not active")
        return self._resource_ownerships

    @property
    def resource_relationships(self) -> SQLAlchemyResourceRelationshipRepository:
        """Return the active resource relationship repository."""
        self.session
        if self._resource_relationships is None:
            raise UnitOfWorkNotActiveError(
                "Resource relationship repository is not active"
            )
        return self._resource_relationships

    @property
    def resource_classifications(self) -> SQLAlchemyResourceClassificationRepository:
        """Return the active resource classification repository."""
        self.session
        if self._resource_classifications is None:
            raise UnitOfWorkNotActiveError(
                "Resource classification repository is not active"
            )
        return self._resource_classifications

    @property
    def resource_labels(self) -> SQLAlchemyResourceLabelRepository:
        """Return the active resource label repository."""
        self.session
        if self._resource_labels is None:
            raise UnitOfWorkNotActiveError("Resource label repository is not active")
        return self._resource_labels

    @property
    def resource_states(self) -> SQLAlchemyResourceStateRepository:
        """Return the active resource state repository."""
        self.session
        if self._resource_states is None:
            raise UnitOfWorkNotActiveError("Resource state repository is not active")
        return self._resource_states

    @property
    def resource_aliases(self) -> SQLAlchemyResourceAliasRepository:
        """Return the active resource alias repository."""
        self.session
        if self._resource_aliases is None:
            raise UnitOfWorkNotActiveError("Resource alias repository is not active")
        return self._resource_aliases

    @property
    def resource_merges(self) -> SQLAlchemyResourceMergeRepository:
        """Return the active resource merge repository."""
        self.session
        if self._resource_merges is None:
            raise UnitOfWorkNotActiveError("Resource merge repository is not active")
        return self._resource_merges

    @property
    def session(self) -> Session:
        """Return the active SQLAlchemy session for infrastructure adapters."""
        session = self._require_session()
        if self._state is not _UnitOfWorkState.ACTIVE:
            raise UnitOfWorkNotActiveError("Unit of Work is not active")
        if not session.is_active:
            self._state = _UnitOfWorkState.FAILED
            raise UnitOfWorkStateError("Unit of Work transaction has failed")
        return session

    def commit(self) -> None:
        session = self._require_session()
        if self._state is _UnitOfWorkState.ROLLED_BACK:
            raise UnitOfWorkStateError("Cannot commit after rollback")
        if self._state is _UnitOfWorkState.COMMITTED:
            raise UnitOfWorkStateError("Unit of Work has already committed")
        if self._state is _UnitOfWorkState.FAILED or not session.is_active:
            self._state = _UnitOfWorkState.FAILED
            raise UnitOfWorkStateError("Cannot commit a failed transaction")
        if self._state is not _UnitOfWorkState.ACTIVE:
            raise UnitOfWorkNotActiveError("Unit of Work is not active")

        try:
            session.commit()
        except Exception as exc:
            self._state = _UnitOfWorkState.FAILED
            translated = translate_sqlalchemy_error(exc)
            if translated is exc:
                raise
            raise translated from exc

        self._state = _UnitOfWorkState.COMMITTED

    def rollback(self) -> None:
        session = self._require_session()
        if self._state is _UnitOfWorkState.COMMITTED:
            raise UnitOfWorkStateError("Cannot roll back after commit")
        if self._state is not _UnitOfWorkState.ROLLED_BACK:
            session.rollback()
            self._state = _UnitOfWorkState.ROLLED_BACK

    def _rollback_for_cleanup(self) -> None:
        if self._session is None:
            return
        if self._state is _UnitOfWorkState.COMMITTED:
            return
        self._session.rollback()
        if self._state is not _UnitOfWorkState.CLOSED:
            self._state = _UnitOfWorkState.ROLLED_BACK

    def _require_session(self) -> Session:
        if self._session is None:
            raise UnitOfWorkNotActiveError("Unit of Work is not active")
        if self._state is _UnitOfWorkState.CLOSED:
            raise UnitOfWorkNotActiveError("Unit of Work is closed")
        return self._session
