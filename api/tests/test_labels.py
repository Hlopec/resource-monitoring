from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Label, Tenant


def _tenant(session: Session, slug: str) -> Tenant:
    tenant = Tenant(slug=slug, display_name=slug.title(), status="active")
    session.add(tenant)
    session.flush()
    return tenant


def _label(
    tenant: Tenant,
    *,
    key: str = "environment",
    value: str = "Production",
    display_name: str | None = "Production",
    description: str | None = "Production resources",
    color: str | None = "#22AA66",
    is_active: bool = True,
) -> Label:
    return Label(
        tenant_id=tenant.id,
        key=key,
        value=value,
        display_name=display_name,
        description=description,
        color=color,
        is_active=is_active,
    )


def test_label_valid_insert(db_session: Session) -> None:
    tenant = _tenant(db_session, "tenant-a")
    label = _label(tenant)
    db_session.add(label)
    db_session.flush()

    assert label.id is not None
    assert label.key == "environment"
    assert label.value == "Production"


def test_label_allows_same_key_value_in_different_tenants(db_session: Session) -> None:
    tenant_a = _tenant(db_session, "tenant-a")
    tenant_b = _tenant(db_session, "tenant-b")
    db_session.add(_label(tenant_a))
    db_session.add(_label(tenant_b))
    db_session.flush()


def test_label_allows_same_key_with_different_values(db_session: Session) -> None:
    tenant = _tenant(db_session, "tenant-a")
    db_session.add(_label(tenant, value="Production"))
    db_session.add(_label(tenant, value="Staging"))
    db_session.flush()


def test_label_allows_inactive_label(db_session: Session) -> None:
    tenant = _tenant(db_session, "tenant-a")
    label = _label(tenant, is_active=False)
    db_session.add(label)
    db_session.flush()

    assert label.is_active is False


def test_label_allows_nullable_optional_metadata(db_session: Session) -> None:
    tenant = _tenant(db_session, "tenant-a")
    db_session.add(
        _label(
            tenant,
            display_name=None,
            description=None,
            color=None,
        )
    )
    db_session.flush()


def test_label_allows_valid_hex_color(db_session: Session) -> None:
    tenant = _tenant(db_session, "tenant-a")
    db_session.add(_label(tenant, color="#A1b2C3"))
    db_session.flush()


def test_label_orm_tenant_relationship(db_session: Session) -> None:
    tenant = _tenant(db_session, "tenant-a")
    label = _label(tenant)
    db_session.add(label)
    db_session.flush()

    assert label.tenant is tenant
    assert label in tenant.labels


def test_label_rejects_invalid_tenant(db_session: Session) -> None:
    label = Label(
        tenant_id=UUID("01984000-0000-7000-8000-ffffffffffff"),
        key="environment",
        value="Production",
        is_active=True,
    )
    db_session.add(label)

    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()
    assert "fk_label_tenant_id_tenant" in str(exc_info.value.orig)


@pytest.mark.parametrize(
    ("key", "constraint_name"),
    [
        ("", "ck_label_key_not_empty"),
        ("   ", "ck_label_key_not_empty"),
        ("Environment", "ck_label_key_lowercase"),
        (" environment", "ck_label_key_trimmed"),
        ("environment ", "ck_label_key_trimmed"),
    ],
)
def test_label_rejects_noncanonical_key(
    db_session: Session, key: str, constraint_name: str
) -> None:
    tenant = _tenant(db_session, "tenant-a")
    db_session.add(_label(tenant, key=key))

    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()
    assert constraint_name in str(exc_info.value.orig)


@pytest.mark.parametrize(
    ("value", "constraint_name"),
    [
        ("", "ck_label_value_not_empty"),
        ("   ", "ck_label_value_not_empty"),
        (" Production", "ck_label_value_trimmed"),
        ("Production ", "ck_label_value_trimmed"),
    ],
)
def test_label_rejects_noncanonical_value(
    db_session: Session, value: str, constraint_name: str
) -> None:
    tenant = _tenant(db_session, "tenant-a")
    db_session.add(_label(tenant, value=value))

    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()
    assert constraint_name in str(exc_info.value.orig)


@pytest.mark.parametrize("display_name", ["", "   "])
def test_label_rejects_empty_display_name_when_present(
    db_session: Session, display_name: str
) -> None:
    tenant = _tenant(db_session, "tenant-a")
    db_session.add(_label(tenant, display_name=display_name))

    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()
    assert "ck_label_display_name_not_empty" in str(exc_info.value.orig)


@pytest.mark.parametrize("description", ["", "   "])
def test_label_rejects_empty_description_when_present(
    db_session: Session, description: str
) -> None:
    tenant = _tenant(db_session, "tenant-a")
    db_session.add(_label(tenant, description=description))

    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()
    assert "ck_label_description_not_empty" in str(exc_info.value.orig)


@pytest.mark.parametrize("color", ["", "   ", "red", "#12345", "#1234567", "123456"])
def test_label_rejects_invalid_color(db_session: Session, color: str) -> None:
    tenant = _tenant(db_session, "tenant-a")
    db_session.add(_label(tenant, color=color))

    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()
    assert (
        "ck_label_color_not_empty" in str(exc_info.value.orig)
        or "ck_label_color_hex_format" in str(exc_info.value.orig)
    )


def test_label_rejects_duplicate_tenant_key_value(db_session: Session) -> None:
    tenant = _tenant(db_session, "tenant-a")
    db_session.add(_label(tenant))
    db_session.flush()
    db_session.add(_label(tenant, display_name="Duplicate"))

    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()
    assert "uq_label_tenant_id_key_value" in str(exc_info.value.orig)


def test_label_rejects_duplicate_inactive_label(db_session: Session) -> None:
    tenant = _tenant(db_session, "tenant-a")
    db_session.add(_label(tenant, is_active=False))
    db_session.flush()
    db_session.add(_label(tenant, display_name="Duplicate", is_active=False))

    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()
    assert "uq_label_tenant_id_key_value" in str(exc_info.value.orig)


def test_tenant_delete_is_restricted_while_label_exists(db_session: Session) -> None:
    tenant = _tenant(db_session, "tenant-a")
    db_session.add(_label(tenant))
    db_session.flush()

    with pytest.raises(IntegrityError):
        db_session.execute(delete(Tenant).where(Tenant.id == tenant.id))
        db_session.flush()
