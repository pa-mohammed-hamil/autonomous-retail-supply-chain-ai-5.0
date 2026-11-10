from __future__ import annotations

"""Planned module: market trend service. Implementation pending."""

"""
backend/services/market_trend_service.py

Autonomous Retail Supply Chain AI 5.0
Market Trend Intelligence Service

Python 3.10+
Standard library only.

Features:
- Multi-tenant market observation storage
- Role-based read/write permissions
- Product/category/region trend analysis
- Historical sales and demand trends
- Growth and momentum indicators
- Moving-average demand forecasting
- Competitor price comparison
- Simple seasonality indicators
- Market trend classifications
- Idempotent trend alert generation
- JSON export

Reference implementation only.

Does not scrape competitor sites or
provide real-time market data.
Observations must come from
authorized, validated data sources.
"""


import copy
import json
import math
import statistics
import threading
import uuid

from collections import defaultdict
from dataclasses import (
    asdict,
    dataclass,
)
from datetime import (
    date,
    datetime,
    timezone,
)
from enum import Enum
from pathlib import Path
from typing import Any, Iterable


def utc_now() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


def required_text(
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


def nonnegative_number(
    value: float,
    name: str,
) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
    ):
        raise ValueError(
            f"{name} must be finite and nonnegative"
        )

    return float(value)


class MarketTrendDirection(str, Enum):
    STRONG_GROWTH = "strong_growth"
    GROWTH = "growth"
    STABLE = "stable"
    DECLINE = "decline"
    STRONG_DECLINE = "strong_decline"
    INSUFFICIENT_DATA = "insufficient_data"


class MarketAlertType(str, Enum):
    DEMAND_SURGE = "demand_surge"
    DEMAND_DROP = "demand_drop"
    PRICE_GAP = "price_gap"


@dataclass(frozen=True)
class MarketTrendActor:
    user_id: str
    tenant_id: str
    roles: frozenset[str]
    is_active: bool = True


@dataclass(frozen=True)
class MarketObservation:
    tenant_id: str
    sku: str
    category: str
    region: str
    observation_date: str
    units_sold: float
    demand_units: float
    own_price: float
    competitor_price: float | None = None


@dataclass(frozen=True)
class MarketTrendResult:
    tenant_id: str
    sku: str
    category: str
    region: str
    history_days: int
    recent_average_demand: float
    previous_average_demand: float
    growth_pct: float | None
    momentum_pct: float | None
    direction: MarketTrendDirection
    forecast_daily_demand: float
    forecast_horizon_days: int
    forecast_total_demand: float
    average_own_price: float
    average_competitor_price: float | None
    price_gap_pct: float | None
    peak_weekday: str | None
    assessed_at: str


@dataclass(frozen=True)
class MarketTrendAlert:
    alert_id: str
    tenant_id: str
    sku: str
    region: str
    alert_type: MarketAlertType
    message: str
    created_at: str


