from __future__ import annotations

"""Planned module: engine. Implementation pending."""

"""
backend/database/engine.py

Autonomous Retail Supply Chain AI 5.0

Centralized SQLAlchemy database engine.

Features:
- PostgreSQL connection management
- Environment-based configuration
- Connection pooling
- Session lifecycle management
- Transaction context manager
- FastAPI session dependency
- Database health checks
- Explicit rollback on errors
- Safe connection disposal

Python 3.10+
SQLAlchemy 2.x
psycopg 3
"""


import logging
from contextlib import contextmanager
from functools import lru_cache
from typing import Generator, Iterator

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker


logger = logging.getLogger(__name__)


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = Field(
        ...,
        alias="DATABASE_URL",
    )

    database_echo: bool = Field(
        default=False,
        alias="DATABASE_ECHO",
    )

    database_pool_size: int = Field(
        default=10,
        ge=1,
        le=100,
        alias="DATABASE_POOL_SIZE",
    )

    database_max_overflow: int = Field(
        default=20,
        ge=0,
        le=200,
        alias="DATABASE_MAX_OVERFLOW",
    )

    database_pool_timeout: int = Field(
        default=30,
        ge=1,
        alias="DATABASE_POOL_TIMEOUT",
    )

    database_pool_recycle: int = Field(
        default=1800,
        ge=1,
        alias="DATABASE_POOL_RECYCLE",
    )


@lru_cache(maxsize=1)
def get_database_settings() -> DatabaseSettings:
    return DatabaseSettings()


class DatabaseManager:
    """
    Manages one SQLAlchemy engine and
    its associated session factory.

    Instantiate once per application process.
    """

    def __init__(
        self,
        settings: DatabaseSettings,
    ) -> None:
        self.settings = settings

        if not settings.database_url.startswith(
            (
                "postgresql+psycopg://",
                "postgresql://",
            )
        ):
            raise ValueError(
                "A PostgreSQL database URL is required"
            )

        self.engine: Engine = create_engine(
            settings.database_url,
            echo=settings.database_echo,
            pool_size=settings.database_pool_size,
            max_overflow=(
                settings.database_max_overflow
            ),
            pool_timeout=(
                settings.database_pool_timeout
            ),
            pool_recycle=(
                settings.database_pool_recycle
            ),
            pool_pre_ping=True,
            future=True,
            hide_parameters=True,
            connect_args={
                "connect_timeout": 10,
            },
        )

        self.session_factory = sessionmaker(
            bind=self.engine,
            class_=Session,
            autoflush=False,
            expire_on_commit=False,
        )

    def new_session(self) -> Session:
        return self.session_factory()

    @contextmanager
    def transaction(
        self,
    ) -> Iterator[Session]:
        """
        Commit only when the context
        exits successfully.

        Roll back on any exception.
        """
        with self.session_factory() as session:
            try:
                yield session
                session.commit()

            except Exception:
                session.rollback()
                raise

    def health_check(self) -> bool:
        try:
            with self.engine.connect() as connection:
                result = connection.execute(
                    text("SELECT 1")
                )

                return result.scalar_one() == 1

        except SQLAlchemyError:
            logger.exception(
                "Database health check failed"
            )
            return False

    def dispose(self) -> None:
        self.engine.dispose()
        logger.info(
            "Database connection pool disposed"
        )


@lru_cache(maxsize=1)
def get_database_manager() -> DatabaseManager:
    return DatabaseManager(
        get_database_settings()
    )


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency.

    Read and write operations share a
    request-scoped session.

    Commit is intentionally NOT automatic:
    service/unit-of-work boundaries should
    explicitly commit transactions.
    """
    manager = get_database_manager()

    with manager.new_session() as session:
        try:
            yield session
        except Exception:
            session.rollback()
            raise


@contextmanager
def database_transaction() -> Iterator[Session]:
    """
    Convenience transaction wrapper
    for background jobs and scripts.
    """
    manager = get_database_manager()

    with manager.transaction() as session:
        yield session


def database_health() -> dict[str, object]:
    manager = get_database_manager()

    healthy = manager.health_check()

    return {
        "database": "postgresql",
        "status": (
            "healthy" if healthy else "unhealthy"
        ),
        "connected": healthy,
    }


def close_database() -> None:
    """
    Call during application shutdown.
    """
    get_database_manager().dispose()


if __name__ == "__main__":
    print(database_health())
