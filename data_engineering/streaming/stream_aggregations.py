
"""
ai/pipelines/stream_aggregations.py

Event-time stream aggregations for Autonomous
Retail Supply Chain AI 5.0.

Features:
- Tumbling event-time windows
- Sales, returns, revenue, inventory and logistics KPIs
- Duplicate event protection
- Watermark and late-event handling
- Decimal-safe financial calculations
- Per-dimension aggregation
- Window closure and snapshot reporting
- No external side effects

Consumes validated EventSchemas v1.0 envelopes.

Reference implementation:
- In-memory state
- Single-process execution
- Not durable across restarts

For production, persist aggregation state and
deduplication IDs in a transactional state store.
"""

from __future__ import annotations

import json
import math

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from ai.pipelines.event_schemas import EventSchemas


def parse_time(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        dt = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )
    else:
        raise ValueError("Invalid event timestamp")

    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("Timezone-aware timestamp required")

    return dt.astimezone(timezone.utc)


def decimal_value(value: Any) -> Decimal:
    if isinstance(value, bool):
        raise ValueError("Boolean is not numeric")

    try:
        result = Decimal(str(value))
    except (ValueError, InvalidOperation, TypeError):
        raise ValueError("Invalid decimal value") from None

    if not result.is_finite():
        raise ValueError("Non-finite numeric value")

    return result


@dataclass(frozen=True)
class AggregationConfig:
    window_minutes: int = 60
    allowed_lateness_minutes: int = 10
    max_seen_events: int = 1_000_000

    def __post_init__(self):
        if self.window_minutes < 1:
            raise ValueError("Invalid window size")

        if self.allowed_lateness_minutes < 0:
            raise ValueError("Invalid allowed lateness")

        if self.max_seen_events < 1:
            raise ValueError("Invalid deduplication capacity")


@dataclass
class WindowMetrics:
    event_count: int = 0
    sales_units: int = 0
    return_units: int = 0
    gross_sales: Decimal = Decimal("0")
    return_value: Decimal = Decimal("0")
    inventory_updates: int = 0
    latest_available_stock: int | None = None
    latest_inventory_time: datetime | None = None
    latest_inventory_event_id: str | None = None
    shipment_events: int = 0
    delayed_shipments: set[str] = field(
        default_factory=set
    )
    delivered_shipments: set[str] = field(
        default_factory=set
    )


