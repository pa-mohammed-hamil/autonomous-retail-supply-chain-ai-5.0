from __future__ import annotations

"""Planned module: replenishment worker. Implementation pending."""

"""
ai/workers/replenishment_worker.py

Autonomous Retail Supply Chain AI 5.0

Features:
- Inventory replenishment recommendations
- Demand and lead-time calculations
- Safety stock and reorder points
- Economic Order Quantity (EOQ)
- Stock coverage estimation
- Supplier selection via configured inputs
- Purchase-order proposal generation
- Human approval workflow
- Idempotent replenishment jobs
- SQLite persistence
- Retry and dead-letter handling
- Optional low-stock alert integration

Python 3.10+
Standard library only.

IMPORTANT:
This module generates purchase-order PROPOSALS.
It does not automatically place orders or
authorize spending.
"""


import json
import math
import sqlite3
import uuid

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utc_now().isoformat()


@dataclass(frozen=True)
class ReplenishmentConfig:
    database_path: str = (
        "data/workers/replenishment.db"
    )
    service_level_z: float = 1.65
    review_period_days: int = 7
    max_order_quantity: int = 100000
    max_attempts: int = 3
    retry_base_seconds: int = 10
    lease_seconds: int = 300

    def __post_init__(self):
        if self.service_level_z < 0:
            raise ValueError("Invalid service level")

        if self.review_period_days < 1:
            raise ValueError("Invalid review period")

        if self.max_order_quantity < 1:
            raise ValueError("Invalid maximum quantity")

        if self.max_attempts < 1:
            raise ValueError("Invalid max attempts")

        if self.lease_seconds < 1:
            raise ValueError("Invalid lease")


@dataclass(frozen=True)
class ReplenishmentRequest:
    request_id: str
    store_id: str
    warehouse_id: str
    sku: str
    supplier_id: str
    on_hand: int
    reserved: int
    on_order: int
    average_daily_demand: float
    demand_std_dev: float
    lead_time_days: float
    unit_cost: float
    ordering_cost: float
    annual_holding_cost_per_unit: float
    budget_limit: float
    currency: str = "INR"


