from __future__ import annotations

"""Planned module: evaluation repository. Implementation pending."""

"""
backend/repositories/evaluation_repository.py

Autonomous Retail Supply Chain AI 5.0

Requirements:
    pip install "sqlalchemy>=2.0,<3.0"

Depends on:
    backend/repositories/base.py

Reference implementation.
Repositories do not commit transactions.
"""


import math
from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKeyConstraint,
    Index,
    Integer,
    JSON,
    String,
    UniqueConstraint,
    select,
)
from sqlalchemy.orm import Mapped, Session, mapped_column

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


class EvaluationType(str, Enum):
    CLASSIFICATION = "classification"
    FORECASTING = "forecasting"
    RETRIEVAL = "retrieval"
    RAG = "rag"
    AGENT = "agent"


class EvaluationStatus(str, Enum):
    DRAFT = "draft"
    PASSED = "passed"
    FAILED = "failed"


class EvaluationRun(TenantModel):
    __tablename__ = "evaluation_runs"

    model_name: Mapped[str] = mapped_column(
        String(150), nullable=False
    )
    model_version: Mapped[str] = mapped_column(
        String(80), nullable=False
    )
    dataset_name: Mapped[str] = mapped_column(
        String(150), nullable=False
    )
    dataset_version: Mapped[str] = mapped_column(
        String(80), nullable=False
    )
    evaluation_type: Mapped[str] = mapped_column(
        String(40), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(30),
        default=EvaluationStatus.DRAFT.value,
        nullable=False,
    )
    created_by: Mapped[str] = mapped_column(
        String(120), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    finalized_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "id",
            name="uq_evaluation_run_tenant_id",
        ),
        Index(
            "ix_evaluation_lookup",
            "tenant_id",
            "model_name",
            "evaluation_type",
            "created_at",
        ),
    )


class EvaluationMetric(TenantModel):
    __tablename__ = "evaluation_metrics"

    run_id: Mapped[str] = mapped_column(
        String(120), nullable=False
    )
    metric_name: Mapped[str] = mapped_column(
        String(100), nullable=False
    )
    metric_value: Mapped[float] = mapped_column(
        Float, nullable=False
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "run_id"],
            [
                "evaluation_runs.tenant_id",
                "evaluation_runs.id",
            ],
        ),
        UniqueConstraint(
            "tenant_id",
            "run_id",
            "metric_name",
            name="uq_evaluation_metric",
        ),
    )


class EvaluationGate(TenantModel):
    __tablename__ = "evaluation_gates"

    run_id: Mapped[str] = mapped_column(
        String(120), nullable=False
    )
    metric_name: Mapped[str] = mapped_column(
        String(100), nullable=False
    )
    operator: Mapped[str] = mapped_column(
        String(10), nullable=False
    )
    threshold: Mapped[float] = mapped_column(
        Float, nullable=False
    )
    passed: Mapped[bool] = mapped_column(
        nullable=False
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "run_id"],
            [
                "evaluation_runs.tenant_id",
                "evaluation_runs.id",
            ],
        ),
    )


