from __future__ import annotations

"""Planned module: demand spike service. Implementation pending."""

"""
backend/services/demand_spike_service.py

Autonomous Retail Supply Chain AI 5.0

Demand Spike Detection and Response

Python 3.10+
Dependencies: standard library only.

Features:
- Tenant-scoped demand validation
- Rolling historical baseline
- Robust MAD-based anomaly scoring
- Demand spike ratio
- Minimum demand-volume safeguards
- Severity classification
- Stockout exposure estimation
- Suggested replenishment quantity
- Batch SKU/warehouse analysis
- JSON report export

No automatic purchasing or
notifications are performed.

Historical data must be complete
and chronological, with one
daily demand record per date.

Production systems should distinguish
sales from uncensored true demand.
"""


import json
import math
import statistics

from dataclasses import (
    asdict,
    dataclass,
)
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Any, Iterable


def validate_number(
    value: float,
    name: str,
) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
    ):
        raise ValueError(
            f"{name} must be a finite "
            "nonnegative number"
        )

    return float(value)


class SpikeSeverity(str, Enum):
    NORMAL = "normal"
    WARNING = "warning"
    HIGH = "high"
    CRITICAL = "critical"
    INSUFFICIENT_DATA = (
        "insufficient_data"
    )


@dataclass(frozen=True)
class DemandObservation:
    tenant_id: str
    sku: str
    warehouse_id: str
    demand_date: str
    quantity: float


@dataclass(frozen=True)
class DemandSpikeConfig:
    baseline_days: int = 14
    minimum_history_days: int = 7

    warning_ratio: float = 1.5
    high_ratio: float = 2.0
    critical_ratio: float = 3.0

    robust_z_threshold: float = 3.5
    minimum_spike_units: float = 5.0

    # A minimum baseline prevents
    # unstable ratios for low-volume
    # products. Zero-demand products
    # are handled separately.
    baseline_floor: float = 1.0


@dataclass(frozen=True)
class DemandSpikeResult:
    tenant_id: str
    sku: str
    warehouse_id: str
    observation_date: str

    observed_demand: float
    baseline_demand: float | None

    demand_ratio: float | None
    percentage_increase: float | None
    robust_z_score: float | None

    excess_demand_units: float | None
    severity: SpikeSeverity
    spike_detected: bool
    method: str
    reason: str


@dataclass(frozen=True)
class StockExposure:
    tenant_id: str
    sku: str
    warehouse_id: str

    current_stock: float
    incoming_stock: float
    reserved_stock: float
    available_stock: float

    demand_per_day: float
    days_of_cover: float | None

    lead_time_days: int
    safety_stock: float

    target_stock: float
    suggested_reorder_quantity: float

    stockout_before_replenishment: bool
    requires_approval: bool


