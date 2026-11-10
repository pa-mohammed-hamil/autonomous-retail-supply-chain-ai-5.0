from __future__ import annotations

"""Planned module: pos adapter. Implementation pending."""

"""
backend/integrations/pos_adapter.py

Autonomous Retail Supply Chain AI 5.0

Python 3.10+
Dependency: httpx

Provider-neutral Point-of-Sale integration.

Features:
- POS sales and returns ingestion
- Configurable REST endpoints and field mappings
- Tenant-scoped connections
- Bearer token authentication
- Decimal financial calculations
- UTC timestamp normalization
- Atomic deduplication interface
- Cursor-based pagination
- Structured synchronization results
- Async-compatible execution
- Injectable HTTP and persistence interfaces

No real POS provider is integrated by default.
"""


import asyncio
import hashlib
import json
import logging
import re

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Mapping, Protocol
from urllib.parse import urlsplit

import httpx


logger = logging.getLogger(__name__)


class POSError(ValueError):
    pass


class POSTransactionType(str, Enum):
    SALE = "sale"
    RETURN = "return"


class POSSyncStatus(str, Enum):
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


@dataclass(frozen=True)
class POSConnectionConfig:
    tenant_id: str
    connection_id: str
    base_url: str
    access_token: str
    enabled: bool = True
    timeout_seconds: float = 15.0
    max_pages: int = 20

    def __post_init__(self) -> None:
        for name in (
            "tenant_id",
            "connection_id",
            "access_token",
        ):
            value = getattr(self, name)

            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} is required")

        parsed = urlsplit(self.base_url)

        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.port not in (None, 443)
        ):
            raise ValueError(
                "POS base URL must use HTTPS"
            )

        if self.timeout_seconds <= 0:
            raise ValueError(
                "Timeout must be positive"
            )

        if not 1 <= self.max_pages <= 100:
            raise ValueError(
                "max_pages must be between 1 and 100"
            )


@dataclass(frozen=True)
class POSFieldMapping:
    endpoint: str = "/transactions"
    items_field: str = "items"
    next_cursor_field: str = "next_cursor"

    transaction_id: str = "transaction_id"
    store_id: str = "store_id"
    occurred_at: str = "occurred_at"
    transaction_type: str = "type"
    currency: str = "currency"
    items: str = "lines"

    line_id: str = "line_id"
    sku: str = "sku"
    quantity: str = "quantity"
    unit_price: str = "unit_price"
    discount: str = "discount"
    tax: str = "tax"

    def __post_init__(self) -> None:
        if not re.fullmatch(
            r"/[A-Za-z0-9/_-]+",
            self.endpoint,
        ):
            raise ValueError(
                "Invalid POS endpoint"
            )


@dataclass(frozen=True)
class POSLineItem:
    line_id: str
    sku: str
    quantity: Decimal
    unit_price: Decimal
    discount: Decimal
    tax: Decimal
    line_total: Decimal


@dataclass(frozen=True)
class POSTransaction:
    tenant_id: str
    connection_id: str
    transaction_id: str
    store_id: str
    transaction_type: POSTransactionType
    occurred_at: datetime
    currency: str
    lines: tuple[POSLineItem, ...]
    total: Decimal
    fingerprint: str


@dataclass(frozen=True)
class POSSyncResult:
    tenant_id: str
    connection_id: str
    status: POSSyncStatus
    fetched: int
    imported: int
    duplicates: int
    rejected: int
    pages_processed: int
    next_cursor: str | None
    retryable: bool
    errors: tuple[str, ...] = ()


class POSConnectionRepository(Protocol):
    def get_connection(
        self,
        *,
        tenant_id: str,
        connection_id: str,
    ) -> POSConnectionConfig | None:
        ...


class POSTransactionRepository(Protocol):
    """
    Must enforce uniqueness atomically on:
    (tenant_id, fingerprint).
    """

    def insert_if_absent(
        self,
        transaction: POSTransaction,
    ) -> bool:
        ...


class POSHTTPTransport(Protocol):
    def get(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        params: Mapping[str, str],
        timeout: float,
    ) -> httpx.Response:
        ...


