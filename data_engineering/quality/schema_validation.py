"""Planned module: schema validation. Implementation pending."""
"""Planned module: reconciliation. Implementation pending."""

"""
ai/pipelines/schema_validation.py

Schema validation for retail supply-chain data.

Features:
- Required and optional fields
- Strict primitive types
- Decimal-safe numeric validation
- Timezone-aware datetime validation
- Date and enum validation
- Minimum/maximum constraints
- Unknown-field detection
- Nested object and array validation
- Batch validation with row-level errors
- Reusable retail dataset schemas

Standard-library only. Python 3.10+.
No input records are modified.
"""

from __future__ import annotations

import math
import re

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any


@dataclass(frozen=True)
class FieldSpec:
    kind: str
    required: bool = True
    nullable: bool = False
    minimum: float | None = None
    maximum: float | None = None
    allowed_values: frozenset | None = None
    pattern: str | None = None
    min_length: int | None = None
    max_length: int | None = None
    fields: dict[str, "FieldSpec"] | None = None
    items: "FieldSpec | None" = None


@dataclass(frozen=True)
class SchemaSpec:
    name: str
    fields: dict[str, FieldSpec]
    allow_extra_fields: bool = False


class SchemaValidation:

    SUPPORTED_TYPES = {
        "string",
        "integer",
        "number",
        "boolean",
        "datetime",
        "date",
        "object",
        "array",
    }

    def __init__(self, schema: SchemaSpec):
        if not schema.name:
            raise ValueError("Schema name required")

        if not schema.fields:
            raise ValueError("Schema fields required")

        self.schema = schema

    @staticmethod
    def _decimal(value: Any) -> Decimal:
        if isinstance(value, bool):
            raise ValueError("Boolean is not numeric")

        try:
            number = Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError):
            raise ValueError(
                "Invalid numeric value"
            ) from None

        if not number.is_finite():
            raise ValueError(
                "Number must be finite"
            )

        return number

    @staticmethod
    def _parse_datetime(value: Any) -> datetime:
        if isinstance(value, datetime):
            dt = value

        elif isinstance(value, str):
            dt = datetime.fromisoformat(
                value.replace("Z", "+00:00")
            )

        else:
            raise ValueError(
                "Expected ISO datetime"
            )

        if dt.tzinfo is None or dt.utcoffset() is None:
            raise ValueError(
                "Datetime must include timezone"
            )

        return dt.astimezone(timezone.utc)

    @staticmethod
    def _parse_date(value: Any) -> date:
        if isinstance(value, datetime):
            raise ValueError(
                "Expected date, not datetime"
            )

        if isinstance(value, date):
            return value

        if isinstance(value, str):
            return date.fromisoformat(value)

        raise ValueError("Expected ISO date")

    def _validate_field(
        self,
        value: Any,
        spec: FieldSpec,
        path: str,
        errors: list[dict],
    ) -> None:

        if spec.kind not in self.SUPPORTED_TYPES:
            raise ValueError(
                f"Unsupported schema type: {spec.kind}"
            )

        if value is None:
            if not spec.nullable:
                errors.append({
                    "field": path,
                    "code": "NULL_NOT_ALLOWED",
                    "message": "Null value not allowed",
                })
            return

        try:
            if spec.kind == "string":
                if not isinstance(value, str):
                    raise ValueError(
                        "Expected string"
                    )

                if (
                    spec.min_length is not None
                    and len(value) < spec.min_length
                ):
                    raise ValueError(
                        "String shorter than minimum"
                    )

                if (
                    spec.max_length is not None
                    and len(value) > spec.max_length
                ):
                    raise ValueError(
                        "String longer than maximum"
                    )

                if (
                    spec.pattern is not None
                    and re.fullmatch(
                        spec.pattern, value
                    ) is None
                ):
                    raise ValueError(
                        "String does not match pattern"
                    )

            elif spec.kind == "integer":
                if (
                    isinstance(value, bool)
                    or not isinstance(value, int)
                ):
                    raise ValueError(
                        "Expected integer"
                    )

            elif spec.kind == "number":
                self._decimal(value)

            elif spec.kind == "boolean":
                if not isinstance(value, bool):
                    raise ValueError(
                        "Expected boolean"
                    )

            elif spec.kind == "datetime":
                self._parse_datetime(value)

            elif spec.kind == "date":
                self._parse_date(value)

            elif spec.kind == "object":
                if not isinstance(value, dict):
                    raise ValueError(
                        "Expected object"
                    )

                if spec.fields is not None:
                    self._validate_object(
                        value,
                        spec.fields,
                        path,
                        errors,
                        allow_extra=False,
                    )

            elif spec.kind == "array":
                if not isinstance(value, list):
                    raise ValueError(
                        "Expected array"
                    )

                if spec.items is not None:
                    for index, item in enumerate(value):
                        self._validate_field(
                            item,
                            spec.items,
                            f"{path}[{index}]",
                            errors,
                        )

            if spec.kind in {"integer", "number"}:
                number = self._decimal(value)

                if (
                    spec.minimum is not None
                    and number
                    < self._decimal(spec.minimum)
                ):
                    raise ValueError(
                        "Below minimum"
                    )

                if (
                    spec.maximum is not None
                    and number
                    > self._decimal(spec.maximum)
                ):
                    raise ValueError(
                        "Above maximum"
                    )

            if spec.allowed_values is not None:
                try:
                    allowed = (
                        value in spec.allowed_values
                    )
                except TypeError:
                    allowed = False

                if not allowed:
                    raise ValueError(
                        "Value not in allowed set"
                    )

        except (
            ValueError,
            TypeError,
            OverflowError,
        ) as exc:
            errors.append({
                "field": path,
                "code": "INVALID_FIELD",
                "message": str(exc),
            })

    def _validate_object(
        self,
        record: dict,
        fields: dict[str, FieldSpec],
        prefix: str,
        errors: list[dict],
        allow_extra: bool,
    ) -> None:

        for name, spec in fields.items():
            path = (
                f"{prefix}.{name}"
                if prefix
                else name
            )

            if name not in record:
                if spec.required:
                    errors.append({
                        "field": path,
                        "code": "MISSING_REQUIRED_FIELD",
                        "message": "Required field missing",
                    })
                continue

            self._validate_field(
                record[name],
                spec,
                path,
                errors,
            )

        if not allow_extra:
            for name in record:
                if name not in fields:
                    path = (
                        f"{prefix}.{name}"
                        if prefix
                        else name
                    )

                    errors.append({
                        "field": path,
                        "code": "UNKNOWN_FIELD",
                        "message": "Unexpected field",
                    })

    def validate_record(
        self,
        record: dict[str, Any],
    ) -> dict:

        if not isinstance(record, dict):
            return {
                "valid": False,
                "errors": [{
                    "field": "$",
                    "code": "INVALID_RECORD",
                    "message": "Expected dictionary",
                }],
            }

        errors = []

        self._validate_object(
            record=record,
            fields=self.schema.fields,
            prefix="",
            errors=errors,
            allow_extra=(
                self.schema.allow_extra_fields
            ),
        )

        return {
            "valid": not errors,
            "errors": errors,
        }

    def validate_batch(
        self,
        records: list[dict],
    ) -> dict:

        if not isinstance(records, list):
            raise ValueError(
                "records must be a list"
            )

        accepted = []
        rejected = []

        for index, record in enumerate(records):
            result = self.validate_record(record)

            if result["valid"]:
                accepted.append(dict(record))
            else:
                rejected.append({
                    "row_index": index,
                    "errors": result["errors"],
                })

        return {
            "schema": self.schema.name,
            "total": len(records),
            "accepted_count": len(accepted),
            "rejected_count": len(rejected),
            "passed": not rejected,
            "records": accepted,
            "rejected": rejected,
            "source_modified": False,
        }


