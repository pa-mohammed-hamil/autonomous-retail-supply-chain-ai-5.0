from __future__ import annotations


"""
backend/database/session.py

Autonomous Retail Supply Chain AI 5.0

Centralized SQLAlchemy session management.

Python 3.10+
SQLAlchemy 2.x

Features:
- Reuses the existing database engine
- FastAPI session dependency
- Explicit transaction boundaries
- Automatic rollback on exceptions
- Tenant-aware session context
- Read-only transaction option
- Nested transaction savepoints
- Session lifecycle management
- Sync and async-compatible dependencies

Important:
This module uses synchronous SQLAlchemy sessions.
The async dependency is a convenience wrapper,
not a replacement for AsyncSession.
"""


from contextlib import contextmanager
from typing import Generator, Iterator

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.database.engine import (
    get_database_manager,
)


class DatabaseSessionError(RuntimeError):
    """Raised for invalid database session usage."""


def get_session_factory():
    """
    Return the existing session factory.

    Do not create another SQLAlchemy engine.
    """
    return get_database_manager().session_factory


def new_session() -> Session:
    """
    Create a new database session.

    Caller is responsible for closing it.
    """
    return get_session_factory()()


@contextmanager
def session_scope() -> Iterator[Session]:
    """
    Open and close a session.

    Does not commit automatically.
    """
    session = new_session()

    try:
        yield session

    except Exception:
        session.rollback()
        raise

    finally:
        session.close()


@contextmanager
def transaction_scope() -> Iterator[Session]:
    """
    Execute operations atomically.

    Commits on success.
    Rolls back on failure.
    """
    with session_scope() as session:
        try:
            yield session
            session.commit()

        except Exception:
            session.rollback()
            raise


@contextmanager
def read_only_scope() -> Iterator[Session]:
    """
    PostgreSQL read-only transaction.

    Prevents database writes inside
    this transaction.

    Requires PostgreSQL.
    """
    with session_scope() as session:
        with session.begin():
            session.execute(
                text(
                    "SET TRANSACTION READ ONLY"
                )
            )

            yield session


@contextmanager
def tenant_transaction(
    tenant_id: str,
) -> Iterator[Session]:
    """
    Tenant-scoped transaction context.

    Stores tenant identity in session.info
    and a PostgreSQL transaction-local setting.

    Repositories MUST still enforce tenant
    filtering, or PostgreSQL RLS must be
    configured to use this setting.
    """
    if (
        not isinstance(tenant_id, str)
        or not tenant_id.strip()
    ):
        raise DatabaseSessionError(
            "A valid tenant_id is required"
        )

    with session_scope() as session:
        try:
            with session.begin():
                session.info["tenant_id"] = tenant_id

                session.execute(
                    text(
                        "SELECT set_config("
                        "'app.current_tenant', "
                        ":tenant_id, true)"
                    ),
                    {"tenant_id": tenant_id},
                )

                yield session

        finally:
            session.info.pop(
                "tenant_id", None
            )


@contextmanager
def nested_transaction(
    session: Session,
) -> Iterator[Session]:
    """
    Create a SAVEPOINT within an
    existing transaction.

    Useful when a smaller operation may
    fail without aborting the outer unit
    of work.
    """
    if not session.in_transaction():
        raise DatabaseSessionError(
            "An active outer transaction "
            "is required"
        )

    with session.begin_nested():
        yield session


def get_db_session() -> Generator[
    Session, None, None
]:
    """
    FastAPI dependency.

    Does not automatically commit.
    """
    with session_scope() as session:
        yield session


def get_read_only_session() -> Generator[
    Session, None, None
]:
    """
    FastAPI read-only dependency.

    The transaction is rolled back
    if request processing fails.
    """
    with read_only_scope() as session:
        yield session


def require_tenant(
    session: Session,
    tenant_id: str,
) -> None:
    """
    Check that the session carries
    the expected tenant identity.

    This is a defense-in-depth check,
    not an authorization decision.
    """
    current = session.info.get(
        "tenant_id"
    )

    if current != tenant_id:
        raise DatabaseSessionError(
            "Database tenant context mismatch"
        )


def close_session(
    session: Session,
) -> None:
    """
    Explicit cleanup helper.
    """
    session.close()


if __name__ == "__main__":
    print(
        "Database session manager module loaded."
    )
    print(
        "Configure DATABASE_URL before "
        "opening a database session."
    )