class HTTPXPOSTransport:
    def get(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        params: Mapping[str, str],
        timeout: float,
    ) -> httpx.Response:
        with httpx.Client(
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            return client.get(
                url,
                headers=dict(headers),
                params=dict(params),
            )


class POSNormalizer:
    @staticmethod
    def identifier(
        value: Any,
        name: str,
    ) -> str:
        if isinstance(value, bool) or not isinstance(
            value, (str, int)
        ):
            raise POSError(
                f"Invalid {name}"
            )

        result = str(value).strip()

        if not 1 <= len(result) <= 128:
            raise POSError(
                f"Invalid {name} length"
            )

        return result

    @staticmethod
    def decimal(
        value: Any,
        name: str,
        *,
        allow_zero: bool = True,
    ) -> Decimal:
        if isinstance(value, bool):
            raise POSError(
                f"Invalid {name}"
            )

        try:
            number = Decimal(str(value))
        except (InvalidOperation, ValueError):
            raise POSError(
                f"Invalid {name}"
            ) from None

        if not number.is_finite():
            raise POSError(
                f"Non-finite {name}"
            )

        if number < 0 or (
            not allow_zero and number == 0
        ):
            raise POSError(
                f"Invalid {name} value"
            )

        return number

    @staticmethod
    def timestamp(
        value: Any,
    ) -> datetime:
        if not isinstance(value, str):
            raise POSError(
                "Timestamp must be an ISO string"
            )

        try:
            result = datetime.fromisoformat(
                value.replace("Z", "+00:00")
            )
        except ValueError:
            raise POSError(
                "Invalid timestamp"
            ) from None

        if (
            result.tzinfo is None
            or result.utcoffset() is None
        ):
            raise POSError(
                "Timestamp must include timezone"
            )

        return result.astimezone(
            timezone.utc
        )


class RetailPOSAdapter:
    def __init__(
        self,
        *,
        connection_repository: POSConnectionRepository,
        transaction_repository: POSTransactionRepository,
        mappings: Mapping[str, POSFieldMapping],
        transport: POSHTTPTransport | None = None,
    ) -> None:
        self.connections = connection_repository
        self.transactions = transaction_repository
        self.mappings = dict(mappings)
        self.transport = (
            transport or HTTPXPOSTransport()
        )

    @staticmethod
    def _fingerprint(
        tenant_id: str,
        connection_id: str,
        transaction_id: str,
    ) -> str:
        identity = json.dumps(
            {
                "tenant_id": tenant_id,
                "connection_id": connection_id,
                "transaction_id": transaction_id,
            },
            sort_keys=True,
            separators=(",", ":"),
        )

        return hashlib.sha256(
            identity.encode("utf-8")
        ).hexdigest()

    def normalize(
        self,
        *,
        tenant_id: str,
        connection_id: str,
        raw: Mapping[str, Any],
        mapping: POSFieldMapping,
    ) -> POSTransaction:
        transaction_id = POSNormalizer.identifier(
            raw.get(mapping.transaction_id),
            "transaction_id",
        )

        store_id = POSNormalizer.identifier(
            raw.get(mapping.store_id),
            "store_id",
        )

        try:
            transaction_type = POSTransactionType(
                str(
                    raw.get(mapping.transaction_type)
                ).lower()
            )
        except ValueError:
            raise POSError(
                "Unsupported transaction type"
            ) from None

        occurred_at = POSNormalizer.timestamp(
            raw.get(mapping.occurred_at)
        )

        currency = str(
            raw.get(mapping.currency, "")
        ).upper()

        if not re.fullmatch(r"[A-Z]{3}", currency):
            raise POSError(
                "Invalid currency code"
            )

        raw_lines = raw.get(mapping.items)

        if (
            not isinstance(raw_lines, list)
            or not raw_lines
        ):
            raise POSError(
                "Transaction requires line items"
            )

        lines: list[POSLineItem] = []
        seen_line_ids: set[str] = set()
        total = Decimal("0")

        for raw_line in raw_lines:
            if not isinstance(raw_line, dict):
                raise POSError(
                    "Invalid line item"
                )

            line_id = POSNormalizer.identifier(
                raw_line.get(mapping.line_id),
                "line_id",
            )

            if line_id in seen_line_ids:
                raise POSError(
                    "Duplicate line_id"
                )

            seen_line_ids.add(line_id)

            sku = POSNormalizer.identifier(
                raw_line.get(mapping.sku),
                "sku",
            )

            quantity = POSNormalizer.decimal(
                raw_line.get(mapping.quantity),
                "quantity",
                allow_zero=False,
            )

            unit_price = POSNormalizer.decimal(
                raw_line.get(mapping.unit_price),
                "unit_price",
            )

            discount = POSNormalizer.decimal(
                raw_line.get(mapping.discount, 0),
                "discount",
            )

            tax = POSNormalizer.decimal(
                raw_line.get(mapping.tax, 0),
                "tax",
            )

            gross = quantity * unit_price

            if discount > gross:
                raise POSError(
                    "Discount exceeds gross amount"
                )

            line_total = (
                gross - discount + tax
            )

            total += line_total

            lines.append(
                POSLineItem(
                    line_id=line_id,
                    sku=sku,
                    quantity=quantity,
                    unit_price=unit_price,
                    discount=discount,
                    tax=tax,
                    line_total=line_total,
                )
            )

        # Return amounts are represented as
        # negative net revenue, while line
        # quantities remain positive.
        if transaction_type == POSTransactionType.RETURN:
            total = -total

        return POSTransaction(
            tenant_id=tenant_id,
            connection_id=connection_id,
            transaction_id=transaction_id,
            store_id=store_id,
            transaction_type=transaction_type,
            occurred_at=occurred_at,
            currency=currency,
            lines=tuple(lines),
            total=total,
            fingerprint=self._fingerprint(
                tenant_id,
                connection_id,
                transaction_id,
            ),
        )

    def synchronize(
        self,
        *,
        tenant_id: str,
        connection_id: str,
        cursor: str | None = None,
    ) -> POSSyncResult:
        config = self.connections.get_connection(
            tenant_id=tenant_id,
            connection_id=connection_id,
        )

        if config is None:
            raise PermissionError(
                "POS connection not found"
            )

        if (
            config.tenant_id != tenant_id
            or config.connection_id != connection_id
        ):
            raise PermissionError(
                "POS connection scope mismatch"
            )

        if not config.enabled:
            raise PermissionError(
                "POS connection disabled"
            )

        mapping = self.mappings.get(
            connection_id
        )

        if mapping is None:
            raise POSError(
                "POS mapping missing"
            )

        url = (
            config.base_url.rstrip("/")
            + mapping.endpoint
        )

        headers = {
            "Authorization": (
                f"Bearer {config.access_token}"
            ),
            "Accept": "application/json",
        }

        fetched = 0
        imported = 0
        duplicates = 0
        rejected = 0
        pages_processed = 0
        retryable = False
        errors: list[str] = []
        seen_cursors: set[str] = set()

        next_cursor = cursor

        for _ in range(config.max_pages):
            params: dict[str, str] = {}

            if next_cursor:
                params["cursor"] = next_cursor

            try:
                response = self.transport.get(
                    url=url,
                    headers=headers,
                    params=params,
                    timeout=config.timeout_seconds,
                )

            except (
                httpx.TimeoutException,
                httpx.TransportError,
            ):
                retryable = True
                errors.append(
                    "POS transport failure"
                )
                break

            if response.status_code != 200:
                code = response.status_code

                retryable = (
                    code in (408, 425, 429)
                    or 500 <= code < 600
                )

                errors.append(
                    f"POS HTTP {code}"
                )
                break

            try:
                body = response.json()
            except ValueError:
                errors.append(
                    "Invalid POS JSON response"
                )
                break

            if not isinstance(body, dict):
                errors.append(
                    "POS response must be an object"
                )
                break

            items = body.get(
                mapping.items_field
            )

            if not isinstance(items, list):
                errors.append(
                    "POS items must be a list"
                )
                break

            pages_processed += 1

            page_failed = False

            for index, raw in enumerate(items):
                fetched += 1

                if not isinstance(raw, dict):
                    rejected += 1
                    errors.append(
                        f"Invalid transaction at index {index}"
                    )
                    page_failed = True
                    continue

                try:
                    transaction = self.normalize(
                        tenant_id=tenant_id,
                        connection_id=connection_id,
                        raw=raw,
                        mapping=mapping,
                    )

                    inserted = (
                        self.transactions.insert_if_absent(
                            transaction
                        )
                    )

                    if inserted:
                        imported += 1
                    else:
                        duplicates += 1

                except POSError as exc:
                    rejected += 1
                    page_failed = True
                    errors.append(
                        f"Transaction {index}: {exc}"
                    )

            # A page containing rejected records
            # should not advance the checkpoint
            # without a dead-letter/replay policy.
            if page_failed:
                break

            incoming_cursor = body.get(
                mapping.next_cursor_field
            )

            if incoming_cursor is None or incoming_cursor == "":
                next_cursor = None
                break

            if not isinstance(
                incoming_cursor, (str, int)
            ):
                errors.append(
                    "Invalid POS cursor"
                )
                break

            candidate = str(incoming_cursor)

            if (
                candidate == next_cursor
                or candidate in seen_cursors
            ):
                errors.append(
                    "Repeated POS cursor"
                )
                break

            seen_cursors.add(candidate)
            next_cursor = candidate

        if errors:
            status = (
                POSSyncStatus.PARTIAL
                if pages_processed
                else POSSyncStatus.FAILED
            )
        else:
            status = POSSyncStatus.COMPLETED

        return POSSyncResult(
            tenant_id=tenant_id,
            connection_id=connection_id,
            status=status,
            fetched=fetched,
            imported=imported,
            duplicates=duplicates,
            rejected=rejected,
            pages_processed=pages_processed,
            next_cursor=next_cursor,
            retryable=retryable,
            errors=tuple(errors),
        )

    async def synchronize_async(
        self,
        *,
        tenant_id: str,
        connection_id: str,
        cursor: str | None = None,
    ) -> POSSyncResult:
        return await asyncio.to_thread(
            self.synchronize,
            tenant_id=tenant_id,
            connection_id=connection_id,
            cursor=cursor,
        )


class InMemoryPOSConnectionRepository:
    def __init__(
        self,
        configs: list[POSConnectionConfig],
    ) -> None:
        self.configs = {
            (c.tenant_id, c.connection_id): c
            for c in configs
        }

    def get_connection(
        self,
        *,
        tenant_id: str,
        connection_id: str,
    ) -> POSConnectionConfig | None:
        return self.configs.get(
            (tenant_id, connection_id)
        )


class InMemoryPOSTransactionRepository:
    def __init__(self) -> None:
        self.transactions: dict[
            tuple[str, str],
            POSTransaction,
        ] = {}

    def insert_if_absent(
        self,
        transaction: POSTransaction,
    ) -> bool:
        key = (
            transaction.tenant_id,
            transaction.fingerprint,
        )

        if key in self.transactions:
            return False

        self.transactions[key] = transaction
        return True


if __name__ == "__main__":
    # Local normalization demonstration.
    # No external POS request is performed.

    mapping = POSFieldMapping()

    adapter = RetailPOSAdapter(
        connection_repository=(
            InMemoryPOSConnectionRepository([])
        ),
        transaction_repository=(
            InMemoryPOSTransactionRepository()
        ),
        mappings={"POS001": mapping},
    )

    transaction = adapter.normalize(
        tenant_id="retail-demo",
        connection_id="POS001",
        mapping=mapping,
        raw={
            "transaction_id": "TXN001",
            "store_id": "STORE001",
            "type": "sale",
            "occurred_at": (
                "2026-10-28T12:00:00+05:30"
            ),
            "currency": "INR",
            "lines": [
                {
                    "line_id": "L001",
                    "sku": "SKU001",
                    "quantity": "2",
                    "unit_price": "150.00",
                    "discount": "20.00",
                    "tax": "14.00",
                }
            ],
        },
    )

    print(transaction)
