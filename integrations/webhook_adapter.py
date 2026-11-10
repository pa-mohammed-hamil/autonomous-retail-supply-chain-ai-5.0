from __future__ import annotations

"""Planned module: webhook adapter. Implementation pending."""

"""
backend/integrations/supplier_api_adapter.py

Autonomous Retail Supply Chain AI 5.0

Python 3.10+
Dependency: httpx

Provider-neutral Supplier API Adapter.

Features:
- Supplier catalog retrieval
- Supplier inventory availability
- Purchase order submission
- Purchase order status retrieval
- Tenant-scoped supplier connections
- Bearer-token authentication
- Configurable field mappings
- Decimal quantity/price validation
- Idempotency-key propagation
- Read-only / write-enabled modes
- Retryable error classification
- Async-compatible execution
- Injectable HTTP transport

Production:
- Use a trusted supplier registry.
- Store credentials in a secret manager.
- Restrict outbound network destinations.
- Require approval for purchase orders.
- Reconcile uncertain submission outcomes.
"""


import asyncio
import logging
import re

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Mapping, Protocol
from urllib.parse import quote, urlsplit

import httpx


logger = logging.getLogger(__name__)

SAFE_ID = re.compile(
    r"^[A-Za-z0-9_-]{1,128}$"
)


class SupplierAPIError(ValueError):
    pass


class SupplierOperation(str, Enum):
    GET_CATALOG = "get_catalog"
    GET_AVAILABILITY = "get_availability"
    CREATE_PURCHASE_ORDER = "create_purchase_order"
    GET_PURCHASE_ORDER = "get_purchase_order"


class SupplierAPIStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"


@dataclass(frozen=True)
class SupplierConnectionConfig:
    tenant_id: str
    supplier_id: str
    base_url: str
    access_token: str
    enabled: bool = True
    allow_purchase_orders: bool = False
    timeout_seconds: float = 15.0

    def __post_init__(self) -> None:
        for name in (
            "tenant_id",
            "supplier_id",
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
                "Supplier API URL must use HTTPS"
            )

        if self.timeout_seconds <= 0:
            raise ValueError(
                "timeout_seconds must be positive"
            )


@dataclass(frozen=True)
class SupplierEndpointMapping:
    catalog_endpoint: str = "/catalog"
    availability_endpoint: str = (
        "/inventory/{id}"
    )
    purchase_order_endpoint: str = (
        "/purchase-orders"
    )
    purchase_order_status_endpoint: str = (
        "/purchase-orders/{id}"
    )

    outbound_fields: Mapping[str, str] = field(
        default_factory=dict
    )

    inbound_fields: Mapping[str, str] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        pattern = r"/[A-Za-z0-9/_{}-]+"

        for endpoint in (
            self.catalog_endpoint,
            self.availability_endpoint,
            self.purchase_order_endpoint,
            self.purchase_order_status_endpoint,
        ):
            if not re.fullmatch(pattern, endpoint):
                raise ValueError(
                    "Invalid supplier endpoint"
                )


@dataclass(frozen=True)
class PurchaseOrderLine:
    sku: str
    quantity: Decimal
    unit_price: Decimal

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

        if (
            not self.unit_price.is_finite()
            or self.unit_price < 0
        ):
            raise ValueError(
                "Unit price cannot be negative"
            )


@dataclass(frozen=True)
class PurchaseOrderPayload:
    purchase_order_id: str
    currency: str
    lines: tuple[PurchaseOrderLine, ...]
    warehouse_id: str

    def __post_init__(self) -> None:
        if not SAFE_ID.fullmatch(
            self.purchase_order_id
        ):
            raise ValueError(
                "Invalid purchase order ID"
            )

        if not SAFE_ID.fullmatch(
            self.warehouse_id
        ):
            raise ValueError(
                "Invalid warehouse ID"
            )

        if not re.fullmatch(
            r"[A-Z]{3}",
            self.currency,
        ):
            raise ValueError(
                "Invalid currency code"
            )

        if not self.lines:
            raise ValueError(
                "Purchase order requires lines"
            )

    @property
    def total(self) -> Decimal:
        return sum(
            (
                line.quantity * line.unit_price
                for line in self.lines
            ),
            Decimal("0"),
        )


