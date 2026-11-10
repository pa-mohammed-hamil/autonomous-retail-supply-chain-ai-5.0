"""Planned module: supplier risk refresh. Implementation pending."""

"""
ai/risk/supplier_risk_refresh.py

Supplier operational risk refresh.

Risk factors:
- Delivery reliability
- Quality acceptance
- Lead time
- Capacity sufficiency
- Data freshness

Features:
- Weighted risk score
- Low / medium / high classification
- Explainable risk components
- Configurable thresholds
- Supplier risk alerts
- Structured JSON-ready output

No suppliers are automatically suspended,
blocked or removed.
"""

from __future__ import annotations

import math

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class SupplierRiskWeights:
    delivery: float = 0.30
    quality: float = 0.25
    lead_time: float = 0.15
    capacity: float = 0.20
    freshness: float = 0.10

    def as_dict(self) -> dict:
        return {
            "delivery": self.delivery,
            "quality": self.quality,
            "lead_time": self.lead_time,
            "capacity": self.capacity,
            "freshness": self.freshness,
        }


class SupplierRiskRefresh:

    def __init__(
        self,
        weights: SupplierRiskWeights | None = None,
        reference_lead_time_days: float = 7.0,
        max_data_age_days: float = 30.0,
    ):
        self.weights = (
            weights or SupplierRiskWeights()
        )

        values = self.weights.as_dict()

        if any(
            not math.isfinite(value) or value < 0
            for value in values.values()
        ):
            raise ValueError("Invalid risk weights")

        if not math.isclose(
            sum(values.values()),
            1.0,
            abs_tol=1e-9,
        ):
            raise ValueError(
                "Risk weights must sum to 1"
            )

        if (
            not math.isfinite(reference_lead_time_days)
            or reference_lead_time_days <= 0
            or not math.isfinite(max_data_age_days)
            or max_data_age_days <= 0
        ):
            raise ValueError(
                "Invalid risk reference values"
            )

        self.reference_lead_time_days = (
            reference_lead_time_days
        )
        self.max_data_age_days = max_data_age_days

    @staticmethod
    def _number(
        row: dict,
        key: str,
        minimum: float = 0,
        maximum: float = math.inf,
    ) -> float:

        value = row.get(key)

        if isinstance(value, bool):
            raise ValueError(f"Invalid {key}")

        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Invalid {key}"
            ) from exc

        if (
            not math.isfinite(number)
            or not minimum <= number <= maximum
        ):
            raise ValueError(
                f"{key} out of range"
            )

        return number

    @staticmethod
    def _timestamp(value: str) -> datetime:
        if not isinstance(value, str):
            raise ValueError(
                "Invalid observed_at"
            )

        dt = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )

        if dt.tzinfo is None or dt.utcoffset() is None:
            raise ValueError(
                "Timestamp must include timezone"
            )

        return dt.astimezone(timezone.utc)

    def evaluate(
        self,
        supplier: dict,
        required_quantity: int,
        as_of: datetime | None = None,
    ) -> dict:

        if (
            isinstance(required_quantity, bool)
            or not isinstance(required_quantity, int)
            or required_quantity <= 0
        ):
            raise ValueError(
                "required_quantity must be positive"
            )

        supplier_id = supplier.get("supplier_id")
        sku = supplier.get("sku")

        if (
            not isinstance(supplier_id, str)
            or not supplier_id.strip()
            or not isinstance(sku, str)
            or not sku.strip()
        ):
            raise ValueError(
                "Supplier ID and SKU required"
            )

        on_time = self._number(
            supplier, "on_time_rate", 0, 1
        )

        quality = self._number(
            supplier, "quality_rate", 0, 1
        )

        lead_time = self._number(
            supplier, "lead_time_days"
        )

        capacity = self._number(
            supplier, "available_capacity"
        )

        observed_at = self._timestamp(
            supplier["observed_at"]
        )

        as_of = as_of or datetime.now(
            timezone.utc
        )

        if (
            as_of.tzinfo is None
            or as_of.utcoffset() is None
        ):
            raise ValueError(
                "as_of must include timezone"
            )

        as_of = as_of.astimezone(timezone.utc)

        age_days = (
            as_of - observed_at
        ).total_seconds() / 86400

        if age_days < 0:
            raise ValueError(
                "Supplier observation is in the future"
            )

        components = {
            "delivery": 1.0 - on_time,
            "quality": 1.0 - quality,
            "lead_time": min(
                1.0,
                max(
                    0.0,
                    (
                        lead_time
                        - self.reference_lead_time_days
                    )
                    / self.reference_lead_time_days,
                ),
            ),
            "capacity": max(
                0.0,
                1.0 - capacity / required_quantity,
            ),
            "freshness": min(
                1.0,
                age_days / self.max_data_age_days,
            ),
        }

        weights = self.weights.as_dict()

        score = 100 * sum(
            components[key] * weights[key]
            for key in components
        )

        if score < 25:
            level = "low"
        elif score < 50:
            level = "medium"
        else:
            level = "high"

        alerts = []

        if level == "high":
            alerts.append("HIGH_SUPPLIER_RISK")

        if capacity < required_quantity:
            alerts.append(
                "INSUFFICIENT_SUPPLIER_CAPACITY"
            )

        if age_days > self.max_data_age_days:
            alerts.append("STALE_SUPPLIER_DATA")

        if quality < 0.95:
            alerts.append("QUALITY_BELOW_THRESHOLD")

        return {
            "supplier_id": supplier_id,
            "sku": sku,
            "risk_score": round(score, 2),
            "risk_level": level,
            "risk_components": {
                key: round(value, 4)
                for key, value in components.items()
            },
            "data_age_days": round(
                age_days, 2
            ),
            "required_quantity": required_quantity,
            "available_capacity": capacity,
            "alerts": alerts,
            "requires_human_review": bool(alerts),
            "supplier_status_changed": False,
        }

    def refresh_all(
        self,
        suppliers: list[dict],
        required_quantities: dict[str, int],
        as_of: datetime | None = None,
    ) -> dict:

        results = []
        rejected = []

        for index, supplier in enumerate(suppliers):
            try:
                sku = supplier["sku"]

                if sku not in required_quantities:
                    raise ValueError(
                        f"No required quantity for {sku}"
                    )

                results.append(
                    self.evaluate(
                        supplier=supplier,
                        required_quantity=(
                            required_quantities[sku]
                        ),
                        as_of=as_of,
                    )
                )

            except (
                ValueError,
                TypeError,
                KeyError,
                OverflowError,
            ) as exc:
                rejected.append({
                    "row_index": index,
                    "reason": str(exc),
                })

        return {
            "evaluated_count": len(results),
            "rejected_count": len(rejected),
            "results": results,
            "rejected": rejected,
            "supplier_status_changed": False,
        }
