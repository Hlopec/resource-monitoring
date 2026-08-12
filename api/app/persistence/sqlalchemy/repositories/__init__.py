"""Internal SQLAlchemy repository infrastructure."""

from app.persistence.sqlalchemy.repositories.base import (
    RepositoryT,
    SQLAlchemyRepository,
    bind_repository,
)
from app.persistence.sqlalchemy.repositories.catalogs import (
    SQLAlchemyClassificationValueRepository,
    SQLAlchemyManagedCatalogRepository,
)
from app.persistence.sqlalchemy.repositories.helpers import (
    apply_for_update,
    entity_select,
    tenant_entity_select,
    tenant_select,
    with_options,
)
from app.persistence.sqlalchemy.repositories.lineage import (
    SQLAlchemyResourceAliasRepository,
    SQLAlchemyResourceMergeRepository,
)
from app.persistence.sqlalchemy.repositories.labels import SQLAlchemyLabelRepository
from app.persistence.sqlalchemy.repositories.organizations import (
    SQLAlchemyOrganizationRepository,
)
from app.persistence.sqlalchemy.repositories.resources import SQLAlchemyResourceRepository
from app.persistence.sqlalchemy.repositories.tenant_scoped import (
    TenantScopedSQLAlchemyRepository,
)
from app.persistence.sqlalchemy.repositories.tenants import SQLAlchemyTenantRepository
from app.persistence.sqlalchemy.repositories.temporal import (
    SQLAlchemyResourceClassificationRepository,
    SQLAlchemyResourceIdentifierRepository,
    SQLAlchemyResourceLabelRepository,
    SQLAlchemyResourceOwnershipRepository,
    SQLAlchemyResourceRelationshipRepository,
    SQLAlchemyResourceStateRepository,
    current_temporal_statement,
)

__all__ = [
    "RepositoryT",
    "SQLAlchemyClassificationValueRepository",
    "SQLAlchemyLabelRepository",
    "SQLAlchemyManagedCatalogRepository",
    "SQLAlchemyOrganizationRepository",
    "SQLAlchemyResourceAliasRepository",
    "SQLAlchemyResourceClassificationRepository",
    "SQLAlchemyResourceIdentifierRepository",
    "SQLAlchemyResourceLabelRepository",
    "SQLAlchemyResourceMergeRepository",
    "SQLAlchemyResourceOwnershipRepository",
    "SQLAlchemyResourceRelationshipRepository",
    "SQLAlchemyResourceRepository",
    "SQLAlchemyResourceStateRepository",
    "SQLAlchemyRepository",
    "SQLAlchemyTenantRepository",
    "TenantScopedSQLAlchemyRepository",
    "apply_for_update",
    "bind_repository",
    "current_temporal_statement",
    "entity_select",
    "tenant_entity_select",
    "tenant_select",
    "with_options",
]
