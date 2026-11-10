from __future__ import annotations

"""Planned module: common. Implementation pending."""

"""
Autonomous Retail Supply Chain AI 5.0
backend/common.py

Shared backend utilities.

Python 3.10+
Standard library only.

Includes:
- Application exceptions
- Input validation
- UTC timestamps
- Date parsing
- Decimal/money handling
- Secure identifiers and hashing
- JSON serialization
- Pagination
- Audit metadata
- Tenant validation
"""


import hashlib
import hmac
import json
import math
import re
import secrets
import uuid

from dataclasses import (
    asdict,
    dataclass,
    is_dataclass,
)
from datetime import (
    date,
    datetime,
    timezone,
)
from decimal import (
    Decimal,
    InvalidOperation,
    ROUND_HALF_UP,
)
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, TypeVar


# -----------------------------------
# Application exceptions
# -----------------------------------

class RetailError(Exception):
    """Base application error."""


class ValidationError(RetailError):
    """Invalid input data."""


class AuthenticationError(RetailError):
    """Authentication failed."""


class AuthorizationError(RetailError):
    """Permission denied."""


class ResourceNotFoundError(RetailError):
    """Requested resource does not exist."""


class ConflictError(RetailError):
    """Resource or version conflict."""


class BusinessRuleError(RetailError):
    """Business rule violation."""


class IntegrationError(RetailError):
    """External integration failed."""


# -----------------------------------
# Time utilities
# -----------------------------------

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_timestamp() -> str:
    return utc_now().isoformat()


def parse_datetime(
    value: str,
) -> datetime:
    try:
        parsed = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )
    except (ValueError, AttributeError) as exc:
        raise ValidationError(
            "Invalid ISO datetime"
        ) from exc

    if parsed.tzinfo is None:
        raise ValidationError(
            "Timezone-aware datetime required"
        )

    return parsed.astimezone(
        timezone.utc
    )


def parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError) as exc:
        raise ValidationError(
            "Invalid ISO date"
        ) from exc


def is_expired(
    expiry: str,
) -> bool:
    return utc_now() >= parse_datetime(
        expiry
    )


# -----------------------------------
# Text validation
# -----------------------------------

def required_text(
    value: str,
    field_name: str,
    max_length: int = 255,
) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > max_length
    ):
        raise ValidationError(
            f"Invalid {field_name}"
        )

    return value.strip()


def optional_text(
    value: str | None,
    field_name: str,
    max_length: int = 255,
) -> str | None:
    if value is None:
        return None

    return required_text(
        value,
        field_name,
        max_length,
    )


def normalize_email(
    email: str,
) -> str:
    email = required_text(
        email,
        "email",
        254,
    ).lower()

    pattern = (
        r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
    )

    if not re.fullmatch(
        pattern,
        email,
    ):
        raise ValidationError(
            "Invalid email address"
        )

    return email


def validate_sku(
    sku: str,
) -> str:
    sku = required_text(
        sku,
        "sku",
        100,
    ).upper()

    if not re.fullmatch(
        r"[A-Z0-9_-]+",
        sku,
    ):
        raise ValidationError(
            "Invalid SKU format"
        )

    return sku


# -----------------------------------
# Numeric validation
# -----------------------------------

def nonnegative_int(
    value: int,
    field_name: str,
) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
    ):
        raise ValidationError(
            f"{field_name} must be "
            "a nonnegative integer"
        )

    return value


def positive_int(
    value: int,
    field_name: str,
) -> int:
    result = nonnegative_int(
        value,
        field_name,
    )

    if result == 0:
        raise ValidationError(
            f"{field_name} must be positive"
        )

    return result


def finite_number(
    value: int | float,
    field_name: str,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(
            value,
            (int, float),
        )
    ):
        raise ValidationError(
            f"Invalid {field_name}"
        )

    result = float(value)

    if not math.isfinite(result):
        raise ValidationError(
            f"{field_name} must be finite"
        )

    if (
        minimum is not None
        and result < minimum
    ):
        raise ValidationError(
            f"{field_name} below minimum"
        )

    if (
        maximum is not None
        and result > maximum
    ):
        raise ValidationError(
            f"{field_name} above maximum"
        )

    return result


