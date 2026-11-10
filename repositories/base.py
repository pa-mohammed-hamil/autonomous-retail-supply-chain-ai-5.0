from __future__ import annotations

"""Planned module: base. Implementation pending."""

"""
backend/repositories/base.py

Autonomous Retail Supply Chain AI 5.0

Requirements:
    pip install "sqlalchemy>=2.0,<3.0"

Shared SQLAlchemy repository foundation.

Features:
- Tenant-isolated CRUD
- Generic typed repository
- Pagination and filtering
- Optimistic concurrency
- Safe field updates
- Database transaction support
- No automatic commit inside repositories
"""


from typing import Any, Generic, TypeVar

from sqlalchemy import select, func
from sqlalchemy.orm import Session
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.orm.exc import StaleDataError


class Base(DeclarativeBase):
    pass


class TenantModel(Base):
    """
    Abstract base for tenant-owned records.
    """

    __abstract__ = True

    id: Mapped[str] = mapped_column(
        primary_key=True
    )

    tenant_id: Mapped[str] = mapped_column(
        index=True,
        nullable=False,
    )

    version: Mapped[int] = mapped_column(
        nullable=False,
        default=1,
    )

    __mapper_args__ = {
        "version_id_col": version,
    }


ModelT = TypeVar(
    "ModelT",
    bound=TenantModel,
)


class RepositoryError(Exception):
    pass


class RecordNotFound(RepositoryError):
    pass


class DuplicateRecord(RepositoryError):
    pass


class VersionConflict(RepositoryError):
    pass


class BaseRepository(Generic[ModelT]):
    """
    Shared tenant-aware repository.

    Authorization must be performed by
    a trusted service layer.

    Each repository instance is bound
    to exactly one tenant.
    """

    def __init__(
        self,
        session: Session,
        model: type[ModelT],
        tenant_id: str,
    ):
        if not tenant_id.strip():
            raise ValueError("Tenant ID required")

        self.session = session
        self.model = model
        self.tenant_id = tenant_id

    def _query(self):
        return select(self.model).where(
            self.model.tenant_id == self.tenant_id
        )

    def get(
        self,
        record_id: str,
    ) -> ModelT:
        statement = self._query().where(
            self.model.id == record_id
        )

        record = self.session.scalar(statement)

        if record is None:
            raise RecordNotFound(
                f"Record not found: {record_id}"
            )

        return record

    def get_optional(
        self,
        record_id: str,
    ) -> ModelT | None:
        statement = self._query().where(
            self.model.id == record_id
        )

        return self.session.scalar(statement)

    def create(
        self,
        record: ModelT,
    ) -> ModelT:
        if record.tenant_id != self.tenant_id:
            raise PermissionError(
                "Cross-tenant insert denied"
            )

        if self.get_optional(record.id) is not None:
            raise DuplicateRecord(
                "Record already exists"
            )

        self.session.add(record)
        self.session.flush()

        return record

    def list(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        filters: dict[str, Any] | None = None,
    ) -> list[ModelT]:
        if (
            type(limit) is not int
            or type(offset) is not int
            or not 1 <= limit <= 500
            or offset < 0
        ):
            raise ValueError("Invalid pagination")

        statement = self._query()

        for field, value in (filters or {}).items():
            if field in {
                "tenant_id",
                "id",
                "version",
            }:
                raise ValueError(
                    "Protected filter field"
                )

            if field not in self.model.__table__.columns:
                raise ValueError(
                    f"Unknown filter: {field}"
                )

            statement = statement.where(
                getattr(self.model, field) == value
            )

        statement = (
            statement
            .order_by(self.model.id)
            .limit(limit)
            .offset(offset)
        )

        return list(self.session.scalars(statement))

    def count(self) -> int:
        statement = (
            select(func.count())
            .select_from(self.model)
            .where(
                self.model.tenant_id == self.tenant_id
            )
        )

        return self.session.scalar(statement) or 0

    def update(
        self,
        record_id: str,
        expected_version: int,
        changes: dict[str, Any],
        allowed_fields: set[str],
    ) -> ModelT:
        if (
            type(expected_version) is not int
            or expected_version < 1
        ):
            raise ValueError("Invalid expected version")

        record = self.get(record_id)

        if record.version != expected_version:
            raise VersionConflict(
                "Record was modified concurrently"
            )

        protected = {
            "id",
            "tenant_id",
            "version",
        }

        if (
            not changes
            or not changes.keys() <= allowed_fields
            or changes.keys() & protected
        ):
            raise ValueError(
                "Invalid update fields"
            )

        for field, value in changes.items():
            if field not in self.model.__table__.columns:
                raise ValueError(
                    f"Unknown field: {field}"
                )

            setattr(record, field, value)

        try:
            self.session.flush()
        except StaleDataError as exc:
            raise VersionConflict(
                "Concurrent update detected"
            ) from exc

        return record

    def delete(
        self,
        record_id: str,
        expected_version: int,
    ) -> None:
        record = self.get(record_id)

        if record.version != expected_version:
            raise VersionConflict(
                "Version mismatch"
            )

        self.session.delete(record)

        try:
            self.session.flush()
        except StaleDataError as exc:
            raise VersionConflict(
                "Concurrent delete detected"
            ) from exc


class UnitOfWork:
    """
    Transaction boundary for multiple
    repository operations.

    Usage:
        with UnitOfWork(session):
            repository.create(record)
            # Additional operations
    """

    def __init__(self, session: Session):
        self.session = session

    def __enter__(self):
        self._transaction = self.session.begin()
        self._transaction.__enter__()
        return self

    def __exit__(
        self,
        exc_type,
        exc_value,
        traceback,
    ):
        return self._transaction.__exit__(
            exc_type,
            exc_value,
            traceback,
        )
