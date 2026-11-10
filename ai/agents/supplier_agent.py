"""Planned module: supplier agent. Implementation pending."""

"""
File: ai/agents/supplier_agent.py
Autonomous Retail Supply Chain AI 5.0
"""

from __future__ import annotations

import threading
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from .base_agent import (
    BaseAgent, AgentRequest, AgentValidationError
)


def supplier_money(value: Any, name: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(
        value, (str, int, Decimal)
    ):
        raise AgentValidationError(f"Invalid {name}")

    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise AgentValidationError(f"Invalid {name}") from exc

    if not number.is_finite() or number < 0:
        raise AgentValidationError(f"Invalid {name}")

    return number


@dataclass
class Supplier:
    supplier_id: str
    tenant_id: str
    name: str
    category: str
    lead_time_days: int
    on_time_delivery_percent: float
    defect_rate_percent: float
    active: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


class SupplierAgent(BaseAgent):

    def __init__(self, working_memory=None):
        super().__init__(
            agent_id="supplier_agent",
            name="Retail Supplier Intelligence Agent",
            capabilities={
                "register_supplier",
                "get_supplier",
                "evaluate_supplier",
                "compare_suppliers",
                "evaluate_quotation",
                "supplier_report",
            },
            working_memory=working_memory,
        )

        self._suppliers: dict[
            tuple[str, str], Supplier
        ] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _text(value, name):
        if not isinstance(value, str) or not value.strip():
            raise AgentValidationError(f"{name} is required")
        return value.strip()

    @staticmethod
    def _percent(value, name):
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not 0 <= value <= 100
        ):
            raise AgentValidationError(
                f"{name} must be between 0 and 100"
            )
        return float(value)

    @staticmethod
    def _positive_int(value, name):
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or value <= 0
        ):
            raise AgentValidationError(
                f"{name} must be a positive integer"
            )
        return value

    def _get(self, tenant_id, supplier_id):
        supplier = self._suppliers.get(
            (tenant_id, supplier_id)
        )
        if supplier is None:
            raise AgentValidationError("Supplier not found")
        return supplier

    def _register(self, request):
        p = request.payload
        tenant_id = request.context.tenant_id

        supplier = Supplier(
            supplier_id=self._text(
                p.get("supplier_id"), "supplier_id"
            ),
            tenant_id=tenant_id,
            name=self._text(p.get("name"), "name"),
            category=self._text(
                p.get("category"), "category"
            ),
            lead_time_days=self._positive_int(
                p.get("lead_time_days"), "lead_time_days"
            ),
            on_time_delivery_percent=self._percent(
                p.get("on_time_delivery_percent"),
                "on_time_delivery_percent",
            ),
            defect_rate_percent=self._percent(
                p.get("defect_rate_percent"),
                "defect_rate_percent",
            ),
        )

        with self._lock:
            key = (tenant_id, supplier.supplier_id)
            if key in self._suppliers:
                raise AgentValidationError(
                    "Supplier already registered"
                )
            self._suppliers[key] = supplier

        return supplier.to_dict()

    def _evaluate(self, supplier):
        # Transparent heuristic, not an ML model.
        delivery = supplier.on_time_delivery_percent
        quality = 100 - supplier.defect_rate_percent
        lead_score = max(
            0, 100 - supplier.lead_time_days * 5
        )

        score = (
            delivery * 0.45
            + quality * 0.40
            + lead_score * 0.15
        )

        if score >= 85:
            rating = "excellent"
        elif score >= 70:
            rating = "good"
        elif score >= 50:
            rating = "needs_review"
        else:
            rating = "high_risk"

        return {
            "supplier_id": supplier.supplier_id,
            "supplier_name": supplier.name,
            "score": round(score, 2),
            "rating": rating,
            "active": supplier.active,
            "evaluation_method": "weighted_heuristic",
        }

    def _compare(self, tenant_id, payload):
        ids = payload.get("supplier_ids")

        if (
            not isinstance(ids, list)
            or not 2 <= len(ids) <= 30
            or not all(isinstance(x, str) for x in ids)
            or len(set(ids)) != len(ids)
        ):
            raise AgentValidationError(
                "Provide 2-30 unique supplier IDs"
            )

        with self._lock:
            suppliers = [
                self._get(tenant_id, sid)
                for sid in ids
            ]
            results = [
                self._evaluate(s)
                for s in suppliers
            ]

        results.sort(
            key=lambda item: (
                not item["active"],
                -item["score"],
            )
        )

        eligible = [
            item for item in results if item["active"]
        ]

        return {
            "ranking": results,
            "recommended_supplier": (
                eligible[0]["supplier_id"]
                if eligible else None
            ),
            "selection_requires_review": True,
        }

    def _quotation(self, tenant_id, payload):
        supplier_id = self._text(
            payload.get("supplier_id"), "supplier_id"
        )

        with self._lock:
            supplier = self._get(
                tenant_id, supplier_id
            )
            if not supplier.active:
                raise AgentValidationError(
                    "Supplier is inactive"
                )
            evaluation = self._evaluate(supplier)

        quantity = self._positive_int(
            payload.get("quantity"), "quantity"
        )
        unit_price = supplier_money(
            payload.get("unit_price"), "unit_price"
        )
        shipping = supplier_money(
            payload.get("shipping_cost", "0"),
            "shipping_cost",
        )

        total = unit_price * quantity + shipping

        return {
            "supplier_id": supplier_id,
            "quantity": quantity,
            "unit_price": str(unit_price),
            "shipping_cost": str(shipping),
            "estimated_total": str(total),
            "supplier_score": evaluation["score"],
            "lead_time_days": supplier.lead_time_days,
            "approval_required": True,
            "purchase_executed": False,
        }

    def process(self, request: AgentRequest) -> dict:
        task = request.task_type
        p = request.payload
        tenant = request.context.tenant_id

        if task == "register_supplier":
            return self._register(request)

        if task == "get_supplier":
            supplier_id = self._text(
                p.get("supplier_id"), "supplier_id"
            )
            with self._lock:
                return self._get(
                    tenant, supplier_id
                ).to_dict()

        if task == "evaluate_supplier":
            supplier_id = self._text(
                p.get("supplier_id"), "supplier_id"
            )
            with self._lock:
                return self._evaluate(
                    self._get(tenant, supplier_id)
                )

        if task == "compare_suppliers":
            return self._compare(tenant, p)

        if task == "evaluate_quotation":
            return self._quotation(tenant, p)

        if task == "supplier_report":
            with self._lock:
                suppliers = [
                    s.to_dict()
                    for s in self._suppliers.values()
                    if s.tenant_id == tenant
                ]
            return {
                "supplier_count": len(suppliers),
                "suppliers": suppliers[:100],
            }

        raise AgentValidationError(
            "Unsupported supplier task"
        )
