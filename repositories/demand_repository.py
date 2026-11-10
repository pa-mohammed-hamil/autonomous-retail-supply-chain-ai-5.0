from __future__ import annotations

"""Planned module: demand repository. Implementation pending."""

"""
backend/repositories/demand_repository.py

Autonomous Retail Supply Chain AI 5.0

Requirements:
    pip install "sqlalchemy>=2.0,<3.0"

Depends on:
    backend/repositories/base.py

Features:
- Tenant-scoped demand history
- Idempotent source event ingestion
- Historical aggregation
- Versioned forecast batches
- Forecast horizon records
- Optimistic concurrency
- SQLAlchemy persistence
"""


from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
    select,
)
from sqlalchemy.orm import (
    Mapped,
    Session,
    mapped_column,
)

from backend.repositories.base import (
    BaseRepository,
    TenantModel,
    VersionConflict,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def required(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")
    return value.strip()


def valid_quantity(value: int) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(
            "Quantity must be a non-negative integer"
        )
    return value


class ForecastStatus(str, Enum):
    DRAFT = "draft"
    APPROVED = "approved"
    ARCHIVED = "archived"


class DemandHistory(TenantModel):
    __tablename__ = "demand_history"

    sku: Mapped[str] = mapped_column(
        String(100), nullable=False
    )
    warehouse_id: Mapped[str] = mapped_column(
        String(100), nullable=False
    )
    demand_date: Mapped[date] = mapped_column(
        Date, nullable=False
    )
    quantity: Mapped[int] = mapped_column(
        Integer, nullable=False
    )
    source_event_id: Mapped[str] = mapped_column(
        String(150), nullable=False
    )
    source_system: Mapped[str] = mapped_column(
        String(100), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "source_event_id",
            name="uq_demand_source_event",
        ),
        CheckConstraint(
            "quantity >= 0",
            name="ck_demand_quantity",
        ),
        Index(
            "ix_demand_lookup",
            "tenant_id",
            "warehouse_id",
            "sku",
            "demand_date",
        ),
    )


class DemandForecastBatch(TenantModel):
    __tablename__ = "demand_forecast_batches"

    sku: Mapped[str] = mapped_column(
        String(100), nullable=False
    )
    warehouse_id: Mapped[str] = mapped_column(
        String(100), nullable=False
    )
    model_name: Mapped[str] = mapped_column(
        String(100), nullable=False
    )
    model_version: Mapped[str] = mapped_column(
        String(50), nullable=False
    )
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(30),
        default=ForecastStatus.DRAFT.value,
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "id",
            name="uq_forecast_batch_tenant_id",
        ),
        Index(
            "ix_forecast_batch_lookup",
            "tenant_id",
            "warehouse_id",
            "sku",
            "generated_at",
        ),
    )


class DemandForecastPoint(TenantModel):
    __tablename__ = "demand_forecast_points"

    batch_id: Mapped[str] = mapped_column(
        String(100), nullable=False
    )
    forecast_date: Mapped[date] = mapped_column(
        Date, nullable=False
    )
    predicted_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 3), nullable=False
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "batch_id"],
            [
                "demand_forecast_batches.tenant_id",
                "demand_forecast_batches.id",
            ],
            name="fk_forecast_point_batch",
        ),
        UniqueConstraint(
            "tenant_id",
            "batch_id",
            "forecast_date",
            name="uq_forecast_point_date",
        ),
        CheckConstraint(
            "predicted_quantity >= 0",
            name="ck_forecast_quantity",
        ),
    )


