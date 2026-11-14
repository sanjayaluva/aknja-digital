"""Database engine, session management and declarative base.

Production database is PostgreSQL (authoritative live state, SRS §8).
A SQLite URL is tolerated for throwaway local experiments only; the
test suite runs against real PostgreSQL.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import MetaData, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings

_convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base with a stable naming convention for constraints."""

    metadata = MetaData(naming_convention=_convention)


def _configure_engine(url: str) -> Any:
    kwargs: dict[str, Any] = {}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        kwargs["pool_pre_ping"] = True
        kwargs["pool_size"] = 5
        kwargs["max_overflow"] = 10
    return create_engine(url, **kwargs)


_engine: Any = None
_SessionLocal: sessionmaker[Session] | None = None


def get_engine() -> Any:
    global _engine, _SessionLocal
    if _engine is None:
        settings = get_settings()
        _engine = _configure_engine(settings.database_url)
        if _engine.url.get_backend_name() == "sqlite":

            @event.listens_for(_engine, "connect")
            def _set_sqlite_pragma(dbapi_conn: Any, _record: Any) -> None:
                cursor = dbapi_conn.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()

        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def get_session_local() -> sessionmaker[Session]:
    get_engine()
    assert _SessionLocal is not None
    return _SessionLocal


def reset_engine() -> None:
    """Dispose cached engine (used by tests and config reloads)."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None


def create_testing_engine(url: str) -> Any:
    """Engine factory for the test suite (fresh PostgreSQL database per run)."""
    return create_engine(url, pool_pre_ping=True)
