from __future__ import annotations

"""Planned module: alert rules. Implementation pending."""

"""
backend/rules/alert_rules.py

Autonomous Retail Supply Chain AI 5.0

Deterministic, tenant-aware retail alert rules.

Features:
- Low stock and stockout alerts
- Predicted stockout risk
- Supplier delivery delays
- Warehouse capacity thresholds
- Product quality defects
- Logistics delivery delays
- Financial anomalies
- Stable deduplication keys
- Configurable thresholds
- Structured decisions for downstream services

No external dependencies.
No network calls or database writes.
"""


from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from hashlib import sha256
from typing import Any, Mapping
import json


class AlertSeverity(str, Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AlertCategory(str, Enum):
    INVENTORY = "inventory"
    STOCKOUT = "stockout"
    SUPPLIER = "supplier"
    WAREHOUSE = "warehouse"
    QUALITY = "quality"
    LOGISTICS = "logistics"
    FINANCE = "finance"


@dataclass(frozen=True)
class AlertThresholds:
    low_stock_ratio: Decimal = Decimal("1.00")
    critical_stock_ratio: Decimal = Decimal("0.25")

    high_stockout_probability: Decimal = Decimal("0.70")
    critical_stockout_probability: Decimal = Decimal("0.90")

    supplier_delay_days: int = 2
    critical_supplier_delay_days: int = 7

    warehouse_warning_pct: Decimal = Decimal("80")
    warehouse_critical_pct: Decimal = Decimal("95")

    quality_warning_pct: Decimal = Decimal("2")
    quality_critical_pct: Decimal = Decimal("5")

    delivery_delay_hours: Decimal = Decimal("4")
    critical_delivery_delay_hours: Decimal = Decimal("24")

    financial_warning_amount: Decimal = Decimal("10000")
    financial_critical_amount: Decimal = Decimal("100000")

    def __post_init__(self):
        pairs = (
            (self.critical_stock_ratio,
             self.low_stock_ratio),
            (self.high_stockout_probability,
             self.critical_stockout_probability),
            (self.supplier_delay_days,
             self.critical_supplier_delay_days),
            (self.warehouse_warning_pct,
             self.warehouse_critical_pct),
            (self.quality_warning_pct,
             self.quality_critical_pct),
            (self.delivery_delay_hours,
             self.critical_delivery_delay_hours),
            (self.financial_warning_amount,
             self.financial_critical_amount),
        )

        for lower, upper in pairs:
            if lower > upper:
                raise ValueError(
                    "Alert thresholds are inconsistent"
                )


@dataclass(frozen=True)
class AlertDecision:
    tenant_id: str
    category: AlertCategory
    severity: AlertSeverity
    rule_code: str
    resource_id: str
    title: str
    message: str
    deduplication_key: str
    metrics: dict[str, Any] = field(default_factory=dict)
    recommended_action: str = ""


def required(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} is required")
    return value.strip()


def number(value: Any, field_name: str) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be numeric")

    try:
        result = Decimal(str(value))
    except Exception as exc:
        raise ValueError(
            f"{field_name} must be numeric"
        ) from exc

    if not result.is_finite():
        raise ValueError(
            f"{field_name} must be finite"
        )

    return result


def nonnegative(value: Any, field_name: str) -> Decimal:
    result = number(value, field_name)
    if result < 0:
        raise ValueError(
            f"{field_name} cannot be negative"
        )
    return result


class RetailAlertRules:
    def __init__(
        self,
        tenant_id: str,
        thresholds: AlertThresholds | None = None,
    ):
        self.tenant_id = required(tenant_id, "tenant_id")
        self.thresholds = thresholds or AlertThresholds()

    def _decision(
        self,
        *,
        category: AlertCategory,
        severity: AlertSeverity,
        rule_code: str,
        resource_id: str,
        title: str,
        message: str,
        metrics: dict[str, Any],
        recommended_action: str,
    ) -> AlertDecision:
        resource_id = required(
            resource_id, "resource_id"
        )

        identity = json.dumps(
            {
                "tenant_id": self.tenant_id,
                "rule_code": rule_code,
                "resource_id": resource_id,
            },
            sort_keys=True,
            separators=(",", ":"),
        )

        key = sha256(
            identity.encode("utf-8")
        ).hexdigest()

        return AlertDecision(
            tenant_id=self.tenant_id,
            category=category,
            severity=severity,
            rule_code=rule_code,
            resource_id=resource_id,
            title=title,
            message=message,
            deduplication_key=key,
            metrics=metrics,
            recommended_action=recommended_action,
        )

    def low_stock(
        self,
        *,
        sku: str,
        warehouse_id: str,
        available: int,
        reorder_point: int,
    ) -> AlertDecision | None:
        sku = required(sku, "sku")
        warehouse_id = required(
            warehouse_id, "warehouse_id"
        )

        if (
            type(available) is not int
            or type(reorder_point) is not int
            or available < 0
            or reorder_point < 0
        ):
            raise ValueError(
                "Invalid inventory quantities"
            )

        if reorder_point == 0:
            return None

        ratio = Decimal(available) / Decimal(
            reorder_point
        )

        if ratio > self.thresholds.low_stock_ratio:
            return None

        severity = (
            AlertSeverity.CRITICAL
            if ratio <= self.thresholds.critical_stock_ratio
            else AlertSeverity.HIGH
        )

        return self._decision(
            category=AlertCategory.INVENTORY,
            severity=severity,
            rule_code="LOW_STOCK",
            resource_id=f"{warehouse_id}:{sku}",
            title="Low inventory detected",
            message=(
                f"{sku} has {available} available units "
                f"against reorder point {reorder_point}."
            ),
            metrics={
                "available": available,
                "reorder_point": reorder_point,
                "stock_ratio": str(ratio),
            },
            recommended_action=(
                "Review replenishment and supplier lead time."
            ),
        )

    def stockout_risk(
        self,
        *,
        sku: str,
        warehouse_id: str,
        probability: Any,
        forecast_horizon_days: int,
    ) -> AlertDecision | None:
        p = number(probability, "probability")

        if not Decimal("0") <= p <= Decimal("1"):
            raise ValueError(
                "Probability must be between 0 and 1"
            )

        if (
            type(forecast_horizon_days) is not int
            or forecast_horizon_days <= 0
        ):
            raise ValueError("Invalid forecast horizon")

        if p < self.thresholds.high_stockout_probability:
            return None

        severity = (
            AlertSeverity.CRITICAL
            if p >= self.thresholds.critical_stockout_probability
            else AlertSeverity.HIGH
        )

        return self._decision(
            category=AlertCategory.STOCKOUT,
            severity=severity,
            rule_code="STOCKOUT_RISK",
            resource_id=(
                f"{required(warehouse_id, 'warehouse_id')}:"
                f"{required(sku, 'sku')}"
            ),
            title="Predicted stockout risk",
            message=(
                f"Stockout probability is {p * 100}% "
                f"over {forecast_horizon_days} days."
            ),
            metrics={
                "probability": str(p),
                "horizon_days": forecast_horizon_days,
            },
            recommended_action=(
                "Review forecast, reserve stock, "
                "and prepare replenishment."
            ),
        )

    def supplier_delay(
        self,
        *,
        supplier_id: str,
        purchase_order_id: str,
        delay_days: int,
    ) -> AlertDecision | None:
        if type(delay_days) is not int:
            raise ValueError("delay_days must be integer")

        if delay_days < self.thresholds.supplier_delay_days:
            return None

        severity = (
            AlertSeverity.CRITICAL
            if delay_days >=
            self.thresholds.critical_supplier_delay_days
            else AlertSeverity.HIGH
        )

        return self._decision(
            category=AlertCategory.SUPPLIER,
            severity=severity,
            rule_code="SUPPLIER_DELAY",
            resource_id=required(
                purchase_order_id, "purchase_order_id"
            ),
            title="Supplier delivery delay",
            message=(
                f"Supplier {required(supplier_id, 'supplier_id')} "
                f"is delayed by {delay_days} days."
            ),
            metrics={
                "supplier_id": supplier_id,
                "delay_days": delay_days,
            },
            recommended_action=(
                "Contact supplier and evaluate alternate sourcing."
            ),
        )

    def warehouse_capacity(
        self,
        *,
        warehouse_id: str,
        occupied_units: int,
        capacity_units: int,
    ) -> AlertDecision | None:
        if (
            type(occupied_units) is not int
            or type(capacity_units) is not int
            or occupied_units < 0
            or capacity_units <= 0
        ):
            raise ValueError("Invalid warehouse capacity")

        pct = (
            Decimal(occupied_units)
            / Decimal(capacity_units)
            * 100
        )

        if pct < self.thresholds.warehouse_warning_pct:
            return None

        severity = (
            AlertSeverity.CRITICAL
            if pct >= self.thresholds.warehouse_critical_pct
            else AlertSeverity.HIGH
        )

        return self._decision(
            category=AlertCategory.WAREHOUSE,
            severity=severity,
            rule_code="WAREHOUSE_CAPACITY",
            resource_id=required(
                warehouse_id, "warehouse_id"
            ),
            title="Warehouse capacity warning",
            message=f"Warehouse utilization is {pct:.2f}%.",
            metrics={
                "occupied_units": occupied_units,
                "capacity_units": capacity_units,
                "utilization_pct": str(pct),
            },
            recommended_action=(
                "Review slotting, transfers, and capacity planning."
            ),
        )

    def quality_defect(
        self,
        *,
        batch_id: str,
        defect_rate_pct: Any,
    ) -> AlertDecision | None:
        rate = nonnegative(
            defect_rate_pct, "defect_rate_pct"
        )

        if rate > 100:
            raise ValueError(
                "Defect rate cannot exceed 100%"
            )

        if rate < self.thresholds.quality_warning_pct:
            return None

        severity = (
            AlertSeverity.CRITICAL
            if rate >= self.thresholds.quality_critical_pct
            else AlertSeverity.HIGH
        )

        return self._decision(
            category=AlertCategory.QUALITY,
            severity=severity,
            rule_code="QUALITY_DEFECT",
            resource_id=required(batch_id, "batch_id"),
            title="Product quality issue",
            message=f"Batch defect rate is {rate}%.",
            metrics={"defect_rate_pct": str(rate)},
            recommended_action=(
                "Inspect affected batch and consider quarantine."
            ),
        )

    def delivery_delay(
        self,
        *,
        shipment_id: str,
        delay_hours: Any,
    ) -> AlertDecision | None:
        hours = nonnegative(
            delay_hours, "delay_hours"
        )

        if hours < self.thresholds.delivery_delay_hours:
            return None

        severity = (
            AlertSeverity.CRITICAL
            if hours >=
            self.thresholds.critical_delivery_delay_hours
            else AlertSeverity.HIGH
        )

        return self._decision(
            category=AlertCategory.LOGISTICS,
            severity=severity,
            rule_code="DELIVERY_DELAY",
            resource_id=required(
                shipment_id, "shipment_id"
            ),
            title="Shipment delivery delay",
            message=f"Shipment delayed by {hours} hours.",
            metrics={"delay_hours": str(hours)},
            recommended_action=(
                "Check carrier status and notify affected teams."
            ),
        )

    def financial_anomaly(
        self,
        *,
        transaction_id: str,
        anomaly_amount: Any,
        currency: str = "INR",
    ) -> AlertDecision | None:
        amount = nonnegative(
            anomaly_amount, "anomaly_amount"
        )

        if amount < self.thresholds.financial_warning_amount:
            return None

        severity = (
            AlertSeverity.CRITICAL
            if amount >=
            self.thresholds.financial_critical_amount
            else AlertSeverity.HIGH
        )

        return self._decision(
            category=AlertCategory.FINANCE,
            severity=severity,
            rule_code="FINANCIAL_ANOMALY",
            resource_id=required(
                transaction_id, "transaction_id"
            ),
            title="Financial anomaly detected",
            message=(
                f"Potential anomaly amount: "
                f"{amount} {required(currency, 'currency')}."
            ),
            metrics={
                "anomaly_amount": str(amount),
                "currency": currency,
            },
            recommended_action=(
                "Request financial review before any action."
            ),
        )

    def evaluate(
        self,
        event_type: str,
        payload: Mapping[str, Any],
    ) -> AlertDecision | None:
        if not isinstance(payload, Mapping):
            raise ValueError("payload must be a mapping")

        handlers = {
            "inventory.low_stock": self.low_stock,
            "inventory.stockout_risk": self.stockout_risk,
            "supplier.delay": self.supplier_delay,
            "warehouse.capacity": self.warehouse_capacity,
            "quality.defect": self.quality_defect,
            "logistics.delivery_delay": self.delivery_delay,
            "finance.anomaly": self.financial_anomaly,
        }

        handler = handlers.get(event_type)

        if handler is None:
            raise ValueError(
                f"Unsupported event type: {event_type}"
            )

        return handler(**dict(payload))

    def evaluate_batch(
        self,
        events: list[tuple[str, Mapping[str, Any]]],
    ) -> list[AlertDecision]:
        results = []

        for event_type, payload in events:
            decision = self.evaluate(
                event_type, payload
            )
            if decision is not None:
                results.append(decision)

        return results


if __name__ == "__main__":
    rules = RetailAlertRules(
        tenant_id="retail-demo"
    )

    events = [
        (
            "inventory.low_stock",
            {
                "sku": "SKU001",
                "warehouse_id": "WH001",
                "available": 12,
                "reorder_point": 100,
            },
        ),
        (
            "inventory.stockout_risk",
            {
                "sku": "SKU001",
                "warehouse_id": "WH001",
                "probability": 0.94,
                "forecast_horizon_days": 7,
            },
        ),
        (
            "supplier.delay",
            {
                "supplier_id": "SUP001",
                "purchase_order_id": "PO001",
                "delay_days": 8,
            },
        ),
        (
            "warehouse.capacity",
            {
                "warehouse_id": "WH001",
                "occupied_units": 970,
                "capacity_units": 1000,
            },
        ),
    ]

    for alert in rules.evaluate_batch(events):
        print(
            alert.severity.value,
            alert.rule_code,
            alert.resource_id,
            alert.recommended_action,
        )