class StreamAggregations:

    def __init__(
        self,
        config: AggregationConfig | None = None,
    ):
        self.config = config or AggregationConfig()

        # Key: (window_start, metric_type, dimension)
        self.windows: dict[
            tuple[datetime, str, str],
            WindowMetrics,
        ] = {}

        self.seen_event_ids: set[str] = set()

        self.max_event_time: datetime | None = None

        self.closed_windows: list[dict] = []
        self.late_events: list[dict] = []

        self.total_processed = 0
        self.total_duplicates = 0
        self.total_late = 0
        self.total_unsupported = 0

    def _window_start(
        self,
        timestamp: datetime,
    ) -> datetime:
        timestamp = parse_time(timestamp)

        window_seconds = (
            self.config.window_minutes * 60
        )

        epoch_seconds = int(timestamp.timestamp())

        start_seconds = (
            epoch_seconds // window_seconds
        ) * window_seconds

        return datetime.fromtimestamp(
            start_seconds,
            tz=timezone.utc,
        )

    def _window_end(
        self,
        start: datetime,
    ) -> datetime:
        return start + timedelta(
            minutes=self.config.window_minutes
        )

    def _watermark(self) -> datetime | None:
        if self.max_event_time is None:
            return None

        return self.max_event_time - timedelta(
            minutes=self.config.allowed_lateness_minutes
        )

    def _metrics(
        self,
        start: datetime,
        metric_type: str,
        dimension: str,
    ) -> WindowMetrics:
        key = (start, metric_type, dimension)

        if key not in self.windows:
            self.windows[key] = WindowMetrics()

        return self.windows[key]

    @staticmethod
    def _validate_event(event: dict) -> None:
        result = EventSchemas.validate(event)

        if not result["valid"]:
            raise ValueError(
                "Invalid event: "
                + "; ".join(result["errors"])
            )

    def process(self, event: dict) -> dict:
        """
        Aggregate one validated event.

        An event is considered late if its window
        has already reached the current watermark.
        """

        self._validate_event(event)

        event_id = event["event_id"]

        if event_id in self.seen_event_ids:
            self.total_duplicates += 1
            return {
                "accepted": False,
                "status": "duplicate",
                "event_id": event_id,
            }

        if (
            len(self.seen_event_ids)
            >= self.config.max_seen_events
        ):
            raise RuntimeError(
                "Deduplication capacity reached; "
                "persist or rotate state before continuing"
            )

        occurred_at = parse_time(
            event["occurred_at"]
        )

        start = self._window_start(occurred_at)
        end = self._window_end(start)

        watermark = self._watermark()

        if watermark is not None and end <= watermark:
            self.seen_event_ids.add(event_id)
            self.total_late += 1

            late = {
                "event_id": event_id,
                "event_type": event["event_type"],
                "occurred_at": occurred_at.isoformat(),
                "window_start": start.isoformat(),
                "reason": "window_already_closed",
            }

            self.late_events.append(late)

            return {
                "accepted": False,
                "status": "late",
                **late,
            }

        event_type = event["event_type"]
        payload = event["payload"]

        if event_type == "pos.transaction_recorded":
            self._aggregate_sales(
                start,
                payload,
            )

        elif event_type == "inventory.snapshot_updated":
            self._aggregate_inventory(
                start,
                occurred_at,
                event_id,
                payload,
            )

        elif event_type == "logistics.shipment_updated":
            self._aggregate_logistics(
                start,
                payload,
            )

        else:
            self.seen_event_ids.add(event_id)
            self.total_unsupported += 1

            return {
                "accepted": False,
                "status": "unsupported_metric_type",
                "event_id": event_id,
                "event_type": event_type,
            }

        self.seen_event_ids.add(event_id)
        self.total_processed += 1

        if (
            self.max_event_time is None
            or occurred_at > self.max_event_time
        ):
            self.max_event_time = occurred_at

        closed = self.close_ready_windows()

        return {
            "accepted": True,
            "status": "aggregated",
            "event_id": event_id,
            "window_start": start.isoformat(),
            "window_end": end.isoformat(),
            "closed_window_count": len(closed),
        }

    def _aggregate_sales(
        self,
        start: datetime,
        payload: dict,
    ) -> None:
        store_id = payload["store_id"]
        sku = payload["sku"]
        currency = payload["currency"]

        quantity = payload["quantity"]
        unit_price = decimal_value(
            payload["unit_price"]
        )

        value = unit_price * quantity

        dimensions = [
            f"store:{store_id}:currency:{currency}",
            f"sku:{sku}:currency:{currency}",
            f"store:{store_id}:sku:{sku}:currency:{currency}",
        ]

        for dimension in dimensions:
            metrics = self._metrics(
                start,
                "sales",
                dimension,
            )

            metrics.event_count += 1

            if payload["transaction_type"] == "sale":
                metrics.sales_units += quantity
                metrics.gross_sales += value
            else:
                metrics.return_units += quantity
                metrics.return_value += value

    def _aggregate_inventory(
        self,
        start: datetime,
        occurred_at: datetime,
        event_id: str,
        payload: dict,
    ) -> None:
        dimension = (
            f"warehouse:{payload['warehouse_id']}:"
            f"sku:{payload['sku']}"
        )

        metrics = self._metrics(
            start,
            "inventory",
            dimension,
        )

        metrics.event_count += 1
        metrics.inventory_updates += 1

        # Inventory snapshots are point-in-time
        # values, not additive quantities.
        # Use the latest event-time observation.
        candidate = (occurred_at, event_id)

        current = (
            metrics.latest_inventory_time,
            metrics.latest_inventory_event_id,
        )

        if (
            metrics.latest_inventory_time is None
            or candidate > current
        ):
            metrics.latest_inventory_time = occurred_at
            metrics.latest_inventory_event_id = event_id
            metrics.latest_available_stock = (
                payload["available"]
            )

    def _aggregate_logistics(
        self,
        start: datetime,
        payload: dict,
    ) -> None:
        dimension = (
            f"vehicle:{payload['vehicle_id']}"
        )

        metrics = self._metrics(
            start,
            "logistics",
            dimension,
        )

        metrics.event_count += 1
        metrics.shipment_events += 1

        shipment_id = payload["shipment_id"]
        status = payload["status"]

        if status == "delayed":
            metrics.delayed_shipments.add(
                shipment_id
            )

        if status == "delivered":
            metrics.delivered_shipments.add(
                shipment_id
            )

    def _serialize_window(
        self,
        key: tuple[datetime, str, str],
        metrics: WindowMetrics,
    ) -> dict:
        start, metric_type, dimension = key

        result = {
            "window_start": start.isoformat(),
            "window_end": self._window_end(
                start
            ).isoformat(),
            "metric_type": metric_type,
            "dimension": dimension,
            "event_count": metrics.event_count,
        }

        if metric_type == "sales":
            result.update({
                "sales_units": metrics.sales_units,
                "return_units": metrics.return_units,
                "net_units": (
                    metrics.sales_units
                    - metrics.return_units
                ),
                "gross_sales": str(
                    metrics.gross_sales
                ),
                "return_value": str(
                    metrics.return_value
                ),
                "net_sales": str(
                    metrics.gross_sales
                    - metrics.return_value
                ),
                "revenue_basis": (
                    "unit_price_times_quantity"
                    "_excluding_tax_and_discounts"
                ),
            })

        elif metric_type == "inventory":
            result.update({
                "inventory_updates": (
                    metrics.inventory_updates
                ),
                "latest_available_stock": (
                    metrics.latest_available_stock
                ),
                "latest_observation_at": (
                    metrics.latest_inventory_time.isoformat()
                    if metrics.latest_inventory_time
                    else None
                ),
            })

        elif metric_type == "logistics":
            result.update({
                "shipment_events": (
                    metrics.shipment_events
                ),
                "delayed_shipment_count": len(
                    metrics.delayed_shipments
                ),
                "delivered_shipment_count": len(
                    metrics.delivered_shipments
                ),
            })

        return result

    def close_ready_windows(self) -> list[dict]:
        watermark = self._watermark()

        if watermark is None:
            return []

        ready_keys = [
            key
            for key in self.windows
            if self._window_end(key[0]) <= watermark
        ]

        ready_keys.sort(
            key=lambda key: (
                key[0],
                key[1],
                key[2],
            )
        )

        closed = []

        for key in ready_keys:
            metrics = self.windows.pop(key)

            report = self._serialize_window(
                key,
                metrics,
            )

            closed.append(report)
            self.closed_windows.append(report)

        return closed

    def advance_watermark(
        self,
        watermark: datetime,
    ) -> list[dict]:
        """
        Explicitly advance event-time progress.

        Use only when upstream guarantees that
        older events are no longer expected.
        """

        watermark = parse_time(watermark)

        candidate_max_event_time = (
            watermark
            + timedelta(
                minutes=self.config.allowed_lateness_minutes
            )
        )

        if (
            self.max_event_time is None
            or candidate_max_event_time
            > self.max_event_time
        ):
            self.max_event_time = (
                candidate_max_event_time
            )

        return self.close_ready_windows()

    def snapshot(self) -> dict:
        active = [
            self._serialize_window(key, metrics)
            for key, metrics in self.windows.items()
        ]

        active.sort(
            key=lambda row: (
                row["window_start"],
                row["metric_type"],
                row["dimension"],
            )
        )

        watermark = self._watermark()

        return {
            "processed_events": self.total_processed,
            "duplicate_events": self.total_duplicates,
            "late_events_count": self.total_late,
            "unsupported_events": self.total_unsupported,
            "watermark": (
                watermark.isoformat()
                if watermark
                else None
            ),
            "active_windows": active,
            "closed_windows": list(
                self.closed_windows
            ),
            "late_events": list(
                self.late_events
            ),
            "state_persisted": False,
        }


