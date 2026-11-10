from __future__ import annotations

"""Planned module: audit repository. Implementation pending."""

"""
backend/repositories/audit_repository.py

Autonomous Retail Supply Chain AI 5.0
Python 3.10+ | Standard library only

Reference features:
- Tenant-isolated audit events
- Append-only repository interface
- Warehouse-scoped reading
- Role-based permissions
- Actor, action, resource, timestamp
- Event idempotency
- SHA-256 hash chain
- Integrity verification
- Search and pagination
- JSON export

Security limitations:
- In-memory storage is not durable.
- Hash chaining alone is not tamper-proof.
- Caller identity must be verified externally.
- Production storage requires immutable retention.
"""


import copy
import hashlib
import json
import threading
import uuid

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def required(value: str, name: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > 255
    ):
        raise ValueError(f"Invalid {name}")
    return value.strip()


def canonical_json(data: dict[str, Any]) -> str:
    return json.dumps(
        data,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


@dataclass(frozen=True)
class AuditActor:
    user_id: str
    tenant_id: str
    roles: frozenset[str]
    warehouse_ids: frozenset[str] = frozenset()
    is_active: bool = True


@dataclass(frozen=True)
class AuditEvent:
    event_id: str
    tenant_id: str
    sequence: int
    actor_id: str
    action: str
    resource_type: str
    resource_id: str
    warehouse_id: str | None
    timestamp: str
    correlation_id: str | None
    details: dict[str, Any]
    previous_hash: str
    event_hash: str


class RetailAuditRepository:
    WRITE_ROLES = frozenset({
        "corporate_admin",
        "security_manager",
        "audit_writer",
    })

    READ_ROLES = frozenset({
        "corporate_admin",
        "security_manager",
        "auditor",
        "warehouse_manager",
    })

    GLOBAL_READ_ROLES = frozenset({
        "corporate_admin",
        "security_manager",
        "auditor",
    })

    def __init__(self, tenant_id: str):
        self.tenant_id = required(
            tenant_id, "tenant_id"
        )

        self._lock = threading.RLock()
        self._events: list[AuditEvent] = []
        self._source_index: dict[str, str] = {}

    def _authorize(
        self,
        actor: AuditActor,
        roles: frozenset[str],
    ) -> None:
        if (
            not actor.is_active
            or actor.tenant_id != self.tenant_id
            or not actor.user_id.strip()
            or not actor.roles.intersection(roles)
        ):
            raise PermissionError(
                "Audit repository access denied"
            )

    def _can_read(
        self,
        actor: AuditActor,
        event: AuditEvent,
    ) -> bool:
        if actor.roles.intersection(
            self.GLOBAL_READ_ROLES
        ):
            return True

        return (
            event.warehouse_id is not None
            and event.warehouse_id
            in actor.warehouse_ids
        )

    @staticmethod
    def _payload(
        event_id: str,
        tenant_id: str,
        sequence: int,
        actor_id: str,
        action: str,
        resource_type: str,
        resource_id: str,
        warehouse_id: str | None,
        timestamp: str,
        correlation_id: str | None,
        details: dict[str, Any],
        previous_hash: str,
    ) -> dict[str, Any]:
        return {
            "event_id": event_id,
            "tenant_id": tenant_id,
            "sequence": sequence,
            "actor_id": actor_id,
            "action": action,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "warehouse_id": warehouse_id,
            "timestamp": timestamp,
            "correlation_id": correlation_id,
            "details": details,
            "previous_hash": previous_hash,
        }

    @staticmethod
    def _hash(payload: dict[str, Any]) -> str:
        return hashlib.sha256(
            canonical_json(payload).encode("utf-8")
        ).hexdigest()

    def append(
        self,
        actor: AuditActor,
        *,
        action: str,
        resource_type: str,
        resource_id: str,
        details: dict[str, Any] | None = None,
        warehouse_id: str | None = None,
        correlation_id: str | None = None,
        source_event_id: str | None = None,
        subject_actor_id: str | None = None,
    ) -> AuditEvent:
        self._authorize(actor, self.WRITE_ROLES)

        action = required(action, "action")
        resource_type = required(
            resource_type, "resource_type"
        )
        resource_id = required(
            resource_id, "resource_id"
        )

        if warehouse_id is not None:
            warehouse_id = required(
                warehouse_id, "warehouse_id"
            )

        if correlation_id is not None:
            correlation_id = required(
                correlation_id, "correlation_id"
            )

        if source_event_id is not None:
            source_event_id = required(
                source_event_id, "source_event_id"
            )

        if subject_actor_id is not None:
            subject_actor_id = required(
                subject_actor_id, "subject_actor_id"
            )

        if (
            warehouse_id is not None
            and not actor.roles.intersection(
                self.GLOBAL_READ_ROLES
            )
            and warehouse_id not in actor.warehouse_ids
        ):
            raise PermissionError(
                "Warehouse access denied"
            )

        if details is None:
            details = {}

        if not isinstance(details, dict):
            raise ValueError(
                "Audit details must be a dictionary"
            )

        # Validate serializability and detach caller data.
        serialized_details = canonical_json(details)
        normalized_details = json.loads(
            serialized_details
        )

        # Identity override is allowed only for trusted
        # system writers. In production, bind this to
        # authenticated service identity.
        if (
            subject_actor_id is not None
            and "audit_writer" not in actor.roles
        ):
            raise PermissionError(
                "Actor override requires audit_writer"
            )

        recorded_actor_id = (
            subject_actor_id or actor.user_id
        )

        with self._lock:
            if source_event_id is not None:
                existing_id = self._source_index.get(
                    source_event_id
                )

                if existing_id is not None:
                    existing = next(
                        event
                        for event in self._events
                        if event.event_id == existing_id
                    )

                    if (
                        existing.action != action
                        or existing.resource_type
                        != resource_type
                        or existing.resource_id
                        != resource_id
                        or existing.actor_id
                        != recorded_actor_id
                        or existing.warehouse_id
                        != warehouse_id
                        or existing.details
                        != normalized_details
                        or existing.correlation_id
                        != correlation_id
                    ):
                        raise ValueError(
                            "Conflicting source event"
                        )

                    return copy.deepcopy(existing)

            sequence = len(self._events) + 1

            previous_hash = (
                self._events[-1].event_hash
                if self._events
                else "GENESIS"
            )

            event_id = str(uuid.uuid4())
            timestamp = utc_now()

            payload = self._payload(
                event_id=event_id,
                tenant_id=self.tenant_id,
                sequence=sequence,
                actor_id=recorded_actor_id,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                warehouse_id=warehouse_id,
                timestamp=timestamp,
                correlation_id=correlation_id,
                details=normalized_details,
                previous_hash=previous_hash,
            )

            event = AuditEvent(
                **payload,
                event_hash=self._hash(payload),
            )

            self._events.append(event)

            if source_event_id is not None:
                self._source_index[
                    source_event_id
                ] = event.event_id

            return copy.deepcopy(event)

    def get(
        self,
        actor: AuditActor,
        event_id: str,
    ) -> AuditEvent:
        self._authorize(actor, self.READ_ROLES)

        with self._lock:
            for event in self._events:
                if event.event_id == event_id:
                    if not self._can_read(
                        actor, event
                    ):
                        raise PermissionError(
                            "Audit event access denied"
                        )
                    return copy.deepcopy(event)

        raise KeyError("Audit event not found")

    def search(
        self,
        actor: AuditActor,
        *,
        action: str | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        actor_id: str | None = None,
        warehouse_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AuditEvent]:
        self._authorize(actor, self.READ_ROLES)

        if (
            type(limit) is not int
            or type(offset) is not int
            or not 1 <= limit <= 500
            or offset < 0
        ):
            raise ValueError("Invalid pagination")

        with self._lock:
            results = [
                event
                for event in self._events
                if (
                    self._can_read(actor, event)
                    and (
                        action is None
                        or event.action == action
                    )
                    and (
                        resource_type is None
                        or event.resource_type
                        == resource_type
                    )
                    and (
                        resource_id is None
                        or event.resource_id
                        == resource_id
                    )
                    and (
                        actor_id is None
                        or event.actor_id == actor_id
                    )
                    and (
                        warehouse_id is None
                        or event.warehouse_id
                        == warehouse_id
                    )
                )
            ]

            results.sort(
                key=lambda event: event.sequence,
                reverse=True,
            )

            return copy.deepcopy(
                results[offset:offset + limit]
            )

    def count(
        self,
        actor: AuditActor,
    ) -> int:
        self._authorize(actor, self.READ_ROLES)

        with self._lock:
            return sum(
                self._can_read(actor, event)
                for event in self._events
            )

    def verify_integrity(
        self,
        actor: AuditActor,
    ) -> dict[str, Any]:
        self._authorize(
            actor, self.GLOBAL_READ_ROLES
        )

        with self._lock:
            previous_hash = "GENESIS"

            for expected_sequence, event in enumerate(
                self._events, start=1
            ):
                payload = self._payload(
                    event_id=event.event_id,
                    tenant_id=event.tenant_id,
                    sequence=event.sequence,
                    actor_id=event.actor_id,
                    action=event.action,
                    resource_type=event.resource_type,
                    resource_id=event.resource_id,
                    warehouse_id=event.warehouse_id,
                    timestamp=event.timestamp,
                    correlation_id=event.correlation_id,
                    details=event.details,
                    previous_hash=event.previous_hash,
                )

                if (
                    event.sequence != expected_sequence
                    or event.previous_hash != previous_hash
                    or event.event_hash
                    != self._hash(payload)
                ):
                    return {
                        "valid": False,
                        "failed_sequence": expected_sequence,
                    }

                previous_hash = event.event_hash

            return {
                "valid": True,
                "events_verified": len(self._events),
                "last_hash": previous_hash,
            }

    def export_json(
        self,
        actor: AuditActor,
        output_path: str | Path,
    ) -> Path:
        self._authorize(
            actor, self.GLOBAL_READ_ROLES
        )

        with self._lock:
            events = [
                asdict(event)
                for event in self._events
            ]

        path = Path(output_path)
        path.parent.mkdir(
            parents=True, exist_ok=True
        )

        path.write_text(
            json.dumps(
                events,
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        return path


if __name__ == "__main__":
    repository = RetailAuditRepository("demo")

    system = AuditActor(
        user_id="SYSTEM",
        tenant_id="demo",
        roles=frozenset({
            "audit_writer",
            "auditor",
        }),
    )

    repository.append(
        system,
        action="stock_received",
        resource_type="inventory",
        resource_id="SKU001",
        warehouse_id="WH001",
        details={
            "quantity": 100,
            "reference": "GRN001",
        },
        source_event_id="EVENT001",
        correlation_id="REQUEST001",
    )

    repository.append(
        system,
        action="supplier_activated",
        resource_type="supplier",
        resource_id="SUP001",
        details={
            "approval_reference": "APP001",
        },
        source_event_id="EVENT002",
    )

    print(
        "Audit count:",
        repository.count(system),
    )

    print(
        "Integrity:",
        repository.verify_integrity(system),
    )
