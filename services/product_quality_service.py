from __future__ import annotations

"""Planned module: product quality service. Implementation pending."""

"""
backend/services/product_quality_service.py

Autonomous Retail Supply Chain AI 5.0
Product Quality Management Service

Python 3.10+ | Standard library only

Features:
- Tenant and warehouse authorization
- Product batch registration
- Inspection record management
- Defect-rate calculations
- Critical defect classification
- Quality-control decisions
- Batch quarantine
- Approval-gated quarantine release
- Supplier quality metrics
- Idempotent inspection references
- Audit history
- Integration outbox events
- JSON export

Reference prototype only.

No physical stock movement, product
recall, supplier notification or
external system update is executed.

Production must enforce quarantine
within the authoritative inventory
allocation and fulfillment systems.
"""


import copy
import json
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
from typing import (
    Any,
    Callable,
)


def utc_now() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


def require_text(
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


def positive_int(
    value: int,
    name: str,
) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value <= 0
    ):
        raise ValueError(
            f"{name} must be positive integer"
        )

    return value


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


class QualityStatus(str, Enum):
    PENDING = "pending"
    PASSED = "passed"
    REVIEW = "review"
    FAILED = "failed"
    QUARANTINED = "quarantined"
    RELEASED = "released"


class DefectSeverity(str, Enum):
    MINOR = "minor"
    MAJOR = "major"
    CRITICAL = "critical"


@dataclass(frozen=True)
class QualityActor:
    user_id: str
    tenant_id: str
    roles: frozenset[str]
    warehouse_ids: frozenset[str] = (
        frozenset()
    )
    is_active: bool = True


@dataclass
class QualityBatch:
    batch_id: str
    tenant_id: str
    warehouse_id: str
    sku: str
    supplier_id: str
    received_quantity: int
    status: QualityStatus
    created_at: str
    updated_at: str
    quarantine_reason: str | None = None
    release_reference: str | None = None


@dataclass(frozen=True)
class QualityInspection:
    inspection_id: str
    tenant_id: str
    batch_id: str
    inspected_units: int
    defective_units: int
    critical_defects: int
    severity: DefectSeverity
    defect_rate_pct: float
    inspection_reference: str
    inspector_id: str
    inspected_at: str
    notes: str = ""


@dataclass(frozen=True)
class QualityAuditEvent:
    event_id: str
    tenant_id: str
    batch_id: str
    actor_id: str
    action: str
    timestamp: str
    details: dict[str, Any] = field(
        default_factory=dict
    )


@dataclass
class QualityOutboxEvent:
    event_id: str
    tenant_id: str
    event_type: str
    batch_id: str
    warehouse_id: str
    payload: dict[str, Any]
    created_at: str
    delivered: bool = False


# Approval verifier arguments:
# approval_reference, tenant_id,
# batch_id, warehouse_id, sku
#
# Must verify finalized authorization
# for the exact batch release.

ReleaseVerifier = Callable[
    [str, str, str, str, str],
    bool,
]


