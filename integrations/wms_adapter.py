from __future__ import annotations

"""Planned module: wms adapter. Implementation pending."""

"""
backend/integrations/wms_adapter.py

Autonomous Retail Supply Chain AI 5.0

Python 3.10+
Dependency: httpx

Provider-neutral WMS REST adapter.

Features:
- Warehouse inventory retrieval
- Bin-level inventory normalization
- Inbound receipt submission
- Stock transfer submission
- Fulfillment status retrieval
- Tenant-scoped WMS connections
- Bearer-token authentication
- Read-only / write-enabled modes
- Decimal stock quantity validation
- Idempotency-key propagation
- Structured HTTP error classification
- Async-compatible execution
- Injectable HTTP transport

Provider-specific endpoint mappings are
required for real WMS integrations.
"""


import asyncio
import logging
import re

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Mapping, Protocol
from urllib.parse import quote, urlsplit

import httpx


logger = logging.getLogger(__name__)

SAFE_ID = re.compile(
    r"^[A-Za-z0-9_-]{1,128}$"
)


class WMSError(ValueError):
    pass


class WMSOperation(str, Enum):
    GET_INVENTORY = "get_inventory"
    GET_BIN_STOCK = "get_bin_stock"
    RECEIVE_STOCK = "receive_stock"
    TRANSFER_STOCK = "transfer_stock"
    GET_FULFILLMENT = "get_fulfillment"


class WMSResultStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"


@dataclass(frozen=True)
class WMSConnectionConfig:
    tenant_id: str
    connection_id: str
    base_url: str
    access_token: str
    enabled: bool = True
    allow_writes: bool = False
    timeout_seconds: float = 15.0

    def __post_init__(self) -> None:
        for name in (
            "tenant_id",
            "connection_id",
            "access_token",
        ):
            value = getattr(self, name)

            if not isinstance(value, str) or not value.strip():
                raise ValueError(
                    f"{name} is required"
                )

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
                "WMS URL must use HTTPS"
            )

        if self.timeout_seconds <= 0:
            raise ValueError(
                "timeout_seconds must be positive"
            )


@dataclass(frozen=True)
class WMSEndpointMapping:
    inventory_endpoint: str = (
        "/warehouses/{id}/inventory"
    )
    bin_stock_endpoint: str = (
        "/bins/{id}/stock"
    )
    receipt_endpoint: str = (
        "/receipts"
    )
    transfer_endpoint: str = (
        "/transfers"
    )
    fulfillment_endpoint: str = (
        "/fulfillments/{id}"
    )

    def __post_init__(self) -> None:
        pattern = r"/[A-Za-z0-9/_{}-]+"

        for endpoint in (
            self.inventory_endpoint,
            self.bin_stock_endpoint,
            self.receipt_endpoint,
            self.transfer_endpoint,
            self.fulfillment_endpoint,
        ):
            if not re.fullmatch(pattern, endpoint):
                raise ValueError(
                    "Invalid WMS endpoint"
                )


@dataclass(frozen=True)
class WMSStockLine:
    sku: str
    quantity: Decimal

    def __post_init__(self) -> None:
        if not SAFE_ID.fullmatch(self.sku):
            raise ValueError(
                "Invalid SKU"
            )

        if (
            not self.quantity.is_finite()
            or self.quantity <= 0
        ):
            raise ValueError(
                "Quantity must be positive"
            )


@dataclass(frozen=True)
class WMSReceiptPayload:
    receipt_id: str
    warehouse_id: str
    lines: tuple[WMSStockLine, ...]

    def __post_init__(self) -> None:
        if not SAFE_ID.fullmatch(
            self.receipt_id
        ):
            raise ValueError(
                "Invalid receipt ID"
            )

        if not SAFE_ID.fullmatch(
            self.warehouse_id
        ):
            raise ValueError(
                "Invalid warehouse ID"
            )

        if not self.lines:
            raise ValueError(
                "Receipt requires stock lines"
            )


@dataclass(frozen=True)
class WMSTransferPayload:
    transfer_id: str
    source_warehouse_id: str
    destination_warehouse_id: str
    lines: tuple[WMSStockLine, ...]

    def __post_init__(self) -> None:
        for name in (
            "transfer_id",
            "source_warehouse_id",
            "destination_warehouse_id",
        ):
            if not SAFE_ID.fullmatch(
                getattr(self, name)
            ):
                raise ValueError(
                    f"Invalid {name}"
                )

        if (
            self.source_warehouse_id
            == self.destination_warehouse_id
        ):
            raise ValueError(
                "Source and destination must differ"
            )

        if not self.lines:
            raise ValueError(
                "Transfer requires stock lines"
            )


