from __future__ import annotations

"""Planned module: logistics. Implementation pending."""

"""
Autonomous Retail Supply Chain AI 5.0
backend/services/logistics_service.py

Python 3.10+ | Standard library only

Features:
- Tenant and warehouse scoped RBAC
- Carrier registration
- Shipment creation and carrier assignment
- Dispatch and delivery lifecycle
- Tracking updates
- ETA management
- Delayed shipment detection
- Transport cost recording
- Proof-of-delivery reference
- Idempotent external events
- Shipment audit history
- Logistics KPIs
- JSON export

In-memory reference implementation.
No GPS, maps, database, or carrier API connected.
"""


import copy
import json
import math
import threading
import uuid

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from pathlib import Path
from typing import Any


def now() -> datetime:
    return datetime.now(timezone.utc)


def stamp() -> str:
    return now().isoformat()


def required(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Invalid {name}")
    if len(value) > 255:
        raise ValueError(f"{name} too long")
    return value.strip()


def parse_time(value: str) -> datetime:
    try:
        dt = datetime.fromisoformat(value)
    except (ValueError, TypeError) as exc:
        raise ValueError("Invalid ISO datetime") from exc

    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("Timezone-aware datetime required")

    return dt.astimezone(timezone.utc)


def money(value: Any) -> Decimal:
    if isinstance(value, bool):
        raise ValueError("Invalid amount")
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount < 0:
            raise ValueError("Invalid amount")
        return amount.quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Invalid monetary amount") from exc


class ShipmentStatus(str, Enum):
    CREATED = "created"
    ASSIGNED = "assigned"
    DISPATCHED = "dispatched"
    IN_TRANSIT = "in_transit"
    DELAYED = "delayed"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class LogisticsActor:
    user_id: str
    tenant_id: str
    roles: frozenset[str]
    warehouse_ids: frozenset[str] = frozenset()
    is_active: bool = True


@dataclass(frozen=True)
class Carrier:
    carrier_id: str
    tenant_id: str
    name: str
    service_level: str
    active: bool
    created_at: str


@dataclass
class Shipment:
    shipment_id: str
    tenant_id: str
    order_id: str
    warehouse_id: str
    destination_code: str
    carrier_id: str | None
    tracking_number: str | None
    status: ShipmentStatus
    expected_delivery_at: str
    dispatched_at: str | None
    delivered_at: str | None
    proof_of_delivery_ref: str | None
    transport_cost: Decimal
    currency: str
    created_at: str
    updated_at: str
    version: int = 1


@dataclass(frozen=True)
class LogisticsEvent:
    event_id: str
    tenant_id: str
    shipment_id: str
    actor_id: str
    event_type: str
    timestamp: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class LogisticsOutboxEvent:
    event_id: str
    tenant_id: str
    shipment_id: str
    event_type: str
    payload: dict[str, Any]
    created_at: str
    delivered: bool = False


class RetailLogisticsService:
    WRITER_ROLES = frozenset({
        "logistics_manager",
        "warehouse_manager",
        "operations_manager",
        "corporate_admin",
    })

    READER_ROLES = WRITER_ROLES | frozenset({
        "logistics_analyst",
        "inventory_analyst",
        "customer_service",
        "business_analyst",
    })

    TRANSITIONS = {
        ShipmentStatus.CREATED: {
            ShipmentStatus.ASSIGNED,
            ShipmentStatus.CANCELLED,
        },
        ShipmentStatus.ASSIGNED: {
            ShipmentStatus.DISPATCHED,
            ShipmentStatus.CANCELLED,
        },
        ShipmentStatus.DISPATCHED: {
            ShipmentStatus.IN_TRANSIT,
            ShipmentStatus.DELAYED,
            ShipmentStatus.DELIVERED,
        },
        ShipmentStatus.IN_TRANSIT: {
            ShipmentStatus.DELAYED,
            ShipmentStatus.DELIVERED,
        },
        ShipmentStatus.DELAYED: {
            ShipmentStatus.IN_TRANSIT,
            ShipmentStatus.DELIVERED,
        },
        ShipmentStatus.DELIVERED: set(),
        ShipmentStatus.CANCELLED: set(),
    }

    def __init__(
        self,
        tenant_id: str,
        currency: str = "INR",
    ):
        self.tenant_id = required(tenant_id, "tenant_id")
        self.currency = required(currency, "currency").upper()

        self._lock = threading.RLock()
        self._carriers: dict[str, Carrier] = {}
        self._shipments: dict[str, Shipment] = {}
        self._source_events: dict[
            tuple[str, str], tuple[str, str]
        ] = {}
        self._events: list[LogisticsEvent] = []
        self._outbox: dict[str, LogisticsOutboxEvent] = {}

    def _authorize(
        self,
        actor: LogisticsActor,
        roles: frozenset[str],
        warehouse_id: str | None = None,
    ) -> None:
        if (
            not actor.is_active
            or actor.tenant_id != self.tenant_id
            or not actor.user_id.strip()
            or not actor.roles.intersection(roles)
        ):
            raise PermissionError("Logistics access denied")

        if warehouse_id is None:
            if "corporate_admin" not in actor.roles:
                raise PermissionError("Corporate access required")
        elif (
            "corporate_admin" not in actor.roles
            and warehouse_id not in actor.warehouse_ids
        ):
            raise PermissionError("Warehouse scope denied")

    def _get(self, shipment_id: str) -> Shipment:
        shipment = self._shipments.get(shipment_id)
        if shipment is None:
            raise KeyError("Shipment not found")
        return shipment

    def _record(
        self,
        actor_id: str,
        shipment: Shipment,
        event_type: str,
        details: dict | None = None,
    ) -> None:
        self._events.append(LogisticsEvent(
            event_id=str(uuid.uuid4()),
            tenant_id=self.tenant_id,
            shipment_id=shipment.shipment_id,
            actor_id=actor_id,
            event_type=event_type,
            timestamp=stamp(),
            details=copy.deepcopy(details or {}),
        ))

        outbox = LogisticsOutboxEvent(
            event_id=str(uuid.uuid4()),
            tenant_id=self.tenant_id,
            shipment_id=shipment.shipment_id,
            event_type=f"logistics.{event_type}",
            payload={
                "shipment_id": shipment.shipment_id,
                "order_id": shipment.order_id,
                "warehouse_id": shipment.warehouse_id,
                "status": shipment.status.value,
                "expected_delivery_at": shipment.expected_delivery_at,
            },
            created_at=stamp(),
        )
        self._outbox[outbox.event_id] = outbox

    @staticmethod
    def _touch(shipment: Shipment) -> None:
        shipment.version += 1
        shipment.updated_at = stamp()

    def register_carrier(
        self,
        actor: LogisticsActor,
        carrier_id: str,
        name: str,
        service_level: str,
    ) -> Carrier:
        self._authorize(actor, frozenset({
            "logistics_manager",
            "operations_manager",
            "corporate_admin",
        }), None if "corporate_admin" in actor.roles else next(
            iter(actor.warehouse_ids), None
        ))

        carrier_id = required(carrier_id, "carrier_id")

        with self._lock:
            if carrier_id in self._carriers:
                raise ValueError("Carrier already exists")

            carrier = Carrier(
                carrier_id=carrier_id,
                tenant_id=self.tenant_id,
                name=required(name, "name"),
                service_level=required(service_level, "service_level"),
                active=True,
                created_at=stamp(),
            )
            self._carriers[carrier_id] = carrier
            return copy.deepcopy(carrier)

    def create_shipment(
        self,
        actor: LogisticsActor,
        shipment_id: str,
        order_id: str,
        warehouse_id: str,
        destination_code: str,
        expected_delivery_at: str,
    ) -> Shipment:
        self._authorize(actor, self.WRITER_ROLES, warehouse_id)
        shipment_id = required(shipment_id, "shipment_id")
        eta = parse_time(expected_delivery_at)

        with self._lock:
            if shipment_id in self._shipments:
                raise ValueError("Shipment already exists")

            shipment = Shipment(
                shipment_id=shipment_id,
                tenant_id=self.tenant_id,
                order_id=required(order_id, "order_id"),
                warehouse_id=warehouse_id,
                destination_code=required(
                    destination_code, "destination_code"
                ),
                carrier_id=None,
                tracking_number=None,
                status=ShipmentStatus.CREATED,
                expected_delivery_at=eta.isoformat(),
                dispatched_at=None,
                delivered_at=None,
                proof_of_delivery_ref=None,
                transport_cost=Decimal("0.00"),
                currency=self.currency,
                created_at=stamp(),
                updated_at=stamp(),
            )

            self._shipments[shipment_id] = shipment
            self._record(actor.user_id, shipment, "created")
            return copy.deepcopy(shipment)

    def assign_carrier(
        self,
        actor: LogisticsActor,
        shipment_id: str,
        carrier_id: str,
        tracking_number: str,
        expected_version: int,
    ) -> Shipment:
        with self._lock:
            shipment = self._get(shipment_id)
            self._authorize(
                actor, self.WRITER_ROLES, shipment.warehouse_id
            )

            if shipment.version != expected_version:
                raise ValueError("Version conflict")

            if shipment.status != ShipmentStatus.CREATED:
                raise ValueError("Shipment not assignable")

            carrier = self._carriers.get(carrier_id)
            if carrier is None or not carrier.active:
                raise ValueError("Carrier unavailable")

            shipment.carrier_id = carrier_id
            shipment.tracking_number = required(
                tracking_number, "tracking_number"
            )
            shipment.status = ShipmentStatus.ASSIGNED
            self._touch(shipment)
            self._record(actor.user_id, shipment, "carrier_assigned")
            return copy.deepcopy(shipment)

    def dispatch(
        self,
        actor: LogisticsActor,
        shipment_id: str,
        expected_version: int,
    ) -> Shipment:
        with self._lock:
            shipment = self._get(shipment_id)
            self._authorize(
                actor, self.WRITER_ROLES, shipment.warehouse_id
            )

            if shipment.version != expected_version:
                raise ValueError("Version conflict")

            if shipment.status != ShipmentStatus.ASSIGNED:
                raise ValueError("Shipment must be assigned")

            shipment.status = ShipmentStatus.DISPATCHED
            shipment.dispatched_at = stamp()
            self._touch(shipment)
            self._record(actor.user_id, shipment, "dispatched")
            return copy.deepcopy(shipment)

    def update_status(
        self,
        actor: LogisticsActor,
        shipment_id: str,
        new_status: ShipmentStatus,
        expected_version: int,
        source_event_id: str,
    ) -> Shipment:
        with self._lock:
            shipment = self._get(shipment_id)
            self._authorize(
                actor, self.WRITER_ROLES, shipment.warehouse_id
            )

            source_event_id = required(
                source_event_id, "source_event_id"
            )
            key = (shipment_id, source_event_id)
            prior = self._source_events.get(key)

            if prior is not None:
                if prior != ("status", new_status.value):
                    raise ValueError("Conflicting tracking event")
                return copy.deepcopy(shipment)

            if shipment.version != expected_version:
                raise ValueError("Version conflict")

            if new_status not in self.TRANSITIONS[shipment.status]:
                raise ValueError("Invalid shipment transition")

            if new_status == ShipmentStatus.DELIVERED:
                raise ValueError(
                    "Use confirm_delivery for proof of delivery"
                )

            shipment.status = new_status
            self._touch(shipment)
            self._source_events[key] = ("status", new_status.value)
            self._record(actor.user_id, shipment, "status_updated", {
                "new_status": new_status.value
            })
            return copy.deepcopy(shipment)

    def update_eta(
        self,
        actor: LogisticsActor,
        shipment_id: str,
        expected_delivery_at: str,
        expected_version: int,
    ) -> Shipment:
        eta = parse_time(expected_delivery_at)

        with self._lock:
            shipment = self._get(shipment_id)
            self._authorize(
                actor, self.WRITER_ROLES, shipment.warehouse_id
            )

            if shipment.version != expected_version:
                raise ValueError("Version conflict")

            if shipment.status in {
                ShipmentStatus.DELIVERED,
                ShipmentStatus.CANCELLED,
            }:
                raise ValueError("Shipment is finalized")

            shipment.expected_delivery_at = eta.isoformat()
            self._touch(shipment)
            self._record(actor.user_id, shipment, "eta_updated")
            return copy.deepcopy(shipment)

    def confirm_delivery(
        self,
        actor: LogisticsActor,
        shipment_id: str,
        proof_reference: str,
        expected_version: int,
    ) -> Shipment:
        proof_reference = required(
            proof_reference, "proof_reference"
        )

        with self._lock:
            shipment = self._get(shipment_id)
            self._authorize(
                actor, self.WRITER_ROLES, shipment.warehouse_id
            )

            if shipment.version != expected_version:
                raise ValueError("Version conflict")

            if shipment.status not in {
                ShipmentStatus.DISPATCHED,
                ShipmentStatus.IN_TRANSIT,
                ShipmentStatus.DELAYED,
            }:
                raise ValueError("Shipment cannot be delivered")

            shipment.status = ShipmentStatus.DELIVERED
            shipment.delivered_at = stamp()
            shipment.proof_of_delivery_ref = proof_reference
            self._touch(shipment)
            self._record(actor.user_id, shipment, "delivered")
            return copy.deepcopy(shipment)

    def record_transport_cost(
        self,
        actor: LogisticsActor,
        shipment_id: str,
        amount: Any,
        expected_version: int,
    ) -> Shipment:
        cost = money(amount)

        with self._lock:
            shipment = self._get(shipment_id)
            self._authorize(
                actor, self.WRITER_ROLES, shipment.warehouse_id
            )

            if shipment.version != expected_version:
                raise ValueError("Version conflict")

            shipment.transport_cost += cost
            self._touch(shipment)
            self._record(actor.user_id, shipment, "cost_recorded", {
                "amount": str(cost),
                "currency": self.currency,
            })
            return copy.deepcopy(shipment)

    def get_shipment(
        self,
        actor: LogisticsActor,
        shipment_id: str,
    ) -> Shipment:
        with self._lock:
            shipment = self._get(shipment_id)
            self._authorize(
                actor, self.READER_ROLES, shipment.warehouse_id
            )
            return copy.deepcopy(shipment)

    def list_shipments(
        self,
        actor: LogisticsActor,
        status: ShipmentStatus | None = None,
    ) -> list[Shipment]:
        if (
            not actor.is_active
            or actor.tenant_id != self.tenant_id
            or not actor.roles.intersection(self.READER_ROLES)
        ):
            raise PermissionError("Logistics access denied")

        with self._lock:
            return [
                copy.deepcopy(shipment)
                for shipment in self._shipments.values()
                if (
                    (
                        "corporate_admin" in actor.roles
                        or shipment.warehouse_id in actor.warehouse_ids
                    )
                    and (
                        status is None
                        or shipment.status == status
                    )
                )
            ]

    def delayed_shipments(
        self,
        actor: LogisticsActor,
        as_of: datetime | None = None,
    ) -> list[Shipment]:
        current = as_of or now()

        if current.tzinfo is None:
            raise ValueError("Timezone-aware datetime required")

        return [
            shipment
            for shipment in self.list_shipments(actor)
            if (
                shipment.status in {
                    ShipmentStatus.DISPATCHED,
                    ShipmentStatus.IN_TRANSIT,
                    ShipmentStatus.DELAYED,
                }
                and parse_time(
                    shipment.expected_delivery_at
                ) < current
            )
        ]

    def logistics_metrics(
        self,
        actor: LogisticsActor,
    ) -> dict[str, Any]:
        shipments = self.list_shipments(actor)
        delivered = [
            s for s in shipments
            if s.status == ShipmentStatus.DELIVERED
        ]

        on_time = sum(
            parse_time(s.delivered_at)
            <= parse_time(s.expected_delivery_at)
            for s in delivered
        )

        total_cost = sum(
            (s.transport_cost for s in shipments),
            Decimal("0.00"),
        )

        return {
            "tenant_id": self.tenant_id,
            "shipment_count": len(shipments),
            "delivered_count": len(delivered),
            "delayed_count": len(self.delayed_shipments(actor)),
            "on_time_delivery_rate_pct": (
                round(on_time / len(delivered) * 100, 2)
                if delivered else None
            ),
            "transport_cost": str(total_cost),
            "currency": self.currency,
        }

    def event_history(
        self,
        actor: LogisticsActor,
        shipment_id: str,
    ) -> list[LogisticsEvent]:
        self.get_shipment(actor, shipment_id)

        with self._lock:
            return [
                copy.deepcopy(event)
                for event in self._events
                if event.shipment_id == shipment_id
            ]

    def pending_events(
        self,
        actor: LogisticsActor,
    ) -> list[LogisticsOutboxEvent]:
        if (
            not actor.is_active
            or actor.tenant_id != self.tenant_id
            or not actor.roles.intersection(self.WRITER_ROLES)
        ):
            raise PermissionError("Outbox access denied")

        with self._lock:
            return [
                copy.deepcopy(event)
                for event in self._outbox.values()
                if (
                    not event.delivered
                    and (
                        "corporate_admin" in actor.roles
                        or self._shipments[
                            event.shipment_id
                        ].warehouse_id in actor.warehouse_ids
                    )
                )
            ]

    def mark_event_delivered(
        self,
        actor: LogisticsActor,
        event_id: str,
    ) -> None:
        with self._lock:
            event = self._outbox.get(event_id)
            if event is None:
                raise KeyError("Outbox event not found")

            shipment = self._get(event.shipment_id)
            self._authorize(
                actor, self.WRITER_ROLES, shipment.warehouse_id
            )
            event.delivered = True

    def export_json(
        self,
        actor: LogisticsActor,
        output_path: str | Path,
    ) -> Path:
        records = self.list_shipments(actor)
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                [asdict(r) for r in records],
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
        return path


if __name__ == "__main__":
    service = RetailLogisticsService(
        tenant_id="demo",
        currency="INR",
    )

    admin = LogisticsActor(
        user_id="admin001",
        tenant_id="demo",
        roles=frozenset({"corporate_admin"}),
    )

    service.register_carrier(
        admin,
        carrier_id="CARRIER001",
        name="Demo Express",
        service_level="standard",
    )

    shipment = service.create_shipment(
        admin,
        shipment_id="SHIP001",
        order_id="ORDER001",
        warehouse_id="WH001",
        destination_code="KOCHI",
        expected_delivery_at="2026-11-01T18:00:00+05:30",
    )

    shipment = service.assign_carrier(
        admin,
        shipment.shipment_id,
        "CARRIER001",
        "TRACK001",
        shipment.version,
    )

    shipment = service.dispatch(
        admin,
        shipment.shipment_id,
        shipment.version,
    )

    shipment = service.update_status(
        admin,
        shipment.shipment_id,
        ShipmentStatus.IN_TRANSIT,
        shipment.version,
        source_event_id="TRACK-EVENT001",
    )

    shipment = service.record_transport_cost(
        admin,
        shipment.shipment_id,
        "450.00",
        shipment.version,
    )

    shipment = service.confirm_delivery(
        admin,
        shipment.shipment_id,
        proof_reference="POD001",
        expected_version=shipment.version,
    )

    print("Status:", shipment.status.value)
    print("Metrics:", service.logistics_metrics(admin))
