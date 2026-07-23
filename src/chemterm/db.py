"""Database engine and session management."""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from chemterm.config import get_settings


def create_database_engine(database_url: str | None = None) -> Engine:
    """Create a PostgreSQL SQLAlchemy engine."""

    settings = get_settings()
    return create_engine(
        database_url or settings.database_url,
        echo=settings.sql_echo,
        pool_pre_ping=True,
    )


engine = create_database_engine()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Provide a transactional session with rollback on failure."""

    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
