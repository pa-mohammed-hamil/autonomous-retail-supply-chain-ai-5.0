"""Deterministic demand analysis tools for AI agents.

No external services are required. Predictions are simple baselines, not trained ML.
"""
from __future__ import annotations
from dataclasses import asdict, dataclass
from math import ceil, isfinite, sqrt
from statistics import mean, pstdev
from typing import Sequence


def _sales(values: Sequence[float]) -> list[float]:
    if not values:
        raise ValueError('sales_history cannot be empty')
    result = [float(x) for x in values]
    if any(not isfinite(x) or x < 0 for x in result):
        raise ValueError('sales values must be finite and nonnegative')
    return result


def forecast_demand(sales_history: Sequence[float], horizon_days: int = 7, window: int = 14) -> dict:
    """Forecast units/day using a trailing moving average baseline."""
    values = _sales(sales_history)
    if not 1 <= horizon_days <= 365 or window < 1:
        raise ValueError('invalid horizon_days or window')
    baseline = mean(values[-window:])
    return {'method': 'trailing_moving_average', 'history_days': len(values),
            'daily_forecast': round(baseline, 3), 'horizon_days': horizon_days,
            'forecast_units': round(baseline * horizon_days, 2),
            'daily_predictions': [round(baseline, 3)] * horizon_days}


def detect_demand_spike(sales_history: Sequence[float], latest_sales: float,
                        z_threshold: float = 2.0, minimum_ratio: float = 1.5) -> dict:
    """Flag spikes using both relative uplift and population z-score."""
    values = _sales(sales_history)
    latest = float(latest_sales)
    if not isfinite(latest) or latest < 0 or z_threshold <= 0 or minimum_ratio <= 1:
        raise ValueError('invalid spike detection inputs')
    baseline, sigma = mean(values), pstdev(values)
    ratio = latest / baseline if baseline else (float('inf') if latest else 1.0)
    z = (latest - baseline) / sigma if sigma else (float('inf') if latest > baseline else 0.0)
    spike = latest > baseline and ratio >= minimum_ratio and z >= z_threshold
    return {'spike_detected': spike, 'latest_sales': latest,
            'baseline': round(baseline, 3), 'uplift_percent': round((ratio - 1) * 100, 2) if isfinite(ratio) else None,
            'z_score': round(z, 3) if isfinite(z) else None,
            'reason': 'Thresholds exceeded' if spike else 'No significant spike'}


def analyze_sales_trend(sales_history: Sequence[float], comparison_days: int = 7) -> dict:
    values = _sales(sales_history)
    if comparison_days < 1 or len(values) < comparison_days * 2:
        raise ValueError('need at least two complete comparison windows')
    previous = mean(values[-2 * comparison_days:-comparison_days])
    current = mean(values[-comparison_days:])
    change = ((current - previous) / previous * 100) if previous else None
    direction = 'rising' if current > previous else 'falling' if current < previous else 'stable'
    return {'trend': direction, 'previous_daily_average': round(previous, 3),
            'current_daily_average': round(current, 3),
            'change_percent': round(change, 2) if change is not None else None}


def recommend_reorder(current_stock: float, sales_history: Sequence[float],
                      lead_time_days: int, review_period_days: int = 7,
                      service_z: float = 1.65, on_order: float = 0) -> dict:
    """Periodic-review reorder baseline; service_z is a chosen safety factor."""
    values = _sales(sales_history)
    if any(not isfinite(float(v)) or float(v) < 0 for v in (current_stock, on_order, service_z)):
        raise ValueError('stock, on_order and service_z must be nonnegative and finite')
    if lead_time_days < 0 or review_period_days < 1:
        raise ValueError('invalid lead time or review period')
    daily = mean(values)
    protection_days = lead_time_days + review_period_days
    safety = service_z * pstdev(values) * sqrt(protection_days)
    target = ceil(daily * protection_days + safety)
    quantity = max(0, target - ceil(current_stock + on_order))
    return {'daily_demand': round(daily, 3), 'target_stock': target,
            'safety_stock': ceil(safety), 'reorder_quantity': quantity,
            'reorder_required': quantity > 0, 'method': 'periodic_review_baseline'}