class RetailMarketTrendService:
    WRITER_ROLES = frozenset({
        "market_data_writer",
        "market_analyst",
        "corporate_admin",
    })

    READER_ROLES = frozenset({
        "market_analyst",
        "demand_planner",
        "operations_manager",
        "corporate_admin",
    })

    MANAGER_ROLES = frozenset({
        "operations_manager",
        "corporate_admin",
    })

    def __init__(
        self,
        tenant_id: str,
    ):
        self.tenant_id = required_text(
            tenant_id,
            "tenant_id",
        )

        self._lock = threading.RLock()

        self._observations: dict[
            tuple[str, str, str],
            MarketObservation,
        ] = {}

        self._alerts: dict[
            tuple[str, str, str, str],
            MarketTrendAlert,
        ] = {}

    def _authorize(
        self,
        actor: MarketTrendActor,
        roles: frozenset[str],
    ) -> None:
        if (
            not actor.is_active
            or actor.tenant_id
            != self.tenant_id
            or not actor.user_id.strip()
            or not (actor.roles & roles)
        ):
            raise PermissionError(
                "Market trend access denied"
            )

    @staticmethod
    def _validate_observation(
        observation: MarketObservation,
    ) -> None:
        for name in (
            "sku",
            "category",
            "region",
        ):
            required_text(
                getattr(
                    observation,
                    name,
                ),
                name,
            )

        date.fromisoformat(
            observation.observation_date
        )

        for name in (
            "units_sold",
            "demand_units",
            "own_price",
        ):
            nonnegative_number(
                getattr(
                    observation,
                    name,
                ),
                name,
            )

        if observation.competitor_price is not None:
            nonnegative_number(
                observation.competitor_price,
                "competitor_price",
            )

    def ingest(
        self,
        actor: MarketTrendActor,
        observations: Iterable[
            MarketObservation
        ],
    ) -> int:
        self._authorize(
            actor,
            self.WRITER_ROLES,
        )

        records = list(
            observations
        )

        for observation in records:
            if observation.tenant_id != (
                self.tenant_id
            ):
                raise PermissionError(
                    "Cross-tenant market observation"
                )

            self._validate_observation(
                observation
            )

        with self._lock:
            for observation in records:
                key = (
                    observation.sku,
                    observation.region,
                    observation.observation_date,
                )

                existing = (
                    self._observations.get(
                        key
                    )
                )

                if (
                    existing is not None
                    and existing != observation
                ):
                    raise ValueError(
                        "Conflicting observation"
                    )

            for observation in records:
                key = (
                    observation.sku,
                    observation.region,
                    observation.observation_date,
                )

                self._observations[
                    key
                ] = copy.deepcopy(
                    observation
                )

        return len(records)

    def observations(
        self,
        actor: MarketTrendActor,
        sku: str,
        region: str,
    ) -> list[MarketObservation]:
        self._authorize(
            actor,
            self.READER_ROLES,
        )

        with self._lock:
            records = [
                copy.deepcopy(record)
                for record in (
                    self._observations.values()
                )
                if (
                    record.sku == sku
                    and record.region == region
                )
            ]

        return sorted(
            records,
            key=lambda record: (
                record.observation_date
            ),
        )

    @staticmethod
    def _percentage_change(
        previous: float,
        current: float,
    ) -> float | None:
        if previous == 0:
            return (
                0.0
                if current == 0
                else None
            )

        return (
            (current - previous)
            / previous * 100
        )

    @staticmethod
    def _direction(
        growth_pct: float | None,
    ) -> MarketTrendDirection:
        if growth_pct is None:
            return (
                MarketTrendDirection.INSUFFICIENT_DATA
            )

        if growth_pct >= 30:
            return (
                MarketTrendDirection.STRONG_GROWTH
            )

        if growth_pct >= 10:
            return (
                MarketTrendDirection.GROWTH
            )

        if growth_pct <= -30:
            return (
                MarketTrendDirection.STRONG_DECLINE
            )

        if growth_pct <= -10:
            return (
                MarketTrendDirection.DECLINE
            )

        return (
            MarketTrendDirection.STABLE
        )

    def analyze(
        self,
        actor: MarketTrendActor,
        sku: str,
        region: str,
        window: int = 7,
        forecast_horizon_days: int = 7,
    ) -> MarketTrendResult:
        self._authorize(
            actor,
            self.READER_ROLES,
        )

        if (
            not isinstance(window, int)
            or isinstance(window, bool)
            or window < 2
        ):
            raise ValueError(
                "window must be >= 2"
            )

        if (
            not isinstance(
                forecast_horizon_days,
                int,
            )
            or isinstance(
                forecast_horizon_days,
                bool,
            )
            or not (
                1 <= forecast_horizon_days <= 365
            )
        ):
            raise ValueError(
                "Invalid forecast horizon"
            )

        records = self.observations(
            actor,
            sku,
            region,
        )

        if not records:
            raise ValueError(
                "No market observations"
            )

        demand = [
            record.demand_units
            for record in records
        ]

        recent = demand[
            -window:
        ]

        previous = demand[
            -2 * window:-window
        ]

        recent_average = (
            statistics.mean(recent)
        )

        previous_average = (
            statistics.mean(previous)
            if previous
            else 0.0
        )

        growth = (
            self._percentage_change(
                previous_average,
                recent_average,
            )
            if len(previous) == window
            and len(recent) == window
            else None
        )

        half = max(
            1,
            len(recent) // 2,
        )

        earlier_half = recent[
            :-half
        ]

        later_half = recent[
            -half:
        ]

        momentum = (
            self._percentage_change(
                statistics.mean(
                    earlier_half
                ),
                statistics.mean(
                    later_half
                ),
            )
            if earlier_half
            else None
        )

        own_prices = [
            record.own_price
            for record in records
        ]

        competitor_prices = [
            record.competitor_price
            for record in records
            if record.competitor_price
            is not None
        ]

        own_price = (
            statistics.mean(
                own_prices
            )
        )

        competitor_price = (
            statistics.mean(
                competitor_prices
            )
            if competitor_prices
            else None
        )

        price_gap = (
            self._percentage_change(
                competitor_price,
                own_price,
            )
            if competitor_price
            is not None
            else None
        )

        weekday_demand = (
            defaultdict(list)
        )

        for record in records:
            weekday = (
                date.fromisoformat(
                    record.observation_date
                ).strftime("%A")
            )

            weekday_demand[
                weekday
            ].append(
                record.demand_units
            )

        peak_weekday = (
            max(
                weekday_demand,
                key=lambda day: (
                    statistics.mean(
                        weekday_demand[day]
                    )
                ),
            )
            if len(records) >= 14
            else None
        )

        forecast_daily = (
            recent_average
        )

        return MarketTrendResult(
            tenant_id=self.tenant_id,
            sku=sku,
            category=records[-1].category,
            region=region,
            history_days=len(records),
            recent_average_demand=round(
                recent_average, 2
            ),
            previous_average_demand=round(
                previous_average, 2
            ),
            growth_pct=(
                round(growth, 2)
                if growth is not None
                else None
            ),
            momentum_pct=(
                round(momentum, 2)
                if momentum is not None
                else None
            ),
            direction=self._direction(
                growth
            ),
            forecast_daily_demand=round(
                forecast_daily, 2
            ),
            forecast_horizon_days=(
                forecast_horizon_days
            ),
            forecast_total_demand=round(
                forecast_daily
                * forecast_horizon_days,
                2,
            ),
            average_own_price=round(
                own_price, 2
            ),
            average_competitor_price=(
                round(
                    competitor_price,
                    2,
                )
                if competitor_price
                is not None
                else None
            ),
            price_gap_pct=(
                round(
                    price_gap,
                    2,
                )
                if price_gap
                is not None
                else None
            ),
            peak_weekday=peak_weekday,
            assessed_at=utc_now(),
        )

    def generate_alerts(
        self,
        actor: MarketTrendActor,
        result: MarketTrendResult,
    ) -> list[MarketTrendAlert]:
        self._authorize(
            actor,
            self.MANAGER_ROLES,
        )

        if result.tenant_id != (
            self.tenant_id
        ):
            raise PermissionError(
                "Cross-tenant result"
            )

        candidates = []

        if result.growth_pct is not None:
            if result.growth_pct >= 30:
                candidates.append((
                    MarketAlertType.DEMAND_SURGE,
                    "Demand increased by at least 30%",
                ))

            elif result.growth_pct <= -30:
                candidates.append((
                    MarketAlertType.DEMAND_DROP,
                    "Demand decreased by at least 30%",
                ))

        if (
            result.price_gap_pct
            is not None
            and result.price_gap_pct >= 20
        ):
            candidates.append((
                MarketAlertType.PRICE_GAP,
                "Own price exceeds competitor "
                "average by at least 20%",
            ))

        alerts = []

        with self._lock:
            for alert_type, message in candidates:
                key = (
                    result.sku,
                    result.region,
                    alert_type.value,
                    result.assessed_at[:10],
                )

                if key in self._alerts:
                    alerts.append(
                        self._alerts[
                            key
                        ]
                    )

                    continue

                alert = MarketTrendAlert(
                    alert_id=str(
                        uuid.uuid4()
                    ),
                    tenant_id=self.tenant_id,
                    sku=result.sku,
                    region=result.region,
                    alert_type=alert_type,
                    message=message,
                    created_at=utc_now(),
                )

                self._alerts[
                    key
                ] = alert

                alerts.append(
                    alert
                )

        return alerts

    def export_json(
        self,
        actor: MarketTrendActor,
        output_path: str | Path,
    ) -> Path:
        self._authorize(
            actor,
            self.MANAGER_ROLES,
        )

        with self._lock:
            payload = {
                "tenant_id": self.tenant_id,
                "observations": [
                    asdict(record)
                    for record in (
                        self._observations.values()
                    )
                ],
                "alerts": [
                    asdict(alert)
                    for alert in (
                        self._alerts.values()
                    )
                ],
            }

        output = Path(
            output_path
        )

        output.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        output.write_text(
            json.dumps(
                payload,
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        return output


if __name__ == "__main__":
    from datetime import timedelta

    service = RetailMarketTrendService(
        tenant_id="demo"
    )

    analyst = MarketTrendActor(
        user_id="market-analyst",
        tenant_id="demo",
        roles=frozenset({
            "market_analyst",
            "operations_manager",
        }),
    )

    start = date(
        2026, 10, 1
    )

    records = []

    for day in range(21):
        demand = (
            50 + day * 3
        )

        records.append(
            MarketObservation(
                tenant_id="demo",
                sku="SKU001",
                category="Electronics",
                region="Kerala",
                observation_date=(
                    start + timedelta(
                        days=day
                    )
                ).isoformat(),
                units_sold=demand,
                demand_units=demand,
                own_price=1200.0,
                competitor_price=1100.0,
            )
        )

    service.ingest(
        analyst,
        records,
    )

    result = service.analyze(
        analyst,
        sku="SKU001",
        region="Kerala",
        window=7,
    )

    print(
        json.dumps(
            asdict(result),
            indent=2,
            default=str,
        )
    )

    alerts = service.generate_alerts(
        analyst,
        result,
    )

    print(
        "Generated alerts:",
        len(alerts),
    )
