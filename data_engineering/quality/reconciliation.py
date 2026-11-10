"""Planned module: dead letter queue. Implementation pending."""

"""
ai/pipelines/reconciliation.py

Retail supply-chain reconciliation engine.

Features:
- POS sales vs inventory movements
- Purchase orders vs supplier receipts
- Warehouse dispatch vs logistics shipment events
- Missing and unmatched records
- Quantity variance detection
- Duplicate business-key protection
- Decimal-safe quantity calculations
- Structured reconciliation reports

Read-only: does not modify inventory, orders,
payments, or shipment records.

Python 3.10+
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable


@dataclass(frozen=True)
class ReconciliationConfig:
    quantity_tolerance: Decimal = Decimal("0")
    fail_on_duplicate_keys: bool = True

    def __post_init__(self):
        tolerance = Reconciliation._decimal(
            self.quantity_tolerance,
            "quantity_tolerance",
        )
        if tolerance < 0:
            raise ValueError(
                "quantity_tolerance cannot be negative"
            )
        object.__setattr__(
            self, "quantity_tolerance", tolerance
        )


class Reconciliation:

    def __init__(
        self,
        config: ReconciliationConfig | None = None,
    ):
        self.config = config or ReconciliationConfig()

    @staticmethod
    def _decimal(value: Any, name: str) -> Decimal:
        if isinstance(value, bool):
            raise ValueError(f"Invalid {name}")

        try:
            number = Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError):
            raise ValueError(
                f"{name} must be numeric"
            ) from None

        if not number.is_finite():
            raise ValueError(
                f"{name} must be finite"
            )

        return number

    @staticmethod
    def _validate_rows(
        rows: list[dict],
        dataset_name: str,
    ) -> None:
        if not isinstance(rows, list):
            raise ValueError(
                f"{dataset_name} must be a list"
            )

        if any(
            not isinstance(row, dict)
            for row in rows
        ):
            raise ValueError(
                f"{dataset_name} must contain dictionaries"
            )

    @staticmethod
    def _business_key(
        row: dict,
        fields: tuple[str, ...],
    ) -> tuple:
        values = []

        for field in fields:
            value = row.get(field)

            if (
                value is None
                or isinstance(value, bool)
                or not isinstance(
                    value, (str, int)
                )
                or (
                    isinstance(value, str)
                    and not value.strip()
                )
            ):
                raise ValueError(
                    f"Missing/invalid business key: {field}"
                )

            values.append(value)

        return tuple(values)

    def _aggregate(
        self,
        rows: list[dict],
        key_fields: tuple[str, ...],
        quantity_field: str,
        dataset_name: str,
        unique_fields: tuple[str, ...] | None = None,
        allowed_types: set[str] | None = None,
        type_field: str | None = None,
    ) -> dict:
        """
        Aggregate quantities by business key.

        unique_fields identify source events/lines,
        preventing accidental double counting.
        """

        self._validate_rows(rows, dataset_name)

        quantities = defaultdict(
            lambda: Decimal("0")
        )
        seen = set()
        duplicate_keys = []

        for index, row in enumerate(rows):
            if allowed_types is not None:
                if row.get(type_field) not in allowed_types:
                    continue

            key = self._business_key(
                row, key_fields
            )

            if unique_fields:
                unique_key = self._business_key(
                    row, unique_fields
                )

                if unique_key in seen:
                    duplicate_keys.append({
                        "row_index": index,
                        "key": list(unique_key),
                    })
                    continue

                seen.add(unique_key)

            quantity = self._decimal(
                row.get(quantity_field),
                quantity_field,
            )

            if quantity < 0:
                raise ValueError(
                    f"Negative quantity in {dataset_name}"
                )

            quantities[key] += quantity

        if (
            duplicate_keys
            and self.config.fail_on_duplicate_keys
        ):
            raise ValueError(
                f"Duplicate source keys in {dataset_name}: "
                f"{duplicate_keys}"
            )

        return {
            "quantities": dict(quantities),
            "duplicate_keys": duplicate_keys,
        }

    def reconcile_quantities(
        self,
        left_rows: list[dict],
        right_rows: list[dict],
        key_fields: Iterable[str],
        left_quantity_field: str,
        right_quantity_field: str,
        left_name: str = "source",
        right_name: str = "target",
        left_unique_fields: Iterable[str] | None = None,
        right_unique_fields: Iterable[str] | None = None,
        left_types: set[str] | None = None,
        right_types: set[str] | None = None,
        left_type_field: str | None = None,
        right_type_field: str | None = None,
    ) -> dict:

        keys = tuple(key_fields)

        if not keys:
            raise ValueError(
                "At least one key field required"
            )

        left = self._aggregate(
            rows=left_rows,
            key_fields=keys,
            quantity_field=left_quantity_field,
            dataset_name=left_name,
            unique_fields=(
                tuple(left_unique_fields)
                if left_unique_fields
                else None
            ),
            allowed_types=left_types,
            type_field=left_type_field,
        )

        right = self._aggregate(
            rows=right_rows,
            key_fields=keys,
            quantity_field=right_quantity_field,
            dataset_name=right_name,
            unique_fields=(
                tuple(right_unique_fields)
                if right_unique_fields
                else None
            ),
            allowed_types=right_types,
            type_field=right_type_field,
        )

        left_map = left["quantities"]
        right_map = right["quantities"]

        all_keys = sorted(
            set(left_map) | set(right_map),
            key=lambda value: tuple(
                str(part) for part in value
            ),
        )

        matches = []
        mismatches = []

        for key in all_keys:
            source_exists = key in left_map
            target_exists = key in right_map

            source_quantity = left_map.get(
                key, Decimal("0")
            )
            target_quantity = right_map.get(
                key, Decimal("0")
            )

            variance = (
                source_quantity - target_quantity
            )

            if not source_exists:
                status = "missing_in_source"
            elif not target_exists:
                status = "missing_in_target"
            elif (
                abs(variance)
                <= self.config.quantity_tolerance
            ):
                status = "matched"
            else:
                status = "quantity_mismatch"

            result = {
                "key": {
                    field: value
                    for field, value in zip(keys, key)
                },
                "source_quantity": str(
                    source_quantity
                ),
                "target_quantity": str(
                    target_quantity
                ),
                "variance": str(variance),
                "status": status,
            }

            if status == "matched":
                matches.append(result)
            else:
                mismatches.append(result)

        total = len(all_keys)

        return {
            "reconciliation": (
                f"{left_name}_vs_{right_name}"
            ),
            "generated_at": datetime.now(
                timezone.utc
            ).isoformat(),
            "key_fields": list(keys),
            "total_keys": total,
            "matched_count": len(matches),
            "mismatch_count": len(mismatches),
            "match_rate": (
                round(len(matches) / total, 4)
                if total
                else None
            ),
            "passed": (
                not mismatches
                and not left["duplicate_keys"]
                and not right["duplicate_keys"]
            ),
            "matches": matches,
            "mismatches": mismatches,
            "duplicate_source_keys": (
                left["duplicate_keys"]
            ),
            "duplicate_target_keys": (
                right["duplicate_keys"]
            ),
            "requires_human_review": bool(
                mismatches
                or left["duplicate_keys"]
                or right["duplicate_keys"]
            ),
            "records_modified": False,
        }

    def sales_vs_inventory(
        self,
        sales: list[dict],
        movements: list[dict],
    ) -> dict:
        """
        Expected schemas:

        Sales:
          store_id, sku, quantity,
          transaction_type, transaction_id, line_id

        Movements:
          store_id, sku, quantity_delta,
          movement_type, event_id

        Compare net sold units against net stock
        depletion. Assumes movement events are
        already scoped to the same time period.

        For returns, positive stock restoration
        is assumed; damaged returns require
        separate handling.
        """

        normalized_sales = []

        for row in sales:
            kind = row["transaction_type"]

            if kind not in {"sale", "return"}:
                raise ValueError(
                    "Unsupported POS transaction type"
                )

            quantity = self._decimal(
                row["quantity"], "quantity"
            )

            if quantity <= 0:
                raise ValueError(
                    "POS quantity must be positive"
                )

            normalized_sales.append({
                **row,
                "reconciliation_quantity": (
                    quantity
                    if kind == "sale"
                    else -quantity
                ),
            })

        normalized_movements = []

        for row in movements:
            if row["movement_type"] not in {
                "sale",
                "customer_return",
            }:
                continue

            delta = self._decimal(
                row["quantity_delta"],
                "quantity_delta",
            )

            normalized_movements.append({
                **row,
                "reconciliation_quantity": -delta,
            })

        # Signed quantities are needed here.
        # Use a separate signed reconciliation path.
        return self._reconcile_signed(
            normalized_sales,
            normalized_movements,
            keys=("store_id", "sku"),
            left_quantity="reconciliation_quantity",
            right_quantity="reconciliation_quantity",
            left_unique=("store_id", "transaction_id", "line_id"),
            right_unique=("event_id",),
            name="sales_vs_inventory",
        )

    def _reconcile_signed(
        self,
        left_rows: list[dict],
        right_rows: list[dict],
        keys: tuple[str, ...],
        left_quantity: str,
        right_quantity: str,
        left_unique: tuple[str, ...],
        right_unique: tuple[str, ...],
        name: str,
    ) -> dict:

        def aggregate(
            rows: list[dict],
            quantity_field: str,
            unique_fields: tuple[str, ...],
        ) -> dict:
            totals = defaultdict(
                lambda: Decimal("0")
            )
            seen = set()

            for row in rows:
                unique_key = self._business_key(
                    row, unique_fields
                )

                if unique_key in seen:
                    raise ValueError(
                        f"Duplicate event: {unique_key}"
                    )

                seen.add(unique_key)

                key = self._business_key(
                    row, keys
                )

                totals[key] += self._decimal(
                    row[quantity_field],
                    quantity_field,
                )

            return dict(totals)

        left_map = aggregate(
            left_rows, left_quantity, left_unique
        )
        right_map = aggregate(
            right_rows, right_quantity, right_unique
        )

        matches = []
        mismatches = []

        for key in sorted(
            set(left_map) | set(right_map)
        ):
            left_exists = key in left_map
            right_exists = key in right_map

            left_value = left_map.get(
                key, Decimal("0")
            )
            right_value = right_map.get(
                key, Decimal("0")
            )

            variance = left_value - right_value

            if not left_exists:
                status = "missing_in_source"
            elif not right_exists:
                status = "missing_in_target"
            elif (
                abs(variance)
                <= self.config.quantity_tolerance
            ):
                status = "matched"
            else:
                status = "quantity_mismatch"

            item = {
                "key": dict(zip(keys, key)),
                "source_quantity": str(left_value),
                "target_quantity": str(right_value),
                "variance": str(variance),
                "status": status,
            }

            (
                matches
                if status == "matched"
                else mismatches
            ).append(item)

        return {
            "reconciliation": name,
            "matched_count": len(matches),
            "mismatch_count": len(mismatches),
            "matches": matches,
            "mismatches": mismatches,
            "passed": not mismatches,
            "requires_human_review": bool(mismatches),
            "records_modified": False,
        }

    def purchase_orders_vs_receipts(
        self,
        purchase_orders: list[dict],
        receipts: list[dict],
    ) -> dict:
        return self.reconcile_quantities(
            left_rows=purchase_orders,
            right_rows=receipts,
            key_fields=(
                "purchase_order_id",
                "sku",
            ),
            left_quantity_field="ordered_quantity",
            right_quantity_field="received_quantity",
            left_name="purchase_orders",
            right_name="receipts",
            left_unique_fields=(
                "purchase_order_id",
                "line_id",
            ),
            right_unique_fields=(
                "receipt_id",
            ),
        )

    def warehouse_vs_logistics(
        self,
        warehouse_dispatches: list[dict],
        shipment_events: list[dict],
    ) -> dict:
        """
        Shipment events must represent dispatched
        quantities, not repeated status updates.
        """

        return self.reconcile_quantities(
            left_rows=warehouse_dispatches,
            right_rows=shipment_events,
            key_fields=(
                "shipment_id",
                "sku",
            ),
            left_quantity_field="dispatched_quantity",
            right_quantity_field="shipped_quantity",
            left_name="warehouse_dispatch",
            right_name="logistics_dispatch",
            left_unique_fields=("dispatch_id",),
            right_unique_fields=("event_id",),
            right_types={"dispatched"},
            right_type_field="event_type",
        )


if __name__ == "__main__":
    import json

    engine = Reconciliation()

    purchase_orders = [
        {
            "purchase_order_id": "PO-101",
            "line_id": "1",
            "sku": "SKU-101",
            "ordered_quantity": 100,
        },
        {
            "purchase_order_id": "PO-102",
            "line_id": "1",
            "sku": "SKU-202",
            "ordered_quantity": 50,
        },
    ]

    receipts = [
        {
            "receipt_id": "REC-001",
            "purchase_order_id": "PO-101",
            "sku": "SKU-101",
            "received_quantity": 100,
        },
        {
            "receipt_id": "REC-002",
            "purchase_order_id": "PO-102",
            "sku": "SKU-202",
            "received_quantity": 45,
        },
    ]

    report = engine.purchase_orders_vs_receipts(
        purchase_orders,
        receipts,
    )

    print(json.dumps(report, indent=2))
