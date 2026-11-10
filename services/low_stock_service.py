from __future__ import annotations

"""Planned module: low stock service. Implementation pending."""

"""
backend/services/low_stock_service.py

Autonomous Retail Supply Chain AI 5.0
Low Stock Intelligence Service

Python 3.10+
Standard library only.

Features:
- Multi-tenant inventory monitoring
- Warehouse-scoped RBAC
- Available stock calculation
- Reorder point and safety stock
- Demand-aware stock coverage
- Incoming stock analysis
- Low-stock severity classification
- Suggested reorder quantities
- Idempotent low-stock alert events
- Alert recovery / reactivation
- Batch inventory scanning
- JSON export

No purchase orders or external alerts
are executed automatically.

Production requires persistent data,
validated forecasts, durable events,
and approval-controlled procurement.
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
            f"{name} must be nonnegative integer"
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


class StockSeverity(str, Enum):
    HEALTHY = "healthy"
    WARNING = "warning"
    HIGH = "high"
    CRITICAL = "critical"
    OUT_OF_STOCK = "out_of_stock"


class StockAlertStatus(str, Enum):
    ACTIVE = "active"
    RESOLVED = "resolved"


@dataclass(frozen=True)
class LowStockActor:
    user_id: str
    tenant_id: str
    roles: frozenset[str]
    warehouse_ids: frozenset[str] = (
        frozenset()
    )
    is_active: bool = True


@dataclass(frozen=True)
class LowStockRecord:
    tenant_id: str
    warehouse_id: str
    sku: str
    on_hand: int
    reserved: int
    incoming: int
    reorder_point: int
    safety_stock: int
    daily_demand: float
    lead_time_days: int


@dataclass(frozen=True)
class LowStockAssessment:
    tenant_id: str
    warehouse_id: str
    sku: str
    available_stock: int
    incoming_stock: int
    inventory_position: int
    reorder_point: int
    safety_stock: int
    daily_demand: float
    days_of_cover: float | None
    lead_time_days: int
    expected_lead_time_demand: int
    target_stock: int
    suggested_reorder_quantity: int
    severity: StockSeverity
    stockout_before_replenishment: bool
    requires_approval: bool
    assessed_at: str


@dataclass
class LowStockAlert:
    alert_id: str
    tenant_id: str
    warehouse_id: str
    sku: str
    severity: StockSeverity
    status: StockAlertStatus
    created_at: str
    updated_at: str
    occurrence_count: int = 1
    resolved_at: str | None = None


@dataclass(frozen=True)
class LowStockEvent:
    event_id: str
    tenant_id: str
    alert_id: str
    warehouse_id: str
    sku: str
    event_type: str
    timestamp: str
    severity: StockSeverity


class RetailLowStockService:
    READER_ROLES = frozenset({
        "inventory_analyst",
        "inventory_worker",
        "warehouse_staff",
        "warehouse_manager",
        "inventory_manager",
        "operations_manager",
        "corporate_admin",
    })

    MONITOR_ROLES = frozenset({
        "stock_monitor",
        "inventory_manager",
        "warehouse_manager",
        "corporate_admin",
    })

    MANAGER_ROLES = frozenset({
        "inventory_manager",
        "warehouse_manager",
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
            tuple[str, str],
            LowStockAlert,
        ] = {}

        self._events: list[
            LowStockEvent
        ] = []

    def _authorize(
        self,
        actor: LowStockActor,
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
                "Low-stock access denied"
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

    def assess(
        self,
        actor: LowStockActor,
        record: LowStockRecord,
    ) -> LowStockAssessment:
        self._authorize(
            actor,
            self.READER_ROLES,
            record.warehouse_id,
        )

        if record.tenant_id != (
            self.tenant_id
        ):
            raise PermissionError(
                "Cross-tenant stock record"
            )

        require_text(
            record.warehouse_id,
            "warehouse_id",
        )

        require_text(
            record.sku,
            "sku",
        )

        for name in (
            "on_hand",
            "reserved",
            "incoming",
            "reorder_point",
            "safety_stock",
            "lead_time_days",
        ):
            nonnegative_int(
                getattr(record, name),
                name,
            )

        daily_demand = (
            nonnegative_float(
                record.daily_demand,
                "daily_demand",
            )
        )

        if record.reserved > (
            record.on_hand
        ):
            raise ValueError(
                "Reserved exceeds on-hand stock"
            )

        available = (
            record.on_hand
            - record.reserved
        )

        inventory_position = (
            available
            + record.incoming
        )

        lead_time_demand = math.ceil(
            daily_demand
            * record.lead_time_days
        )

        dynamic_reorder_point = (
            lead_time_demand
            + record.safety_stock
        )

        effective_reorder_point = max(
            record.reorder_point,
            dynamic_reorder_point,
        )

        # Target includes a configurable
        # safety-stock buffer.
        target_stock = (
            effective_reorder_point
            + record.safety_stock
        )

        suggested_quantity = max(
            0,
            target_stock
            - inventory_position,
        )

        days_of_cover = (
            available / daily_demand
            if daily_demand > 0
            else None
        )

        stockout_before_replenishment = (
            daily_demand > 0
            and available
            < lead_time_demand
        )

        if available == 0:
            severity = (
                StockSeverity.OUT_OF_STOCK
            )

        elif (
            daily_demand > 0
            and days_of_cover is not None
            and days_of_cover <= 1
        ):
            severity = (
                StockSeverity.CRITICAL
            )

        elif stockout_before_replenishment:
            severity = (
                StockSeverity.HIGH
            )

        elif available <= (
            effective_reorder_point
        ):
            severity = (
                StockSeverity.WARNING
            )

        else:
            severity = (
                StockSeverity.HEALTHY
            )

        return LowStockAssessment(
            tenant_id=self.tenant_id,
            warehouse_id=(
                record.warehouse_id
            ),
            sku=record.sku,
            available_stock=available,
            incoming_stock=(
                record.incoming
            ),
            inventory_position=(
                inventory_position
            ),
            reorder_point=(
                effective_reorder_point
            ),
            safety_stock=(
                record.safety_stock
            ),
            daily_demand=daily_demand,
            days_of_cover=(
                round(days_of_cover, 2)
                if days_of_cover is not None
                else None
            ),
            lead_time_days=(
                record.lead_time_days
            ),
            expected_lead_time_demand=(
                lead_time_demand
            ),
            target_stock=target_stock,
            suggested_reorder_quantity=(
                suggested_quantity
            ),
            severity=severity,
            stockout_before_replenishment=(
                stockout_before_replenishment
            ),
            requires_approval=(
                suggested_quantity > 0
            ),
            assessed_at=utc_now(),
        )

    def assess_batch(
        self,
        actor: LowStockActor,
        records: Iterable[
            LowStockRecord
        ],
    ) -> list[LowStockAssessment]:
        results = []

        seen = set()

        for record in records:
            key = (
                record.warehouse_id,
                record.sku,
            )

            if key in seen:
                raise ValueError(
                    "Duplicate warehouse/SKU record"
                )

            seen.add(key)

            results.append(
                self.assess(
                    actor,
                    record,
                )
            )

        priority = {
            StockSeverity.OUT_OF_STOCK: 0,
            StockSeverity.CRITICAL: 1,
            StockSeverity.HIGH: 2,
            StockSeverity.WARNING: 3,
            StockSeverity.HEALTHY: 4,
        }

        return sorted(
            results,
            key=lambda item: (
                priority[item.severity],
                item.warehouse_id,
                item.sku,
            ),
        )

    def _event(
        self,
        alert: LowStockAlert,
        event_type: str,
    ) -> None:
        self._events.append(
            LowStockEvent(
                event_id=str(uuid.uuid4()),
                tenant_id=self.tenant_id,
                alert_id=alert.alert_id,
                warehouse_id=(
                    alert.warehouse_id
                ),
                sku=alert.sku,
                event_type=event_type,
                timestamp=utc_now(),
                severity=alert.severity,
            )
        )

    def synchronize_alert(
        self,
        actor: LowStockActor,
        assessment: LowStockAssessment,
    ) -> LowStockAlert | None:
        self._authorize(
            actor,
            self.MONITOR_ROLES,
            assessment.warehouse_id,
        )

        if assessment.tenant_id != (
            self.tenant_id
        ):
            raise PermissionError(
                "Cross-tenant assessment"
            )

        key = (
            assessment.warehouse_id,
            assessment.sku,
        )

        with self._lock:
            existing = self._alerts.get(
                key
            )

            if assessment.severity == (
                StockSeverity.HEALTHY
            ):
                if (
                    existing
                    and existing.status
                    == StockAlertStatus.ACTIVE
                ):
                    existing.status = (
                        StockAlertStatus.RESOLVED
                    )

                    existing.resolved_at = (
                        utc_now()
                    )

                    existing.updated_at = (
                        existing.resolved_at
                    )

                    self._event(
                        existing,
                        "stock_recovered",
                    )

                return (
                    copy.deepcopy(existing)
                    if existing
                    else None
                )

            if existing is None:
                now = utc_now()

                alert = LowStockAlert(
                    alert_id=str(
                        uuid.uuid4()
                    ),
                    tenant_id=self.tenant_id,
                    warehouse_id=(
                        assessment.warehouse_id
                    ),
                    sku=assessment.sku,
                    severity=assessment.severity,
                    status=(
                        StockAlertStatus.ACTIVE
                    ),
                    created_at=now,
                    updated_at=now,
                )

                self._alerts[
                    key
                ] = alert

                self._event(
                    alert,
                    "low_stock_detected",
                )

                return copy.deepcopy(
                    alert
                )

            if existing.status == (
                StockAlertStatus.RESOLVED
            ):
                existing.status = (
                    StockAlertStatus.ACTIVE
                )

                existing.resolved_at = None
                existing.occurrence_count += 1
                existing.severity = (
                    assessment.severity
                )

                existing.updated_at = (
                    utc_now()
                )

                self._event(
                    existing,
                    "low_stock_reactivated",
                )

            elif existing.severity != (
                assessment.severity
            ):
                existing.severity = (
                    assessment.severity
                )

                existing.updated_at = (
                    utc_now()
                )

                self._event(
                    existing,
                    "stock_severity_changed",
                )

            return copy.deepcopy(
                existing
            )

    def synchronize_batch(
        self,
        actor: LowStockActor,
        assessments: Iterable[
            LowStockAssessment
        ],
    ) -> list[LowStockAlert]:
        results = []

        for assessment in assessments:
            alert = self.synchronize_alert(
                actor,
                assessment,
            )

            if alert is not None:
                results.append(
                    alert
                )

        return results

    def active_alerts(
        self,
        actor: LowStockActor,
    ) -> list[LowStockAlert]:
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
                    == StockAlertStatus.ACTIVE
                    and (
                        "corporate_admin"
                        in actor.roles
                        or alert.warehouse_id
                        in actor.warehouse_ids
                    )
                )
            ]

    def event_history(
        self,
        actor: LowStockActor,
        warehouse_id: str,
    ) -> list[LowStockEvent]:
        self._authorize(
            actor,
            self.READER_ROLES,
            warehouse_id,
        )

        with self._lock:
            return [
                copy.deepcopy(event)
                for event in self._events
                if event.warehouse_id
                == warehouse_id
            ]

    def summary(
        self,
        actor: LowStockActor,
        assessments: Iterable[
            LowStockAssessment
        ],
    ) -> dict[str, Any]:
        self._authorize(
            actor,
            self.READER_ROLES,
        )

        counts = {
            severity.value: 0
            for severity in StockSeverity
        }

        total_reorder = 0
        total = 0

        for item in assessments:
            self._authorize(
                actor,
                self.READER_ROLES,
                item.warehouse_id,
            )

            if item.tenant_id != (
                self.tenant_id
            ):
                raise PermissionError(
                    "Cross-tenant assessment"
                )

            total += 1
            counts[
                item.severity.value
            ] += 1

            total_reorder += (
                item.suggested_reorder_quantity
            )

        return {
            "tenant_id": self.tenant_id,
            "total_skus_assessed": total,
            "severity_counts": counts,
            "total_suggested_reorder_units": (
                total_reorder
            ),
        }

    def export_json(
        self,
        actor: LowStockActor,
        output_path: str | Path,
    ) -> Path:
        self._authorize(
            actor,
            self.MANAGER_ROLES,
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
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        return output


if __name__ == "__main__":
    service = RetailLowStockService(
        tenant_id="demo"
    )

    monitor = LowStockActor(
        user_id="stock-monitor",
        tenant_id="demo",
        roles=frozenset({
            "stock_monitor",
            "inventory_analyst",
        }),
        warehouse_ids=frozenset({
            "WH001",
        }),
    )

    records = [
        LowStockRecord(
            tenant_id="demo",
            warehouse_id="WH001",
            sku="SKU001",
            on_hand=100,
            reserved=20,
            incoming=30,
            reorder_point=50,
            safety_stock=15,
            daily_demand=12,
            lead_time_days=7,
        ),
        LowStockRecord(
            tenant_id="demo",
            warehouse_id="WH001",
            sku="SKU002",
            on_hand=8,
            reserved=3,
            incoming=0,
            reorder_point=20,
            safety_stock=10,
            daily_demand=8,
            lead_time_days=5,
        ),
    ]

    assessments = service.assess_batch(
        monitor,
        records,
    )

    service.synchronize_batch(
        monitor,
        assessments,
    )

    for result in assessments:
        print(
            json.dumps(
                asdict(result),
                indent=2,
                default=str,
            )
        )

    print(
        service.summary(
            monitor,
            assessments,
        )
    )