@dataclass(frozen=True)
class SupplierAPIRequest:
    tenant_id: str
    supplier_id: str
    operation: SupplierOperation
    resource_id: str | None = None
    purchase_order: PurchaseOrderPayload | None = None
    idempotency_key: str | None = None

    def __post_init__(self) -> None:
        if not self.tenant_id or not self.supplier_id:
            raise ValueError(
                "Tenant and supplier are required"
            )

        if self.operation in (
            SupplierOperation.GET_AVAILABILITY,
            SupplierOperation.GET_PURCHASE_ORDER,
        ):
            if not self.resource_id:
                raise ValueError(
                    "resource_id is required"
                )

        if self.operation == SupplierOperation.CREATE_PURCHASE_ORDER:
            if self.purchase_order is None:
                raise ValueError(
                    "Purchase order payload required"
                )

            if not self.idempotency_key:
                raise ValueError(
                    "Idempotency key required"
                )


@dataclass(frozen=True)
class SupplierAPIResult:
    tenant_id: str
    supplier_id: str
    operation: SupplierOperation
    status: SupplierAPIStatus
    accepted: bool
    retryable: bool
    status_code: int | None
    data: Any = None
    error_code: str | None = None


class SupplierConnectionRepository(Protocol):
    def get_connection(
        self,
        *,
        tenant_id: str,
        supplier_id: str,
    ) -> SupplierConnectionConfig | None:
        ...


class SupplierHTTPTransport(Protocol):
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


class HTTPXSupplierTransport:
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


