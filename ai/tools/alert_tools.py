"""Pure alert decision tools; delivery and persistence belong to backend services."""
from __future__ import annotations
from datetime import datetime, timezone
from hashlib import sha256
from math import isfinite
from typing import Any, Mapping

SEVERITIES = ('info', 'warning', 'critical')


def _number(value: float, name: str) -> float:
    value = float(value)
    if not isfinite(value) or value < 0:
        raise ValueError(f'{name} must be finite and nonnegative')
    return value


def build_alert(kind: str, entity_id: str, message: str,
                severity: str = 'warning', details: Mapping[str, Any] | None = None) -> dict:
    if severity not in SEVERITIES:
        raise ValueError(f'severity must be one of {SEVERITIES}')
    if not all(isinstance(v, str) and v.strip() for v in (kind, entity_id, message)):
        raise ValueError('kind, entity_id, and message are required strings')
    fingerprint = sha256(f'{kind.strip()}:{entity_id.strip()}'.encode()).hexdigest()[:20]
    return {'fingerprint': fingerprint, 'kind': kind.strip(), 'entity_id': entity_id.strip(),
            'message': message.strip(), 'severity': severity, 'status': 'open',
            'created_at': datetime.now(timezone.utc).isoformat(), 'details': dict(details or {})}


def low_stock_alert(product_id: str, stock: float, reorder_point: float,
                    critical_point: float = 0) -> dict | None:
    stock, reorder_point, critical_point = (_number(v, n) for v, n in
        ((stock, 'stock'), (reorder_point, 'reorder_point'), (critical_point, 'critical_point')))
    if critical_point > reorder_point:
        raise ValueError('critical_point cannot exceed reorder_point')
    if stock > reorder_point:
        return None
    severity = 'critical' if stock <= critical_point else 'warning'
    return build_alert('low_stock', product_id, f'Stock {stock:g} is at/below reorder point {reorder_point:g}',
                       severity, {'stock': stock, 'reorder_point': reorder_point})


def demand_spike_alert(product_id: str, spike_result: Mapping[str, Any]) -> dict | None:
    if not spike_result.get('spike_detected'):
        return None
    return build_alert('demand_spike', product_id, 'Unusual demand spike detected',
                       'warning', {'latest_sales': spike_result.get('latest_sales'),
                                   'baseline': spike_result.get('baseline')})


def supplier_delay_alert(supplier_id: str, expected_delay_days: float,
                         warning_days: float = 2, critical_days: float = 7) -> dict | None:
    delay = _number(expected_delay_days, 'expected_delay_days')
    warning = _number(warning_days, 'warning_days')
    critical = _number(critical_days, 'critical_days')
    if critical < warning:
        raise ValueError('critical_days must be >= warning_days')
    if delay < warning:
        return None
    return build_alert('supplier_delay', supplier_id, f'Expected supplier delay: {delay:g} days',
                       'critical' if delay >= critical else 'warning', {'delay_days': delay})


def deduplicate_alerts(alerts: list[dict]) -> list[dict]:
    """Keep latest alert for each fingerprint, preserving first-seen order."""
    result: dict[str, dict] = {}
    for alert in alerts:
        key = alert['fingerprint']
        result[key] = alert
    return list(result.values())


def acknowledge_alert(alert: Mapping[str, Any], actor_id: str) -> dict:
    if not actor_id.strip():
        raise ValueError('actor_id required')
    updated = dict(alert)
    if updated.get('status') not in ('open', 'escalated'):
        raise ValueError('only open or escalated alerts can be acknowledged')
    updated.update(status='acknowledged', acknowledged_by=actor_id,
                   acknowledged_at=datetime.now(timezone.utc).isoformat())
    return updated


def escalate_alert(alert: Mapping[str, Any], reason: str) -> dict:
    if not reason.strip():
        raise ValueError('escalation reason required')
    updated = dict(alert)
    if updated.get('status') != 'open':
        raise ValueError('only open alerts can be escalated')
    updated.update(status='escalated', escalation_reason=reason,
                   escalated_at=datetime.now(timezone.utc).isoformat())
    return updated
