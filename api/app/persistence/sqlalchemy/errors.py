"""Translate known SQLAlchemy persistence errors at the adapter boundary."""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

from app.application.errors import ConcurrentModificationError, ConflictError

UNIQUE_VIOLATION = "23505"


def _conflict(
    message: str,
    *,
    entity_type: str,
    conflict_field: str,
) -> Callable[[str], ConflictError]:
    def build(constraint: str) -> ConflictError:
        return ConflictError(
            message,
            entity_type=entity_type,
            conflict_field=conflict_field,
            constraint=constraint,
        )

    return build


CONSTRAINT_TRANSLATORS: dict[str, Callable[[str], ConflictError]] = {
    "uq_resource_state_current": _conflict(
        "Resource state conflicts with an existing current state",
        entity_type="ResourceState",
        conflict_field="current",
    ),
    "uq_resource_identifier_current_value": _conflict(
        "Resource identifier conflicts with an existing current value",
        entity_type="ResourceIdentifier",
        conflict_field="current_value",
    ),
    "uq_resource_identifier_current_primary": _conflict(
        "Resource identifier conflicts with an existing current primary identifier",
        entity_type="ResourceIdentifier",
        conflict_field="current_primary",
    ),
    "uq_resource_ownership_current": _conflict(
        "Resource ownership conflicts with an existing current ownership",
        entity_type="ResourceOwnership",
        conflict_field="current",
    ),
    "uq_resource_ownership_current_primary": _conflict(
        "Resource ownership conflicts with an existing current primary ownership",
        entity_type="ResourceOwnership",
        conflict_field="current_primary",
    ),
    "uq_resource_classification_current_value": _conflict(
        "Resource classification conflicts with an existing current classification",
        entity_type="ResourceClassification",
        conflict_field="current_value",
    ),
    "uq_resource_classification_current_primary_type": _conflict(
        "Resource classification conflicts with an existing current primary classification",
        entity_type="ResourceClassification",
        conflict_field="current_primary",
    ),
    "uq_resource_label_current": _conflict(
        "Resource label conflicts with an existing current assignment",
        entity_type="ResourceLabel",
        conflict_field="current",
    ),
    "uq_resource_alias_tenant_alias_type_normalized_value": _conflict(
        "Resource alias already resolves to a resource",
        entity_type="ResourceAlias",
        conflict_field="alias",
    ),
    "uq_resource_merge_tenant_source_resource_id": _conflict(
        "Resource merge already exists for the source resource",
        entity_type="ResourceMerge",
        conflict_field="source_resource_id",
    ),
}


def translate_sqlalchemy_error(exc: Exception) -> Exception:
    """Return a technology-neutral error for known SQLAlchemy failures."""
    if isinstance(exc, IntegrityError):
        return translate_integrity_error(exc)
    if isinstance(exc, StaleDataError):
        return translate_stale_data_error(exc)
    return exc


def translate_integrity_error(exc: IntegrityError) -> Exception:
    """Translate explicitly mapped PostgreSQL integrity constraints."""
    sqlstate = _sqlstate(exc)
    constraint = _constraint_name(exc)
    if sqlstate != UNIQUE_VIOLATION or constraint is None:
        return exc

    translator = CONSTRAINT_TRANSLATORS.get(constraint)
    if translator is None:
        return exc
    return translator(constraint)


def translate_stale_data_error(exc: StaleDataError) -> ConcurrentModificationError:
    """Translate SQLAlchemy optimistic concurrency failures."""
    return ConcurrentModificationError(
        "Resource was modified concurrently",
        entity_type="Resource",
        conflict_field="record_version",
    )


def _sqlstate(exc: IntegrityError) -> str | None:
    original = exc.orig
    sqlstate = getattr(original, "sqlstate", None)
    if sqlstate is not None:
        return str(sqlstate)
    pgcode = getattr(original, "pgcode", None)
    if pgcode is not None:
        return str(pgcode)
    return None


def _constraint_name(exc: IntegrityError) -> str | None:
    diag = getattr(exc.orig, "diag", None)
    constraint_name = getattr(diag, "constraint_name", None)
    if constraint_name is not None:
        return str(constraint_name)
    return None