@dataclass(frozen=True)
class WMSRequest:
    tenant_id: str
    connection_id: str
    operation: WMSOperation
    resource_id: str | None = None
    receipt: WMSReceiptPayload | None = None
    transfer: WMSTransferPayload | None = None
    idempotency_key: str | None = None

    def __post_init__(self) -> None:
        if not self.tenant_id or not self.connection_id:
            raise ValueError(
                "Tenant and connection are required"
            )

        if self.operation in (
            WMSOperation.GET_INVENTORY,
            WMSOperation.GET_BIN_STOCK,
            WMSOperation.GET_FULFILLMENT,
        ):
            if not self.resource_id:
                raise ValueError(
                    "resource_id is required"
                )

        if self.operation == WMSOperation.RECEIVE_STOCK:
            if self.receipt is None:
                raise ValueError(
                    "Receipt payload required"
                )

        if self.operation == WMSOperation.TRANSFER_STOCK:
            if self.transfer is None:
                raise ValueError(
                    "Transfer payload required"
                )

        if self.operation in (
            WMSOperation.RECEIVE_STOCK,
            WMSOperation.TRANSFER_STOCK,
        ):
            if not self.idempotency_key:
                raise ValueError(
                    "Write operation requires idempotency key"
                )


@dataclass(frozen=True)
class WMSResult:
    tenant_id: str
    connection_id: str
    operation: WMSOperation
    status: WMSResultStatus
    accepted: bool
    retryable: bool
    status_code: int | None
    data: Any = None
    error_code: str | None = None


class WMSConnectionRepository(Protocol):
    def get_connection(
        self,
        *,
        tenant_id: str,
        connection_id: str,
    ) -> WMSConnectionConfig | None:
        ...


class WMSHTTPTransport(Protocol):
    def request(
        self,
        *,
        method: str,
        url: str,
        headers: Mapping[str, str],
        payload: Mapping[str, Any] | None,
        timeout: float,
    ) -> httpx.Response:
        ...


