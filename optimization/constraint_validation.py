"""Planned module: constraint validation. Implementation pending."""

"""
ai/optimization/constraint_validation.py

Operational constraint validation engine.

Supported checks:
- Purchase budget
- Order quantity and MOQ
- Supplier lead time
- Warehouse weight and volume
- Vehicle payload and volume
- Workforce staffing and hours

No operational action is executed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ConstraintIssue:
    code: str
    severity: str
    message: str


@dataclass
class ValidationResult:
    issues: list[ConstraintIssue] = field(
        default_factory=list
    )

    @property
    def valid(self) -> bool:
        return not any(
            issue.severity == "error"
            for issue in self.issues
        )

    def error(self, code: str, message: str):
        self.issues.append(
            ConstraintIssue(code, "error", message)
        )

    def warning(self, code: str, message: str):
        self.issues.append(
            ConstraintIssue(code, "warning", message)
        )

    def to_dict(self) -> dict:
        return {
            "valid": self.valid,
            "issues": [
                {
                    "code": issue.code,
                    "severity": issue.severity,
                    "message": issue.message,
                }
                for issue in self.issues
            ],
            "requires_approval": True,
        }


class ConstraintValidator:

    @staticmethod
    def number(
        data: dict[str, Any],
        name: str,
        result: ValidationResult,
    ) -> float | None:
        value = data.get(name)

        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value < 0
        ):
            result.error(
                "INVALID_INPUT",
                f"{name} must be a finite nonnegative number",
            )
            return None

        return float(value)

    def validate_purchase(self, data: dict) -> dict:
        result = ValidationResult()

        quantity = self.number(
            data, "quantity", result
        )
        minimum = self.number(
            data, "minimum_order_quantity", result
        )
        unit_cost = self.number(
            data, "unit_cost", result
        )
        budget = self.number(
            data, "available_budget", result
        )
        lead_time = self.number(
            data, "lead_time_days", result
        )
        max_lead_time = self.number(
            data, "max_lead_time_days", result
        )

        if quantity is not None and quantity <= 0:
            result.error(
                "INVALID_QUANTITY",
                "Purchase quantity must be positive",
            )

        if (
            quantity is not None
            and minimum is not None
            and quantity < minimum
        ):
            result.error(
                "MOQ_VIOLATION",
                "Quantity is below supplier MOQ",
            )

        if all(
            v is not None
            for v in (quantity, unit_cost, budget)
        ):
            if quantity * unit_cost > budget:
                result.error(
                    "BUDGET_EXCEEDED",
                    "Purchase cost exceeds available budget",
                )

        if (
            lead_time is not None
            and max_lead_time is not None
            and lead_time > max_lead_time
        ):
            result.error(
                "LEAD_TIME_EXCEEDED",
                "Supplier lead time exceeds the limit",
            )

        return result.to_dict()

    def validate_warehouse(self, data: dict) -> dict:
        result = ValidationResult()

        weight = self.number(
            data, "planned_weight_kg", result
        )
        max_weight = self.number(
            data, "available_weight_kg", result
        )
        volume = self.number(
            data, "planned_volume_m3", result
        )
        max_volume = self.number(
            data, "available_volume_m3", result
        )

        if (
            weight is not None
            and max_weight is not None
            and weight > max_weight
        ):
            result.error(
                "WAREHOUSE_WEIGHT_EXCEEDED",
                "Insufficient warehouse weight capacity",
            )

        if (
            volume is not None
            and max_volume is not None
            and volume > max_volume
        ):
            result.error(
                "WAREHOUSE_VOLUME_EXCEEDED",
                "Insufficient warehouse volume capacity",
            )

        return result.to_dict()

    def validate_vehicle(self, data: dict) -> dict:
        result = ValidationResult()

        weight = self.number(
            data, "load_weight_kg", result
        )
        capacity = self.number(
            data, "vehicle_capacity_kg", result
        )
        volume = self.number(
            data, "load_volume_m3", result
        )
        max_volume = self.number(
            data, "vehicle_capacity_m3", result
        )

        if (
            weight is not None
            and capacity is not None
            and weight > capacity
        ):
            result.error(
                "VEHICLE_OVERLOADED",
                "Vehicle payload limit exceeded",
            )

        if (
            volume is not None
            and max_volume is not None
            and volume > max_volume
        ):
            result.error(
                "VEHICLE_VOLUME_EXCEEDED",
                "Vehicle volume capacity exceeded",
            )

        return result.to_dict()

    def validate_workforce(self, data: dict) -> dict:
        result = ValidationResult()

        assigned = self.number(
            data, "assigned_workers", result
        )
        required = self.number(
            data, "required_workers", result
        )
        hours = self.number(
            data, "scheduled_hours", result
        )
        maximum = self.number(
            data, "max_allowed_hours", result
        )

        if (
            assigned is not None
            and required is not None
            and assigned < required
        ):
            result.error(
                "UNDERSTAFFED",
                "Assigned workers below requirement",
            )

        if (
            hours is not None
            and maximum is not None
            and hours > maximum
        ):
            result.error(
                "WORK_HOURS_EXCEEDED",
                "Scheduled hours exceed allowed limit",
            )

        return result.to_dict()

    def validate(
        self,
        category: str,
        data: dict,
    ) -> dict:

        handlers = {
            "purchase": self.validate_purchase,
            "warehouse": self.validate_warehouse,
            "vehicle": self.validate_vehicle,
            "workforce": self.validate_workforce,
        }

        handler = handlers.get(category)

        if handler is None:
            raise ValueError(
                f"Unsupported validation category: {category}"
            )

        return handler(data)
