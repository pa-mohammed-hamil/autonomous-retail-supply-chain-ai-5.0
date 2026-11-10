from __future__ import annotations

"""Planned module: severity classifier. Implementation pending."""

"""
backend/notifications/severity_classifier.py

Autonomous Retail Supply Chain AI 5.0

Python 3.10+
No external dependencies.

Features:
- Explainable severity classification
- Inventory and stockout risk
- Supplier delivery delays
- Warehouse capacity utilization
- Product defect rates
- Logistics delays
- Financial anomalies
- Safety incidents
- Configurable thresholds
- Tenant-scoped event metadata
- Batch classification
- Policy version tracking

This module classifies events only.
It does not send notifications or modify records.
"""


from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import IntEnum
from typing import Any, Mapping
from datetime import datetime, timezone


class Severity(IntEnum):
    INFO = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


class ClassificationError(ValueError):
    pass


@dataclass(frozen=True)
class SeverityThresholds:
    low_stock_ratio: Decimal = Decimal("1.0")
    critical_stock_ratio: Decimal = Decimal("0.25")

    high_stockout_probability: Decimal = Decimal("0.70")
    critical_stockout_probability: Decimal = Decimal("0.90")

    supplier_warning_days: Decimal = Decimal("2")
    supplier_critical_days: Decimal = Decimal("7")

    warehouse_warning_pct: Decimal = Decimal("80")
    warehouse_critical_pct: Decimal = Decimal("95")

    defect_warning_pct: Decimal = Decimal("2")
    defect_critical_pct: Decimal = Decimal("5")

    delivery_warning_hours: Decimal = Decimal("4")
    delivery_critical_hours: Decimal = Decimal("24")

    financial_warning_amount: Decimal = Decimal("10000")
    financial_critical_amount: Decimal = Decimal("100000")

    def __post_init__(self) -> None:
        if not (
            Decimal("0")
            <= self.critical_stock_ratio
            < self.low_stock_ratio
        ):
            raise ValueError("Invalid stock thresholds")

        if not (
            Decimal("0")
            <= self.high_stockout_probability
            < self.critical_stockout_probability
            <= Decimal("1")
        ):
            raise ValueError("Invalid stockout thresholds")

        pairs = (
            (
                self.supplier_warning_days,
                self.supplier_critical_days,
            ),
            (
                self.warehouse_warning_pct,
                self.warehouse_critical_pct,
            ),
            (
                self.defect_warning_pct,
                self.defect_critical_pct,
            ),
            (
                self.delivery_warning_hours,
                self.delivery_critical_hours,
            ),
            (
                self.financial_warning_amount,
                self.financial_critical_amount,
            ),
        )

        for warning, critical in pairs:
            if not (
                Decimal("0") <= warning < critical
            ):
                raise ValueError(
                    "Warning threshold must be "
                    "below critical threshold"
                )


@dataclass(frozen=True)
class ClassificationEvent:
    tenant_id: str
    event_id: str
    event_type: str
    resource_id: str
    metrics: Mapping[str, Any]
    occurred_at: datetime = field(
        default_factory=lambda:
        datetime.now(timezone.utc)
    )

    def __post_init__(self) -> None:
        for name in (
            "tenant_id",
            "event_id",
            "event_type",
            "resource_id",
        ):
            value = getattr(self, name)

            if not isinstance(value, str) or not value.strip():
                raise ClassificationError(
                    f"{name} is required"
                )

        if not isinstance(self.metrics, Mapping):
            raise ClassificationError(
                "metrics must be a mapping"
            )

        if (
            self.occurred_at.tzinfo is None
            or self.occurred_at.utcoffset() is None
        ):
            raise ClassificationError(
                "occurred_at must be timezone-aware"
            )


@dataclass(frozen=True)
class ClassificationResult:
    tenant_id: str
    event_id: str
    event_type: str
    resource_id: str
    severity: Severity
    rule_code: str
    reason: str
    recommended_action: str
    policy_version: str
    evaluated_at: datetime

    @property
    def severity_label(self) -> str:
        return self.severity.name.lower()


