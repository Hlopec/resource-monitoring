"""Application-facing persistence contracts."""

from app.application.ports.catalogs import (
    ClassificationValueRepository,
    ManagedCatalogRepository,
)
from app.application.ports.labels import LabelRepository
from app.application.ports.lineage import (
    ResourceAliasRepository,
    ResourceMergeRepository,
)
from app.application.ports.organizations import OrganizationRepository
from app.application.ports.repositories import (
    GlobalCatalogLookupRepository,
    TenantScopedLookupRepository,
)
from app.application.ports.resources import ResourceRepository
from app.application.ports.resource_queries import (
    ResourceAliasProjection,
    ResourceAliasLookupProjection,
    ResourceClassificationProjection,
    ResourceDetailsProjection,
    ResourceIdentifierProjection,
    ResourceIdentifierLookupProjection,
    ResourceLabelProjection,
    ResourceMergeProjection,
    ResourceOwnershipProjection,
    ResourceQueryPage,
    ResourceQueryService,
    ResourceStateProjection,
    ResourceSummaryProjection,
)
from app.application.ports.temporal import (
    ResourceClassificationRepository,
    ResourceIdentifierRepository,
    ResourceLabelRepository,
    ResourceOwnershipRepository,
    ResourceRelationshipRepository,
    ResourceStateRepository,
)
from app.application.ports.tenants import TenantRepository
from app.application.ports.unit_of_work import UnitOfWork, UnitOfWorkFactory

__all__ = [
    "ClassificationValueRepository",
    "GlobalCatalogLookupRepository",
    "LabelRepository",
    "ManagedCatalogRepository",
    "OrganizationRepository",
    "ResourceAliasRepository",
    "ResourceAliasProjection",
    "ResourceClassificationRepository",
    "ResourceClassificationProjection",
    "ResourceDetailsProjection",
    "ResourceIdentifierProjection",
    "ResourceIdentifierRepository",
    "ResourceLabelRepository",
    "ResourceLabelProjection",
    "ResourceMergeProjection",
    "ResourceMergeRepository",
    "ResourceOwnershipRepository",
    "ResourceOwnershipProjection",
    "ResourceAliasLookupProjection",
    "ResourceIdentifierLookupProjection",
    "ResourceQueryPage",
    "ResourceQueryService",
    "ResourceRelationshipRepository",
    "ResourceRepository",
    "ResourceStateRepository",
    "ResourceStateProjection",
    "ResourceSummaryProjection",
    "TenantRepository",
    "TenantScopedLookupRepository",
    "UnitOfWork",
    "UnitOfWorkFactory",
]