if __name__ == "__main__":
    aggregator = StreamAggregations(
        AggregationConfig(
            window_minutes=60,
            allowed_lateness_minutes=10,
        )
    )

    events = [
        EventSchemas.create(
            event_type="pos.transaction_recorded",
            source="pos_pipeline",
            occurred_at="2026-10-25T10:05:00+00:00",
            payload={
                "store_id": "STORE-KOCHI",
                "transaction_id": "TXN-001",
                "line_id": "1",
                "sku": "SKU-101",
                "transaction_type": "sale",
                "quantity": 3,
                "unit_price": "250.00",
                "currency": "INR",
            },
        ),
        EventSchemas.create(
            event_type="pos.transaction_recorded",
            source="pos_pipeline",
            occurred_at="2026-10-25T10:25:00+00:00",
            payload={
                "store_id": "STORE-KOCHI",
                "transaction_id": "TXN-002",
                "line_id": "1",
                "sku": "SKU-101",
                "transaction_type": "return",
                "quantity": 1,
                "unit_price": "250.00",
                "currency": "INR",
            },
        ),
    ]

    for event in events:
        print(aggregator.process(event))

    aggregator.advance_watermark(
        datetime(
            2026, 10, 25, 11, 30,
            tzinfo=timezone.utc,
        )
    )

    print(
        json.dumps(
            aggregator.snapshot(),
            indent=2,
        )
    )