class DemandRepository(
    BaseRepository[DemandHistory]
):
    def __init__(
        self,
        session: Session,
        tenant_id: str,
    ):
        super().__init__(
            session, DemandHistory, tenant_id
        )

    def ingest(
        self,
        *,
        sku: str,
        warehouse_id: str,
        demand_date: date,
        quantity: int,
        source_event_id: str,
        source_system: str = "sales",
    ) -> DemandHistory:
        sku = required(sku, "sku")
        warehouse_id = required(
            warehouse_id, "warehouse_id"
        )
        source_event_id = required(
            source_event_id, "source_event_id"
        )
        source_system = required(
            source_system, "source_system"
        )
        valid_quantity(quantity)

        if type(demand_date) is not date:
            raise ValueError("Invalid demand date")

        existing = self.session.scalar(
            select(DemandHistory).where(
                DemandHistory.tenant_id
                == self.tenant_id,
                DemandHistory.source_event_id
                == source_event_id,
            )
        )

        if existing is not None:
            if (
                existing.sku != sku
                or existing.warehouse_id != warehouse_id
                or existing.demand_date != demand_date
                or existing.quantity != quantity
                or existing.source_system != source_system
            ):
                raise ValueError(
                    "Conflicting source event"
                )
            return existing

        record = DemandHistory(
            id=str(uuid4()),
            tenant_id=self.tenant_id,
            sku=sku,
            warehouse_id=warehouse_id,
            demand_date=demand_date,
            quantity=quantity,
            source_event_id=source_event_id,
            source_system=source_system,
        )

        return self.create(record)

    def history(
        self,
        *,
        sku: str,
        warehouse_id: str,
        start_date: date,
        end_date: date,
    ) -> list[DemandHistory]:
        if start_date > end_date:
            raise ValueError("Invalid date range")

        statement = (
            self._query()
            .where(
                DemandHistory.sku == sku,
                DemandHistory.warehouse_id
                == warehouse_id,
                DemandHistory.demand_date
                >= start_date,
                DemandHistory.demand_date
                <= end_date,
            )
            .order_by(
                DemandHistory.demand_date,
                DemandHistory.id,
            )
        )

        return list(
            self.session.scalars(statement)
        )

    def daily_totals(
        self,
        *,
        sku: str,
        warehouse_id: str,
        start_date: date,
        end_date: date,
    ) -> list[dict]:
        if start_date > end_date:
            raise ValueError("Invalid date range")

        statement = (
            select(
                DemandHistory.demand_date,
                func.sum(
                    DemandHistory.quantity
                ).label("total_quantity"),
            )
            .where(
                DemandHistory.tenant_id
                == self.tenant_id,
                DemandHistory.sku == sku,
                DemandHistory.warehouse_id
                == warehouse_id,
                DemandHistory.demand_date
                >= start_date,
                DemandHistory.demand_date
                <= end_date,
            )
            .group_by(
                DemandHistory.demand_date
            )
            .order_by(
                DemandHistory.demand_date
            )
        )

        return [
            {
                "date": row.demand_date.isoformat(),
                "quantity": int(
                    row.total_quantity
                ),
            }
            for row in self.session.execute(
                statement
            )
        ]

    def total_demand(
        self,
        *,
        sku: str,
        warehouse_id: str,
        start_date: date,
        end_date: date,
    ) -> int:
        return sum(
            row["quantity"]
            for row in self.daily_totals(
                sku=sku,
                warehouse_id=warehouse_id,
                start_date=start_date,
                end_date=end_date,
            )
        )