def percentage(
    value: int | float,
    field_name: str = "percentage",
) -> float:
    return finite_number(
        value,
        field_name,
        minimum=0,
        maximum=100,
    )


def safe_percentage(
    numerator: int | float,
    denominator: int | float,
) -> float | None:
    numerator = finite_number(
        numerator,
        "numerator",
    )

    denominator = finite_number(
        denominator,
        "denominator",
        minimum=0,
    )

    if denominator == 0:
        return None

    return round(
        numerator / denominator * 100,
        2,
    )


# -----------------------------------
# Money utilities
# -----------------------------------

MONEY_QUANTUM = Decimal("0.01")


def decimal_value(
    value: Any,
    field_name: str,
) -> Decimal:
    if isinstance(value, bool):
        raise ValidationError(
            f"Invalid {field_name}"
        )

    try:
        result = Decimal(
            str(value)
        )
    except (
        InvalidOperation,
        ValueError,
        TypeError,
    ) as exc:
        raise ValidationError(
            f"Invalid {field_name}"
        ) from exc

    if not result.is_finite():
        raise ValidationError(
            f"{field_name} must be finite"
        )

    return result


def money(
    value: Any,
    allow_negative: bool = False,
) -> Decimal:
    result = decimal_value(
        value,
        "money",
    )

    if (
        not allow_negative
        and result < 0
    ):
        raise ValidationError(
            "Money cannot be negative"
        )

    return result.quantize(
        MONEY_QUANTUM,
        rounding=ROUND_HALF_UP,
    )


def calculate_discount(
    amount: Any,
    discount_pct: Any,
) -> Decimal:
    base = money(amount)

    discount = decimal_value(
        discount_pct,
        "discount_pct",
    )

    if not (
        Decimal("0")
        <= discount
        <= Decimal("100")
    ):
        raise ValidationError(
            "Discount must be 0-100%"
        )

    return money(
        base * discount / Decimal("100")
    )


def calculate_tax(
    taxable_amount: Any,
    tax_pct: Any,
) -> Decimal:
    base = money(
        taxable_amount
    )

    tax = decimal_value(
        tax_pct,
        "tax_pct",
    )

    if not (
        Decimal("0")
        <= tax
        <= Decimal("100")
    ):
        raise ValidationError(
            "Tax must be 0-100%"
        )

    return money(
        base * tax / Decimal("100")
    )


# -----------------------------------
# Identity and hashing
# -----------------------------------

def generate_id(
    prefix: str = "",
) -> str:
    identifier = uuid.uuid4().hex

    if not prefix:
        return identifier

    prefix = required_text(
        prefix,
        "prefix",
        30,
    )

    if not re.fullmatch(
        r"[A-Za-z0-9_-]+",
        prefix,
    ):
        raise ValidationError(
            "Invalid ID prefix"
        )

    return f"{prefix}_{identifier}"


def generate_secure_token(
    bytes_length: int = 32,
) -> str:
    if not 16 <= bytes_length <= 128:
        raise ValidationError(
            "Token length must be 16-128 bytes"
        )

    return secrets.token_urlsafe(
        bytes_length
    )


def sha256_text(
    value: str,
) -> str:
    if not isinstance(value, str):
        raise ValidationError(
            "Expected text"
        )

    return hashlib.sha256(
        value.encode("utf-8")
    ).hexdigest()


def constant_time_equal(
    first: str,
    second: str,
) -> bool:
    return hmac.compare_digest(
        first,
        second,
    )


# -----------------------------------
# Tenant isolation
# -----------------------------------

def require_tenant(
    actor_tenant_id: str,
    resource_tenant_id: str,
) -> None:
    if (
        not actor_tenant_id
        or not resource_tenant_id
        or actor_tenant_id
        != resource_tenant_id
    ):
        raise AuthorizationError(
            "Tenant access denied"
        )


