"""Small cursor helpers for application-level keyset pagination."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.application.errors import ValidationError, ValidationFailure

RESOURCE_LIST_CURSOR_VERSION = 1


@dataclass(frozen=True)
class ResourceListCursor:
    """Decoded position for Resource list keyset pagination."""

    created_at: datetime
    resource_id: UUID


def encode_resource_list_cursor(cursor: ResourceListCursor) -> str:
    payload = {
        "v": RESOURCE_LIST_CURSOR_VERSION,
        "created_at": cursor.created_at.isoformat(),
        "id": str(cursor.resource_id),
    }
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).decode("ascii")
    return encoded.rstrip("=")


def decode_resource_list_cursor(cursor: str | None) -> ResourceListCursor | None:
    if cursor is None:
        return None
    try:
        padded = cursor + ("=" * (-len(cursor) % 4))
        decoded = base64.urlsafe_b64decode(padded.encode("ascii"))
        payload = json.loads(decoded.decode("utf-8"))
    except Exception as exc:
        raise _invalid_cursor() from exc

    if not isinstance(payload, dict) or set(payload) != {"v", "created_at", "id"}:
        raise _invalid_cursor()
    if payload["v"] != RESOURCE_LIST_CURSOR_VERSION:
        raise _invalid_cursor()
    if not isinstance(payload["created_at"], str) or not isinstance(payload["id"], str):
        raise _invalid_cursor()

    try:
        created_at = datetime.fromisoformat(payload["created_at"])
        resource_id = UUID(payload["id"])
    except ValueError as exc:
        raise _invalid_cursor() from exc
    if created_at.tzinfo is None or created_at.utcoffset() is None:
        raise _invalid_cursor()

    return ResourceListCursor(created_at=created_at, resource_id=resource_id)


def _invalid_cursor() -> ValidationError:
    return ValidationError(
        "Invalid resource list cursor",
        failures=(ValidationFailure("cursor", "is invalid"),),
    )