class EvaluationRepository(
    BaseRepository[EvaluationRun]
):
    def __init__(
        self,
        session: Session,
        tenant_id: str,
    ):
        super().__init__(
            session,
            EvaluationRun,
            tenant_id,
        )

    def create_run(
        self,
        *,
        model_name: str,
        model_version: str,
        dataset_name: str,
        dataset_version: str,
        evaluation_type: EvaluationType,
        created_by: str,
    ) -> EvaluationRun:
        if not isinstance(
            evaluation_type, EvaluationType
        ):
            raise ValueError("Invalid evaluation type")

        run = EvaluationRun(
            id=str(uuid4()),
            tenant_id=self.tenant_id,
            model_name=required(
                model_name, "model_name"
            ),
            model_version=required(
                model_version, "model_version"
            ),
            dataset_name=required(
                dataset_name, "dataset_name"
            ),
            dataset_version=required(
                dataset_version, "dataset_version"
            ),
            evaluation_type=evaluation_type.value,
            created_by=required(
                created_by, "created_by"
            ),
        )

        return self.create(run)

    def add_metric(
        self,
        *,
        run_id: str,
        metric_name: str,
        metric_value: float,
    ) -> EvaluationMetric:
        run = self.get(run_id)

        if run.status != EvaluationStatus.DRAFT.value:
            raise ValueError(
                "Finalized runs cannot be modified"
            )

        metric_name = required(
            metric_name, "metric_name"
        )

        if (
            isinstance(metric_value, bool)
            or not isinstance(
                metric_value, (int, float)
            )
            or not math.isfinite(metric_value)
        ):
            raise ValueError(
                "Metric must be a finite number"
            )

        existing = self.session.scalar(
            select(EvaluationMetric).where(
                EvaluationMetric.tenant_id
                == self.tenant_id,
                EvaluationMetric.run_id == run_id,
                EvaluationMetric.metric_name
                == metric_name,
            )
        )

        if existing is not None:
            raise ValueError(
                "Metric already exists"
            )

        metric = EvaluationMetric(
            id=str(uuid4()),
            tenant_id=self.tenant_id,
            run_id=run_id,
            metric_name=metric_name,
            metric_value=float(metric_value),
        )

        self.session.add(metric)
        self.session.flush()
        return metric

    def metrics(
        self,
        run_id: str,
    ) -> dict[str, float]:
        self.get(run_id)

        statement = select(
            EvaluationMetric
        ).where(
            EvaluationMetric.tenant_id
            == self.tenant_id,
            EvaluationMetric.run_id == run_id,
        )

        return {
            metric.metric_name: metric.metric_value
            for metric in self.session.scalars(
                statement
            )
        }

    def finalize(
        self,
        *,
        run_id: str,
        expected_version: int,
        gates: dict[str, tuple[str, float]],
    ) -> EvaluationRun:
        """
        Example gates:
        {
            "accuracy": (">=", 0.90),
            "latency_ms": ("<=", 500),
        }
        """
        run = self.get(run_id)

        if run.version != expected_version:
            raise VersionConflict(
                "Evaluation version conflict"
            )

        if run.status != EvaluationStatus.DRAFT.value:
            raise ValueError(
                "Evaluation already finalized"
            )

        if not gates:
            raise ValueError(
                "At least one gate is required"
            )

        values = self.metrics(run_id)

        decisions: list[tuple[str, str, float, bool]] = []

        for name, (operator, threshold) in gates.items():
            if name not in values:
                raise ValueError(
                    f"Missing metric: {name}"
                )

            if operator not in {">=", "<="}:
                raise ValueError(
                    "Unsupported gate operator"
                )

            if (
                isinstance(threshold, bool)
                or not isinstance(
                    threshold, (int, float)
                )
                or not math.isfinite(threshold)
            ):
                raise ValueError(
                    "Invalid gate threshold"
                )

            value = values[name]

            passed = (
                value >= threshold
                if operator == ">="
                else value <= threshold
            )

            decisions.append((
                name,
                operator,
                float(threshold),
                passed,
            ))

        all_passed = all(
            result[3] for result in decisions
        )

        for name, operator, threshold, passed in decisions:
            self.session.add(EvaluationGate(
                id=str(uuid4()),
                tenant_id=self.tenant_id,
                run_id=run_id,
                metric_name=name,
                operator=operator,
                threshold=threshold,
                passed=passed,
            ))

        updated = self.update(
            record_id=run_id,
            expected_version=expected_version,
            changes={
                "status": (
                    EvaluationStatus.PASSED.value
                    if all_passed
                    else EvaluationStatus.FAILED.value
                ),
                "finalized_at": utc_now(),
            },
            allowed_fields={
                "status",
                "finalized_at",
            },
        )

        self.session.flush()
        return updated

    def gate_results(
        self,
        run_id: str,
    ) -> list[EvaluationGate]:
        self.get(run_id)

        statement = (
            select(EvaluationGate)
            .where(
                EvaluationGate.tenant_id
                == self.tenant_id,
                EvaluationGate.run_id == run_id,
            )
            .order_by(EvaluationGate.metric_name)
        )

        return list(
            self.session.scalars(statement)
        )

    def model_history(
        self,
        model_name: str,
        limit: int = 50,
    ) -> list[EvaluationRun]:
        if type(limit) is not int or not 1 <= limit <= 500:
            raise ValueError("Invalid limit")

        statement = (
            self._query()
            .where(
                EvaluationRun.model_name
                == required(model_name, "model_name")
            )
            .order_by(
                EvaluationRun.created_at.desc(),
                EvaluationRun.id.desc(),
            )
            .limit(limit)
        )

        return list(
            self.session.scalars(statement)
        )

    def compare_runs(
        self,
        first_run_id: str,
        second_run_id: str,
    ) -> dict:
        first = self.get(first_run_id)
        second = self.get(second_run_id)

        first_metrics = self.metrics(first_run_id)
        second_metrics = self.metrics(second_run_id)

        metric_names = sorted(
            set(first_metrics) | set(second_metrics)
        )

        return {
            "first_run": first.id,
            "second_run": second.id,
            "metrics": {
                name: {
                    "first": first_metrics.get(name),
                    "second": second_metrics.get(name),
                    "delta": (
                        second_metrics[name]
                        - first_metrics[name]
                        if name in first_metrics
                        and name in second_metrics
                        else None
                    ),
                }
                for name in metric_names
            },
        }


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
        repo = EvaluationRepository(
            session, "demo"
        )

        with UnitOfWork(session):
            run = repo.create_run(
                model_name="stockout_predictor",
                model_version="1.0.0",
                dataset_name="retail_stockout_test",
                dataset_version="2026-10",
                evaluation_type=(
                    EvaluationType.CLASSIFICATION
                ),
                created_by="AI_ENGINEER",
            )

            repo.add_metric(
                run_id=run.id,
                metric_name="accuracy",
                metric_value=0.94,
            )

            repo.add_metric(
                run_id=run.id,
                metric_name="f1_score",
                metric_value=0.91,
            )

            run = repo.finalize(
                run_id=run.id,
                expected_version=run.version,
                gates={
                    "accuracy": (">=", 0.90),
                    "f1_score": (">=", 0.88),
                },
            )

        print("Run:", run.id)
        print("Status:", run.status)
        print("Metrics:", repo.metrics(run.id))