def retail_schemas() -> dict[str, SchemaSpec]:
    """
    Reference schemas for normalized pipeline data.

    Adapt fields to your ingestion contracts.
    """

    nonempty = lambda: FieldSpec(
        "string",
        min_length=1,
    )

    timestamp = lambda: FieldSpec(
        "datetime",
    )

    positive_int = lambda: FieldSpec(
        "integer",
        minimum=1,
    )

    nonnegative_int = lambda: FieldSpec(
        "integer",
        minimum=0,
    )

    rate = lambda: FieldSpec(
        "number",
        minimum=0,
        maximum=1,
    )

    return {
        "pos": SchemaSpec(
            name="pos",
            fields={
                "transaction_id": nonempty(),
                "line_id": nonempty(),
                "store_id": nonempty(),
                "sku": nonempty(),
                "transaction_type": FieldSpec(
                    "string",
                    allowed_values=frozenset({
                        "sale",
                        "return",
                    }),
                ),
                "quantity": positive_int(),
                "currency": FieldSpec(
                    "string",
                    pattern=r"[A-Z]{3}",
                ),
                "unit_price": FieldSpec(
                    "number",
                    minimum=0,
                ),
                "occurred_at": timestamp(),
            },
            allow_extra_fields=True,
        ),

        "inventory_snapshot": SchemaSpec(
            name="inventory_snapshot",
            fields={
                "record_id": nonempty(),
                "sku": nonempty(),
                "warehouse_id": nonempty(),
                "on_hand": nonnegative_int(),
                "reserved": nonnegative_int(),
                "updated_at": timestamp(),
            },
            allow_extra_fields=True,
        ),

        "supplier": SchemaSpec(
            name="supplier",
            fields={
                "supplier_id": nonempty(),
                "sku": nonempty(),
                "on_time_rate": rate(),
                "quality_rate": rate(),
                "lead_time_days": FieldSpec(
                    "number",
                    minimum=0,
                ),
                "available_capacity": nonnegative_int(),
                "observed_at": timestamp(),
            },
            allow_extra_fields=True,
        ),

        "feedback": SchemaSpec(
            name="feedback",
            fields={
                "feedback_id": nonempty(),
                "product_id": nonempty(),
                "rating": FieldSpec(
                    "integer",
                    minimum=1,
                    maximum=5,
                ),
                "review_text": FieldSpec(
                    "string",
                    required=False,
                ),
                "created_at": timestamp(),
            },
            allow_extra_fields=True,
        ),

        "shipment_event": SchemaSpec(
            name="shipment_event",
            fields={
                "event_id": nonempty(),
                "shipment_id": nonempty(),
                "vehicle_id": nonempty(),
                "event_type": nonempty(),
                "occurred_at": timestamp(),
            },
            allow_extra_fields=True,
        ),
    }


if __name__ == "__main__":
    import json

    schemas = retail_schemas()

    validator = SchemaValidation(
        schemas["pos"]
    )

    records = [
        {
            "transaction_id": "TXN-001",
            "line_id": "1",
            "store_id": "STORE-KOCHI",
            "sku": "SKU-101",
            "transaction_type": "sale",
            "quantity": 5,
            "currency": "INR",
            "unit_price": "250.00",
            "occurred_at": (
                "2026-10-25T10:00:00+05:30"
            ),
        },
        {
            "transaction_id": "TXN-002",
            "line_id": "1",
            "store_id": "STORE-KOCHI",
            "sku": "SKU-202",
            "transaction_type": "sale",
            "quantity": -3,
            "currency": "INR",
            "unit_price": "100.00",
            "occurred_at": (
                "2026-10-25T11:00:00+05:30"
            ),
        },
    ]

    report = validator.validate_batch(records)

    print(json.dumps(report, indent=2))
