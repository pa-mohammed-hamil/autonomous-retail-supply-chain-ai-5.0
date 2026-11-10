from __future__ import annotations

"""Planned module: feedback adapter. Implementation pending."""

"""
backend/integrations/erp_adapter.py

Autonomous Retail Supply Chain AI 5.0

Python 3.10+
Dependency: httpx

Features:
- Generic REST ERP integration
- Tenant-scoped ERP connections
- Inventory/product/supplier/PO synchronization
- Bearer token authentication
- Read-only and write-enabled modes
- Strict resource allowlists
- Configurable field mappings
- Request timeouts
- Retry classification
- Idempotency-key propagation
- Async compatibility
- Structured integration results

This is a provider-neutral reference adapter.
Actual SAP, Oracle, Dynamics and Odoo
connectors require vendor-specific mapping.

Security:
- Load tokens from a trusted secret store.
- Never accept arbitrary ERP URLs from users.
- Restrict outbound network destinations.
- Require authorization before ERP writes.
- Persist synchronization checkpoints.
"""


import asyncio
import logging
import re

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Protocol
from urllib.parse import urlsplit, quote

import httpx


logger = logging.getLogger(__name__)


class ERPError(Exception):
    def __init__(
        self,
        message: str,
        *,
        retryable: bool = False,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.status_code = status_code


class ERPProvider(str, Enum):
    SAP = "sap"
    ORACLE = "oracle"
    DYNAMICS = "dynamics"
    ODOO = "odoo"
    GENERIC = "generic"


class ERPResource(str, Enum):
    PRODUCTS = "products"
    INVENTORY = "inventory"
    SUPPLIERS = "suppliers"
    PURCHASE_ORDERS = "purchase_orders"
    WAREHOUSES = "warehouses"


class ERPOperation(str, Enum):
    READ = "read"
    CREATE = "create"
    UPDATE = "update"


class ERPSyncStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"


@dataclass(frozen=True)
class ERPConnectionConfig:
    tenant_id: str
    connection_id: str
    provider: ERPProvider
    base_url: str
    access_token: str
    read_only: bool = True
    timeout_seconds: float = 15.0

    allowed_resources: frozenset[
        ERPResource
    ] = frozenset(ERPResource)

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
        ):
            raise ValueError(
                "ERP base URL must be a valid HTTPS URL"
            )

        if self.timeout_seconds <= 0:
            raise ValueError(
                "Timeout must be positive"
            )


@dataclass(frozen=True)
class ERPResourceMapping:
    resource: ERPResource
    endpoint: str
    field_mapping: Mapping[str, str] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        # Only static relative API paths are accepted.
        if not re.fullmatch(
            r"/[A-Za-z0-9/_-]+",
            self.endpoint,
        ):
            raise ValueError(
                "Invalid ERP endpoint path"
            )

        for source, target in self.field_mapping.items():
            if not (
                re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", source)
                and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", target)
            ):
                raise ValueError(
                    "Invalid field mapping"
                )


@dataclass(frozen=True)
class ERPSyncRequest:
    tenant_id: str
    connection_id: str
    resource: ERPResource
    operation: ERPOperation
    resource_id: str | None = None
    payload: Mapping[str, Any] | None = None
    idempotency_key: str | None = None

    def __post_init__(self) -> None:
        if not self.tenant_id or not self.connection_id:
            raise ValueError(
                "Tenant and connection are required"
            )

        if self.operation == ERPOperation.UPDATE:
            if not self.resource_id:
                raise ValueError(
                    "resource_id required for update"
                )

        if self.operation in (
            ERPOperation.CREATE,
            ERPOperation.UPDATE,
        ):
            if self.payload is None:
                raise ValueError(
                    "Write operation requires payload"
                )

            if not self.idempotency_key:
                raise ValueError(
                    "ERP writes require idempotency key"
                )


@dataclass(frozen=True)
class ERPSyncResult:
    tenant_id: str
    connection_id: str
    resource: ERPResource
    operation: ERPOperation
    status: ERPSyncStatus
    retryable: bool
    status_code: int | None
    data: Any = None
    error_code: str | None = None


class ERPConnectionRepository(Protocol):
    def get_connection(
        self,
        *,
        tenant_id: str,
        connection_id: str,
    ) -> ERPConnectionConfig | None:
        ...


class ERPHTTPTransport(Protocol):
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


class HTTPXERPTransport:
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


