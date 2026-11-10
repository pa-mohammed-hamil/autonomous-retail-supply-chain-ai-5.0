
"""
ai/optimization/lead_time_constraints.py

Supplier lead-time feasibility checker.

Assumptions:
- Calendar excludes weekends only.
- Lead times are measured in business days.
- The standard deviation is also expressed
  in business days.
- Supplier capacity applies to the planning
  period represented by the input.
- Results are planning estimates, not
  guaranteed delivery dates.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta
from statistics import NormalDist


def add_business_days(
    start: date,
    days: int,
) -> date:
    if days < 0:
        raise ValueError("Days cannot be negative")

    current = start
    added = 0

    while added < days:
        current += timedelta(days=1)

        if current.weekday() < 5:
            added += 1

    return current


@dataclass(frozen=True)
class LeadTimeRequest:
    sku: str
    supplier_id: str
    order_date: date
    required_by: date
    quantity: int
    mean_lead_time_days: float
    lead_time_std_days: float = 0.0
    processing_days: int = 0
    supplier_capacity: int | None = None
    confidence_level: float = 0.95

    def __post_init__(self):
        if not self.sku or not self.supplier_id:
            raise ValueError(
                "SKU and supplier ID required"
            )

        if self.required_by < self.order_date:
            raise ValueError(
                "Required date precedes order date"
            )

        if (
            isinstance(self.quantity, bool)
            or not isinstance(self.quantity, int)
            or self.quantity <= 0
        ):
            raise ValueError("Quantity must be positive")

        for name in (
            "mean_lead_time_days",
            "lead_time_std_days",
        ):
            value = getattr(self, name)

            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value < 0
            ):
                raise ValueError(f"Invalid {name}")

        if (
            isinstance(self.processing_days, bool)
            or not isinstance(self.processing_days, int)
            or self.processing_days < 0
        ):
            raise ValueError("Invalid processing days")

        if self.supplier_capacity is not None:
            if (
                isinstance(self.supplier_capacity, bool)
                or not isinstance(self.supplier_capacity, int)
                or self.supplier_capacity < 0
            ):
                raise ValueError(
                    "Invalid supplier capacity"
                )

        if (
            isinstance(self.confidence_level, bool)
            or not isinstance(
                self.confidence_level, (int, float)
            )
            or not math.isfinite(self.confidence_level)
            or not 0 < self.confidence_level < 1
        ):
            raise ValueError("Invalid confidence level")


class LeadTimeConstraintOptimizer:

    def evaluate(
        self,
        request: LeadTimeRequest,
    ) -> dict:

        z = NormalDist().inv_cdf(
            request.confidence_level
        )

        expected_days = math.ceil(
            request.processing_days
            + request.mean_lead_time_days
        )

        confidence_days = math.ceil(
            max(
                0.0,
                request.processing_days
                + request.mean_lead_time_days
                + z * request.lead_time_std_days,
            )
        )

        expected_date = add_business_days(
            request.order_date,
            expected_days,
        )

        confidence_date = add_business_days(
            request.order_date,
            confidence_days,
        )

        capacity_ok = (
            request.supplier_capacity is None
            or request.quantity
            <= request.supplier_capacity
        )

        expected_on_time = (
            expected_date <= request.required_by
        )

        confidence_on_time = (
            confidence_date <= request.required_by
        )

        feasible = (
            capacity_ok and confidence_on_time
        )

        issues = []

        if not capacity_ok:
            issues.append(
                "Requested quantity exceeds "
                "supplier capacity"
            )

        if not confidence_on_time:
            issues.append(
                "Delivery confidence date exceeds "
                "required date"
            )

        return {
            "sku": request.sku,
            "supplier_id": request.supplier_id,
            "requested_quantity": request.quantity,
            "expected_delivery_date": (
                expected_date.isoformat()
            ),
            "confidence_delivery_date": (
                confidence_date.isoformat()
            ),
            "confidence_level": (
                request.confidence_level
            ),
            "expected_on_time": expected_on_time,
            "confidence_on_time": confidence_on_time,
            "capacity_feasible": capacity_ok,
            "feasible": feasible,
            "issues": issues,
            "requires_approval": True,
            "purchase_order_created": False,
        }

    def compare_suppliers(
        self,
        requests: list[LeadTimeRequest],
    ) -> dict:

        if not requests:
            raise ValueError(
                "Supplier requests required"
            )

        results = [
            self.evaluate(request)
            for request in requests
        ]

        feasible = [
            row for row in results
            if row["feasible"]
        ]

        feasible.sort(
            key=lambda row: (
                row["confidence_delivery_date"],
                row["supplier_id"],
            )
        )

        return {
            "recommended_supplier": (
                feasible[0]["supplier_id"]
                if feasible else None
            ),
            "alternatives": results,
            "requires_approval": True,
        }
