from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.settings import get_database_settings

engine: Engine = create_engine(get_database_settings().sqlalchemy_url, pool_pre_ping=True)


def create_session_factory(bind: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=bind, expire_on_commit=False)


SessionLocal: sessionmaker[Session] = create_session_factory(engine)


def get_session() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session


@contextmanager
def transaction_session() -> Generator[Session, None, None]:
    """Commit on successful exit; rollback and re-raise on any exception."""
    with SessionLocal() as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
