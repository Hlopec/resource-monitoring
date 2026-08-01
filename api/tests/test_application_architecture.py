from __future__ import annotations

import ast
import inspect
from pathlib import Path
from typing import get_type_hints

from app.application.errors import (
    ApplicationError,
    ConcurrentModificationError,
    ConflictError,
    EntityNotFoundError,
    PersistenceError,
    TenantBoundaryError,
)
from app.application.ports.repositories import (
    GlobalCatalogLookupRepository,
    TenantScopedLookupRepository,
)
from app.application.ports.unit_of_work import UnitOfWork

ROOT = Path(__file__).resolve().parents[1]
APPLICATION_ROOT = ROOT / "app" / "application"
PORTS_ROOT = APPLICATION_ROOT / "ports"

SQLALCHEMY_IMPORT_ROOTS = {"sqlalchemy"}
SQLALCHEMY_TYPE_NAMES = {"Session", "Select", "Query", "Row"}


def _python_files(path: Path) -> list[Path]:
    return sorted(candidate for candidate in path.rglob("*.py") if candidate.is_file())


def _imports_for(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def test_application_modules_do_not_import_sqlalchemy() -> None:
    for path in _python_files(APPLICATION_ROOT):
        imports = _imports_for(path)
        assert not any(
            imported.split(".", 1)[0] in SQLALCHEMY_IMPORT_ROOTS for imported in imports
        ), path


def test_ports_do_not_import_concrete_persistence_implementations() -> None:
    for path in _python_files(PORTS_ROOT):
        imports = _imports_for(path)
        assert not any(imported.startswith("app.persistence") for imported in imports), path


def test_application_packages_are_importable() -> None:
    import app.application
    import app.application.ports
    import app.persistence
    import app.persistence.sqlalchemy

    assert app.application.ApplicationError is ApplicationError
    assert app.application.ports.UnitOfWork is UnitOfWork
    assert app.persistence.__doc__
    assert app.persistence.sqlalchemy.__doc__


def test_application_error_hierarchy_is_explicit() -> None:
    assert issubclass(EntityNotFoundError, ApplicationError)
    assert issubclass(ConflictError, ApplicationError)
    assert issubclass(ConcurrentModificationError, ConflictError)
    assert issubclass(TenantBoundaryError, ApplicationError)
    assert issubclass(PersistenceError, ApplicationError)


def test_unit_of_work_protocol_declares_lifecycle_methods() -> None:
    expected_methods = {"__enter__", "__exit__", "commit", "rollback"}
    assert expected_methods.issubset(UnitOfWork.__dict__)


def test_repository_protocols_do_not_expose_optional_tenant_scope() -> None:
    for protocol in (TenantScopedLookupRepository,):
        for name, member in inspect.getmembers(protocol, inspect.isfunction):
            if name.startswith("_"):
                continue
            hints = get_type_hints(member)
            assert hints["tenant_id"] is not None
            assert "None" not in str(hints["tenant_id"])


def test_application_facing_ports_do_not_reference_sqlalchemy_types() -> None:
    for protocol in (
        TenantScopedLookupRepository,
        GlobalCatalogLookupRepository,
        UnitOfWork,
    ):
        for name, member in inspect.getmembers(protocol, inspect.isfunction):
            if name.startswith("_") and name not in {"__enter__", "__exit__"}:
                continue
            hints = get_type_hints(member)
            assert SQLALCHEMY_TYPE_NAMES.isdisjoint({str(value) for value in hints.values()})