class RetailDemandSpikeService:
    def __init__(
        self,
        tenant_id: str,
        config: DemandSpikeConfig | None = None,
    ):
        if (
            not isinstance(tenant_id, str)
            or not tenant_id.strip()
        ):
            raise ValueError(
                "tenant_id is required"
            )

        self.tenant_id = tenant_id
        self.config = (
            config or DemandSpikeConfig()
        )

        cfg = self.config

        if (
            cfg.baseline_days < 1
            or cfg.minimum_history_days < 1
            or cfg.minimum_history_days
            > cfg.baseline_days
            or not (
                1.0 < cfg.warning_ratio
                < cfg.high_ratio
                < cfg.critical_ratio
            )
            or cfg.robust_z_threshold <= 0
            or cfg.minimum_spike_units < 0
            or cfg.baseline_floor <= 0
        ):
            raise ValueError(
                "Invalid spike configuration"
            )

    def _validate_observations(
        self,
        records: Iterable[DemandObservation],
    ) -> list[DemandObservation]:
        items = list(records)

        seen = set()

        for item in items:
            if item.tenant_id != self.tenant_id:
                raise PermissionError(
                    "Cross-tenant demand record"
                )

            if (
                not item.sku.strip()
                or not item.warehouse_id.strip()
            ):
                raise ValueError(
                    "SKU and warehouse required"
                )

            date.fromisoformat(
                item.demand_date
            )

            validate_number(
                item.quantity,
                "quantity",
            )

            key = (
                item.sku,
                item.warehouse_id,
                item.demand_date,
            )

            if key in seen:
                raise ValueError(
                    "Duplicate daily demand record"
                )

            seen.add(key)

        return sorted(
            items,
            key=lambda item: (
                item.sku,
                item.warehouse_id,
                item.demand_date,
            ),
        )

    @staticmethod
    def _robust_z_score(
        history: list[float],
        current: float,
    ) -> float:
        median = statistics.median(
            history
        )

        deviations = [
            abs(value - median)
            for value in history
        ]

        mad = statistics.median(
            deviations
        )

        if mad == 0:
            if current <= median:
                return 0.0

            # When all historical
            # values are identical,
            # MAD cannot supply a
            # meaningful finite score.
            return math.inf

        return (
            0.6745
            * (current - median)
            / mad
        )

    def detect(
        self,
        records: Iterable[DemandObservation],
        sku: str,
        warehouse_id: str,
        observation_date: str | None = None,
    ) -> DemandSpikeResult:
        records = self._validate_observations(
            records
        )

        series = [
            item
            for item in records
            if (
                item.sku == sku
                and item.warehouse_id
                == warehouse_id
            )
        ]

        if not series:
            raise ValueError(
                "No demand records found"
            )

        if observation_date is None:
            target = series[-1]
        else:
            matches = [
                item
                for item in series
                if item.demand_date
                == observation_date
            ]

            if not matches:
                raise ValueError(
                    "Observation date not found"
                )

            target = matches[0]

        history = [
            item.quantity
            for item in series
            if item.demand_date
            < target.demand_date
        ]

        history = history[
            -self.config.baseline_days:
        ]

        if len(history) < (
            self.config.minimum_history_days
        ):
            return DemandSpikeResult(
                tenant_id=self.tenant_id,
                sku=sku,
                warehouse_id=warehouse_id,
                observation_date=(
                    target.demand_date
                ),
                observed_demand=(
                    target.quantity
                ),
                baseline_demand=None,
                demand_ratio=None,
                percentage_increase=None,
                robust_z_score=None,
                excess_demand_units=None,
                severity=(
                    SpikeSeverity.INSUFFICIENT_DATA
                ),
                spike_detected=False,
                method="rolling_mean_robust_mad",
                reason=(
                    "Insufficient historical "
                    "demand observations"
                ),
            )

        baseline = statistics.mean(
            history
        )

        current = target.quantity

        excess = max(
            0.0,
            current - baseline,
        )

        if baseline == 0:
            ratio = (
                math.inf
                if current > 0
                else 1.0
            )

            percentage_increase = None

        else:
            ratio = (
                current / baseline
            )

            percentage_increase = (
                (current - baseline)
                / baseline * 100
            )

        robust_z = self._robust_z_score(
            history,
            current,
        )

        volume_gate = (
            excess
            >= self.config.minimum_spike_units
        )

        anomaly_gate = (
            robust_z
            >= self.config.robust_z_threshold
        )

        ratio_gate = (
            ratio
            >= self.config.warning_ratio
        )

        spike_detected = (
            volume_gate
            and ratio_gate
            and anomaly_gate
        )

        if not spike_detected:
            severity = SpikeSeverity.NORMAL
            reason = (
                "Demand did not exceed "
                "all configured spike gates"
            )

        elif ratio >= (
            self.config.critical_ratio
        ):
            severity = SpikeSeverity.CRITICAL
            reason = (
                "Critical demand increase "
                "relative to baseline"
            )

        elif ratio >= (
            self.config.high_ratio
        ):
            severity = SpikeSeverity.HIGH
            reason = (
                "High demand increase "
                "relative to baseline"
            )

        else:
            severity = SpikeSeverity.WARNING
            reason = (
                "Demand spike detected"
            )

        # JSON-safe representation:
        # undefined/infinite ratios
        # are returned as None.
        return DemandSpikeResult(
            tenant_id=self.tenant_id,
            sku=sku,
            warehouse_id=warehouse_id,
            observation_date=(
                target.demand_date
            ),
            observed_demand=round(
                current, 4
            ),
            baseline_demand=round(
                baseline, 4
            ),
            demand_ratio=(
                round(ratio, 4)
                if math.isfinite(ratio)
                else None
            ),
            percentage_increase=(
                round(
                    percentage_increase,
                    2,
                )
                if percentage_increase
                is not None
                else None
            ),
            robust_z_score=(
                round(robust_z, 4)
                if math.isfinite(robust_z)
                else None
            ),
            excess_demand_units=round(
                excess, 4
            ),
            severity=severity,
            spike_detected=spike_detected,
            method="rolling_mean_robust_mad",
            reason=reason,
        )

    def analyze_stock_exposure(
        self,
        spike: DemandSpikeResult,
        current_stock: float,
        lead_time_days: int,
        safety_stock: float,
        incoming_stock: float = 0.0,
        reserved_stock: float = 0.0,
    ) -> StockExposure:
        if spike.tenant_id != self.tenant_id:
            raise PermissionError(
                "Cross-tenant spike result"
            )

        if (
            isinstance(lead_time_days, bool)
            or not isinstance(
                lead_time_days,
                int,
            )
            or lead_time_days < 0
        ):
            raise ValueError(
                "Invalid lead_time_days"
            )

        current_stock = validate_number(
            current_stock,
            "current_stock",
        )

        incoming_stock = validate_number(
            incoming_stock,
            "incoming_stock",
        )

        reserved_stock = validate_number(
            reserved_stock,
            "reserved_stock",
        )

        safety_stock = validate_number(
            safety_stock,
            "safety_stock",
        )

        # Use observed daily demand
        # as a short-term stress scenario.
        # This is not a forecast that
        # the spike will persist.
        demand = spike.observed_demand

        available = max(
            0.0,
            current_stock
            + incoming_stock
            - reserved_stock,
        )

        days_of_cover = (
            available / demand
            if demand > 0
            else None
        )

        target_stock = (
            demand * lead_time_days
            + safety_stock
        )

        reorder = max(
            0.0,
            target_stock - available,
        )

        stockout_risk = (
            demand > 0
            and (
                available
                < demand * lead_time_days
            )
        )

        return StockExposure(
            tenant_id=self.tenant_id,
            sku=spike.sku,
            warehouse_id=spike.warehouse_id,
            current_stock=current_stock,
            incoming_stock=incoming_stock,
            reserved_stock=reserved_stock,
            available_stock=round(
                available, 4
            ),
            demand_per_day=demand,
            days_of_cover=(
                round(
                    days_of_cover, 2
                )
                if days_of_cover is not None
                else None
            ),
            lead_time_days=lead_time_days,
            safety_stock=safety_stock,
            target_stock=round(
                target_stock, 4
            ),
            suggested_reorder_quantity=round(
                reorder, 4
            ),
            stockout_before_replenishment=(
                stockout_risk
            ),
            requires_approval=(
                reorder > 0
            ),
        )

    def detect_all_latest(
        self,
        records: Iterable[DemandObservation],
    ) -> list[DemandSpikeResult]:
        validated = (
            self._validate_observations(
                records
            )
        )

        groups = {}

        for item in validated:
            key = (
                item.sku,
                item.warehouse_id,
            )

            groups.setdefault(
                key,
                [],
            ).append(item)

        results = []

        for (
            sku,
            warehouse_id,
        ), group in groups.items():
            results.append(
                self.detect(
                    group,
                    sku,
                    warehouse_id,
                )
            )

        return results

    @staticmethod
    def export_json(
        results: Any,
        output_path: str | Path,
    ) -> Path:
        output = Path(
            output_path
        )

        output.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        if isinstance(results, list):
            payload = [
                asdict(item)
                for item in results
            ]
        else:
            payload = asdict(
                results
            )

        output.write_text(
            json.dumps(
                payload,
                indent=2,
                ensure_ascii=False,
                allow_nan=False,
            ),
            encoding="utf-8",
        )

        return output


if __name__ == "__main__":
    from datetime import timedelta

    service = RetailDemandSpikeService(
        tenant_id="demo"
    )

    historical = [
        20, 21, 19, 22, 20, 21, 20,
        19, 22, 20, 21, 19, 20, 21,
    ]

    quantities = historical + [75]

    start = date(
        2026, 10, 1
    )

    observations = [
        DemandObservation(
            tenant_id="demo",
            sku="SKU001",
            warehouse_id="WH001",
            demand_date=(
                start
                + timedelta(days=index)
            ).isoformat(),
            quantity=quantity,
        )
        for index, quantity in enumerate(
            quantities
        )
    ]

    result = service.detect(
        observations,
        sku="SKU001",
        warehouse_id="WH001",
    )

    exposure = (
        service.analyze_stock_exposure(
            spike=result,
            current_stock=100,
            lead_time_days=5,
            safety_stock=30,
            incoming_stock=0,
            reserved_stock=10,
        )
    )

    print(
        json.dumps(
            {
                "spike": asdict(result),
                "stock_exposure": asdict(
                    exposure
                ),
            },
            indent=2,
        )
    )

    service.export_json(
        result,
        "reports/demand_spike.json",
    )
