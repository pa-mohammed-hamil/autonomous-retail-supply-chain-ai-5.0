from __future__ import annotations

"""Planned module: stockout prediction service. Implementation pending."""

"""
Autonomous Retail Supply Chain AI 5.0
backend/services/stockout_prediction_service.py

Python 3.10+ | Standard library only.

Reference stockout prediction service.

Features:
- Tenant and warehouse access controls
- Daily inventory projection
- Incoming supply schedule
- Stockout risk classification
- Estimated stockout day
- Reorder quantity recommendation
- Optional external ML risk predictor
- Idempotent prediction IDs
- Risk alert outbox
- Audit logging
- JSON export

The built-in prediction is deterministic.
It is not a calibrated ML probability model.
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
    date,
    datetime,
    timedelta,
    timezone,
)
from enum import Enum
from pathlib import Path
from typing import Callable, Iterable


def utc_now() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


def nonnegative_number(
    value: int | float,
    name: str,
) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(
            value,
            (int, float),
        )
        or not math.isfinite(value)
        or value < 0
    ):
        raise ValueError(
            f"{name} must be finite and nonnegative"
        )

    return float(value)


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


class StockoutRisk(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True)
class StockoutActor:
    user_id: str
    tenant_id: str
    roles: frozenset[str]
    warehouse_ids: frozenset[str] = (
        frozenset()
    )
    is_active: bool = True


@dataclass(frozen=True)
class IncomingSupply:
    arrival_date: str
    quantity: int
    reference_id: str


@dataclass(frozen=True)
class StockoutInput:
    tenant_id: str
    warehouse_id: str
    sku: str
    as_of_date: str
    on_hand: int
    reserved: int
    daily_demand: float
    lead_time_days: int
    safety_stock: int
    forecast_horizon_days: int = 30
    incoming: tuple[
        IncomingSupply, ...
    ] = ()


@dataclass(frozen=True)
class StockoutProjectionDay:
    day: int
    projection_date: str
    incoming_units: float
    demand_units: float
    ending_stock: float


@dataclass(frozen=True)
class StockoutPrediction:
    prediction_id: str
    tenant_id: str
    warehouse_id: str
    sku: str
    as_of_date: str
    risk: StockoutRisk
    available_stock: float
    days_of_cover: float | None
    estimated_stockout_date: str | None
    stockout_within_lead_time: bool
    suggested_reorder_quantity: int
    forecast_horizon_days: int
    projected_stock: tuple[
        StockoutProjectionDay, ...
    ]
    ml_risk_score: float | None
    model_name: str
    predicted_at: str
    input_fingerprint: str


@dataclass(frozen=True)
class StockoutAuditEvent:
    event_id: str
    tenant_id: str
    prediction_id: str
    actor_id: str
    action: str
    timestamp: str
    details: dict = field(
        default_factory=dict
    )


@dataclass
class StockoutOutboxEvent:
    event_id: str
    tenant_id: str
    warehouse_id: str
    event_type: str
    source_id: str
    payload: dict
    created_at: str
    delivered: bool = False


# Optional ML contract:
# predictor(input) -> score between 0 and 1
StockoutMLPredictor = Callable[
    [StockoutInput],
    float,
]


class RetailStockoutPredictionService:
    ANALYST_ROLES = frozenset({
        "inventory_analyst",
        "demand_planner",
        "inventory_manager",
        "operations_manager",
        "corporate_admin",
    })

    READER_ROLES = (
        ANALYST_ROLES
        | frozenset({
            "warehouse_manager",
            "procurement_manager",
        })
    )

    def __init__(
        self,
        tenant_id: str,
        ml_predictor: (
            StockoutMLPredictor | None
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

        self._predictions: dict[
            str, StockoutPrediction
        ] = {}

        self._audit: list[
            StockoutAuditEvent
        ] = []

        self._outbox: dict[
            str, StockoutOutboxEvent
        ] = {}

    def _authorize(
        self,
        actor: StockoutActor,
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
                "Stockout service access denied"
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

    def _validate_input(
        self,
        data: StockoutInput,
    ) -> None:
        if data.tenant_id != (
            self.tenant_id
        ):
            raise PermissionError(
                "Cross-tenant stockout input"
            )

        required_text(
            data.warehouse_id,
            "warehouse_id",
        )

        required_text(
            data.sku,
            "sku",
        )

        today = date.fromisoformat(
            data.as_of_date
        )

        for name in (
            "on_hand",
            "reserved",
            "lead_time_days",
            "safety_stock",
            "forecast_horizon_days",
        ):
            value = getattr(
                data,
                name,
            )

            if (
                isinstance(value, bool)
                or not isinstance(
                    value,
                    int,
                )
                or value < 0
            ):
                raise ValueError(
                    f"{name} must be nonnegative integer"
                )

        if not (
            1 <= data.forecast_horizon_days
            <= 365
        ):
            raise ValueError(
                "Forecast horizon must be 1-365 days"
            )

        if data.reserved > data.on_hand:
            raise ValueError(
                "Reserved exceeds on-hand stock"
            )

        nonnegative_number(
            data.daily_demand,
            "daily_demand",
        )

        references = set()

        for supply in data.incoming:
            required_text(
                supply.reference_id,
                "reference_id",
            )

            if supply.reference_id in (
                references
            ):
                raise ValueError(
                    "Duplicate supply reference"
                )

            references.add(
                supply.reference_id
            )

            if (
                isinstance(
                    supply.quantity,
                    bool,
                )
                or not isinstance(
                    supply.quantity,
                    int,
                )
                or supply.quantity <= 0
            ):
                raise ValueError(
                    "Incoming quantity must be positive"
                )

            arrival = date.fromisoformat(
                supply.arrival_date
            )

            if arrival < today:
                raise ValueError(
                    "Incoming arrival is in the past"
                )

    @staticmethod
    def _fingerprint(
        data: StockoutInput,
    ) -> str:
        payload = json.dumps(
            asdict(data),
            sort_keys=True,
            default=str,
        )

        return hashlib.sha256(
            payload.encode(
                "utf-8"
            )
        ).hexdigest()

    def _project(
        self,
        data: StockoutInput,
    ) -> tuple[
        tuple[StockoutProjectionDay, ...],
        str | None,
    ]:
        start = date.fromisoformat(
            data.as_of_date
        )

        available = float(
            data.on_hand
            - data.reserved
        )

        incoming_by_date: dict[
            date, float
        ] = {}

        for supply in data.incoming:
            arrival = date.fromisoformat(
                supply.arrival_date
            )

            incoming_by_date[
                arrival
            ] = (
                incoming_by_date.get(
                    arrival,
                    0.0,
                )
                + supply.quantity
            )

        # Supply arriving on the
        # assessment date is available
        # before the first projected day.
        available += incoming_by_date.get(
            start,
            0.0,
        )

        projected = []
        stockout_date = None

        for day in range(
            1,
            data.forecast_horizon_days + 1,
        ):
            current_date = (
                start
                + timedelta(
                    days=day
                )
            )

            incoming = (
                incoming_by_date.get(
                    current_date,
                    0.0,
                )
            )

            available += incoming
            available -= (
                data.daily_demand
            )

            if (
                stockout_date is None
                and available <= 0
            ):
                stockout_date = (
                    current_date.isoformat()
                )

            projected.append(
                StockoutProjectionDay(
                    day=day,
                    projection_date=(
                        current_date.isoformat()
                    ),
                    incoming_units=(
                        incoming
                    ),
                    demand_units=(
                        data.daily_demand
                    ),
                    ending_stock=round(
                        available,
                        3,
                    ),
                )
            )

        return (
            tuple(projected),
            stockout_date,
        )

    @staticmethod
    def _risk(
        days_of_cover: float | None,
        stockout_within_lead_time: bool,
        available_stock: float,
        lead_time_days: int,
    ) -> StockoutRisk:
        if available_stock <= 0:
            return (
                StockoutRisk.CRITICAL
            )

        if stockout_within_lead_time:
            return (
                StockoutRisk.CRITICAL
            )

        if days_of_cover is None:
            return (
                StockoutRisk.LOW
            )

        if days_of_cover <= (
            lead_time_days + 2
        ):
            return (
                StockoutRisk.HIGH
            )

        if days_of_cover <= (
            lead_time_days + 7
        ):
            return (
                StockoutRisk.MEDIUM
            )

        return (
            StockoutRisk.LOW
        )

    @staticmethod
    def _reorder_quantity(
        data: StockoutInput,
    ) -> int:
        target_days = (
            data.lead_time_days
            + 7
        )

        target_stock = (
            data.daily_demand
            * target_days
            + data.safety_stock
        )

        cutoff = (
            date.fromisoformat(
                data.as_of_date
            )
            + timedelta(
                days=data.lead_time_days
            )
        )

        incoming_before_cutoff = sum(
            supply.quantity
            for supply in data.incoming
            if date.fromisoformat(
                supply.arrival_date
            ) <= cutoff
        )

        inventory_position = (
            data.on_hand
            - data.reserved
            + incoming_before_cutoff
        )

        return max(
            0,
            math.ceil(
                target_stock
                - inventory_position
            ),
        )

    def predict(
        self,
        actor: StockoutActor,
        prediction_id: str,
        data: StockoutInput,
    ) -> StockoutPrediction:
        self._authorize(
            actor,
            self.ANALYST_ROLES,
            data.warehouse_id,
        )

        prediction_id = required_text(
            prediction_id,
            "prediction_id",
        )

        self._validate_input(
            data
        )

        fingerprint = self._fingerprint(
            data
        )

        with self._lock:
            existing = (
                self._predictions.get(
                    prediction_id
                )
            )

            if existing:
                if existing.input_fingerprint != (
                    fingerprint
                ):
                    raise ValueError(
                        "Prediction ID conflict"
                    )

                return copy.deepcopy(
                    existing
                )

        available_stock = float(
            data.on_hand
            - data.reserved
        )

        if data.daily_demand > 0:
            days_of_cover = (
                available_stock
                / data.daily_demand
            )
        else:
            days_of_cover = None

        (
            projection,
            stockout_date,
        ) = self._project(
            data
        )

        # Include the current date:
        # zero available stock is already
        # an immediate stockout condition.
        if available_stock <= 0:
            stockout_date = (
                data.as_of_date
            )

        lead_time_cutoff = (
            date.fromisoformat(
                data.as_of_date
            )
            + timedelta(
                days=data.lead_time_days
            )
        )

        within_lead_time = (
            stockout_date is not None
            and date.fromisoformat(
                stockout_date
            ) <= lead_time_cutoff
        )

        risk = self._risk(
            days_of_cover,
            within_lead_time,
            available_stock,
            data.lead_time_days,
        )

        ml_score = None
        model_name = (
            "deterministic_stock_projection_v1"
        )

        if self.ml_predictor:
            score = self.ml_predictor(
                data
            )

            if (
                not isinstance(
                    score,
                    (int, float),
                )
                or isinstance(
                    score,
                    bool,
                )
                or not math.isfinite(
                    score
                )
                or not 0 <= score <= 1
            ):
                raise ValueError(
                    "ML score must be between 0 and 1"
                )

            ml_score = float(
                score
            )

            model_name = (
                "external_ml_predictor"
            )

        result = StockoutPrediction(
            prediction_id=prediction_id,
            tenant_id=self.tenant_id,
            warehouse_id=(
                data.warehouse_id
            ),
            sku=data.sku,
            as_of_date=(
                data.as_of_date
            ),
            risk=risk,
            available_stock=(
                available_stock
            ),
            days_of_cover=(
                round(
                    days_of_cover,
                    2,
                )
                if days_of_cover is not None
                else None
            ),
            estimated_stockout_date=(
                stockout_date
            ),
            stockout_within_lead_time=(
                within_lead_time
            ),
            suggested_reorder_quantity=(
                self._reorder_quantity(
                    data
                )
            ),
            forecast_horizon_days=(
                data.forecast_horizon_days
            ),
            projected_stock=projection,
            ml_risk_score=ml_score,
            model_name=model_name,
            predicted_at=utc_now(),
            input_fingerprint=(
                fingerprint
            ),
        )

        with self._lock:
            existing = (
                self._predictions.get(
                    prediction_id
                )
            )

            if existing:
                if existing.input_fingerprint != (
                    fingerprint
                ):
                    raise ValueError(
                        "Prediction ID conflict"
                    )

                return copy.deepcopy(
                    existing
                )

            self._predictions[
                prediction_id
            ] = result

            self._audit.append(
                StockoutAuditEvent(
                    event_id=str(
                        uuid.uuid4()
                    ),
                    tenant_id=self.tenant_id,
                    prediction_id=(
                        prediction_id
                    ),
                    actor_id=actor.user_id,
                    action=(
                        "stockout_predicted"
                    ),
                    timestamp=utc_now(),
                    details={
                        "sku": data.sku,
                        "risk": (
                            risk.value
                        ),
                    },
                )
            )

            if risk in {
                StockoutRisk.HIGH,
                StockoutRisk.CRITICAL,
            }:
                event = StockoutOutboxEvent(
                    event_id=str(
                        uuid.uuid4()
                    ),
                    tenant_id=self.tenant_id,
                    warehouse_id=(
                        data.warehouse_id
                    ),
                    event_type=(
                        "stockout.risk_detected"
                    ),
                    source_id=(
                        prediction_id
                    ),
                    payload={
                        "sku": data.sku,
                        "risk": risk.value,
                        "stockout_date": (
                            stockout_date
                        ),
                        "suggested_reorder_quantity": (
                            result.suggested_reorder_quantity
                        ),
                    },
                    created_at=utc_now(),
                )

                self._outbox[
                    event.event_id
                ] = event

            return copy.deepcopy(
                result
            )

    def predict_batch(
        self,
        actor: StockoutActor,
        items: Iterable[
            tuple[str, StockoutInput]
        ],
    ) -> list[StockoutPrediction]:
        return [
            self.predict(
                actor,
                prediction_id,
                data,
            )
            for prediction_id, data
            in items
        ]

    def get_prediction(
        self,
        actor: StockoutActor,
        prediction_id: str,
    ) -> StockoutPrediction:
        with self._lock:
            result = (
                self._predictions.get(
                    prediction_id
                )
            )

            if result is None:
                raise KeyError(
                    "Prediction not found"
                )

            self._authorize(
                actor,
                self.READER_ROLES,
                result.warehouse_id,
            )

            return copy.deepcopy(
                result
            )

    def list_predictions(
        self,
        actor: StockoutActor,
        risk: StockoutRisk | None = None,
    ) -> list[StockoutPrediction]:
        self._authorize(
            actor,
            self.READER_ROLES,
        )

        with self._lock:
            return [
                copy.deepcopy(
                    result
                )
                for result in (
                    self._predictions.values()
                )
                if (
                    (
                        "corporate_admin"
                        in actor.roles
                        or result.warehouse_id
                        in actor.warehouse_ids
                    )
                    and (
                        risk is None
                        or result.risk == risk
                    )
                )
            ]

    def pending_events(
        self,
        actor: StockoutActor,
    ) -> list[StockoutOutboxEvent]:
        self._authorize(
            actor,
            self.ANALYST_ROLES,
        )

        with self._lock:
            return [
                copy.deepcopy(
                    event
                )
                for event in (
                    self._outbox.values()
                )
                if (
                    not event.delivered
                    and (
                        "corporate_admin"
                        in actor.roles
                        or event.warehouse_id
                        in actor.warehouse_ids
                    )
                )
            ]

    def mark_event_delivered(
        self,
        actor: StockoutActor,
        event_id: str,
    ) -> None:
        with self._lock:
            event = self._outbox.get(
                event_id
            )

            if event is None:
                raise KeyError(
                    "Event not found"
                )

            self._authorize(
                actor,
                self.ANALYST_ROLES,
                event.warehouse_id,
            )

            event.delivered = True

    def export_json(
        self,
        actor: StockoutActor,
        output_path: str | Path,
    ) -> Path:
        results = (
            self.list_predictions(
                actor
            )
        )

        output = Path(
            output_path
        )

        output.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        output.write_text(
            json.dumps(
                [
                    asdict(result)
                    for result in results
                ],
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )

        return output


if __name__ == "__main__":
    service = (
        RetailStockoutPredictionService(
            tenant_id="demo"
        )
    )

    analyst = StockoutActor(
        user_id="inventory-analyst",
        tenant_id="demo",
        roles=frozenset({
            "inventory_analyst",
        }),
        warehouse_ids=frozenset({
            "WH001",
        }),
    )

    data = StockoutInput(
        tenant_id="demo",
        warehouse_id="WH001",
        sku="SKU001",
        as_of_date="2026-10-27",
        on_hand=120,
        reserved=20,
        daily_demand=15,
        lead_time_days=7,
        safety_stock=30,
        forecast_horizon_days=30,
        incoming=(
            IncomingSupply(
                arrival_date="2026-11-05",
                quantity=100,
                reference_id="PO001",
            ),
        ),
    )

    prediction = service.predict(
        actor=analyst,
        prediction_id="STOCKOUT001",
        data=data,
    )

    print(
        "Risk:",
        prediction.risk.value,
    )

    print(
        "Stockout date:",
        prediction.estimated_stockout_date,
    )

    print(
        "Suggested reorder:",
        prediction.suggested_reorder_quantity,
    )

    print(
        "Pending alerts:",
        len(
            service.pending_events(
                analyst
            )
        ),
    )
