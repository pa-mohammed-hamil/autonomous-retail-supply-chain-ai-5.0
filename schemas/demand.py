from __future__ import annotations

"""Planned module: demand. Implementation pending."""

"""
Autonomous Retail Supply Chain AI 5.0
backend/services/demand_service.py

Python 3.10+ | Standard library only.

Features:
- Tenant and warehouse-scoped authorization
- Daily historical demand ingestion
- Idempotent sales observations
- Missing-day zero-demand handling
- Moving-average baseline forecasting
- Weekly seasonality adjustment
- Linear demand trend adjustment
- Nonnegative daily forecasts
- Forecast accuracy evaluation
- Inventory reorder recommendations
- Audit logging
- JSON export

Reference implementation only.
No trained ML model or database is connected.
"""


import copy
import json
import math
import statistics
import threading
import uuid

from dataclasses import (
    asdict,
    dataclass,
    field,
)
from datetime import (
    date,
    datetime,
    timedelta,
    timezone,
)
from enum import Enum
from pathlib import Path
from typing import Any, Iterable


def utc_now() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


def valid_text(
    value: str,
    name: str,
) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > 200
    ):
        raise ValueError(
            f"Invalid {name}"
        )
    return value.strip()


def valid_date(
    value: str,
) -> date:
    try:
        return date.fromisoformat(
            value
        )
    except (ValueError, TypeError) as exc:
        raise ValueError(
            "Date must be YYYY-MM-DD"
        ) from exc


def nonnegative_int(
    value: int,
    name: str,
) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
    ):
        raise ValueError(
            f"{name} must be nonnegative"
        )
    return value


def finite_nonnegative(
    value: int | float,
    name: str,
) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
    ):
        raise ValueError(
            f"Invalid {name}"
        )
    return float(value)


class DemandTrend(str, Enum):
    INCREASING = "increasing"
    STABLE = "stable"
    DECREASING = "decreasing"
    INSUFFICIENT_DATA = (
        "insufficient_data"
    )


@dataclass(frozen=True)
class DemandActor:
    user_id: str
    tenant_id: str
    roles: frozenset[str]
    warehouse_ids: frozenset[str] = (
        frozenset()
    )
    is_active: bool = True


@dataclass(frozen=True)
class DemandObservation:
    tenant_id: str
    warehouse_id: str
    sku: str
    observation_date: str
    units_sold: int
    source_reference: str


@dataclass(frozen=True)
class DemandForecastDay:
    forecast_date: str
    predicted_units: float
    weekday: int


@dataclass(frozen=True)
class DemandForecast:
    forecast_id: str
    tenant_id: str
    warehouse_id: str
    sku: str
    as_of_date: str
    horizon_days: int
    model_name: str
    average_daily_demand: float
    trend: DemandTrend
    forecast_days: tuple[
        DemandForecastDay, ...
    ]
    total_predicted_units: float
    generated_at: str


@dataclass(frozen=True)
class DemandEvaluation:
    mae: float
    rmse: float
    wape_pct: float | None
    bias: float
    evaluated_days: int


@dataclass(frozen=True)
class DemandReorderRecommendation:
    warehouse_id: str
    sku: str
    on_hand: int
    reserved: int
    incoming: int
    inventory_position: int
    lead_time_days: int
    review_period_days: int
    safety_stock: int
    reorder_point: int
    target_stock: int
    recommended_quantity: int
    stockout_risk: bool


@dataclass(frozen=True)
class DemandAuditEvent:
    event_id: str
    tenant_id: str
    actor_id: str
    action: str
    warehouse_id: str
    sku: str
    timestamp: str
    details: dict[str, Any] = field(
        default_factory=dict
    )