def decimal_metric(
    metrics: Mapping[str, Any],
    name: str,
    *,
    minimum: Decimal = Decimal("0"),
    maximum: Decimal | None = None,
) -> Decimal:
    if name not in metrics:
        raise ClassificationError(
            f"Missing metric: {name}"
        )

    value = metrics[name]

    if isinstance(value, bool):
        raise ClassificationError(
            f"Invalid numeric metric: {name}"
        )

    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ClassificationError(
            f"Invalid numeric metric: {name}"
        ) from None

    if not number.is_finite():
        raise ClassificationError(
            f"Non-finite metric: {name}"
        )

    if number < minimum:
        raise ClassificationError(
            f"{name} is below minimum"
        )

    if maximum is not None and number > maximum:
        raise ClassificationError(
            f"{name} exceeds maximum"
        )

    return number


class RetailSeverityClassifier:
    POLICY_VERSION = "severity-v1.0"

    SUPPORTED_EVENTS = frozenset({
        "inventory.low_stock",
        "inventory.stockout_risk",
        "supplier.delay",
        "warehouse.capacity",
        "quality.defect",
        "logistics.delivery_delay",
        "finance.anomaly",
        "safety.incident",
    })

    def __init__(
        self,
        thresholds: SeverityThresholds | None = None,
    ) -> None:
        self.thresholds = (
            thresholds or SeverityThresholds()
        )

    def _result(
        self,
        event: ClassificationEvent,
        *,
        severity: Severity,
        rule_code: str,
        reason: str,
        action: str,
    ) -> ClassificationResult:
        return ClassificationResult(
            tenant_id=event.tenant_id,
            event_id=event.event_id,
            event_type=event.event_type,
            resource_id=event.resource_id,
            severity=severity,
            rule_code=rule_code,
            reason=reason,
            recommended_action=action,
            policy_version=self.POLICY_VERSION,
            evaluated_at=datetime.now(timezone.utc),
        )

    def classify(
        self,
        event: ClassificationEvent,
    ) -> ClassificationResult:
        event_type = event.event_type
        metrics = event.metrics
        t = self.thresholds

        if event_type not in self.SUPPORTED_EVENTS:
            raise ClassificationError(
                f"Unsupported event type: {event_type}"
            )

        if event_type == "inventory.low_stock":
            available = decimal_metric(
                metrics, "available"
            )
            reorder = decimal_metric(
                metrics, "reorder_point"
            )

            if reorder == 0:
                raise ClassificationError(
                    "reorder_point must be positive"
                )

            ratio = available / reorder

            if ratio <= t.critical_stock_ratio:
                severity = Severity.CRITICAL
                action = (
                    "Initiate urgent replenishment "
                    "and review available transfers."
                )
            elif ratio <= t.low_stock_ratio:
                severity = Severity.HIGH
                action = (
                    "Review reorder requirements "
                    "and supplier lead times."
                )
            else:
                severity = Severity.INFO
                action = (
                    "Continue routine inventory monitoring."
                )

            return self._result(
                event,
                severity=severity,
                rule_code="INVENTORY_STOCK_RATIO",
                reason=(
                    f"Available/reorder ratio: {ratio:.3f}"
                ),
                action=action,
            )

        if event_type == "inventory.stockout_risk":
            probability = decimal_metric(
                metrics,
                "probability",
                maximum=Decimal("1"),
            )

            if probability >= (
                t.critical_stockout_probability
            ):
                severity = Severity.CRITICAL
            elif probability >= (
                t.high_stockout_probability
            ):
                severity = Severity.HIGH
            elif probability >= Decimal("0.40"):
                severity = Severity.MEDIUM
            else:
                severity = Severity.LOW

            return self._result(
                event,
                severity=severity,
                rule_code="STOCKOUT_PROBABILITY",
                reason=(
                    f"Predicted stockout probability: "
                    f"{probability:.1%}"
                ),
                action=(
                    "Validate forecast quality and "
                    "review replenishment options."
                ),
            )

        if event_type == "supplier.delay":
            delay = decimal_metric(
                metrics, "delay_days"
            )

            if delay >= t.supplier_critical_days:
                severity = Severity.CRITICAL
            elif delay >= t.supplier_warning_days:
                severity = Severity.HIGH
            elif delay > 0:
                severity = Severity.LOW
            else:
                severity = Severity.INFO

            return self._result(
                event,
                severity=severity,
                rule_code="SUPPLIER_DELAY",
                reason=f"Supplier delay: {delay} days",
                action=(
                    "Contact supplier and assess "
                    "alternative fulfillment options."
                ),
            )

        if event_type == "warehouse.capacity":
            occupied = decimal_metric(
                metrics, "occupied_units"
            )
            capacity = decimal_metric(
                metrics, "capacity_units"
            )

            if capacity <= 0:
                raise ClassificationError(
                    "capacity_units must be positive"
                )

            utilization = (
                occupied / capacity
            ) * Decimal("100")

            if utilization >= (
                t.warehouse_critical_pct
            ):
                severity = Severity.CRITICAL
            elif utilization >= (
                t.warehouse_warning_pct
            ):
                severity = Severity.HIGH
            else:
                severity = Severity.INFO

            return self._result(
                event,
                severity=severity,
                rule_code="WAREHOUSE_UTILIZATION",
                reason=(
                    f"Warehouse utilization: "
                    f"{utilization:.1f}%"
                ),
                action=(
                    "Review storage capacity, "
                    "transfers, and inbound scheduling."
                ),
            )

        if event_type == "quality.defect":
            rate = decimal_metric(
                metrics,
                "defect_rate_pct",
                maximum=Decimal("100"),
            )

            if rate >= t.defect_critical_pct:
                severity = Severity.CRITICAL
            elif rate >= t.defect_warning_pct:
                severity = Severity.HIGH
            else:
                severity = Severity.INFO

            return self._result(
                event,
                severity=severity,
                rule_code="QUALITY_DEFECT_RATE",
                reason=f"Defect rate: {rate}%",
                action=(
                    "Review inspection results and "
                    "consider batch quarantine."
                ),
            )

        if event_type == "logistics.delivery_delay":
            hours = decimal_metric(
                metrics, "delay_hours"
            )

            if hours >= (
                t.delivery_critical_hours
            ):
                severity = Severity.CRITICAL
            elif hours >= (
                t.delivery_warning_hours
            ):
                severity = Severity.HIGH
            elif hours > 0:
                severity = Severity.LOW
            else:
                severity = Severity.INFO

            return self._result(
                event,
                severity=severity,
                rule_code="LOGISTICS_DELAY",
                reason=(
                    f"Delivery delay: {hours} hours"
                ),
                action=(
                    "Check carrier status and update "
                    "affected fulfillment plans."
                ),
            )

        if event_type == "finance.anomaly":
            amount = decimal_metric(
                metrics, "anomaly_amount"
            )

            if amount >= (
                t.financial_critical_amount
            ):
                severity = Severity.CRITICAL
            elif amount >= (
                t.financial_warning_amount
            ):
                severity = Severity.HIGH
            elif amount > 0:
                severity = Severity.MEDIUM
            else:
                severity = Severity.INFO

            return self._result(
                event,
                severity=severity,
                rule_code="FINANCIAL_ANOMALY",
                reason=(
                    f"Anomaly amount: {amount}"
                ),
                action=(
                    "Request authorized financial "
                    "review before taking action."
                ),
            )

        # Safety incident classification.
        # Trusted safety event producers must supply
        # these flags after human/system verification.
        immediate_danger = metrics.get(
            "immediate_danger"
        )
        injury_reported = metrics.get(
            "injury_reported"
        )

        if not isinstance(
            immediate_danger, bool
        ) or not isinstance(
            injury_reported, bool
        ):
            raise ClassificationError(
                "Safety flags must be boolean"
            )

        if immediate_danger or injury_reported:
            severity = Severity.CRITICAL
        else:
            severity = Severity.HIGH

        return self._result(
            event,
            severity=severity,
            rule_code="SAFETY_INCIDENT",
            reason=(
                "Immediate danger: "
                f"{immediate_danger}; "
                "injury reported: "
                f"{injury_reported}"
            ),
            action=(
                "Follow the approved emergency "
                "response and incident review procedure."
            ),
        )

    def classify_batch(
        self,
        events: list[ClassificationEvent],
    ) -> list[ClassificationResult]:
        return [
            self.classify(event)
            for event in events
        ]


if __name__ == "__main__":
    classifier = RetailSeverityClassifier()

    event = ClassificationEvent(
        tenant_id="retail-demo",
        event_id="EVT001",
        event_type="inventory.low_stock",
        resource_id="WH001:SKU001",
        metrics={
            "available": 12,
            "reorder_point": 100,
        },
    )

    result = classifier.classify(event)

    print("Severity:", result.severity_label)
    print("Rule:", result.rule_code)
    print("Reason:", result.reason)
    print("Action:", result.recommended_action)
