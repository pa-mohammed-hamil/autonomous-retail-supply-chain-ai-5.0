"""Planned module: pos ingestion. Implementation pending."""

"""
ai/ingestion/pos_ingestion.py

Point-of-sale ingestion for retail analytics.

Features:
- Sales and return transaction lines
- Store and product identifiers
- Quantity, unit price, discount and tax
- UTC timestamp normalization
- CSV and JSON input
- Duplicate line detection
- Revenue and unit summaries

Does not charge customers, issue refunds,
or update inventory.
"""

from __future__ import annotations

import csv
import io
import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation


def required_text(row: dict, key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Invalid {key}")
    return value.strip()


def parse_money(row: dict, key: str) -> Decimal:
    value = row.get(key)

    if isinstance(value, bool) or value is None:
        raise ValueError(f"Invalid {key}")

    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid {key}") from exc

    if not amount.is_finite() or amount < 0:
        raise ValueError(f"Invalid {key}")

    if amount.as_tuple().exponent < -2:
        raise ValueError(
            f"{key} must have at most two decimal places"
        )

    return amount


def parse_timestamp(row: dict, key: str) -> str:
    value = required_text(row, key)

    try:
        dt = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise ValueError(f"Invalid {key}") from exc

    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError(
            f"{key} must include timezone"
        )

    return dt.astimezone(timezone.utc).isoformat()


@dataclass(frozen=True)
class POSRecord:
    transaction_id: str
    line_id: str
    store_id: str
    sku: str
    transaction_type: str
    quantity: int
    currency: str
    unit_price: str
    discount_amount: str
    tax_amount: str
    net_amount: str
    occurred_at: str
    original_transaction_id: str | None = None


class POSIngestion:

    TYPES = {"sale", "return"}

    def validate(self, row: dict) -> POSRecord:
        transaction_type = required_text(
            row, "transaction_type"
        ).lower()

        if transaction_type not in self.TYPES:
            raise ValueError(
                "transaction_type must be sale or return"
            )

        quantity = row.get("quantity")
        if isinstance(quantity, str):
            try:
                quantity = int(quantity)
            except ValueError:
                pass

        if (
            isinstance(quantity, bool)
            or not isinstance(quantity, int)
            or quantity <= 0
        ):
            raise ValueError(
                "quantity must be a positive integer"
            )

        currency = required_text(
            row, "currency"
        ).upper()

        if (
            len(currency) != 3
            or not currency.isascii()
            or not currency.isalpha()
        ):
            raise ValueError("Invalid currency code")

        price = parse_money(row, "unit_price")
        discount = parse_money(
            row, "discount_amount"
        )
        tax = parse_money(row, "tax_amount")

        subtotal = price * quantity

        if discount > subtotal:
            raise ValueError(
                "Discount exceeds gross amount"
            )

        net = subtotal - discount + tax

        if transaction_type == "return":
            net = -net

        original_id = row.get(
            "original_transaction_id"
        )

        if original_id is not None:
            if (
                not isinstance(original_id, str)
                or not original_id.strip()
            ):
                raise ValueError(
                    "Invalid original transaction ID"
                )
            original_id = original_id.strip()

        if (
            transaction_type == "return"
            and original_id is None
        ):
            raise ValueError(
                "Return requires original_transaction_id"
            )

        return POSRecord(
            transaction_id=required_text(
                row, "transaction_id"
            ),
            line_id=required_text(row, "line_id"),
            store_id=required_text(row, "store_id"),
            sku=required_text(row, "sku"),
            transaction_type=transaction_type,
            quantity=quantity,
            currency=currency,
            unit_price=str(price),
            discount_amount=str(discount),
            tax_amount=str(tax),
            net_amount=str(net),
            occurred_at=parse_timestamp(
                row, "occurred_at"
            ),
            original_transaction_id=original_id,
        )

    def ingest(self, rows: list[dict]) -> dict:
        if not isinstance(rows, list):
            raise ValueError("Expected list of records")

        accepted = []
        rejected = []
        seen = set()

        totals = {}

        for index, row in enumerate(rows):
            try:
                if not isinstance(row, dict):
                    raise ValueError(
                        "Row must be an object"
                    )

                record = self.validate(row)

                key = (
                    record.store_id,
                    record.transaction_id,
                    record.line_id,
                )

                if key in seen:
                    raise ValueError(
                        "Duplicate POS line in batch"
                    )

                seen.add(key)
                accepted.append(asdict(record))

                currency = record.currency
                totals.setdefault(
                    currency, Decimal("0")
                )
                totals[currency] += Decimal(
                    record.net_amount
                )

            except (
                ValueError,
                TypeError,
                InvalidOperation,
            ) as exc:
                rejected.append({
                    "row_index": index,
                    "reason": str(exc),
                })

        return {
            "total": len(rows),
            "accepted_count": len(accepted),
            "rejected_count": len(rejected),
            "records": accepted,
            "rejected": rejected,
            "net_sales_by_currency": {
                currency: str(amount)
                for currency, amount in totals.items()
            },
            "persisted": False,
            "inventory_updated": False,
            "refunds_executed": False,
        }

    def ingest_json(self, text: str) -> dict:
        return self.ingest(json.loads(text))

    def ingest_csv(self, text: str) -> dict:
        return self.ingest(
            list(csv.DictReader(io.StringIO(text)))
        )
