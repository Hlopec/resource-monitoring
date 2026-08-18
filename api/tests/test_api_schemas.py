from __future__ import annotations

import json
from dataclasses import fields
from datetime import UTC, datetime, timezone, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from fastapi import FastAPI
from pydantic import ValidationError

from app.api.mappers import resource_page_response, resource_summary_response
from app.api.schemas import (
    ApiDecimal,
    ApiSchema,
    ResourcePageResponse,
    ResourceSummaryResponse,
)
from app.application.results import ResourcePageResult, ResourceSummaryResult


class DecimalProbeResponse(ApiSchema):
    confidence_score: ApiDecimal


def _summary(
    *,
    resource_id: UUID = UUID("0198a4a2-0000-7000-8000-000000000001"),
    tenant_id: UUID = UUID("0198a4a2-0000-7000-8000-000000000002"),
    display_name: str | None = "Resource",
    primary_organization_id: UUID | None = UUID(
        "0198a4a2-0000-7000-8000-000000000005"
    ),
    primary_ownership_role_id: UUID | None = UUID(
        "0198a4a2-0000-7000-8000-000000000006"
    ),
    created_at: datetime = datetime(2026, 8, 18, 18, 30, tzinfo=UTC),
) -> ResourceSummaryResult:
    return ResourceSummaryResult(
        resource_id=resource_id,
        tenant_id=tenant_id,
        resource_type_id=UUID("0198a4a2-0000-7000-8000-000000000003"),
        lifecycle_status_id=UUID("0198a4a2-0000-7000-8000-000000000004"),
        canonical_name="api.example.com",
        display_name=display_name,
        primary_organization_id=primary_organization_id,
        primary_ownership_role_id=primary_ownership_role_id,
        record_version=7,
        first_seen_at=created_at,
        last_seen_at=created_at + timedelta(minutes=1),
        created_at=created_at,
        updated_at=created_at + timedelta(minutes=2),
    )


def test_uuid_values_serialize_as_canonical_json_strings() -> None:
    response = resource_summary_response(_summary())
    payload = json.loads(response.model_dump_json())

    assert payload["resource_id"] == "0198a4a2-0000-7000-8000-000000000001"
    assert payload["tenant_id"] == "0198a4a2-0000-7000-8000-000000000002"


def test_aware_utc_datetime_serializes_as_iso_8601() -> None:
    response = resource_summary_response(
        _summary(created_at=datetime(2026, 8, 18, 18, 30, tzinfo=UTC))
    )
    payload = json.loads(response.model_dump_json())

    assert payload["created_at"] in {
        "2026-08-18T18:30:00Z",
        "2026-08-18T18:30:00+00:00",
    }


def test_aware_non_utc_datetime_preserves_offset() -> None:
    offset = timezone(timedelta(hours=3))
    response = resource_summary_response(
        _summary(created_at=datetime(2026, 8, 18, 21, 30, tzinfo=offset))
    )
    payload = json.loads(response.model_dump_json())

    assert payload["created_at"] == "2026-08-18T21:30:00+03:00"


def test_naive_datetime_is_rejected_for_timestamp_fields() -> None:
    with pytest.raises(ValidationError):
        resource_summary_response(
            _summary(created_at=datetime(2026, 8, 18, 18, 30))
        )


def test_decimal_serializes_as_string_without_float_conversion() -> None:
    response = DecimalProbeResponse(confidence_score=Decimal("0.875"))
    payload = json.loads(response.model_dump_json())

    assert payload["confidence_score"] == "0.875"
    assert isinstance(payload["confidence_score"], str)


def test_high_precision_decimal_serializes_exactly() -> None:
    value = Decimal("0.123456789123456789123456789")
    response = DecimalProbeResponse(confidence_score=value)
    payload = json.loads(response.model_dump_json())

    assert payload["confidence_score"] == "0.123456789123456789123456789"


def test_cursor_is_preserved_exactly_or_serialized_as_null() -> None:
    opaque_cursor = "opaque.cursor+/=_unchanged"

    page = ResourcePageResponse(items=[], next_cursor=opaque_cursor)
    empty_page = ResourcePageResponse(items=[], next_cursor=None)

    assert json.loads(page.model_dump_json())["next_cursor"] == opaque_cursor
    assert json.loads(empty_page.model_dump_json())["next_cursor"] is None


def test_resource_summary_schema_matches_current_application_result_fields() -> None:
    result_fields = {field.name for field in fields(ResourceSummaryResult)}
    response_fields = set(ResourceSummaryResponse.model_fields)

    assert response_fields == result_fields


def test_resource_summary_mapping_preserves_nullable_and_scalar_values() -> None:
    result = _summary(
        display_name=None,
        primary_organization_id=None,
        primary_ownership_role_id=None,
    )

    response = resource_summary_response(result)
    payload = json.loads(response.model_dump_json())

    assert response.resource_id == result.resource_id
    assert response.canonical_name == "api.example.com"
    assert response.record_version == 7
    assert payload["display_name"] is None
    assert payload["primary_organization_id"] is None
    assert payload["primary_ownership_role_id"] is None


def test_resource_page_mapping_converts_tuple_to_ordered_json_array() -> None:
    first = _summary(
        resource_id=UUID("0198a4a2-0000-7000-8000-000000000011"),
        created_at=datetime(2026, 8, 18, 18, 30, tzinfo=UTC),
    )
    second = _summary(
        resource_id=UUID("0198a4a2-0000-7000-8000-000000000012"),
        created_at=datetime(2026, 8, 18, 18, 31, tzinfo=UTC),
    )
    result = ResourcePageResult(
        items=(first, second),
        next_cursor="opaque-next-cursor",
        page_size=2,
    )

    response = resource_page_response(result)
    payload = json.loads(response.model_dump_json())

    assert [item.resource_id for item in response.items] == [
        first.resource_id,
        second.resource_id,
    ]
    assert [item["resource_id"] for item in payload["items"]] == [
        str(first.resource_id),
        str(second.resource_id),
    ]
    assert payload["next_cursor"] == "opaque-next-cursor"


def test_resource_page_response_exposes_only_items_and_next_cursor() -> None:
    payload = json.loads(
        resource_page_response(
            ResourcePageResult(items=(), next_cursor=None, page_size=200)
        ).model_dump_json()
    )

    assert payload == {"items": [], "next_cursor": None}
    assert {"total_count", "offset", "page", "limit", "total_pages"}.isdisjoint(
        payload
    )


def test_api_schemas_do_not_use_orm_attribute_loading() -> None:
    assert ApiSchema.model_config.get("from_attributes") is False
    assert ResourceSummaryResponse.model_config.get("from_attributes") is False
    assert ResourcePageResponse.model_config.get("from_attributes") is False


def test_resource_page_schema_can_generate_openapi_component() -> None:
    app = FastAPI()

    @app.get("/test", response_model=ResourcePageResponse)
    def test_route() -> ResourcePageResponse:
        return ResourcePageResponse(items=[], next_cursor=None)

    schema = app.openapi()

    assert "ResourcePageResponse" in schema["components"]["schemas"]
    assert "ResourceSummaryResponse" in schema["components"]["schemas"]
