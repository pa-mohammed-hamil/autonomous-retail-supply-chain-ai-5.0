from __future__ import annotations

"""Planned module: supplier risk service. Implementation pending."""

"""
Autonomous Retail Supply Chain AI 5.0
backend/services/supplier_risk_service.py

Python 3.10+ | Standard library only

Reference implementation:
- Multi-tenant access control
- Supplier delivery and quality risk
- Financial and disruption exposure
- Weighted, explainable risk scoring
- Optional trained ML model adapter
- Batch supplier assessment
- Idempotent assessments
- Risk alerts and audit logging
- JSON export

The default risk score is a heuristic,
not a calibrated default probability.

No supplier is blocked automatically.
"""


import copy
import hashlib
import json
import math
import threading
import uuid

from dataclasses import (
    asdict,
    dataclass,
    field,
)
from datetime import (
    datetime,
    timezone,
)
from enum import Enum
from pathlib import Path
from typing import Callable, Iterable


def utc_now() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


def required_text(
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


def percentage(
    value: float,
    name: str,
) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not 0 <= value <= 100
    ):
        raise ValueError(
            f"{name} must be between 0 and 100"
        )

    return float(value)


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


class SupplierRiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True)
class SupplierRiskActor:
    user_id: str
    tenant_id: str
    roles: frozenset[str]
    is_active: bool = True


@dataclass(frozen=True)
class SupplierRiskInput:
    tenant_id: str
    supplier_id: str
    supplier_name: str
    assessment_date: str

    total_deliveries: int
    late_deliveries: int

    inspected_units: int
    defective_units: int

    average_lead_time_days: float
    lead_time_variability_pct: float

    financial_risk_score: float
    disruption_risk_score: float

    dependency_pct: float
    unresolved_incidents: int = 0


@dataclass(frozen=True)
class SupplierRiskFactor:
    factor: str
    raw_score: float
    weight: float
    weighted_score: float


@dataclass(frozen=True)
class SupplierRiskAssessment:
    assessment_id: str
    tenant_id: str
    supplier_id: str
    supplier_name: str
    assessment_date: str
    risk_level: SupplierRiskLevel
    overall_risk_score: float
    delivery_risk_score: float
    quality_risk_score: float
    financial_risk_score: float
    disruption_risk_score: float
    dependency_risk_score: float
    factors: tuple[
        SupplierRiskFactor, ...
    ]
    recommendations: tuple[str, ...]
    ml_risk_score: float | None
    model_name: str
    assessed_at: str
    input_fingerprint: str


@dataclass(frozen=True)
class SupplierRiskAuditEvent:
    event_id: str
    tenant_id: str
    assessment_id: str
    actor_id: str
    action: str
    timestamp: str
    details: dict = field(
        default_factory=dict
    )


@dataclass
class SupplierRiskOutboxEvent:
    event_id: str
    tenant_id: str
    assessment_id: str
    supplier_id: str
    event_type: str
    payload: dict
    created_at: str
    delivered: bool = False


# Optional ML contract:
# predictor(data) -> risk score 0..100
SupplierRiskPredictor = Callable[
    [SupplierRiskInput],
    float,
]