class RetailDemandService:
    WRITER_ROLES = frozenset({
        "demand_planner",
        "operations_manager",
        "corporate_admin",
    })

    READER_ROLES = (
        WRITER_ROLES
        | frozenset({
            "inventory_analyst",
            "procurement_manager",
            "warehouse_manager",
            "business_analyst",
        })
    )

    def __init__(
        self,
        tenant_id: str,
    ):
        self.tenant_id = valid_text(
            tenant_id,
            "tenant_id",
        )

        self._lock = (
            threading.RLock()
        )

        self._observations: dict[
            tuple[str, str, str],
            DemandObservation,
        ] = {}

        self._forecasts: dict[
            str,
            DemandForecast,
        ] = {}

        self._audit: list[
            DemandAuditEvent
        ] = []

    def _authorize(
        self,
        actor: DemandActor,
        roles: frozenset[str],
        warehouse_id: str,
    ) -> None:
        if (
            not actor.is_active
            or actor.tenant_id
            != self.tenant_id
            or not actor.user_id.strip()
            or not (
                actor.roles & roles
            )
        ):
            raise PermissionError(
                "Demand access denied"
            )

        if (
            "corporate_admin"
            not in actor.roles
            and warehouse_id
            not in actor.warehouse_ids
        ):
            raise PermissionError(
                "Warehouse scope denied"
            )

    def _audit_event(
        self,
        actor: DemandActor,
        action: str,
        warehouse_id: str,
        sku: str,
        details: dict | None = None,
    ) -> None:
        self._audit.append(
            DemandAuditEvent(
                event_id=str(
                    uuid.uuid4()
                ),
                tenant_id=self.tenant_id,
                actor_id=actor.user_id,
                action=action,
                warehouse_id=warehouse_id,
                sku=sku,
                timestamp=utc_now(),
                details=copy.deepcopy(
                    details or {}
                ),
            )
        )

    def ingest(
        self,
        actor: DemandActor,
        observations: Iterable[
            DemandObservation
        ],
    ) -> int:
        records = list(
            observations
        )

        validated = []

        for record in records:
            if record.tenant_id != (
                self.tenant_id
            ):
                raise PermissionError(
                    "Cross-tenant observation"
                )

            self._authorize(
                actor,
                self.WRITER_ROLES,
                record.warehouse_id,
            )

            valid_text(
                record.sku,
                "sku",
            )

            valid_text(
                record.source_reference,
                "source_reference",
            )

            valid_date(
                record.observation_date
            )

            nonnegative_int(
                record.units_sold,
                "units_sold",
            )

            validated.append(
                record
            )

        with self._lock:
            # Reject conflicts before any write.
            pending = {}

            for record in validated:
                key = (
                    record.warehouse_id,
                    record.sku,
                    record.observation_date,
                )

                existing = (
                    pending.get(key)
                    or self._observations.get(
                        key
                    )
                )

                if (
                    existing is not None
                    and existing != record
                ):
                    raise ValueError(
                        "Conflicting demand observation"
                    )

                pending[
                    key
                ] = record

            inserted = 0

            for key, record in (
                pending.items()
            ):
                if key not in (
                    self._observations
                ):
                    self._observations[
                        key
                    ] = record

                    inserted += 1

                    self._audit_event(
                        actor,
                        "demand_observation_ingested",
                        record.warehouse_id,
                        record.sku,
                    )

            return inserted

    def history(
        self,
        actor: DemandActor,
        warehouse_id: str,
        sku: str,
        as_of_date: str | None = None,
    ) -> list[DemandObservation]:
        self._authorize(
            actor,
            self.READER_ROLES,
            warehouse_id,
        )

        cutoff = (
            valid_date(as_of_date)
            if as_of_date
            else None
        )

        with self._lock:
            records = [
                copy.deepcopy(
                    observation
                )
                for (
                    wid,
                    product_sku,
                    day,
                ), observation in (
                    self._observations.items()
                )
                if (
                    wid == warehouse_id
                    and product_sku == sku
                    and (
                        cutoff is None
                        or valid_date(day)
                        <= cutoff
                    )
                )
            ]

        return sorted(
            records,
            key=lambda x: (
                x.observation_date
            ),
        )

    @staticmethod
    def _daily_series(
        observations: list[
            DemandObservation
        ],
        as_of: date,
        lookback_days: int,
    ) -> list[tuple[date, float]]:
        start = (
            as_of
            - timedelta(
                days=lookback_days - 1
            )
        )

        by_date = {
            valid_date(
                observation.observation_date
            ): float(
                observation.units_sold
            )
            for observation in observations
        }

        return [
            (
                start + timedelta(days=i),
                by_date.get(
                    start + timedelta(days=i),
                    0.0,
                ),
            )
            for i in range(
                lookback_days
            )
        ]

    @staticmethod
    def _trend(
        values: list[float],
    ) -> tuple[DemandTrend, float]:
        if len(values) < 7:
            return (
                DemandTrend.INSUFFICIENT_DATA,
                0.0,
            )

        n = len(values)
        x_mean = (
            n - 1
        ) / 2

        y_mean = (
            statistics.mean(values)
        )

        denominator = sum(
            (i - x_mean) ** 2
            for i in range(n)
        )

        slope = (
            sum(
                (i - x_mean)
                * (y - y_mean)
                for i, y in enumerate(
                    values
                )
            )
            / denominator
        )

        relative_change = (
            slope * 7
            / max(y_mean, 1.0)
        )

        if relative_change > 0.05:
            direction = (
                DemandTrend.INCREASING
            )
        elif relative_change < -0.05:
            direction = (
                DemandTrend.DECREASING
            )
        else:
            direction = (
                DemandTrend.STABLE
            )

        return direction, slope

    def forecast(
        self,
        actor: DemandActor,
        warehouse_id: str,
        sku: str,
        as_of_date: str,
        horizon_days: int = 14,
        lookback_days: int = 56,
    ) -> DemandForecast:
        self._authorize(
            actor,
            self.READER_ROLES,
            warehouse_id,
        )

        as_of = valid_date(
            as_of_date
        )

        if not (
            1 <= horizon_days <= 365
        ):
            raise ValueError(
                "Invalid forecast horizon"
            )

        if not (
            7 <= lookback_days <= 730
        ):
            raise ValueError(
                "Invalid lookback window"
            )

        observations = self.history(
            actor,
            warehouse_id,
            sku,
            as_of_date,
        )

        if not observations:
            raise ValueError(
                "No historical demand data"
            )

        series = self._daily_series(
            observations,
            as_of,
            lookback_days,
        )

        values = [
            value
            for _, value in series
        ]

        baseline = (
            statistics.mean(values)
        )

        trend, slope = self._trend(
            values
        )

        weekday_means = {}

        for weekday in range(7):
            samples = [
                value
                for day, value in series
                if day.weekday()
                == weekday
            ]

            weekday_means[
                weekday
            ] = (
                statistics.mean(samples)
                if samples
                else baseline
            )

        # Weekly factors are shrunk toward 1
        # to reduce extreme small-sample noise.
        seasonal_factors = {
            weekday: (
                0.5
                + 0.5
                * weekday_means[
                    weekday
                ]
                / max(
                    baseline,
                    0.001,
                )
            )
            for weekday in range(7)
        }

        forecast_days = []

        for step in range(
            1,
            horizon_days + 1,
        ):
            target = (
                as_of
                + timedelta(
                    days=step
                )
            )

            # Project from the end of the
            # observed window, not its start.
            trend_adjusted = max(
                0.0,
                baseline
                + slope
                * (
                    (lookback_days - 1)
                    / 2
                    + step
                ),
            )

            predicted = (
                trend_adjusted
                * seasonal_factors[
                    target.weekday()
                ]
            )

            forecast_days.append(
                DemandForecastDay(
                    forecast_date=(
                        target.isoformat()
                    ),
                    predicted_units=round(
                        max(
                            0.0,
                            predicted,
                        ),
                        2,
                    ),
                    weekday=(
                        target.weekday()
                    ),
                )
            )

        result = DemandForecast(
            forecast_id=str(
                uuid.uuid4()
            ),
            tenant_id=self.tenant_id,
            warehouse_id=warehouse_id,
            sku=sku,
            as_of_date=(
                as_of.isoformat()
            ),
            horizon_days=horizon_days,
            model_name=(
                "moving_average_trend_weekly"
            ),
            average_daily_demand=round(
                baseline,
                2,
            ),
            trend=trend,
            forecast_days=tuple(
                forecast_days
            ),
            total_predicted_units=round(
                sum(
                    day.predicted_units
                    for day in forecast_days
                ),
                2,
            ),
            generated_at=utc_now(),
        )

        with self._lock:
            self._forecasts[
                result.forecast_id
            ] = result

            self._audit_event(
                actor,
                "demand_forecast_generated",
                warehouse_id,
                sku,
                {
                    "forecast_id": (
                        result.forecast_id
                    ),
                },
            )

        return result

    @staticmethod
    def evaluate_forecast(
        actual: Iterable[
            int | float
        ],
        predicted: Iterable[
            int | float
        ],
    ) -> DemandEvaluation:
        actual_values = [
            finite_nonnegative(
                value,
                "actual",
            )
            for value in actual
        ]

        predicted_values = [
            finite_nonnegative(
                value,
                "predicted",
            )
            for value in predicted
        ]

        if (
            not actual_values
            or len(actual_values)
            != len(predicted_values)
        ):
            raise ValueError(
                "Forecast arrays must have "
                "equal nonzero length"
            )

        errors = [
            p - a
            for a, p in zip(
                actual_values,
                predicted_values,
            )
        ]

        mae = statistics.mean(
            abs(e)
            for e in errors
        )

        rmse = math.sqrt(
            statistics.mean(
                e * e
                for e in errors
            )
        )

        actual_total = sum(
            actual_values
        )

        wape = (
            sum(
                abs(e)
                for e in errors
            )
            / actual_total
            * 100
            if actual_total > 0
            else None
        )

        return DemandEvaluation(
            mae=round(mae, 4),
            rmse=round(rmse, 4),
            wape_pct=(
                round(wape, 2)
                if wape is not None
                else None
            ),
            bias=round(
                statistics.mean(
                    errors
                ),
                4,
            ),
            evaluated_days=len(
                actual_values
            ),
        )

    def recommend_reorder(
        self,
        actor: DemandActor,
        warehouse_id: str,
        sku: str,
        on_hand: int,
        reserved: int,
        incoming: int,
        lead_time_days: int,
        safety_stock: int,
        review_period_days: int,
        average_daily_demand: float,
    ) -> DemandReorderRecommendation:
        self._authorize(
            actor,
            self.READER_ROLES,
            warehouse_id,
        )

        for name, value in {
            "on_hand": on_hand,
            "reserved": reserved,
            "incoming": incoming,
            "lead_time_days": (
                lead_time_days
            ),
            "safety_stock": (
                safety_stock
            ),
            "review_period_days": (
                review_period_days
            ),
        }.items():
            nonnegative_int(
                value,
                name,
            )

        demand = finite_nonnegative(
            average_daily_demand,
            "average_daily_demand",
        )

        if reserved > on_hand:
            raise ValueError(
                "Reserved exceeds on-hand"
            )

        available = (
            on_hand
            - reserved
        )

        position = (
            available
            + incoming
        )

        reorder_point = math.ceil(
            demand
            * lead_time_days
            + safety_stock
        )

        target = math.ceil(
            demand
            * (
                lead_time_days
                + review_period_days
            )
            + safety_stock
        )

        recommended = (
            max(
                0,
                target - position,
            )
            if position
            <= reorder_point
            else 0
        )

        return DemandReorderRecommendation(
            warehouse_id=warehouse_id,
            sku=sku,
            on_hand=on_hand,
            reserved=reserved,
            incoming=incoming,
            inventory_position=position,
            lead_time_days=lead_time_days,
            review_period_days=(
                review_period_days
            ),
            safety_stock=safety_stock,
            reorder_point=(
                reorder_point
            ),
            target_stock=target,
            recommended_quantity=(
                recommended
            ),
            stockout_risk=(
                available
                < demand
                * lead_time_days
            ),
        )

    def get_forecast(
        self,
        actor: DemandActor,
        forecast_id: str,
    ) -> DemandForecast:
        with self._lock:
            result = self._forecasts.get(
                forecast_id
            )

            if result is None:
                raise KeyError(
                    "Forecast not found"
                )

            self._authorize(
                actor,
                self.READER_ROLES,
                result.warehouse_id,
            )

            return copy.deepcopy(
                result
            )

    def export_json(
        self,
        actor: DemandActor,
        forecast_id: str,
        output_path: str | Path,
    ) -> Path:
        result = self.get_forecast(
            actor,
            forecast_id,
        )

        path = Path(
            output_path
        )

        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        path.write_text(
            json.dumps(
                asdict(result),
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )

        return path


if __name__ == "__main__":
    service = RetailDemandService(
        tenant_id="demo"
    )

    actor = DemandActor(
        user_id="planner001",
        tenant_id="demo",
        roles=frozenset({
            "demand_planner",
        }),
        warehouse_ids=frozenset({
            "WH001",
        }),
    )

    start = date(
        2026,
        8,
        1,
    )

    observations = [
        DemandObservation(
            tenant_id="demo",
            warehouse_id="WH001",
            sku="SKU001",
            observation_date=(
                start
                + timedelta(days=i)
            ).isoformat(),
            units_sold=(
                25
                + i // 7
                + (
                    8
                    if (
                        start
                        + timedelta(days=i)
                    ).weekday()
                    in (5, 6)
                    else 0
                )
            ),
            source_reference=(
                f"SALES-{i:03d}"
            ),
        )
        for i in range(56)
    ]

    service.ingest(
        actor,
        observations,
    )

    forecast = service.forecast(
        actor=actor,
        warehouse_id="WH001",
        sku="SKU001",
        as_of_date="2026-09-25",
        horizon_days=14,
        lookback_days=56,
    )

    print(
        "Forecast total:",
        forecast.total_predicted_units,
    )

    recommendation = (
        service.recommend_reorder(
            actor=actor,
            warehouse_id="WH001",
            sku="SKU001",
            on_hand=250,
            reserved=30,
            incoming=50,
            lead_time_days=7,
            safety_stock=80,
            review_period_days=7,
            average_daily_demand=(
                forecast.average_daily_demand
            ),
        )
    )

    print(
        "Reorder quantity:",
        recommendation.recommended_quantity,
    )