class RetailProductQualityService:
    INSPECTOR_ROLES = frozenset({
        "quality_inspector",
        "quality_manager",
        "corporate_admin",
    })

    MANAGER_ROLES = frozenset({
        "quality_manager",
        "corporate_admin",
    })

    READER_ROLES = (
        INSPECTOR_ROLES
        | frozenset({
            "warehouse_manager",
            "product_manager",
            "procurement_manager",
            "quality_analyst",
        })
    )

    def __init__(
        self,
        tenant_id: str,
        warning_defect_rate: float = 2.0,
        failure_defect_rate: float = 5.0,
        release_verifier: (
            ReleaseVerifier | None
        ) = None,
    ):
        self.tenant_id = require_text(
            tenant_id,
            "tenant_id",
        )

        if not (
            0 <= warning_defect_rate
            < failure_defect_rate <= 100
        ):
            raise ValueError(
                "Invalid defect thresholds"
            )

        self.warning_defect_rate = (
            warning_defect_rate
        )

        self.failure_defect_rate = (
            failure_defect_rate
        )

        self.release_verifier = (
            release_verifier
        )

        self._lock = threading.RLock()

        self._batches: dict[
            str, QualityBatch
        ] = {}

        self._inspections: dict[
            tuple[str, str],
            QualityInspection,
        ] = {}

        self._audit: list[
            QualityAuditEvent
        ] = []

        self._outbox: dict[
            str, QualityOutboxEvent
        ] = {}

    def _authorize(
        self,
        actor: QualityActor,
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
                "Quality service access denied"
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

    def _get_batch(
        self,
        actor: QualityActor,
        batch_id: str,
        roles: frozenset[str],
    ) -> QualityBatch:
        batch = self._batches.get(
            batch_id
        )

        if batch is None:
            raise KeyError(
                "Batch not found"
            )

        self._authorize(
            actor,
            roles,
            batch.warehouse_id,
        )

        return batch

    def _audit_event(
        self,
        actor: QualityActor,
        batch: QualityBatch,
        action: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        self._audit.append(
            QualityAuditEvent(
                event_id=str(uuid.uuid4()),
                tenant_id=self.tenant_id,
                batch_id=batch.batch_id,
                actor_id=actor.user_id,
                action=action,
                timestamp=utc_now(),
                details=copy.deepcopy(
                    details or {}
                ),
            )
        )

    def _outbox_event(
        self,
        batch: QualityBatch,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        event = QualityOutboxEvent(
            event_id=str(uuid.uuid4()),
            tenant_id=self.tenant_id,
            event_type=event_type,
            batch_id=batch.batch_id,
            warehouse_id=batch.warehouse_id,
            payload=copy.deepcopy(
                payload
            ),
            created_at=utc_now(),
        )

        self._outbox[
            event.event_id
        ] = event

    def register_batch(
        self,
        actor: QualityActor,
        batch_id: str,
        warehouse_id: str,
        sku: str,
        supplier_id: str,
        received_quantity: int,
    ) -> QualityBatch:
        self._authorize(
            actor,
            self.MANAGER_ROLES,
            warehouse_id,
        )

        batch_id = require_text(
            batch_id,
            "batch_id",
        )

        warehouse_id = require_text(
            warehouse_id,
            "warehouse_id",
        )

        sku = require_text(
            sku,
            "sku",
        )

        supplier_id = require_text(
            supplier_id,
            "supplier_id",
        )

        positive_int(
            received_quantity,
            "received_quantity",
        )

        with self._lock:
            existing = self._batches.get(
                batch_id
            )

            if existing:
                if (
                    existing.warehouse_id
                    != warehouse_id
                    or existing.sku != sku
                    or existing.supplier_id
                    != supplier_id
                    or existing.received_quantity
                    != received_quantity
                ):
                    raise ValueError(
                        "Batch ID conflict"
                    )

                return copy.deepcopy(
                    existing
                )

            now = utc_now()

            batch = QualityBatch(
                batch_id=batch_id,
                tenant_id=self.tenant_id,
                warehouse_id=warehouse_id,
                sku=sku,
                supplier_id=supplier_id,
                received_quantity=(
                    received_quantity
                ),
                status=QualityStatus.PENDING,
                created_at=now,
                updated_at=now,
            )

            self._batches[
                batch_id
            ] = batch

            self._audit_event(
                actor,
                batch,
                "batch_registered",
            )

            return copy.deepcopy(
                batch
            )

    def inspect_batch(
        self,
        actor: QualityActor,
        batch_id: str,
        inspected_units: int,
        defective_units: int,
        critical_defects: int,
        inspection_reference: str,
        notes: str = "",
    ) -> QualityInspection:
        positive_int(
            inspected_units,
            "inspected_units",
        )

        nonnegative_int(
            defective_units,
            "defective_units",
        )

        nonnegative_int(
            critical_defects,
            "critical_defects",
        )

        inspection_reference = (
            require_text(
                inspection_reference,
                "inspection_reference",
            )
        )

        if (
            defective_units > inspected_units
            or critical_defects > defective_units
        ):
            raise ValueError(
                "Invalid inspection counts"
            )

        if (
            not isinstance(notes, str)
            or len(notes) > 5000
        ):
            raise ValueError(
                "Invalid inspection notes"
            )

        with self._lock:
            batch = self._get_batch(
                actor,
                batch_id,
                self.INSPECTOR_ROLES,
            )

            key = (
                batch_id,
                inspection_reference,
            )

            existing = (
                self._inspections.get(
                    key
                )
            )

            if existing:
                if (
                    existing.inspected_units
                    != inspected_units
                    or existing.defective_units
                    != defective_units
                    or existing.critical_defects
                    != critical_defects
                    or existing.notes != notes
                ):
                    raise ValueError(
                        "Inspection reference conflict"
                    )

                return existing

            if batch.status not in {
                QualityStatus.PENDING,
                QualityStatus.REVIEW,
            }:
                raise ValueError(
                    "Batch is not open for inspection"
                )

            previously_inspected = sum(
                inspection.inspected_units
                for (
                    inspection_batch_id, _
                ), inspection in (
                    self._inspections.items()
                )
                if inspection_batch_id
                == batch_id
            )

            if (
                previously_inspected
                + inspected_units
                > batch.received_quantity
            ):
                raise ValueError(
                    "Inspections exceed batch quantity"
                )

            defect_rate = (
                defective_units
                / inspected_units
                * 100
            )

            if critical_defects > 0:
                severity = (
                    DefectSeverity.CRITICAL
                )

            elif defect_rate >= (
                self.failure_defect_rate
            ):
                severity = (
                    DefectSeverity.MAJOR
                )

            else:
                severity = (
                    DefectSeverity.MINOR
                )

            inspection = QualityInspection(
                inspection_id=str(
                    uuid.uuid4()
                ),
                tenant_id=self.tenant_id,
                batch_id=batch_id,
                inspected_units=(
                    inspected_units
                ),
                defective_units=(
                    defective_units
                ),
                critical_defects=(
                    critical_defects
                ),
                severity=severity,
                defect_rate_pct=round(
                    defect_rate, 2
                ),
                inspection_reference=(
                    inspection_reference
                ),
                inspector_id=actor.user_id,
                inspected_at=utc_now(),
                notes=notes,
            )

            self._inspections[
                key
            ] = inspection

            self._audit_event(
                actor,
                batch,
                "batch_inspected",
                {
                    "inspection_id": (
                        inspection.inspection_id
                    ),
                    "defect_rate_pct": (
                        inspection.defect_rate_pct
                    ),
                    "severity": (
                        severity.value
                    ),
                },
            )

            return inspection

    def evaluate_batch(
        self,
        actor: QualityActor,
        batch_id: str,
    ) -> dict[str, Any]:
        with self._lock:
            batch = self._get_batch(
                actor,
                batch_id,
                self.READER_ROLES,
            )

            inspections = [
                inspection
                for (
                    inspection_batch_id, _
                ), inspection in (
                    self._inspections.items()
                )
                if inspection_batch_id
                == batch_id
            ]

            inspected = sum(
                item.inspected_units
                for item in inspections
            )

            defective = sum(
                item.defective_units
                for item in inspections
            )

            critical = sum(
                item.critical_defects
                for item in inspections
            )

            defect_rate = (
                defective / inspected * 100
                if inspected
                else None
            )

            if inspected == 0:
                recommendation = (
                    QualityStatus.PENDING
                )

            elif (
                critical > 0
                or defect_rate
                >= self.failure_defect_rate
            ):
                recommendation = (
                    QualityStatus.FAILED
                )

            elif defect_rate >= (
                self.warning_defect_rate
            ):
                recommendation = (
                    QualityStatus.REVIEW
                )

            else:
                recommendation = (
                    QualityStatus.PASSED
                )

            return {
                "batch_id": batch_id,
                "tenant_id": self.tenant_id,
                "received_quantity": (
                    batch.received_quantity
                ),
                "inspected_units": inspected,
                "defective_units": defective,
                "critical_defects": critical,
                "defect_rate_pct": (
                    round(defect_rate, 2)
                    if defect_rate
                    is not None
                    else None
                ),
                "recommendation": (
                    recommendation.value
                ),
                "current_status": (
                    batch.status.value
                ),
            }

    def finalize_inspection(
        self,
        actor: QualityActor,
        batch_id: str,
    ) -> QualityBatch:
        with self._lock:
            batch = self._get_batch(
                actor,
                batch_id,
                self.MANAGER_ROLES,
            )

            if batch.status not in {
                QualityStatus.PENDING,
                QualityStatus.REVIEW,
            }:
                raise ValueError(
                    "Batch cannot be finalized"
                )

            evaluation = self.evaluate_batch(
                actor,
                batch_id,
            )

            recommendation = (
                QualityStatus(
                    evaluation["recommendation"]
                )
            )

            if recommendation == (
                QualityStatus.PENDING
            ):
                raise ValueError(
                    "Inspection required"
                )

            if recommendation == (
                QualityStatus.FAILED
            ):
                batch.status = (
                    QualityStatus.QUARANTINED
                )

                batch.quarantine_reason = (
                    "Inspection failure"
                )

                self._outbox_event(
                    batch,
                    "quality.batch_quarantined",
                    {
                        "batch_id": batch_id,
                        "sku": batch.sku,
                        "warehouse_id": (
                            batch.warehouse_id
                        ),
                    },
                )

            else:
                batch.status = recommendation

            batch.updated_at = utc_now()

            self._audit_event(
                actor,
                batch,
                "inspection_finalized",
                {
                    "status": (
                        batch.status.value
                    ),
                },
            )

            return copy.deepcopy(
                batch
            )

    def quarantine_batch(
        self,
        actor: QualityActor,
        batch_id: str,
        reason: str,
    ) -> QualityBatch:
        reason = require_text(
            reason,
            "reason",
        )

        with self._lock:
            batch = self._get_batch(
                actor,
                batch_id,
                self.MANAGER_ROLES,
            )

            if batch.status == (
                QualityStatus.QUARANTINED
            ):
                return copy.deepcopy(
                    batch
                )

            if batch.status == (
                QualityStatus.RELEASED
            ):
                raise ValueError(
                    "Released batch requires "
                    "a separate recall workflow"
                )

            batch.status = (
                QualityStatus.QUARANTINED
            )

            batch.quarantine_reason = (
                reason
            )

            batch.updated_at = utc_now()

            self._outbox_event(
                batch,
                "quality.batch_quarantined",
                {
                    "batch_id": batch_id,
                    "sku": batch.sku,
                    "warehouse_id": (
                        batch.warehouse_id
                    ),
                    "reason": reason,
                },
            )

            self._audit_event(
                actor,
                batch,
                "batch_quarantined",
                {
                    "reason": reason
                },
            )

            return copy.deepcopy(
                batch
            )

    def release_batch(
        self,
        actor: QualityActor,
        batch_id: str,
        approval_reference: str,
    ) -> QualityBatch:
        approval_reference = require_text(
            approval_reference,
            "approval_reference",
        )

        with self._lock:
            batch = self._get_batch(
                actor,
                batch_id,
                self.MANAGER_ROLES,
            )

            if batch.status == (
                QualityStatus.RELEASED
            ):
                if batch.release_reference != (
                    approval_reference
                ):
                    raise ValueError(
                        "Release reference conflict"
                    )

                return copy.deepcopy(
                    batch
                )

            if batch.status != (
                QualityStatus.QUARANTINED
            ):
                raise ValueError(
                    "Only quarantined batches "
                    "can use this release workflow"
                )

            if self.release_verifier is None:
                raise RuntimeError(
                    "Release verifier unavailable"
                )

            verified = (
                self.release_verifier(
                    approval_reference,
                    self.tenant_id,
                    batch.batch_id,
                    batch.warehouse_id,
                    batch.sku,
                )
            )

            if verified is not True:
                raise PermissionError(
                    "Release approval not verified"
                )

            batch.status = (
                QualityStatus.RELEASED
            )

            batch.release_reference = (
                approval_reference
            )

            batch.updated_at = utc_now()

            self._outbox_event(
                batch,
                "quality.batch_released",
                {
                    "batch_id": batch_id,
                    "sku": batch.sku,
                    "warehouse_id": (
                        batch.warehouse_id
                    ),
                    "approval_reference": (
                        approval_reference
                    ),
                },
            )

            self._audit_event(
                actor,
                batch,
                "batch_released",
                {
                    "approval_reference": (
                        approval_reference
                    ),
                },
            )

            return copy.deepcopy(
                batch
            )

    def get_batch(
        self,
        actor: QualityActor,
        batch_id: str,
    ) -> QualityBatch:
        with self._lock:
            return copy.deepcopy(
                self._get_batch(
                    actor,
                    batch_id,
                    self.READER_ROLES,
                )
            )

    def supplier_quality(
        self,
        actor: QualityActor,
        supplier_id: str,
    ) -> dict[str, Any]:
        self._authorize(
            actor,
            self.READER_ROLES,
        )

        with self._lock:
            batches = [
                batch
                for batch in (
                    self._batches.values()
                )
                if (
                    batch.supplier_id
                    == supplier_id
                    and (
                        "corporate_admin"
                        in actor.roles
                        or batch.warehouse_id
                        in actor.warehouse_ids
                    )
                )
            ]

            batch_ids = {
                batch.batch_id
                for batch in batches
            }

            inspections = [
                inspection
                for (
                    batch_id, _
                ), inspection in (
                    self._inspections.items()
                )
                if batch_id in batch_ids
            ]

            inspected = sum(
                item.inspected_units
                for item in inspections
            )

            defective = sum(
                item.defective_units
                for item in inspections
            )

            return {
                "tenant_id": self.tenant_id,
                "supplier_id": supplier_id,
                "batches": len(batches),
                "inspected_units": inspected,
                "defective_units": defective,
                "defect_rate_pct": (
                    round(
                        defective
                        / inspected * 100,
                        2,
                    )
                    if inspected
                    else None
                ),
                "quarantined_batches": sum(
                    batch.status
                    == QualityStatus.QUARANTINED
                    for batch in batches
                ),
            }

    def pending_events(
        self,
        actor: QualityActor,
    ) -> list[QualityOutboxEvent]:
        self._authorize(
            actor,
            self.MANAGER_ROLES,
        )

        with self._lock:
            return [
                copy.deepcopy(event)
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
        actor: QualityActor,
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
                self.MANAGER_ROLES,
                event.warehouse_id,
            )

            event.delivered = True

    def audit_events(
        self,
        actor: QualityActor,
        batch_id: str,
    ) -> list[QualityAuditEvent]:
        with self._lock:
            self._get_batch(
                actor,
                batch_id,
                self.READER_ROLES,
            )

            return [
                copy.deepcopy(event)
                for event in self._audit
                if event.batch_id == batch_id
            ]

    def export_json(
        self,
        actor: QualityActor,
        output_path: str | Path,
    ) -> Path:
        self._authorize(
            actor,
            self.MANAGER_ROLES,
        )

        with self._lock:
            batches = [
                asdict(batch)
                for batch in (
                    self._batches.values()
                )
                if (
                    "corporate_admin"
                    in actor.roles
                    or batch.warehouse_id
                    in actor.warehouse_ids
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
                batches,
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )

        return output


if __name__ == "__main__":
    def demo_release_verifier(
        approval_reference,
        tenant_id,
        batch_id,
        warehouse_id,
        sku,
    ) -> bool:
        return (
            approval_reference == "QA-APPROVED-001"
            and tenant_id == "demo"
            and batch_id == "BATCH001"
            and warehouse_id == "WH001"
            and sku == "SKU001"
        )

    service = RetailProductQualityService(
        tenant_id="demo",
        release_verifier=(
            demo_release_verifier
        ),
    )

    manager = QualityActor(
        user_id="quality-manager",
        tenant_id="demo",
        roles=frozenset({
            "quality_manager",
        }),
        warehouse_ids=frozenset({
            "WH001",
        }),
    )

    inspector = QualityActor(
        user_id="quality-inspector",
        tenant_id="demo",
        roles=frozenset({
            "quality_inspector",
        }),
        warehouse_ids=frozenset({
            "WH001",
        }),
    )

    service.register_batch(
        manager,
        batch_id="BATCH001",
        warehouse_id="WH001",
        sku="SKU001",
        supplier_id="SUP001",
        received_quantity=100,
    )

    service.inspect_batch(
        inspector,
        batch_id="BATCH001",
        inspected_units=50,
        defective_units=4,
        critical_defects=1,
        inspection_reference="INS001",
    )

    evaluation = service.evaluate_batch(
        manager,
        "BATCH001",
    )

    print(
        "Evaluation:",
        evaluation,
    )

    service.finalize_inspection(
        manager,
        "BATCH001",
    )

    print(
        "Quarantined:",
        service.get_batch(
            manager,
            "BATCH001",
        ).status.value,
    )

    service.release_batch(
        manager,
        "BATCH001",
        approval_reference=(
            "QA-APPROVED-001"
        ),
    )

    print(
        "Final status:",
        service.get_batch(
            manager,
            "BATCH001",
        ).status.value,
    )
