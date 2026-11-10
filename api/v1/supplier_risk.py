from __future__ import annotations

"""Planned module: supplier risk. Implementation pending."""
performance_review

from datetime import datetime, timezone
from enum import Enum
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, ConfigDict

router = APIRouter(
    prefix="/supplier-risk",
    tags=["Supplier Risk Intelligence"],
)


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class SupplierRiskInput(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True
    )

    supplier_id: str = Field(min_length=1)
    supplier_name: str = Field(min_length=1)

    total_orders: int = Field(ge=1)
    delayed_orders: int = Field(ge=0)
    defective_orders: int = Field(ge=0)

    average_delay_days: float = Field(ge=0)
    financial_risk_score: float = Field(ge=0, le=100)
    compliance_risk_score: float = Field(ge=0, le=100)
    disruption_risk_score: float = Field(ge=0, le=100)


class SupplierRiskResult(BaseModel):
    supplier_id: str
    supplier_name: str
    risk_score: float
    risk_level: RiskLevel
    reliability_score: float
    delay_rate: float
    defect_rate: float
    estimated_delay_probability: float
    recommendations: list[str]
    evaluated_at: datetime


class SupplierRiskSummary(BaseModel):
    total_suppliers: int
    low_risk: int
    medium_risk: int
    high_risk: int
    critical_risk: int
    average_risk_score: float


# Demo-only in-memory storage.
# Replace with a tenant-scoped database repository.
risk_store: dict[str, SupplierRiskResult] = {}


def clamp(value: float) -> float:
    return max(0.0, min(100.0, value))


def classify_risk(score: float) -> RiskLevel:
    if score >= 80:
        return RiskLevel.CRITICAL
    if score >= 60:
        return RiskLevel.HIGH
    if score >= 30:
        return RiskLevel.MEDIUM
    return RiskLevel.LOW


def generate_recommendations(
    data: SupplierRiskInput,
    delay_rate: float,
    defect_rate: float,
    score: float,
) -> list[str]:

    recommendations = []

    if delay_rate > 20:
        recommendations.append(
            "Review delivery performance and "
            "consider backup suppliers."
        )

    if defect_rate > 5:
        recommendations.append(
            "Increase product quality inspections."
        )

    if data.financial_risk_score > 60:
        recommendations.append(
            "Review supplier financial stability."
        )

    if data.compliance_risk_score > 60:
        recommendations.append(
            "Conduct a supplier compliance audit."
        )

    if data.disruption_risk_score > 60:
        recommendations.append(
            "Prepare alternative sourcing plans."
        )

    if score >= 80:
        recommendations.append(
            "Escalate to procurement management "
            "for immediate review."
        )

    if not recommendations:
        recommendations.append(
            "Maintain routine supplier monitoring."
        )

    return recommendations


def calculate_supplier_risk(
    data: SupplierRiskInput,
) -> SupplierRiskResult:

    if data.delayed_orders > data.total_orders:
        raise ValueError(
            "Delayed orders cannot exceed total orders."
        )

    if data.defective_orders > data.total_orders:
        raise ValueError(
            "Defective orders cannot exceed total orders."
        )

    delay_rate = (
        data.delayed_orders / data.total_orders
    ) * 100

    defect_rate = (
        data.defective_orders / data.total_orders
    ) * 100

    delay_severity = clamp(
        data.average_delay_days * 10
    )

    delivery_risk = (
        delay_rate * 0.7
        + delay_severity * 0.3
    )

    quality_risk = clamp(defect_rate * 5)

    risk_score = (
        delivery_risk * 0.30
        + quality_risk * 0.20
        + data.financial_risk_score * 0.15
        + data.compliance_risk_score * 0.15
        + data.disruption_risk_score * 0.20
    )

    risk_score = round(clamp(risk_score), 2)

    # Historical delay frequency is a baseline proxy,
    # not a calibrated ML probability.
    delay_probability = round(
        delay_rate / 100, 4
    )

    return SupplierRiskResult(
        supplier_id=data.supplier_id,
        supplier_name=data.supplier_name,
        risk_score=risk_score,
        risk_level=classify_risk(risk_score),
        reliability_score=round(
            100 - risk_score, 2
        ),
        delay_rate=round(delay_rate, 2),
        defect_rate=round(defect_rate, 2),
        estimated_delay_probability=delay_probability,
        recommendations=generate_recommendations(
            data,
            delay_rate,
            defect_rate,
            risk_score,
        ),
        evaluated_at=datetime.now(timezone.utc),
    )


@router.post(
    "/assess",
    response_model=SupplierRiskResult,
)
async def assess_supplier_risk(
    payload: SupplierRiskInput,
):
    try:
        result = calculate_supplier_risk(payload)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc

    risk_store[result.supplier_id] = result
    return result


@router.get(
    "/",
    response_model=list[SupplierRiskResult],
)
async def list_supplier_risks(
    risk_level: RiskLevel | None = None,
):
    results = list(risk_store.values())

    if risk_level:
        results = [
            result
            for result in results
            if result.risk_level == risk_level
        ]

    return sorted(
        results,
        key=lambda item: item.risk_score,
        reverse=True,
    )


@router.get(
    "/summary",
    response_model=SupplierRiskSummary,
)
async def supplier_risk_summary():
    suppliers = list(risk_store.values())

    count = len(suppliers)

    average = (
        sum(s.risk_score for s in suppliers) / count
        if count
        else 0.0
    )

    return SupplierRiskSummary(
        total_suppliers=count,
        low_risk=sum(
            s.risk_level == RiskLevel.LOW
            for s in suppliers
        ),
        medium_risk=sum(
            s.risk_level == RiskLevel.MEDIUM
            for s in suppliers
        ),
        high_risk=sum(
            s.risk_level == RiskLevel.HIGH
            for s in suppliers
        ),
        critical_risk=sum(
            s.risk_level == RiskLevel.CRITICAL
            for s in suppliers
        ),
        average_risk_score=round(average, 2),
    )


@router.get(
    "/rankings",
    response_model=list[SupplierRiskResult],
)
async def rank_suppliers(
    limit: Annotated[
        int,
        Query(ge=1, le=100),
    ] = 20,
):
    return sorted(
        risk_store.values(),
        key=lambda supplier: supplier.risk_score,
    )[:limit]


@router.get(
    "/alerts",
    response_model=list[SupplierRiskResult],
)
async def get_risk_alerts():
    return [
        supplier
        for supplier in risk_store.values()
        if supplier.risk_level in {
            RiskLevel.HIGH,
            RiskLevel.CRITICAL,
        }
    ]


@router.get(
    "/{supplier_id}",
    response_model=SupplierRiskResult,
)
async def get_supplier_risk(supplier_id: str):
    supplier = risk_store.get(supplier_id)

    if supplier is None:
        raise HTTPException(
            status_code=404,
            detail="Supplier risk assessment not found",
        )

    return supplier


@router.delete("/{supplier_id}")
async def delete_supplier_risk(supplier_id: str):
    if supplier_id not in risk_store:
        raise HTTPException(
            status_code=404,
            detail="Supplier risk assessment not found",
        )

    del risk_store[supplier_id]

    return {
        "success": True,
        "message": "Supplier risk assessment deleted",
        "supplier_id": supplier_id,
    }