class DemandForecastRepository(
    BaseRepository[DemandForecastBatch]
):
    def __init__(
        self,
        session: Session,
        tenant_id: str,
    ):
        super().__init__(
            session,
            DemandForecastBatch,
            tenant_id,
        )

    def create_forecast(
        self,
        *,
        sku: str,
        warehouse_id: str,
        model_name: str,
        model_version: str,
        predictions: dict[date, Decimal],
    ) -> DemandForecastBatch:
        if not predictions:
            raise ValueError(
                "Forecast predictions required"
            )

        if any(
            type(day) is not date
            for day in predictions
        ):
            raise ValueError(
                "Forecast dates must be dates"
            )

        if any(
            not isinstance(qty, Decimal)
            or not qty.is_finite()
            or qty < 0
            for qty in predictions.values()
        ):
            raise ValueError(
                "Predictions must be non-negative "
                "finite Decimal values"
            )

        batch = DemandForecastBatch(
            id=str(uuid4()),
            tenant_id=self.tenant_id,
            sku=required(sku, "sku"),
            warehouse_id=required(
                warehouse_id, "warehouse_id"
            ),
            model_name=required(
                model_name, "model_name"
            ),
            model_version=required(
                model_version, "model_version"
            ),
            status=ForecastStatus.DRAFT.value,
        )

        self.create(batch)

        for forecast_date, quantity in sorted(
            predictions.items()
        ):
            self.session.add(
                DemandForecastPoint(
                    id=str(uuid4()),
                    tenant_id=self.tenant_id,
                    batch_id=batch.id,
                    forecast_date=forecast_date,
                    predicted_quantity=quantity,
                )
            )

        self.session.flush()
        return batch

    def forecast_points(
        self,
        batch_id: str,
    ) -> list[DemandForecastPoint]:
        self.get(batch_id)

        statement = (
            select(DemandForecastPoint)
            .where(
                DemandForecastPoint.tenant_id
                == self.tenant_id,
                DemandForecastPoint.batch_id
                == batch_id,
            )
            .order_by(
                DemandForecastPoint.forecast_date
            )
        )

        return list(
            self.session.scalars(statement)
        )

    def latest_forecast(
        self,
        *,
        sku: str,
        warehouse_id: str,
        approved_only: bool = True,
    ) -> DemandForecastBatch | None:
        statement = self._query().where(
            DemandForecastBatch.sku == sku,
            DemandForecastBatch.warehouse_id
            == warehouse_id,
        )

        if approved_only:
            statement = statement.where(
                DemandForecastBatch.status
                == ForecastStatus.APPROVED.value
            )

        statement = (
            statement
            .order_by(
                DemandForecastBatch.generated_at.desc(),
                DemandForecastBatch.id.desc(),
            )
            .limit(1)
        )

        return self.session.scalar(statement)

    def update_status(
        self,
        batch_id: str,
        expected_version: int,
        new_status: ForecastStatus,
    ) -> DemandForecastBatch:
        if not isinstance(
            new_status, ForecastStatus
        ):
            raise ValueError(
                "Invalid forecast status"
            )

        batch = self.get(batch_id)

        transitions = {
            ForecastStatus.DRAFT.value: {
                ForecastStatus.APPROVED.value,
                ForecastStatus.ARCHIVED.value,
            },
            ForecastStatus.APPROVED.value: {
                ForecastStatus.ARCHIVED.value,
            },
            ForecastStatus.ARCHIVED.value: set(),
        }

        if (
            new_status.value
            not in transitions[batch.status]
        ):
            raise ValueError(
                "Invalid forecast transition"
            )

        return self.update(
            record_id=batch_id,
            expected_version=expected_version,
            changes={
                "status": new_status.value
            },
            allowed_fields={"status"},
        )


if __name__ == "__main__":
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from backend.repositories.base import (
        Base,
        UnitOfWork,
    )

    engine = create_engine(
        "sqlite+pysqlite:///:memory:"
    )

    Base.metadata.create_all(engine)

    with Session(engine) as session:
        demand = DemandRepository(
            session, "demo"
        )
        forecasts = DemandForecastRepository(
            session, "demo"
        )

        with UnitOfWork(session):
            demand.ingest(
                sku="SKU001",
                warehouse_id="WH001",
                demand_date=date(2026, 10, 25),
                quantity=120,
                source_event_id="SALE001",
            )

            demand.ingest(
                sku="SKU001",
                warehouse_id="WH001",
                demand_date=date(2026, 10, 26),
                quantity=145,
                source_event_id="SALE002",
            )

        with UnitOfWork(session):
            forecast = forecasts.create_forecast(
                sku="SKU001",
                warehouse_id="WH001",
                model_name="demand_baseline",
                model_version="1.0.0",
                predictions={
                    date(2026, 10, 28): Decimal("155"),
                    date(2026, 10, 29): Decimal("160"),
                    date(2026, 10, 30): Decimal("165"),
                },
            )

            forecasts.update_status(
                forecast.id,
                forecast.version,
                ForecastStatus.APPROVED,
            )

        print(
            "Total historical demand:",
            demand.total_demand(
                sku="SKU001",
                warehouse_id="WH001",
                start_date=date(2026, 10, 25),
                end_date=date(2026, 10, 26),
            ),
        )

        latest = forecasts.latest_forecast(
            sku="SKU001",
            warehouse_id="WH001",
        )

        print(
            "Latest forecast:",
            latest.id if latest else None,
        )
