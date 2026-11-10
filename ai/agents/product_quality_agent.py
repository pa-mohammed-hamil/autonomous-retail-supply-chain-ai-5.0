
"""
File: ai/agents/product_quality_agent.py

Autonomous Retail Supply Chain AI 5.0
Python 3.10+ | Standard library only
"""

from __future__ import annotations

import threading
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any
from uuid import uuid4

from .base_agent import (
    BaseAgent,
    AgentRequest,
    AgentValidationError,
    utc_now,
)


@dataclass
class QualityInspection:
    inspection_id: str
    tenant_id: str
    product_id: str
    batch_id: str
    supplier_id: str
    inspected_units: int
    defective_units: int
    critical_defects: int
    defect_rate_percent: float
    quality_score: float
    decision: str
    defects: list[str]
    inspected_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ProductQualityAgent(BaseAgent):

    def __init__(
        self,
        working_memory: Any | None = None,
        review_threshold_percent: float = 2.0,
        quarantine_threshold_percent: float = 5.0,
    ) -> None:
        super().__init__(
            agent_id="product_quality_agent",
            name="Product Quality Intelligence Agent",
            capabilities={
                "inspect_product_batch",
                "get_inspection",
                "supplier_quality_report",
                "product_quality_report",
                "quality_alerts",
            },
            working_memory=working_memory,
        )

        if not (
            0 <= review_threshold_percent
            < quarantine_threshold_percent <= 100
        ):
            raise ValueError(
                "Invalid quality thresholds."
            )

        self.review_threshold = (
            review_threshold_percent
        )
        self.quarantine_threshold = (
            quarantine_threshold_percent
        )

        self._inspections: dict[
            tuple[str, str], QualityInspection
        ] = {}

        self._lock = threading.RLock()

    @staticmethod
    def _text(value: Any, name: str) -> str:
        if (
            not isinstance(value, str)
            or not value.strip()
        ):
            raise AgentValidationError(
                f"{name} is required."
            )
        return value.strip()

    @staticmethod
    def _integer(
        value: Any,
        name: str,
        minimum: int = 0,
    ) -> int:
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or value < minimum
        ):
            raise AgentValidationError(
                f"{name} must be an integer >= {minimum}."
            )
        return value

    def _inspect(
        self,
        request: AgentRequest,
    ) -> dict:
        payload = request.payload

        inspected = self._integer(
            payload.get("inspected_units"),
            "inspected_units",
            minimum=1,
        )

        defective = self._integer(
            payload.get("defective_units"),
            "defective_units",
        )

        critical = self._integer(
            payload.get("critical_defects", 0),
            "critical_defects",
        )

        if defective > inspected:
            raise AgentValidationError(
                "Defective units exceed inspected units."
            )

        if critical > defective:
            raise AgentValidationError(
                "Critical defects exceed defective units."
            )

        defects = payload.get("defects", [])

        if (
            not isinstance(defects, list)
            or not all(
                isinstance(item, str)
                and item.strip()
                for item in defects
            )
        ):
            raise AgentValidationError(
                "defects must be a list of strings."
            )

        defect_rate = (
            defective / inspected * 100
        )

        quality_score = max(
            0.0,
            100.0 - defect_rate,
        )

        if (
            critical > 0
            or defect_rate >= self.quarantine_threshold
        ):
            decision = "quarantine_recommended"
        elif defect_rate >= self.review_threshold:
            decision = "manual_review"
        else:
            decision = "accept_recommended"

        inspection = QualityInspection(
            inspection_id=str(uuid4()),
            tenant_id=request.context.tenant_id,
            product_id=self._text(
                payload.get("product_id"),
                "product_id",
            ),
            batch_id=self._text(
                payload.get("batch_id"),
                "batch_id",
            ),
            supplier_id=self._text(
                payload.get("supplier_id"),
                "supplier_id",
            ),
            inspected_units=inspected,
            defective_units=defective,
            critical_defects=critical,
            defect_rate_percent=round(
                defect_rate, 2
            ),
            quality_score=round(
                quality_score, 2
            ),
            decision=decision,
            defects=defects,
            inspected_at=utc_now(),
        )

        with self._lock:
            self._inspections[
                (
                    inspection.tenant_id,
                    inspection.inspection_id,
                )
            ] = inspection

        return {
            "inspection": inspection.to_dict(),
            "requires_human_review": (
                decision != "accept_recommended"
            ),
            "inventory_quarantine_executed": False,
            "decision_is_recommendation": True,
        }

    def _get(
        self,
        tenant_id: str,
        inspection_id: str,
    ) -> QualityInspection:
        inspection = self._inspections.get(
            (tenant_id, inspection_id)
        )

        if inspection is None:
            raise AgentValidationError(
                "Inspection not found."
            )

        return inspection

    def _report(
        self,
        tenant_id: str,
        field_name: str,
        field_value: str,
    ) -> dict:
        with self._lock:
            inspections = [
                inspection.to_dict()
                for inspection in self._inspections.values()
                if inspection.tenant_id == tenant_id
                and getattr(
                    inspection, field_name
                ) == field_value
            ]

        inspected_units = sum(
            item["inspected_units"]
            for item in inspections
        )

        defective_units = sum(
            item["defective_units"]
            for item in inspections
        )

        critical_defects = sum(
            item["critical_defects"]
            for item in inspections
        )

        decisions = Counter(
            item["decision"]
            for item in inspections
        )

        return {
            field_name: field_value,
            "inspection_count": len(inspections),
            "total_inspected_units": inspected_units,
            "total_defective_units": defective_units,
            "total_critical_defects": critical_defects,
            "weighted_defect_rate_percent": (
                round(
                    defective_units
                    / inspected_units * 100,
                    2,
                )
                if inspected_units else None
            ),
            "decision_counts": dict(decisions),
        }

    def _alerts(self, tenant_id: str) -> dict:
        with self._lock:
            inspections = [
                inspection.to_dict()
                for inspection in self._inspections.values()
                if inspection.tenant_id == tenant_id
                and inspection.decision in {
                    "manual_review",
                    "quarantine_recommended",
                }
            ]

        return {
            "alert_count": len(inspections),
            "inspections": inspections[:100],
        }

    def process(
        self,
        request: AgentRequest,
    ) -> dict:
        task = request.task_type
        payload = request.payload
        tenant_id = request.context.tenant_id

        if task == "inspect_product_batch":
            return self._inspect(request)

        if task == "get_inspection":
            inspection_id = self._text(
                payload.get("inspection_id"),
                "inspection_id",
            )

            with self._lock:
                return self._get(
                    tenant_id,
                    inspection_id,
                ).to_dict()

        if task == "supplier_quality_report":
            supplier_id = self._text(
                payload.get("supplier_id"),
                "supplier_id",
            )
            return self._report(
                tenant_id,
                "supplier_id",
                supplier_id,
            )

        if task == "product_quality_report":
            product_id = self._text(
                payload.get("product_id"),
                "product_id",
            )
            return self._report(
                tenant_id,
                "product_id",
                product_id,
            )

        if task == "quality_alerts":
            return self._alerts(tenant_id)

        raise AgentValidationError(
            "Unsupported product quality task."
        )
