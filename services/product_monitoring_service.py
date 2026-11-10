from __future__ import annotations

"""Planned module: product monitoring service. Implementation pending."""

"""
backend/services/product_monitoring_service.py

Autonomous Retail Supply Chain AI 5.0
Product Monitoring Service

Python 3.10+
Standard library only.

Features:
- Multi-tenant product monitoring
- Warehouse-scoped RBAC
- Inventory availability monitoring
- Stock coverage calculation
- Sales growth analysis
- Return-rate monitoring
- Defect-rate monitoring
- Product expiry alerts
- Gross margin estimation
- Weighted product health score
- Idempotent alert synchronization
- Product monitoring dashboards
- JSON export

Reference implementation only.
No real sensors, supplier systems,
external notifications, or purchases
are executed by this module.
"""


import copy
import json
import math
import threading
import uuid

from dataclasses import (
    asdict,
    dataclass,
)
from datetime import (
    date,
    datetime,
    timezone,
)
from decimal import (
    Decimal,
    InvalidOperation,
)
from enum import Enum
from pathlib import Path
from typing import Iterable


def utc_now() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


def require_text(
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
            f"{name} must be a nonnegative integer"
        )

    return value


def nonnegative_float(
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


def money(
    value: str | int | float | Decimal,
) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(
            "Invalid money value"
        )

    try:
        amount = Decimal(
            str(value)
        )
    except (
        InvalidOperation,
        ValueError,
    ) as exc:
        raise ValueError(
            "Invalid money value"
        ) from exc

    if (
        not amount.is_finite()
        or amount < 0
    ):
        raise ValueError(
            "Money must be finite and nonnegative"
        )

    return amount


class ProductHealth(str, Enum):
    EXCELLENT = "excellent"
    GOOD = "good"
    WARNING = "warning"
    CRITICAL = "critical"


class ProductAlertType(str, Enum):
    LOW_STOCK = "low_stock"
    SALES_DECLINE = "sales_decline"
    HIGH_RETURNS = "high_returns"
    QUALITY_RISK = "quality_risk"
    EXPIRY_RISK = "expiry_risk"
    LOW_MARGIN = "low_margin"


class ProductAlertStatus(str, Enum):
    ACTIVE = "active"
    RESOLVED = "resolved"


@dataclass(frozen=True)
class ProductMonitoringActor:
    user_id: str
    tenant_id: str
    roles: frozenset[str]
    warehouse_ids: frozenset[str] = (
        frozenset()
    )
    is_active: bool = True


@dataclass(frozen=True)
class ProductMonitoringRecord:
    tenant_id: str
    warehouse_id: str
    sku: str
    product_name: str
    category: str

    on_hand: int
    reserved: int
    reorder_point: int

    daily_demand: float

    previous_period_sales: int
    current_period_sales: int

    returned_units: int
    inspected_units: int
    defective_units: int

    unit_price: Decimal
    unit_cost: Decimal

    nearest_expiry_date: str | None = None


@dataclass(frozen=True)
class ProductMonitoringResult:
    tenant_id: str
    warehouse_id: str
    sku: str
    product_name: str
    category: str

    available_stock: int
    days_of_cover: float | None

    sales_growth_pct: float | None
    return_rate_pct: float | None
    defect_rate_pct: float | None
    gross_margin_pct: float | None

    days_until_expiry: int | None

    health_score: int
    health: ProductHealth

    active_risks: tuple[
        ProductAlertType, ...
    ]

    assessed_at: str


@dataclass
class ProductMonitoringAlert:
    alert_id: str
    tenant_id: str
    warehouse_id: str
    sku: str
    alert_type: ProductAlertType
    status: ProductAlertStatus
    created_at: str
    updated_at: str
    resolved_at: str | None = None


class RetailProductMonitoringService:
    READER_ROLES = frozenset({
        "inventory_analyst",
        "product_analyst",
        "warehouse_manager",
        "product_manager",
        "operations_manager",
        "corporate_admin",
    })

    MONITOR_ROLES = frozenset({
        "product_monitor",
        "product_manager",
        "operations_manager",
        "corporate_admin",
    })

    def __init__(
        self,
        tenant_id: str,
    ):
        self.tenant_id = require_text(
            tenant_id,
            "tenant_id",
        )

        self._lock = threading.RLock()

        self._alerts: dict[
            tuple[
                str,
                str,
                ProductAlertType,
            ],
            ProductMonitoringAlert,
        ] = {}

    def _authorize(
        self,
        actor: ProductMonitoringActor,
        roles: frozenset[str],
        warehouse_id: str | None = None,
    ) -> None:
        if (
            not actor.is_active
            or actor.tenant_id
            != self.tenant_id
            or not actor.user_id.strip()
            or not (actor.roles & roles)
        ):
            raise PermissionError(
                "Product monitoring access denied"
            )

        if (
            warehouse_id is not None
            and "corporate_admin"
            not in actor.roles
            and warehouse_id
            not in actor.warehouse_ids
        ):
            raise PermissionError(
                "Warehouse access denied"
            )

    def _validate(
        self,
        record: ProductMonitoringRecord,
    ) -> None:
        if record.tenant_id != (
            self.tenant_id
        ):
            raise PermissionError(
                "Cross-tenant product record"
            )

        for name in (
            "warehouse_id",
            "sku",
            "product_name",
            "category",
        ):
            require_text(
                getattr(record, name),
                name,
            )

        for name in (
            "on_hand",
            "reserved",
            "reorder_point",
            "previous_period_sales",
            "current_period_sales",
            "returned_units",
            "inspected_units",
            "defective_units",
        ):
            nonnegative_int(
                getattr(record, name),
                name,
            )

        nonnegative_float(
            record.daily_demand,
            "daily_demand",
        )

        money(
            record.unit_price
        )

        money(
            record.unit_cost
        )

        if record.reserved > (
            record.on_hand
        ):
            raise ValueError(
                "Reserved stock exceeds on-hand"
            )

        if record.returned_units > (
            record.current_period_sales
        ):
            raise ValueError(
                "Returned units exceed current sales"
            )

        if record.defective_units > (
            record.inspected_units
        ):
            raise ValueError(
                "Defects exceed inspected units"
            )

        if record.nearest_expiry_date:
            date.fromisoformat(
                record.nearest_expiry_date
            )

    @staticmethod
    def _growth(
        previous: int,
        current: int,
    ) -> float | None:
        if previous == 0:
            return (
                0.0
                if current == 0
                else None
            )

        return round(
            (
                current - previous
            ) / previous * 100,
            2,
        )

    @staticmethod
    def _rate(
        numerator: int,
        denominator: int,
    ) -> float | None:
        if denominator == 0:
            return None

        return round(
            numerator / denominator * 100,
            2,
        )

    def assess(
        self,
        actor: ProductMonitoringActor,
        record: ProductMonitoringRecord,
        as_of: date | None = None,
    ) -> ProductMonitoringResult:
        self._authorize(
            actor,
            self.READER_ROLES,
            record.warehouse_id,
        )

        self._validate(
            record
        )

        as_of = as_of or (
            datetime.now(
                timezone.utc
            ).date()
        )

        available = (
            record.on_hand
            - record.reserved
        )

        days_of_cover = (
            available
            / record.daily_demand
            if record.daily_demand > 0
            else None
        )

        growth = self._growth(
            record.previous_period_sales,
            record.current_period_sales,
        )

        return_rate = self._rate(
            record.returned_units,
            record.current_period_sales,
        )

        defect_rate = self._rate(
            record.defective_units,
            record.inspected_units,
        )

        price = money(
            record.unit_price
        )

        cost = money(
            record.unit_cost
        )

        gross_margin = (
            round(
                float(
                    (price - cost)
                    / price * 100
                ),
                2,
            )
            if price > 0
            else None
        )

        days_until_expiry = (
            (
                date.fromisoformat(
                    record.nearest_expiry_date
                ) - as_of
            ).days
            if record.nearest_expiry_date
            else None
        )

        risks = []

        if available <= (
            record.reorder_point
        ):
            risks.append(
                ProductAlertType.LOW_STOCK
            )

        if (
            growth is not None
            and growth <= -20
        ):
            risks.append(
                ProductAlertType.SALES_DECLINE
            )

        if (
            return_rate is not None
            and return_rate >= 10
        ):
            risks.append(
                ProductAlertType.HIGH_RETURNS
            )

        if (
            defect_rate is not None
            and defect_rate >= 5
        ):
            risks.append(
                ProductAlertType.QUALITY_RISK
            )

        if (
            days_until_expiry
            is not None
            and days_until_expiry <= 30
        ):
            risks.append(
                ProductAlertType.EXPIRY_RISK
            )

        if (
            gross_margin is not None
            and gross_margin < 10
        ):
            risks.append(
                ProductAlertType.LOW_MARGIN
            )

        weights = {
            ProductAlertType.LOW_STOCK: 20,
            ProductAlertType.SALES_DECLINE: 15,
            ProductAlertType.HIGH_RETURNS: 20,
            ProductAlertType.QUALITY_RISK: 25,
            ProductAlertType.EXPIRY_RISK: 25,
            ProductAlertType.LOW_MARGIN: 10,
        }

        score = max(
            0,
            100 - sum(
                weights[risk]
                for risk in risks
            ),
        )

        if score >= 90:
            health = (
                ProductHealth.EXCELLENT
            )
        elif score >= 70:
            health = (
                ProductHealth.GOOD
            )
        elif score >= 40:
            health = (
                ProductHealth.WARNING
            )
        else:
            health = (
                ProductHealth.CRITICAL
            )

        return ProductMonitoringResult(
            tenant_id=self.tenant_id,
            warehouse_id=(
                record.warehouse_id
            ),
            sku=record.sku,
            product_name=(
                record.product_name
            ),
            category=record.category,
            available_stock=available,
            days_of_cover=(
                round(days_of_cover, 2)
                if days_of_cover
                is not None
                else None
            ),
            sales_growth_pct=growth,
            return_rate_pct=return_rate,
            defect_rate_pct=defect_rate,
            gross_margin_pct=gross_margin,
            days_until_expiry=(
                days_until_expiry
            ),
            health_score=score,
            health=health,
            active_risks=tuple(risks),
            assessed_at=utc_now(),
        )

    def assess_batch(
        self,
        actor: ProductMonitoringActor,
        records: Iterable[
            ProductMonitoringRecord
        ],
    ) -> list[ProductMonitoringResult]:
        results = []

        seen = set()

        for record in records:
            key = (
                record.warehouse_id,
                record.sku,
            )

            if key in seen:
                raise ValueError(
                    "Duplicate warehouse/SKU"
                )

            seen.add(key)

            results.append(
                self.assess(
                    actor,
                    record,
                )
            )

        return sorted(
            results,
            key=lambda result: (
                result.health_score,
                result.warehouse_id,
                result.sku,
            ),
        )

    def synchronize_alerts(
        self,
        actor: ProductMonitoringActor,
        result: ProductMonitoringResult,
    ) -> list[ProductMonitoringAlert]:
        self._authorize(
            actor,
            self.MONITOR_ROLES,
            result.warehouse_id,
        )

        if result.tenant_id != (
            self.tenant_id
        ):
            raise PermissionError(
                "Cross-tenant assessment"
            )

        active_risks = set(
            result.active_risks
        )

        with self._lock:
            for alert_type in ProductAlertType:
                key = (
                    result.warehouse_id,
                    result.sku,
                    alert_type,
                )

                existing = (
                    self._alerts.get(
                        key
                    )
                )

                if alert_type in active_risks:
                    if existing is None:
                        now = utc_now()

                        self._alerts[
                            key
                        ] = ProductMonitoringAlert(
                            alert_id=str(
                                uuid.uuid4()
                            ),
                            tenant_id=self.tenant_id,
                            warehouse_id=(
                                result.warehouse_id
                            ),
                            sku=result.sku,
                            alert_type=alert_type,
                            status=(
                                ProductAlertStatus.ACTIVE
                            ),
                            created_at=now,
                            updated_at=now,
                        )

                    elif existing.status == (
                        ProductAlertStatus.RESOLVED
                    ):
                        existing.status = (
                            ProductAlertStatus.ACTIVE
                        )

                        existing.resolved_at = None
                        existing.updated_at = (
                            utc_now()
                        )

                elif (
                    existing is not None
                    and existing.status
                    == ProductAlertStatus.ACTIVE
                ):
                    existing.status = (
                        ProductAlertStatus.RESOLVED
                    )

                    existing.resolved_at = (
                        utc_now()
                    )

                    existing.updated_at = (
                        existing.resolved_at
                    )

            return [
                copy.deepcopy(alert)
                for key, alert in (
                    self._alerts.items()
                )
                if (
                    key[0]
                    == result.warehouse_id
                    and key[1] == result.sku
                    and alert.status
                    == ProductAlertStatus.ACTIVE
                )
            ]

    def active_alerts(
        self,
        actor: ProductMonitoringActor,
    ) -> list[ProductMonitoringAlert]:
        self._authorize(
            actor,
            self.READER_ROLES,
        )

        with self._lock:
            return [
                copy.deepcopy(alert)
                for alert in (
                    self._alerts.values()
                )
                if (
                    alert.status
                    == ProductAlertStatus.ACTIVE
                    and (
                        "corporate_admin"
                        in actor.roles
                        or alert.warehouse_id
                        in actor.warehouse_ids
                    )
                )
            ]

    def summary(
        self,
        actor: ProductMonitoringActor,
        results: Iterable[
            ProductMonitoringResult
        ],
    ) -> dict:
        self._authorize(
            actor,
            self.READER_ROLES,
        )

        records = list(
            results
        )

        for record in records:
            if record.tenant_id != (
                self.tenant_id
            ):
                raise PermissionError(
                    "Cross-tenant assessment"
                )

            self._authorize(
                actor,
                self.READER_ROLES,
                record.warehouse_id,
            )

        return {
            "tenant_id": self.tenant_id,
            "products_assessed": len(
                records
            ),
            "average_health_score": (
                round(
                    sum(
                        record.health_score
                        for record in records
                    ) / len(records),
                    2,
                )
                if records
                else None
            ),
            "health_counts": {
                health.value: sum(
                    record.health == health
                    for record in records
                )
                for health in ProductHealth
            },
            "total_active_risks": sum(
                len(
                    record.active_risks
                )
                for record in records
            ),
        }

    def export_json(
        self,
        actor: ProductMonitoringActor,
        output_path: str | Path,
    ) -> Path:
        self._authorize(
            actor,
            self.MONITOR_ROLES,
        )

        with self._lock:
            alerts = [
                asdict(alert)
                for alert in (
                    self._alerts.values()
                )
                if (
                    "corporate_admin"
                    in actor.roles
                    or alert.warehouse_id
                    in actor.warehouse_ids
                )
            ]

        output = Path(
            output_path
        )

        output.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        output.write_text(
            json.dumps(
                alerts,
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )

        return output


if __name__ == "__main__":
    service = (
        RetailProductMonitoringService(
            tenant_id="demo"
        )
    )

    manager = ProductMonitoringActor(
        user_id="product-manager",
        tenant_id="demo",
        roles=frozenset({
            "product_manager",
        }),
        warehouse_ids=frozenset({
            "WH001",
        }),
    )

    product = ProductMonitoringRecord(
        tenant_id="demo",
        warehouse_id="WH001",
        sku="SKU001",
        product_name="Smart Device",
        category="Electronics",
        on_hand=30,
        reserved=10,
        reorder_point=25,
        daily_demand=8,
        previous_period_sales=150,
        current_period_sales=100,
        returned_units=12,
        inspected_units=100,
        defective_units=6,
        unit_price=Decimal("1500"),
        unit_cost=Decimal("1250"),
        nearest_expiry_date=None,
    )

    result = service.assess(
        manager,
        product,
    )

    print(
        json.dumps(
            asdict(result),
            indent=2,
            default=str,
        )
    )

    alerts = (
        service.synchronize_alerts(
            manager,
            result,
        )
    )

    print(
        "Active alerts:",
        len(alerts),
    )

    print(
        service.summary(
            manager,
            [result],
        )
    )