class ReplenishmentWorker:

    def __init__(
        self,
        config: ReplenishmentConfig | None = None,
    ):
        self.config = config or ReplenishmentConfig()

        path = Path(self.config.database_path)
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.db = sqlite3.connect(
            str(path),
            timeout=30,
        )

        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA busy_timeout=30000")

        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS replenishment_jobs (
                request_id TEXT PRIMARY KEY,
                request_json TEXT NOT NULL,
                status TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                next_attempt_at TEXT NOT NULL,
                lease_until TEXT,
                last_error TEXT,
                created_at TEXT NOT NULL,
                completed_at TEXT
            );

            CREATE TABLE IF NOT EXISTS purchase_proposals (
                proposal_id TEXT PRIMARY KEY,
                request_id TEXT NOT NULL UNIQUE,
                store_id TEXT NOT NULL,
                warehouse_id TEXT NOT NULL,
                sku TEXT NOT NULL,
                supplier_id TEXT NOT NULL,
                recommended_quantity INTEGER NOT NULL,
                estimated_cost REAL NOT NULL,
                currency TEXT NOT NULL,
                metrics_json TEXT NOT NULL,
                status TEXT NOT NULL,
                approved_by TEXT,
                approved_at TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS replenishment_audit (
                audit_id TEXT PRIMARY KEY,
                request_id TEXT NOT NULL,
                action TEXT NOT NULL,
                actor TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
        """)

        self.db.commit()

    @staticmethod
    def validate_request(
        request: ReplenishmentRequest,
    ) -> None:
        identifiers = (
            request.request_id,
            request.store_id,
            request.warehouse_id,
            request.sku,
            request.supplier_id,
            request.currency,
        )

        if any(
            not isinstance(value, str)
            or not value.strip()
            for value in identifiers
        ):
            raise ValueError(
                "Required identifiers are missing"
            )

        for name in (
            "on_hand",
            "reserved",
            "on_order",
        ):
            value = getattr(request, name)

            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
            ):
                raise ValueError(
                    f"Invalid {name}"
                )

        if request.reserved > request.on_hand:
            raise ValueError(
                "Reserved inventory exceeds on-hand"
            )

        numeric_fields = (
            "average_daily_demand",
            "demand_std_dev",
            "lead_time_days",
            "unit_cost",
            "ordering_cost",
            "annual_holding_cost_per_unit",
            "budget_limit",
        )

        for name in numeric_fields:
            value = getattr(request, name)

            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value < 0
            ):
                raise ValueError(
                    f"Invalid {name}"
                )

    def calculate_metrics(
        self,
        request: ReplenishmentRequest,
    ) -> dict:
        self.validate_request(request)

        demand = request.average_daily_demand
        lead_time = request.lead_time_days

        available = (
            request.on_hand - request.reserved
        )

        inventory_position = (
            available + request.on_order
        )

        safety_stock = (
            self.config.service_level_z
            * request.demand_std_dev
            * math.sqrt(lead_time)
        )

        reorder_point = (
            demand * lead_time
            + safety_stock
        )

        target_stock = (
            demand
            * (
                lead_time
                + self.config.review_period_days
            )
            + safety_stock
        )

        annual_demand = demand * 365

        if (
            annual_demand > 0
            and request.ordering_cost > 0
            and request.annual_holding_cost_per_unit > 0
        ):
            eoq = math.sqrt(
                (
                    2
                    * annual_demand
                    * request.ordering_cost
                )
                / request.annual_holding_cost_per_unit
            )
        else:
            eoq = 0.0

        stock_coverage_days = (
            available / demand
            if demand > 0
            else None
        )

        reorder_required = (
            inventory_position <= reorder_point
            and demand > 0
        )

        required_quantity = (
            max(
                0,
                math.ceil(
                    target_stock - inventory_position
                ),
            )
            if reorder_required
            else 0
        )

        if request.unit_cost > 0:
            affordable_quantity = math.floor(
                request.budget_limit
                / request.unit_cost
            )
        else:
            affordable_quantity = (
                self.config.max_order_quantity
            )

        recommended_quantity = min(
            required_quantity,
            affordable_quantity,
            self.config.max_order_quantity,
        )

        estimated_cost = (
            recommended_quantity
            * request.unit_cost
        )

        return {
            "available_stock": available,
            "inventory_position": inventory_position,
            "safety_stock": round(
                safety_stock, 3
            ),
            "reorder_point": round(
                reorder_point, 3
            ),
            "target_stock": round(
                target_stock, 3
            ),
            "economic_order_quantity": round(
                eoq, 3
            ),
            "stock_coverage_days": (
                round(stock_coverage_days, 3)
                if stock_coverage_days is not None
                else None
            ),
            "reorder_required": reorder_required,
            "required_quantity": required_quantity,
            "recommended_quantity": (
                recommended_quantity
            ),
            "estimated_cost": round(
                estimated_cost, 2
            ),
            "budget_constrained": (
                recommended_quantity
                < required_quantity
            ),
            "currency": request.currency,
        }

    def _audit(
        self,
        request_id: str,
        action: str,
        actor: str,
    ) -> None:
        self.db.execute(
            """
            INSERT INTO replenishment_audit (
                audit_id, request_id,
                action, actor, created_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                uuid.uuid4().hex,
                request_id,
                action,
                actor,
                iso_now(),
            ),
        )

    def enqueue(
        self,
        request: ReplenishmentRequest,
    ) -> dict:
        self.validate_request(request)

        with self.db:
            cursor = self.db.execute(
                """
                INSERT OR IGNORE INTO replenishment_jobs (
                    request_id, request_json,
                    status, next_attempt_at,
                    created_at
                )
                VALUES (?, ?, 'pending', ?, ?)
                """,
                (
                    request.request_id,
                    json.dumps(request.__dict__),
                    iso_now(),
                    iso_now(),
                ),
            )

            if cursor.rowcount:
                self._audit(
                    request.request_id,
                    "enqueued",
                    "system",
                )

        return {
            "request_id": request.request_id,
            "created": cursor.rowcount == 1,
        }

    def _claim_next(self) -> dict | None:
        now = utc_now()

        self.db.execute("BEGIN IMMEDIATE")

        try:
            row = self.db.execute(
                """
                SELECT *
                FROM replenishment_jobs
                WHERE (
                    status IN ('pending', 'retry')
                    AND next_attempt_at <= ?
                )
                OR (
                    status = 'processing'
                    AND lease_until <= ?
                )
                ORDER BY created_at
                LIMIT 1
                """,
                (
                    now.isoformat(),
                    now.isoformat(),
                ),
            ).fetchone()

            if row is None:
                self.db.commit()
                return None

            lease_until = (
                now + timedelta(
                    seconds=self.config.lease_seconds
                )
            ).isoformat()

            self.db.execute(
                """
                UPDATE replenishment_jobs
                SET status = 'processing',
                    attempts = attempts + 1,
                    lease_until = ?
                WHERE request_id = ?
                """,
                (
                    lease_until,
                    row["request_id"],
                ),
            )

            self.db.commit()
            return dict(row)

        except Exception:
            self.db.rollback()
            raise

    def process_one(self) -> dict | None:
        job = self._claim_next()

        if job is None:
            return None

        request_id = job["request_id"]
        attempt = job["attempts"] + 1

        try:
            request = ReplenishmentRequest(
                **json.loads(job["request_json"])
            )

            metrics = self.calculate_metrics(
                request
            )

            proposal_id = (
                f"PO-PROPOSAL-{request_id}"
            )

            with self.db:
                if metrics["reorder_required"]:
                    self.db.execute(
                        """
                        INSERT OR IGNORE INTO purchase_proposals (
                            proposal_id, request_id,
                            store_id, warehouse_id,
                            sku, supplier_id,
                            recommended_quantity,
                            estimated_cost, currency,
                            metrics_json, status,
                            created_at
                        )
                        VALUES (
                            ?, ?, ?, ?, ?, ?, ?, ?, ?,
                            ?, 'pending_approval', ?
                        )
                        """,
                        (
                            proposal_id,
                            request_id,
                            request.store_id,
                            request.warehouse_id,
                            request.sku,
                            request.supplier_id,
                            metrics["recommended_quantity"],
                            metrics["estimated_cost"],
                            request.currency,
                            json.dumps(metrics),
                            iso_now(),
                        ),
                    )

                self.db.execute(
                    """
                    UPDATE replenishment_jobs
                    SET status = 'completed',
                        completed_at = ?,
                        lease_until = NULL,
                        last_error = NULL
                    WHERE request_id = ?
                    """,
                    (
                        iso_now(),
                        request_id,
                    ),
                )

                self._audit(
                    request_id,
                    "processed",
                    "worker",
                )

            return {
                "request_id": request_id,
                "status": "completed",
                "proposal_id": (
                    proposal_id
                    if metrics["reorder_required"]
                    else None
                ),
                "metrics": metrics,
            }

        except Exception as exc:
            if attempt >= self.config.max_attempts:
                status = "dead_letter"
                next_time = utc_now()
            else:
                status = "retry"
                next_time = (
                    utc_now()
                    + timedelta(
                        seconds=min(
                            self.config.retry_base_seconds
                            * 2 ** (attempt - 1),
                            3600,
                        )
                    )
                )

            with self.db:
                self.db.execute(
                    """
                    UPDATE replenishment_jobs
                    SET status = ?,
                        next_attempt_at = ?,
                        lease_until = NULL,
                        last_error = ?
                    WHERE request_id = ?
                    """,
                    (
                        status,
                        next_time.isoformat(),
                        type(exc).__name__,
                        request_id,
                    ),
                )

            return {
                "request_id": request_id,
                "status": status,
                "error_type": type(exc).__name__,
            }

    def approve_proposal(
        self,
        proposal_id: str,
        approved_by: str,
        authorization_verified: bool,
    ) -> dict:
        # The caller must verify permissions
        # using the backend authorization system.
        if not authorization_verified:
            raise PermissionError(
                "Verified authorization required"
            )

        if not approved_by.strip():
            raise ValueError("Approver required")

        with self.db:
            cursor = self.db.execute(
                """
                UPDATE purchase_proposals
                SET status = 'approved',
                    approved_by = ?,
                    approved_at = ?
                WHERE proposal_id = ?
                  AND status = 'pending_approval'
                """,
                (
                    approved_by,
                    iso_now(),
                    proposal_id,
                ),
            )

            if cursor.rowcount:
                row = self.db.execute(
                    """
                    SELECT request_id
                    FROM purchase_proposals
                    WHERE proposal_id = ?
                    """,
                    (proposal_id,),
                ).fetchone()

                self._audit(
                    row["request_id"],
                    "proposal_approved",
                    approved_by,
                )

        if not cursor.rowcount:
            raise ValueError(
                "Proposal not found or not pending"
            )

        return {
            "proposal_id": proposal_id,
            "status": "approved",
            "purchase_order_submitted": False,
        }

    def list_proposals(
        self,
        status: str | None = None,
    ) -> list[dict]:
        if status is None:
            rows = self.db.execute(
                """
                SELECT *
                FROM purchase_proposals
                ORDER BY created_at DESC
                """
            ).fetchall()
        else:
            rows = self.db.execute(
                """
                SELECT *
                FROM purchase_proposals
                WHERE status = ?
                ORDER BY created_at DESC
                """,
                (status,),
            ).fetchall()

        result = []

        for row in rows:
            item = dict(row)
            item["metrics"] = json.loads(
                item.pop("metrics_json")
            )
            result.append(item)

        return result

    def close(self) -> None:
        self.db.close()


if __name__ == "__main__":
    worker = ReplenishmentWorker()

    request = ReplenishmentRequest(
        request_id="replenishment-001",
        store_id="STORE-KOCHI-01",
        warehouse_id="WH-KOCHI",
        sku="SKU-101",
        supplier_id="SUP-001",
        on_hand=40,
        reserved=15,
        on_order=10,
        average_daily_demand=12,
        demand_std_dev=3.5,
        lead_time_days=5,
        unit_cost=150,
        ordering_cost=500,
        annual_holding_cost_per_unit=20,
        budget_limit=50000,
    )

    print(worker.enqueue(request))

    print(
        json.dumps(
            worker.process_one(),
            indent=2,
        )
    )

    print(
        json.dumps(
            worker.list_proposals(),
            indent=2,
        )
    )

    worker.close()