def require_role(
    actor_roles: Iterable[str],
    allowed_roles: Iterable[str],
) -> None:
    if not (
        set(actor_roles)
        & set(allowed_roles)
    ):
        raise AuthorizationError(
            "Required role missing"
        )


def require_warehouse(
    warehouse_id: str,
    allowed_warehouse_ids: Iterable[str],
    is_corporate_admin: bool = False,
) -> None:
    if is_corporate_admin:
        return

    if warehouse_id not in set(
        allowed_warehouse_ids
    ):
        raise AuthorizationError(
            "Warehouse access denied"
        )


# -----------------------------------
# JSON serialization
# -----------------------------------

def json_default(
    value: Any,
) -> Any:
    if isinstance(
        value,
        (datetime, date),
    ):
        return value.isoformat()

    if isinstance(
        value,
        Decimal,
    ):
        return str(value)

    if isinstance(
        value,
        Enum,
    ):
        return value.value

    if isinstance(
        value,
        (set, frozenset),
    ):
        return sorted(value)

    if is_dataclass(value) and not isinstance(
        value, type
    ):
        return asdict(value)

    raise TypeError(
        f"Not JSON serializable: "
        f"{type(value).__name__}"
    )


def to_json(
    data: Any,
    indent: int = 2,
) -> str:
    return json.dumps(
        data,
        default=json_default,
        indent=indent,
        allow_nan=False,
    )


def export_json(
    data: Any,
    output_path: str | Path,
) -> Path:
    path = Path(output_path)

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_text(
        to_json(data),
        encoding="utf-8",
    )

    return path


# -----------------------------------
# Pagination
# -----------------------------------

T = TypeVar("T")


@dataclass(frozen=True)
class Page:
    items: list[Any]
    page: int
    page_size: int
    total_items: int
    total_pages: int


def paginate(
    items: Iterable[T],
    page: int = 1,
    page_size: int = 20,
    max_page_size: int = 100,
) -> Page:
    positive_int(
        page,
        "page",
    )

    positive_int(
        page_size,
        "page_size",
    )

    if page_size > max_page_size:
        raise ValidationError(
            "Page size exceeds maximum"
        )

    values = list(items)
    total = len(values)

    start = (
        page - 1
    ) * page_size

    end = start + page_size

    return Page(
        items=values[start:end],
        page=page,
        page_size=page_size,
        total_items=total,
        total_pages=(
            (total + page_size - 1)
            // page_size
        ),
    )


# -----------------------------------
# Audit metadata
# -----------------------------------

@dataclass(frozen=True)
class AuditContext:
    event_id: str
    tenant_id: str
    actor_id: str
    action: str
    timestamp: str
    correlation_id: str


def create_audit_context(
    tenant_id: str,
    actor_id: str,
    action: str,
    correlation_id: str | None = None,
) -> AuditContext:
    return AuditContext(
        event_id=generate_id("evt"),
        tenant_id=required_text(
            tenant_id,
            "tenant_id",
        ),
        actor_id=required_text(
            actor_id,
            "actor_id",
        ),
        action=required_text(
            action,
            "action",
        ),
        timestamp=utc_timestamp(),
        correlation_id=(
            correlation_id
            or generate_id("corr")
        ),
    )


# -----------------------------------
# Example usage
# -----------------------------------

if __name__ == "__main__":
    sku = validate_sku(
        "sku001"
    )

    amount = money(
        "1500.50"
    )

    discount = calculate_discount(
        amount,
        "10"
    )

    tax = calculate_tax(
        amount - discount,
        "18"
    )

    total = (
        amount
        - discount
        + tax
    )

    audit = create_audit_context(
        tenant_id="demo",
        actor_id="admin001",
        action="purchase_order_created",
    )

    result = {
        "sku": sku,
        "amount": amount,
        "discount": discount,
        "tax": tax,
        "total": total,
        "audit": audit,
    }

    print(
        to_json(result)
    )