class RetailERPAdapter:
    """
    Generic ERP REST adapter.

    Each ERP connection requires trusted
    resource mappings configured by an admin.
    """

    def __init__(
        self,
        *,
        repository: ERPConnectionRepository,
        mappings: Mapping[
            ERPResource,
            ERPResourceMapping,
        ],
        transport: ERPHTTPTransport | None = None,
    ) -> None:
        self.repository = repository
        self.mappings = dict(mappings)
        self.transport = (
            transport or HTTPXERPTransport()
        )

    @staticmethod
    def _map_outbound(
        data: Mapping[str, Any],
        mapping: ERPResourceMapping,
    ) -> dict[str, Any]:
        result = {}

        for key, value in data.items():
            target = mapping.field_mapping.get(
                key,
                key,
            )
            if target in result:
                raise ValueError(
                    "Duplicate mapped field"
                )
            result[target] = value

        return result

    @staticmethod
    def _map_inbound(
        data: Any,
        mapping: ERPResourceMapping,
    ) -> Any:
        reverse = {
            external: internal
            for internal, external
            in mapping.field_mapping.items()
        }

        def convert(record: Any) -> Any:
            if not isinstance(record, dict):
                return record

            return {
                reverse.get(key, key): value
                for key, value in record.items()
            }

        if isinstance(data, list):
            return [convert(item) for item in data]

        return convert(data)

    @staticmethod
    def _method(
        operation: ERPOperation,
    ) -> str:
        return {
            ERPOperation.READ: "GET",
            ERPOperation.CREATE: "POST",
            ERPOperation.UPDATE: "PATCH",
        }[operation]

    def execute(
        self,
        request: ERPSyncRequest,
    ) -> ERPSyncResult:
        config = self.repository.get_connection(
            tenant_id=request.tenant_id,
            connection_id=request.connection_id,
        )

        if config is None:
            raise PermissionError(
                "ERP connection not found"
            )

        if (
            config.tenant_id != request.tenant_id
            or config.connection_id
                != request.connection_id
        ):
            raise PermissionError(
                "ERP connection scope mismatch"
            )

        if request.resource not in config.allowed_resources:
            raise PermissionError(
                "ERP resource not authorized"
            )

        if (
            config.read_only
            and request.operation != ERPOperation.READ
        ):
            raise PermissionError(
                "ERP connection is read-only"
            )

        mapping = self.mappings.get(
            request.resource
        )

        if mapping is None:
            raise ERPError(
                "ERP resource mapping missing"
            )

        method = self._method(
            request.operation
        )

        url = (
            config.base_url.rstrip("/")
            + mapping.endpoint
        )

        if request.resource_id:
            if not re.fullmatch(
                r"[A-Za-z0-9_-]{1,128}",
                request.resource_id,
            ):
                raise ValueError(
                    "Invalid ERP resource ID"
                )

            url += "/" + quote(
                request.resource_id,
                safe="",
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

        if request.payload is not None:
            payload = self._map_outbound(
                request.payload,
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

            status_code = response.status_code

            if not (
                200 <= status_code < 300
            ):
                retryable = (
                    status_code in (408, 425, 429)
                    or 500 <= status_code < 600
                )

                return ERPSyncResult(
                    tenant_id=request.tenant_id,
                    connection_id=request.connection_id,
                    resource=request.resource,
                    operation=request.operation,
                    status=ERPSyncStatus.FAILED,
                    retryable=retryable,
                    status_code=status_code,
                    error_code=f"http_{status_code}",
                )

            if status_code == 204 or not response.content:
                data = None
            else:
                try:
                    data = response.json()
                except ValueError:
                    return ERPSyncResult(
                        tenant_id=request.tenant_id,
                        connection_id=request.connection_id,
                        resource=request.resource,
                        operation=request.operation,
                        status=ERPSyncStatus.FAILED,
                        retryable=False,
                        status_code=status_code,
                        error_code="invalid_json_response",
                    )

            return ERPSyncResult(
                tenant_id=request.tenant_id,
                connection_id=request.connection_id,
                resource=request.resource,
                operation=request.operation,
                status=ERPSyncStatus.SUCCESS,
                retryable=False,
                status_code=status_code,
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
                "ERP transport failure: tenant=%s "
                "connection=%s resource=%s",
                request.tenant_id,
                request.connection_id,
                request.resource.value,
            )

            return ERPSyncResult(
                tenant_id=request.tenant_id,
                connection_id=request.connection_id,
                resource=request.resource,
                operation=request.operation,
                status=ERPSyncStatus.FAILED,
                retryable=True,
                status_code=None,
                error_code="transport_error",
            )

    async def execute_async(
        self,
        request: ERPSyncRequest,
    ) -> ERPSyncResult:
        return await asyncio.to_thread(
            self.execute,
            request,
        )


class InMemoryERPConnectionRepository:
    """
    Demo repository only.
    """

    def __init__(
        self,
        connections: list[ERPConnectionConfig],
    ) -> None:
        self.connections = {
            (
                item.tenant_id,
                item.connection_id,
            ): item
            for item in connections
        }

    def get_connection(
        self,
        *,
        tenant_id: str,
        connection_id: str,
    ) -> ERPConnectionConfig | None:
        return self.connections.get(
            (tenant_id, connection_id)
        )


if __name__ == "__main__":
    mappings = {
        ERPResource.INVENTORY: ERPResourceMapping(
            resource=ERPResource.INVENTORY,
            endpoint="/api/inventory",
            field_mapping={
                "sku": "item_code",
                "quantity": "available_quantity",
                "warehouse_id": "location_code",
            },
        ),
        ERPResource.SUPPLIERS: ERPResourceMapping(
            resource=ERPResource.SUPPLIERS,
            endpoint="/api/suppliers",
            field_mapping={
                "supplier_id": "vendor_code",
                "name": "vendor_name",
            },
        ),
    }

    repository = InMemoryERPConnectionRepository(
        [
            ERPConnectionConfig(
                tenant_id="retail-demo",
                connection_id="ERP001",
                provider=ERPProvider.GENERIC,
                base_url="https://erp.example.com",
                access_token="DEMO_TOKEN",
                read_only=True,
            )
        ]
    )

    adapter = RetailERPAdapter(
        repository=repository,
        mappings=mappings,
    )

    # Example request; not executed to avoid
    # making an external network call.
    request = ERPSyncRequest(
        tenant_id="retail-demo",
        connection_id="ERP001",
        resource=ERPResource.INVENTORY,
        operation=ERPOperation.READ,
    )

    print(
        "ERP request prepared:",
        request,
    )