class RetailSupplierAPIAdapter:
    def __init__(
        self,
        *,
        repository: SupplierConnectionRepository,
        mappings: Mapping[
            str,
            SupplierEndpointMapping,
        ],
        transport: SupplierHTTPTransport | None = None,
    ) -> None:
        self.repository = repository
        self.mappings = dict(mappings)
        self.transport = (
            transport or HTTPXSupplierTransport()
        )

    @staticmethod
    def _endpoint(
        request: SupplierAPIRequest,
        mapping: SupplierEndpointMapping,
    ) -> tuple[str, str]:
        if request.operation == SupplierOperation.GET_CATALOG:
            return (
                "GET",
                mapping.catalog_endpoint,
            )

        if request.operation == SupplierOperation.CREATE_PURCHASE_ORDER:
            return (
                "POST",
                mapping.purchase_order_endpoint,
            )

        resource_id = request.resource_id

        if (
            resource_id is None
            or not SAFE_ID.fullmatch(resource_id)
        ):
            raise SupplierAPIError(
                "Invalid resource ID"
            )

        encoded = quote(
            resource_id,
            safe="",
        )

        if request.operation == SupplierOperation.GET_AVAILABILITY:
            return (
                "GET",
                mapping.availability_endpoint.replace(
                    "{id}", encoded
                ),
            )

        return (
            "GET",
            mapping.purchase_order_status_endpoint.replace(
                "{id}", encoded
            ),
        )

    @staticmethod
    def _purchase_order_body(
        order: PurchaseOrderPayload,
    ) -> dict[str, Any]:
        return {
            "purchase_order_id": (
                order.purchase_order_id
            ),
            "warehouse_id": order.warehouse_id,
            "currency": order.currency,
            "total": str(order.total),
            "lines": [
                {
                    "sku": line.sku,
                    "quantity": str(line.quantity),
                    "unit_price": str(
                        line.unit_price
                    ),
                }
                for line in order.lines
            ],
        }

    @staticmethod
    def _map_outbound(
        data: Mapping[str, Any],
        mapping: SupplierEndpointMapping,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {}

        for key, value in data.items():
            target = mapping.outbound_fields.get(
                key,
                key,
            )

            if target in result:
                raise SupplierAPIError(
                    "Duplicate outbound mapping"
                )

            result[target] = value

        return result

    @staticmethod
    def _map_inbound(
        data: Any,
        mapping: SupplierEndpointMapping,
    ) -> Any:
        def convert(item: Any) -> Any:
            if not isinstance(item, dict):
                return item

            return {
                mapping.inbound_fields.get(
                    key, key
                ): value
                for key, value in item.items()
            }

        if isinstance(data, list):
            return [
                convert(item)
                for item in data
            ]

        return convert(data)

    def execute(
        self,
        request: SupplierAPIRequest,
    ) -> SupplierAPIResult:
        config = self.repository.get_connection(
            tenant_id=request.tenant_id,
            supplier_id=request.supplier_id,
        )

        if config is None:
            raise PermissionError(
                "Supplier connection not found"
            )

        if (
            config.tenant_id != request.tenant_id
            or config.supplier_id != request.supplier_id
        ):
            raise PermissionError(
                "Supplier connection scope mismatch"
            )

        if not config.enabled:
            raise PermissionError(
                "Supplier connection disabled"
            )

        if (
            request.operation == SupplierOperation.CREATE_PURCHASE_ORDER
            and not config.allow_purchase_orders
        ):
            raise PermissionError(
                "Purchase order submission disabled"
            )

        mapping = self.mappings.get(
            request.supplier_id
        )

        if mapping is None:
            raise SupplierAPIError(
                "Supplier endpoint mapping missing"
            )

        method, endpoint = self._endpoint(
            request,
            mapping,
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

        payload = None

        if request.purchase_order:
            payload = self._map_outbound(
                self._purchase_order_body(
                    request.purchase_order
                ),
                mapping,
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

                return SupplierAPIResult(
                    tenant_id=request.tenant_id,
                    supplier_id=request.supplier_id,
                    operation=request.operation,
                    status=SupplierAPIStatus.FAILED,
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
                    return SupplierAPIResult(
                        tenant_id=request.tenant_id,
                        supplier_id=request.supplier_id,
                        operation=request.operation,
                        status=SupplierAPIStatus.FAILED,
                        accepted=False,
                        retryable=False,
                        status_code=code,
                        error_code="invalid_json_response",
                    )

            return SupplierAPIResult(
                tenant_id=request.tenant_id,
                supplier_id=request.supplier_id,
                operation=request.operation,
                status=SupplierAPIStatus.SUCCESS,
                accepted=True,
                retryable=False,
                status_code=code,
                data=self._map_inbound(
                    data,
                    mapping,
                ),
            )

        except (
            httpx.TimeoutException,
            httpx.TransportError,
        ):
            logger.warning(
                "Supplier API transport failure: "
                "tenant=%s supplier=%s operation=%s",
                request.tenant_id,
                request.supplier_id,
                request.operation.value,
            )

            return SupplierAPIResult(
                tenant_id=request.tenant_id,
                supplier_id=request.supplier_id,
                operation=request.operation,
                status=SupplierAPIStatus.FAILED,
                accepted=False,
                retryable=True,
                status_code=None,
                error_code="transport_error",
            )

    async def execute_async(
        self,
        request: SupplierAPIRequest,
    ) -> SupplierAPIResult:
        return await asyncio.to_thread(
            self.execute,
            request,
        )


class InMemorySupplierConnectionRepository:
    """
    Demonstration repository only.
    """

    def __init__(
        self,
        connections: list[SupplierConnectionConfig],
    ) -> None:
        self.connections = {
            (c.tenant_id, c.supplier_id): c
            for c in connections
        }

    def get_connection(
        self,
        *,
        tenant_id: str,
        supplier_id: str,
    ) -> SupplierConnectionConfig | None:
        return self.connections.get(
            (tenant_id, supplier_id)
        )


if __name__ == "__main__":
    repository = (
        InMemorySupplierConnectionRepository(
            [
                SupplierConnectionConfig(
                    tenant_id="retail-demo",
                    supplier_id="SUP001",
                    base_url="https://supplier.example.com/api",
                    access_token="DEMO_TOKEN",
                    allow_purchase_orders=False,
                )
            ]
        )
    )

    mappings = {
        "SUP001": SupplierEndpointMapping(
            catalog_endpoint="/catalog",
            availability_endpoint="/inventory/{id}",
            purchase_order_endpoint="/purchase-orders",
            purchase_order_status_endpoint=(
                "/purchase-orders/{id}"
            ),
        )
    }

    adapter = RetailSupplierAPIAdapter(
        repository=repository,
        mappings=mappings,
    )

    order = PurchaseOrderPayload(
        purchase_order_id="PO001",
        currency="INR",
        warehouse_id="WH001",
        lines=(
            PurchaseOrderLine(
                sku="SKU001",
                quantity=Decimal("100"),
                unit_price=Decimal("250.00"),
            ),
            PurchaseOrderLine(
                sku="SKU002",
                quantity=Decimal("50"),
                unit_price=Decimal("120.00"),
            ),
        ),
    )

    print(
        "Purchase order total:",
        order.total,
    )

    # No external request is executed.
    # PO submission requires allow_purchase_orders=True
    # plus upstream approval and authorization.