class RetailSupplierRiskService:
    ASSESSOR_ROLES = frozenset({
        "supplier_risk_analyst",
        "procurement_manager",
        "risk_manager",
        "operations_manager",
        "corporate_admin",
    })

    READER_ROLES = (
        ASSESSOR_ROLES
        | frozenset({
            "procurement_analyst",
            "supplier_manager",
            "finance_analyst",
        })
    )

    WEIGHTS = {
        "delivery": 0.30,
        "quality": 0.25,
        "financial": 0.15,
        "disruption": 0.20,
        "dependency": 0.10,
    }

    def __init__(
        self,
        tenant_id: str,
        ml_predictor: (
            SupplierRiskPredictor | None
        ) = None,
    ):
        self.tenant_id = required_text(
            tenant_id,
            "tenant_id",
        )

        self.ml_predictor = (
            ml_predictor
        )

        self._lock = threading.RLock()

        self._assessments: dict[
            str, SupplierRiskAssessment
        ] = {}

        self._audit: list[
            SupplierRiskAuditEvent
        ] = []

        self._outbox: dict[
            str, SupplierRiskOutboxEvent
        ] = {}

    def _authorize(
        self,
        actor: SupplierRiskActor,
        roles: frozenset[str],
    ) -> None:
        if (
            not actor.is_active
            or actor.tenant_id
            != self.tenant_id
            or not actor.user_id.strip()
            or not (actor.roles & roles)
        ):
            raise PermissionError(
                "Supplier risk access denied"
            )

    def _validate(
        self,
        data: SupplierRiskInput,
    ) -> None:
        if data.tenant_id != (
            self.tenant_id
        ):
            raise PermissionError(
                "Cross-tenant supplier input"
            )

        required_text(
            data.supplier_id,
            "supplier_id",
        )

        required_text(
            data.supplier_name,
            "supplier_name",
        )

        from datetime import date

        date.fromisoformat(
            data.assessment_date
        )

        for name in (
            "total_deliveries",
            "late_deliveries",
            "inspected_units",
            "defective_units",
            "unresolved_incidents",
        ):
            nonnegative_int(
                getattr(data, name),
                name,
            )

        if (
            data.late_deliveries
            > data.total_deliveries
        ):
            raise ValueError(
                "Late deliveries exceed total"
            )

        if (
            data.defective_units
            > data.inspected_units
        ):
            raise ValueError(
                "Defects exceed inspected units"
            )

        if (
            isinstance(
                data.average_lead_time_days,
                bool,
            )
            or not isinstance(
                data.average_lead_time_days,
                (int, float),
            )
            or not math.isfinite(
                data.average_lead_time_days
            )
            or data.average_lead_time_days < 0
        ):
            raise ValueError(
                "Invalid average lead time"
            )

        for name in (
            "lead_time_variability_pct",
            "financial_risk_score",
            "disruption_risk_score",
            "dependency_pct",
        ):
            percentage(
                getattr(data, name),
                name,
            )

    @staticmethod
    def _fingerprint(
        data: SupplierRiskInput,
    ) -> str:
        payload = json.dumps(
            asdict(data),
            sort_keys=True,
        )

        return hashlib.sha256(
            payload.encode(
                "utf-8"
            )
        ).hexdigest()

    def _calculate_factors(
        self,
        data: SupplierRiskInput,
    ) -> dict[str, float]:
        if data.total_deliveries:
            late_rate = (
                data.late_deliveries
                / data.total_deliveries
                * 100
            )
        else:
            # Unknown performance is
            # not equivalent to perfect.
            late_rate = 50.0

        if data.inspected_units:
            defect_rate = (
                data.defective_units
                / data.inspected_units
                * 100
            )
        else:
            defect_rate = 50.0

        delivery_risk = min(
            100.0,
            0.70 * late_rate
            + 0.30
            * data.lead_time_variability_pct,
        )

        quality_risk = min(
            100.0,
            defect_rate * 5,
        )

        disruption_risk = min(
            100.0,
            data.disruption_risk_score
            + data.unresolved_incidents * 5,
        )

        return {
            "delivery": round(
                delivery_risk,
                2,
            ),
            "quality": round(
                quality_risk,
                2,
            ),
            "financial": round(
                data.financial_risk_score,
                2,
            ),
            "disruption": round(
                disruption_risk,
                2,
            ),
            "dependency": round(
                data.dependency_pct,
                2,
            ),
        }

    @staticmethod
    def _risk_level(
        score: float,
    ) -> SupplierRiskLevel:
        if score >= 75:
            return (
                SupplierRiskLevel.CRITICAL
            )

        if score >= 55:
            return (
                SupplierRiskLevel.HIGH
            )

        if score >= 30:
            return (
                SupplierRiskLevel.MEDIUM
            )

        return (
            SupplierRiskLevel.LOW
        )

    @staticmethod
    def _recommendations(
        factors: dict[str, float],
        level: SupplierRiskLevel,
    ) -> tuple[str, ...]:
        actions = []

        if factors["delivery"] >= 50:
            actions.append(
                "Review delivery SLAs and "
                "supplier lead-time reliability."
            )

        if factors["quality"] >= 50:
            actions.append(
                "Increase incoming quality "
                "inspection and investigate defects."
            )

        if factors["financial"] >= 60:
            actions.append(
                "Request financial risk review "
                "before increasing exposure."
            )

        if factors["disruption"] >= 60:
            actions.append(
                "Prepare a supplier continuity "
                "and contingency plan."
            )

        if factors["dependency"] >= 70:
            actions.append(
                "Evaluate alternative suppliers "
                "to reduce concentration risk."
            )

        if level == (
            SupplierRiskLevel.CRITICAL
        ):
            actions.append(
                "Escalate to procurement and "
                "risk managers for human review."
            )

        if not actions:
            actions.append(
                "Continue routine supplier "
                "performance monitoring."
            )

        return tuple(
            actions
        )

    def assess(
        self,
        actor: SupplierRiskActor,
        assessment_id: str,
        data: SupplierRiskInput,
    ) -> SupplierRiskAssessment:
        self._authorize(
            actor,
            self.ASSESSOR_ROLES,
        )

        assessment_id = required_text(
            assessment_id,
            "assessment_id",
        )

        self._validate(
            data
        )

        fingerprint = self._fingerprint(
            data
        )

        with self._lock:
            existing = (
                self._assessments.get(
                    assessment_id
                )
            )

            if existing:
                if existing.input_fingerprint != (
                    fingerprint
                ):
                    raise ValueError(
                        "Assessment ID conflict"
                    )

                return copy.deepcopy(
                    existing
                )

        factor_scores = (
            self._calculate_factors(
                data
            )
        )

        factors = tuple(
            SupplierRiskFactor(
                factor=name,
                raw_score=score,
                weight=(
                    self.WEIGHTS[name]
                ),
                weighted_score=round(
                    score
                    * self.WEIGHTS[name],
                    3,
                ),
            )
            for name, score
            in factor_scores.items()
        )

        overall = round(
            sum(
                factor.weighted_score
                for factor in factors
            ),
            2,
        )

        ml_score = None
        model_name = (
            "weighted_supplier_risk_v1"
        )

        if self.ml_predictor:
            predicted = self.ml_predictor(
                data
            )

            ml_score = percentage(
                predicted,
                "ml_risk_score",
            )

            # Keep the ML result separate
            # from the explainable score.
            model_name = (
                "weighted_score_plus_external_ml"
            )

        level = self._risk_level(
            overall
        )

        result = SupplierRiskAssessment(
            assessment_id=assessment_id,
            tenant_id=self.tenant_id,
            supplier_id=(
                data.supplier_id
            ),
            supplier_name=(
                data.supplier_name
            ),
            assessment_date=(
                data.assessment_date
            ),
            risk_level=level,
            overall_risk_score=(
                overall
            ),
            delivery_risk_score=(
                factor_scores["delivery"]
            ),
            quality_risk_score=(
                factor_scores["quality"]
            ),
            financial_risk_score=(
                factor_scores["financial"]
            ),
            disruption_risk_score=(
                factor_scores["disruption"]
            ),
            dependency_risk_score=(
                factor_scores["dependency"]
            ),
            factors=factors,
            recommendations=(
                self._recommendations(
                    factor_scores,
                    level,
                )
            ),
            ml_risk_score=ml_score,
            model_name=model_name,
            assessed_at=utc_now(),
            input_fingerprint=(
                fingerprint
            ),
        )

        with self._lock:
            existing = (
                self._assessments.get(
                    assessment_id
                )
            )

            if existing:
                if existing.input_fingerprint != (
                    fingerprint
                ):
                    raise ValueError(
                        "Assessment ID conflict"
                    )

                return copy.deepcopy(
                    existing
                )

            self._assessments[
                assessment_id
            ] = result

            self._audit.append(
                SupplierRiskAuditEvent(
                    event_id=str(
                        uuid.uuid4()
                    ),
                    tenant_id=self.tenant_id,
                    assessment_id=(
                        assessment_id
                    ),
                    actor_id=actor.user_id,
                    action=(
                        "supplier_risk_assessed"
                    ),
                    timestamp=utc_now(),
                    details={
                        "supplier_id": (
                            data.supplier_id
                        ),
                        "risk_level": (
                            level.value
                        ),
                        "risk_score": (
                            overall
                        ),
                    },
                )
            )

            if level in {
                SupplierRiskLevel.HIGH,
                SupplierRiskLevel.CRITICAL,
            }:
                event = (
                    SupplierRiskOutboxEvent(
                        event_id=str(
                            uuid.uuid4()
                        ),
                        tenant_id=(
                            self.tenant_id
                        ),
                        assessment_id=(
                            assessment_id
                        ),
                        supplier_id=(
                            data.supplier_id
                        ),
                        event_type=(
                            "supplier.risk_detected"
                        ),
                        payload={
                            "supplier_id": (
                                data.supplier_id
                            ),
                            "risk_level": (
                                level.value
                            ),
                            "risk_score": (
                                overall
                            ),
                            "requires_review": True,
                        },
                        created_at=utc_now(),
                    )
                )

                self._outbox[
                    event.event_id
                ] = event

            return copy.deepcopy(
                result
            )

    def assess_batch(
        self,
        actor: SupplierRiskActor,
        assessments: Iterable[
            tuple[str, SupplierRiskInput]
        ],
    ) -> list[SupplierRiskAssessment]:
        return [
            self.assess(
                actor,
                assessment_id,
                data,
            )
            for assessment_id, data
            in assessments
        ]

    def get_assessment(
        self,
        actor: SupplierRiskActor,
        assessment_id: str,
    ) -> SupplierRiskAssessment:
        self._authorize(
            actor,
            self.READER_ROLES,
        )

        with self._lock:
            result = (
                self._assessments.get(
                    assessment_id
                )
            )

            if result is None:
                raise KeyError(
                    "Assessment not found"
                )

            return copy.deepcopy(
                result
            )

    def supplier_history(
        self,
        actor: SupplierRiskActor,
        supplier_id: str,
    ) -> list[SupplierRiskAssessment]:
        self._authorize(
            actor,
            self.READER_ROLES,
        )

        with self._lock:
            results = [
                copy.deepcopy(
                    result
                )
                for result in (
                    self._assessments.values()
                )
                if result.supplier_id == (
                    supplier_id
                )
            ]

        return sorted(
            results,
            key=lambda item: (
                item.assessment_date,
                item.assessed_at,
            ),
        )

    def risk_dashboard(
        self,
        actor: SupplierRiskActor,
    ) -> dict:
        self._authorize(
            actor,
            self.READER_ROLES,
        )

        with self._lock:
            latest = {}

            for result in (
                self._assessments.values()
            ):
                previous = latest.get(
                    result.supplier_id
                )

                if (
                    previous is None
                    or (
                        result.assessment_date,
                        result.assessed_at,
                    )
                    > (
                        previous.assessment_date,
                        previous.assessed_at,
                    )
                ):
                    latest[
                        result.supplier_id
                    ] = result

        from collections import Counter

        counts = Counter(
            result.risk_level.value
            for result in latest.values()
        )

        return {
            "tenant_id": self.tenant_id,
            "total_suppliers": len(
                latest
            ),
            "low_risk": counts["low"],
            "medium_risk": counts["medium"],
            "high_risk": counts["high"],
            "critical_risk": counts[
                "critical"
            ],
            "high_risk_suppliers": [
                result.supplier_id
                for result in latest.values()
                if result.risk_level in {
                    SupplierRiskLevel.HIGH,
                    SupplierRiskLevel.CRITICAL,
                }
            ],
        }

    def pending_events(
        self,
        actor: SupplierRiskActor,
    ) -> list[SupplierRiskOutboxEvent]:
        self._authorize(
            actor,
            self.ASSESSOR_ROLES,
        )

        with self._lock:
            return [
                copy.deepcopy(
                    event
                )
                for event in (
                    self._outbox.values()
                )
                if not event.delivered
            ]

    def mark_event_delivered(
        self,
        actor: SupplierRiskActor,
        event_id: str,
    ) -> None:
        self._authorize(
            actor,
            self.ASSESSOR_ROLES,
        )

        with self._lock:
            event = self._outbox.get(
                event_id
            )

            if event is None:
                raise KeyError(
                    "Event not found"
                )

            event.delivered = True

    def export_json(
        self,
        actor: SupplierRiskActor,
        output_path: str | Path,
    ) -> Path:
        self._authorize(
            actor,
            self.ASSESSOR_ROLES,
        )

        with self._lock:
            payload = [
                asdict(
                    assessment
                )
                for assessment in (
                    self._assessments.values()
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
                payload,
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )

        return output


if __name__ == "__main__":
    service = RetailSupplierRiskService(
        tenant_id="demo"
    )

    analyst = SupplierRiskActor(
        user_id="risk-analyst",
        tenant_id="demo",
        roles=frozenset({
            "supplier_risk_analyst",
        }),
    )

    data = SupplierRiskInput(
        tenant_id="demo",
        supplier_id="SUP001",
        supplier_name="Example Supplier",
        assessment_date="2026-10-27",
        total_deliveries=100,
        late_deliveries=28,
        inspected_units=1000,
        defective_units=60,
        average_lead_time_days=8.0,
        lead_time_variability_pct=35.0,
        financial_risk_score=55.0,
        disruption_risk_score=70.0,
        dependency_pct=80.0,
        unresolved_incidents=2,
    )

    result = service.assess(
        actor=analyst,
        assessment_id="RISK001",
        data=data,
    )

    print(
        "Supplier:",
        result.supplier_name,
    )

    print(
        "Risk level:",
        result.risk_level.value,
    )

    print(
        "Risk score:",
        result.overall_risk_score,
    )

    print(
        "Recommendations:",
        result.recommendations,
    )

    print(
        "Dashboard:",
        service.risk_dashboard(
            analyst
        ),
    )