class HTTPXWMSTransport:
    def request(
        self,
        *,
        method: str,
        url: str,
        headers: Mapping[str, str],
        payload: Mapping[str, Any] | None,
        timeout: float,
    ) -> httpx.Response:
        with httpx.Client(
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            return client.request(
                method,
                url,
                headers=dict(headers),
                json=payload,
            )


class RetailWMSAdapter:
    def __init__(
        self,
        *,
        repository: WMSConnectionRepository,
        mappings: Mapping[str, WMSEndpointMapping],
        transport: WMSHTTPTransport | None = None,
    ) -> None:
        self.repository = repository
        self.mappings = dict(mappings)
        self.transport = (
            transport or HTTPXWMSTransport()
        )

    @staticmethod
    def _stock_lines(
        lines: tuple[WMSStockLine, ...],
    ) -> list[dict[str, str]]:
        return [
            {
                "sku": line.sku,
                "quantity": str(line.quantity),
            }
            for line in lines
        ]

    @staticmethod
    def _build_request(
        request: WMSRequest,
        mapping: WMSEndpointMapping,
    ) -> tuple[
        str,
        str,
        dict[str, Any] | None,
    ]:
        if request.operation == WMSOperation.RECEIVE_STOCK:
            assert request.receipt is not None

            return (
                "POST",
                mapping.receipt_endpoint,
                {
                    "receipt_id": (
                        request.receipt.receipt_id
                    ),
                    "warehouse_id": (
                        request.receipt.warehouse_id
                    ),
                    "lines": RetailWMSAdapter._stock_lines(
                        request.receipt.lines
                    ),
                },
            )

        if request.operation == WMSOperation.TRANSFER_STOCK:
            assert request.transfer is not None

            return (
                "POST",
                mapping.transfer_endpoint,
                {
                    "transfer_id": (
                        request.transfer.transfer_id
                    ),
                    "source_warehouse_id": (
                        request.transfer.source_warehouse_id
                    ),
                    "destination_warehouse_id": (
                        request.transfer.destination_warehouse_id
                    ),
                    "lines": RetailWMSAdapter._stock_lines(
                        request.transfer.lines
                    ),
                },
            )

        resource_id = request.resource_id

        if (
            resource_id is None
            or not SAFE_ID.fullmatch(resource_id)
        ):
            raise WMSError(
                "Invalid WMS resource ID"
            )

        encoded = quote(
            resource_id,
            safe="",
        )

        endpoints = {
            WMSOperation.GET_INVENTORY: (
                mapping.inventory_endpoint
            ),
            WMSOperation.GET_BIN_STOCK: (
                mapping.bin_stock_endpoint
            ),
            WMSOperation.GET_FULFILLMENT: (
                mapping.fulfillment_endpoint
            ),
        }

        return (
            "GET",
            endpoints[request.operation].replace(
                "{id}", encoded
            ),
            None,
        )

    def execute(
        self,
        request: WMSRequest,
    ) -> WMSResult:
        config = self.repository.get_connection(
            tenant_id=request.tenant_id,
            connection_id=request.connection_id,
        )

        if config is None:
            raise PermissionError(
                "WMS connection not found"
            )

        if (
            config.tenant_id != request.tenant_id
            or config.connection_id != request.connection_id
        ):
            raise PermissionError(
                "WMS connection scope mismatch"
            )

        if not config.enabled:
            raise PermissionError(
                "WMS connection disabled"
            )

        if (
            request.operation in (
                WMSOperation.RECEIVE_STOCK,
                WMSOperation.TRANSFER_STOCK,
            )
            and not config.allow_writes
        ):
            raise PermissionError(
                "WMS writes are disabled"
            )

        mapping = self.mappings.get(
            request.connection_id
        )

        if mapping is None:
            raise WMSError(
                "WMS endpoint mapping missing"
            )

        method, endpoint, payload = (
            self._build_request(
                request,
                mapping,
            )
        )

        url = (
            config.base_url.rstrip("/")
            + endpoint
        )

        headers = {
            "Authorization": (
                f"Bearer {config.access_token}"
            ),
            "Accept": "application/json",
        }

        if request.idempotency_key:
            headers["Idempotency-Key"] = (
                request.idempotency_key
            )

        try:
            response = self.transport.request(
                method=method,
                url=url,
                headers=headers,
                payload=payload,
                timeout=config.timeout_seconds,
            )

            code = response.status_code

            if not 200 <= code < 300:
                retryable = (
                    code in (408, 425, 429)
                    or 500 <= code < 600
                )

                return WMSResult(
                    tenant_id=request.tenant_id,
                    connection_id=request.connection_id,
                    operation=request.operation,
                    status=WMSResultStatus.FAILED,
                    accepted=False,
                    retryable=retryable,
                    status_code=code,
                    error_code=f"http_{code}",
                )

            if code == 204 or not response.content:
                data = None
            else:
                try:
                    data = response.json()
                except ValueError:
                    return WMSResult(
                        tenant_id=request.tenant_id,
                        connection_id=request.connection_id,
                        operation=request.operation,
                        status=WMSResultStatus.FAILED,
                        accepted=False,
                        retryable=False,
                        status_code=code,
                        error_code="invalid_json_response",
                    )

            return WMSResult(
                tenant_id=request.tenant_id,
                connection_id=request.connection_id,
                operation=request.operation,
                status=WMSResultStatus.SUCCESS,
                accepted=True,
                retryable=False,
                status_code=code,
                data=data,
            )

        except (
            httpx.TimeoutException,
            httpx.TransportError,
        ):
            logger.warning(
                "WMS transport failure: "
                "tenant=%s connection=%s operation=%s",
                request.tenant_id,
                request.connection_id,
                request.operation.value,
            )

            return WMSResult(
                tenant_id=request.tenant_id,
                connection_id=request.connection_id,
                operation=request.operation,
                status=WMSResultStatus.FAILED,
                accepted=False,
                retryable=True,
                status_code=None,
                error_code="transport_error",
            )

    async def execute_async(
        self,
        request: WMSRequest,
    ) -> WMSResult:
        return await asyncio.to_thread(
            self.execute,
            request,
        )


class InMemoryWMSConnectionRepository:
    """
    Demo-only repository.
    """

    def __init__(
        self,
        connections: list[WMSConnectionConfig],
    ) -> None:
        self.connections = {
            (c.tenant_id, c.connection_id): c
            for c in connections
        }

    def get_connection(
        self,
        *,
        tenant_id: str,
        connection_id: str,
    ) -> WMSConnectionConfig | None:
        return self.connections.get(
            (tenant_id, connection_id)
        )


if __name__ == "__main__":
    repository = (
        InMemoryWMSConnectionRepository(
            [
                WMSConnectionConfig(
                    tenant_id="retail-demo",
                    connection_id="WMS001",
                    base_url="https://wms.example.com/api",
                    access_token="DEMO_TOKEN",
                    allow_writes=False,
                )
            ]
        )
    )

    mappings = {
        "WMS001": WMSEndpointMapping()
    }

    adapter = RetailWMSAdapter(
        repository=repository,
        mappings=mappings,
    )

    receipt = WMSReceiptPayload(
        receipt_id="REC001",
        warehouse_id="WH001",
        lines=(
            WMSStockLine(
                sku="SKU001",
                quantity=Decimal("100"),
            ),
        ),
    )

    print(
        "Prepared WMS receipt:",
        receipt,
    )

    # No external request is executed.
    # WMS writes require explicit enablement
    # and upstream authorization.
