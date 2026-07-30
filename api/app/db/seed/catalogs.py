from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    ClassificationType,
    ClassificationValue,
    IdentifierType,
    OwnershipRole,
    RelationshipType,
    ResourceType,
)


@dataclass(frozen=True)
class CatalogSeedResult:
    inserted: int
    existing: int


BASELINE_RESOURCE_TYPES = (
    {
        "id": UUID("01984000-0000-7000-8000-000000000101"),
        "code": "domain",
        "display_name": "Domain",
        "category": "internet",
        "schema_version": 1,
    },
    {
        "id": UUID("01984000-0000-7000-8000-000000000102"),
        "code": "ip",
        "display_name": "IP address",
        "category": "network",
        "schema_version": 1,
    },
)
BASELINE_IDENTIFIER_TYPES = (
    {
        "id": UUID("01984000-0000-7000-8000-000000000201"),
        "code": "fqdn",
        "display_name": "Fully qualified domain name",
        "normalization_strategy": "lowercase_idna",
        "uniqueness_scope": "tenant",
        "is_case_sensitive": False,
    },
    {
        "id": UUID("01984000-0000-7000-8000-000000000202"),
        "code": "ip_address",
        "display_name": "IP address",
        "normalization_strategy": "inet_canonical",
        "uniqueness_scope": "tenant",
        "is_case_sensitive": False,
    },
)
BASELINE_OWNERSHIP_ROLES = (
    {
        "id": UUID("01984000-0000-7000-8000-000000000301"),
        "code": "owner",
        "display_name": "Owner",
    },
    {
        "id": UUID("01984000-0000-7000-8000-000000000302"),
        "code": "custodian",
        "display_name": "Custodian",
    },
)
BASELINE_RELATIONSHIP_TYPES = (
    {
        "id": UUID("01984000-0000-7000-8000-000000000401"),
        "code": "depends_on",
        "display_name": "Depends on",
        "inverse_code": "supports",
        "is_directional": True,
        "is_transitive": False,
    },
)
BASELINE_CLASSIFICATION_TYPES = (
    {
        "id": UUID("01984000-0000-7000-8000-000000000501"),
        "code": "environment",
        "display_name": "Environment",
    },
)
BASELINE_CLASSIFICATION_VALUES = (
    {
        "id": UUID("01984000-0000-7000-8000-000000000601"),
        "classification_type_code": "environment",
        "code": "production",
        "display_name": "Production",
    },
    {
        "id": UUID("01984000-0000-7000-8000-000000000602"),
        "classification_type_code": "environment",
        "code": "staging",
        "display_name": "Staging",
    },
)


def _upsert_by_code(
    session: Session,
    model: type,
    records: Iterable[dict[str, object]],
) -> CatalogSeedResult:
    inserted = 0
    existing = 0
    for record in records:
        code = str(record["code"])
        instance = session.scalar(select(model).where(model.code == code))
        if instance is None:
            session.add(model(**record))
            inserted += 1
        else:
            existing += 1
    return CatalogSeedResult(inserted=inserted, existing=existing)


def seed_catalogs(session: Session) -> CatalogSeedResult:
    inserted = 0
    existing = 0

    for result in (
        _upsert_by_code(session, ResourceType, BASELINE_RESOURCE_TYPES),
        _upsert_by_code(session, IdentifierType, BASELINE_IDENTIFIER_TYPES),
        _upsert_by_code(session, OwnershipRole, BASELINE_OWNERSHIP_ROLES),
        _upsert_by_code(session, RelationshipType, BASELINE_RELATIONSHIP_TYPES),
        _upsert_by_code(session, ClassificationType, BASELINE_CLASSIFICATION_TYPES),
    ):
        inserted += result.inserted
        existing += result.existing

    session.flush()
    type_ids = {
        row.code: row.id for row in session.scalars(select(ClassificationType)).all()
    }

    for record in BASELINE_CLASSIFICATION_VALUES:
        type_code = str(record["classification_type_code"])
        code = str(record["code"])
        classification_type_id = type_ids[type_code]
        instance = session.scalar(
            select(ClassificationValue).where(
                ClassificationValue.classification_type_id == classification_type_id,
                ClassificationValue.code == code,
            )
        )
        if instance is None:
            payload = {
                "id": record["id"],
                "classification_type_id": classification_type_id,
                "code": code,
                "display_name": record["display_name"],
            }
            session.add(ClassificationValue(**payload))
            inserted += 1
        else:
            existing += 1

    return CatalogSeedResult(inserted=inserted, existing=existing)
