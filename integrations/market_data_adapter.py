from __future__ import annotations

"""Planned module: market data adapter. Implementation pending."""

"""
backend/integrations/market_data_adapter.py

Autonomous Retail Supply Chain AI 5.0

Python 3.10+
Dependency: httpx

Features:
- Authorized market data API ingestion
- Competitor and commodity pricing
- Market demand indicators
- Configurable provider mappings
- Tenant-scoped connections
- Bearer/API-key authentication
- Decimal-based price validation
- ISO currency validation
- Timezone-aware timestamps
- Pagination support
- Deduplication fingerprints
- Structured error classification
- Async-compatible execution

Production requirements:
- Trusted provider configuration
- Egress allowlists and SSRF protection
- Secure credential storage
- Rate limits and durable checkpoints
- Data licensing compliance
"""


import asyncio
import hashlib
import json
import logging
import re

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Mapping, Protocol
from urllib.parse import urlsplit

import httpx


logger = logging.getLogger(__name__)


class MarketDataError(ValueError):
    pass


class MarketDataType(str, Enum):
    COMPETITOR_PRICE = "competitor_price"
    COMMODITY_PRICE = "commodity_price"
    DEMAND_INDICATOR = "demand_indicator"
    MARKET_TREND = "market_trend"


class AuthenticationMode(str, Enum):
    BEARER = "bearer"
    API_KEY_HEADER = "api_key_header"


@dataclass(frozen=True)
class MarketProviderConfig:
    tenant_id: str
    provider_id: str
    base_url: str
    credential: str
    auth_mode: AuthenticationMode
    api_key_header: str = "X-API-Key"
    enabled: bool = True
    timeout_seconds: float = 15.0
    max_pages: int = 10

    def __post_init__(self) -> None:
        for name in (
            "tenant_id",
            "provider_id",
            "credential",
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
                "Market provider URL must use HTTPS"
            )

        if not re.fullmatch(
            r"[A-Za-z][A-Za-z0-9-]{0,63}",
            self.api_key_header,
        ):
            raise ValueError(
                "Invalid API key header"
            )

        if self.timeout_seconds <= 0:
            raise ValueError(
                "Timeout must be positive"
            )

        if not (1 <= self.max_pages <= 100):
            raise ValueError(
                "max_pages must be between 1 and 100"
            )


@dataclass(frozen=True)
class MarketDataMapping:
    data_type: MarketDataType
    endpoint: str
    items_field: str = "items"
    next_page_field: str = "next_page"

    product_id_field: str = "product_id"
    value_field: str = "value"
    currency_field: str = "currency"
    timestamp_field: str = "timestamp"
    external_id_field: str = "id"

    def __post_init__(self) -> None:
        if not re.fullmatch(
            r"/[A-Za-z0-9/_-]+",
            self.endpoint,
        ):
            raise ValueError(
                "Invalid market data endpoint"
            )


@dataclass(frozen=True)
class MarketDataRecord:
    tenant_id: str
    provider_id: str
    data_type: MarketDataType
    external_id: str
    product_id: str
    value: Decimal
    currency: str | None
    observed_at: datetime
    fingerprint: str


@dataclass(frozen=True)
class MarketDataImportResult:
    tenant_id: str
    provider_id: str
    data_type: MarketDataType
    fetched: int
    imported: int
    duplicates: int
    rejected: int
    pages_processed: int
    errors: tuple[str, ...] = ()


class MarketProviderRepository(Protocol):
    def get_provider(
        self,
        *,
        tenant_id: str,
        provider_id: str,
    ) -> MarketProviderConfig | None:
        ...


class MarketDataRepository(Protocol):
    """
    Implement with atomic uniqueness on:
    (tenant_id, fingerprint)
    """

    def insert_if_absent(
        self,
        record: MarketDataRecord,
    ) -> bool:
        ...


class MarketHTTPTransport(Protocol):
    def get(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        params: Mapping[str, str],
        timeout: float,
    ) -> httpx.Response:
        ...


class HTTPXMarketTransport:
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


class MarketDataNormalizer:
    @staticmethod
    def identifier(
        value: Any,
        name: str,
    ) -> str:
        if isinstance(value, bool) or not isinstance(
            value, (str, int)
        ):
            raise MarketDataError(
                f"Invalid {name}"
            )

        result = str(value).strip()

        if not (
            1 <= len(result) <= 128
        ):
            raise MarketDataError(
                f"Invalid {name} length"
            )

        return result

    @staticmethod
    def decimal_value(
        value: Any,
    ) -> Decimal:
        if isinstance(value, bool):
            raise MarketDataError(
                "Invalid numeric value"
            )

        try:
            result = Decimal(str(value))
        except (InvalidOperation, ValueError):
            raise MarketDataError(
                "Invalid numeric value"
            ) from None

        if not result.is_finite():
            raise MarketDataError(
                "Non-finite numeric value"
            )

        if result < 0:
            raise MarketDataError(
                "Negative values are not supported"
            )

        return result

    @staticmethod
    def currency(
        value: Any,
    ) -> str | None:
        if value is None or value == "":
            return None

        if not isinstance(value, str):
            raise MarketDataError(
                "Invalid currency"
            )

        code = value.strip().upper()

        if not re.fullmatch(r"[A-Z]{3}", code):
            raise MarketDataError(
                "Currency must be a 3-letter code"
            )

        return code

    @staticmethod
    def timestamp(
        value: Any,
    ) -> datetime:
        if not isinstance(value, str):
            raise MarketDataError(
                "Timestamp must be an ISO string"
            )

        try:
            result = datetime.fromisoformat(
                value.replace("Z", "+00:00")
            )
        except ValueError:
            raise MarketDataError(
                "Invalid timestamp"
            ) from None

        if (
            result.tzinfo is None
            or result.utcoffset() is None
        ):
            raise MarketDataError(
                "Timestamp requires timezone"
            )

        return result.astimezone(
            timezone.utc
        )


class RetailMarketDataAdapter:
    def __init__(
        self,
        *,
        provider_repository: MarketProviderRepository,
        data_repository: MarketDataRepository,
        mappings: Mapping[
            MarketDataType,
            MarketDataMapping,
        ],
        transport: MarketHTTPTransport | None = None,
    ) -> None:
        self.providers = provider_repository
        self.data = data_repository
        self.mappings = dict(mappings)
        self.transport = (
            transport or HTTPXMarketTransport()
        )

    @staticmethod
    def _headers(
        config: MarketProviderConfig,
    ) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
        }

        if config.auth_mode == AuthenticationMode.BEARER:
            headers["Authorization"] = (
                f"Bearer {config.credential}"
            )
        else:
            headers[config.api_key_header] = (
                config.credential
            )

        return headers

    @staticmethod
    def _fingerprint(
        *,
        tenant_id: str,
        provider_id: str,
        data_type: MarketDataType,
        external_id: str,
    ) -> str:
        identity = json.dumps(
            {
                "tenant_id": tenant_id,
                "provider_id": provider_id,
                "data_type": data_type.value,
                "external_id": external_id,
            },
            sort_keys=True,
            separators=(",", ":"),
        )

        return hashlib.sha256(
            identity.encode("utf-8")
        ).hexdigest()

    def _normalize(
        self,
        *,
        tenant_id: str,
        provider_id: str,
        raw: Mapping[str, Any],
        mapping: MarketDataMapping,
    ) -> MarketDataRecord:
        external_id = (
            MarketDataNormalizer.identifier(
                raw.get(mapping.external_id_field),
                "external_id",
            )
        )

        product_id = (
            MarketDataNormalizer.identifier(
                raw.get(mapping.product_id_field),
                "product_id",
            )
        )

        value = (
            MarketDataNormalizer.decimal_value(
                raw.get(mapping.value_field)
            )
        )

        currency = (
            MarketDataNormalizer.currency(
                raw.get(mapping.currency_field)
            )
        )

        if mapping.data_type in (
            MarketDataType.COMPETITOR_PRICE,
            MarketDataType.COMMODITY_PRICE,
        ) and currency is None:
            raise MarketDataError(
                "Price records require currency"
            )

        observed_at = (
            MarketDataNormalizer.timestamp(
                raw.get(mapping.timestamp_field)
            )
        )

        return MarketDataRecord(
            tenant_id=tenant_id,
            provider_id=provider_id,
            data_type=mapping.data_type,
            external_id=external_id,
            product_id=product_id,
            value=value,
            currency=currency,
            observed_at=observed_at,
            fingerprint=self._fingerprint(
                tenant_id=tenant_id,
                provider_id=provider_id,
                data_type=mapping.data_type,
                external_id=external_id,
            ),
        )

    def import_data(
        self,
        *,
        tenant_id: str,
        provider_id: str,
        data_type: MarketDataType,
    ) -> MarketDataImportResult:
        config = self.providers.get_provider(
            tenant_id=tenant_id,
            provider_id=provider_id,
        )

        if config is None:
            raise PermissionError(
                "Market provider not found"
            )

        if (
            config.tenant_id != tenant_id
            or config.provider_id != provider_id
        ):
            raise PermissionError(
                "Market provider scope mismatch"
            )

        if not config.enabled:
            raise PermissionError(
                "Market provider disabled"
            )

        mapping = self.mappings.get(
            data_type
        )

        if mapping is None:
            raise MarketDataError(
                "Market data mapping missing"
            )

        url = (
            config.base_url.rstrip("/")
            + mapping.endpoint
        )

        headers = self._headers(config)

        fetched = 0
        imported = 0
        duplicates = 0
        rejected = 0
        pages_processed = 0
        errors: list[str] = []

        page_token: str | None = None
        seen_tokens: set[str] = set()

        for _ in range(config.max_pages):
            params: dict[str, str] = {}

            if page_token:
                params["page"] = page_token

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
                errors.append(
                    "Transport failure; retry required"
                )
                break

            if response.status_code != 200:
                errors.append(
                    f"HTTP {response.status_code}"
                )
                break

            try:
                body = response.json()
            except ValueError:
                errors.append(
                    "Invalid JSON response"
                )
                break

            if not isinstance(body, dict):
                errors.append(
                    "Response must be an object"
                )
                break

            items = body.get(
                mapping.items_field
            )

            if not isinstance(items, list):
                errors.append(
                    "Response items must be a list"
                )
                break

            pages_processed += 1

            for index, raw in enumerate(items):
                fetched += 1

                if not isinstance(raw, dict):
                    rejected += 1
                    errors.append(
                        f"Invalid record at index {index}"
                    )
                    continue

                try:
                    record = self._normalize(
                        tenant_id=tenant_id,
                        provider_id=provider_id,
                        raw=raw,
                        mapping=mapping,
                    )

                    inserted = (
                        self.data.insert_if_absent(
                            record
                        )
                    )

                    if inserted:
                        imported += 1
                    else:
                        duplicates += 1

                except MarketDataError as exc:
                    rejected += 1
                    errors.append(
                        f"Record {index}: {exc}"
                    )

            next_token = body.get(
                mapping.next_page_field
            )

            if next_token is None or next_token == "":
                break

            if not isinstance(next_token, (str, int)):
                errors.append(
                    "Invalid pagination token"
                )
                break

            page_token = str(next_token)

            if page_token in seen_tokens:
                errors.append(
                    "Repeated pagination token"
                )
                break

            seen_tokens.add(page_token)

        return MarketDataImportResult(
            tenant_id=tenant_id,
            provider_id=provider_id,
            data_type=data_type,
            fetched=fetched,
            imported=imported,
            duplicates=duplicates,
            rejected=rejected,
            pages_processed=pages_processed,
            errors=tuple(errors),
        )

    async def import_data_async(
        self,
        *,
        tenant_id: str,
        provider_id: str,
        data_type: MarketDataType,
    ) -> MarketDataImportResult:
        return await asyncio.to_thread(
            self.import_data,
            tenant_id=tenant_id,
            provider_id=provider_id,
            data_type=data_type,
        )


class InMemoryMarketProviderRepository:
    def __init__(
        self,
        providers: list[MarketProviderConfig],
    ) -> None:
        self.providers = {
            (p.tenant_id, p.provider_id): p
            for p in providers
        }

    def get_provider(
        self,
        *,
        tenant_id: str,
        provider_id: str,
    ) -> MarketProviderConfig | None:
        return self.providers.get(
            (tenant_id, provider_id)
        )


class InMemoryMarketDataRepository:
    def __init__(self) -> None:
        self.records: dict[
            tuple[str, str],
            MarketDataRecord,
        ] = {}

    def insert_if_absent(
        self,
        record: MarketDataRecord,
    ) -> bool:
        key = (
            record.tenant_id,
            record.fingerprint,
        )

        if key in self.records:
            return False

        self.records[key] = record
        return True


if __name__ == "__main__":
    # Demonstration configuration only.
    # No live API request is executed.

    provider_repository = (
        InMemoryMarketProviderRepository(
            [
                MarketProviderConfig(
                    tenant_id="retail-demo",
                    provider_id="MARKET001",
                    base_url="https://market.example.com",
                    credential="DEMO_TOKEN",
                    auth_mode=AuthenticationMode.BEARER,
                )
            ]
        )
    )

    data_repository = (
        InMemoryMarketDataRepository()
    )

    mappings = {
        MarketDataType.COMPETITOR_PRICE: (
            MarketDataMapping(
                data_type=(
                    MarketDataType.COMPETITOR_PRICE
                ),
                endpoint="/api/prices",
                product_id_field="sku",
                value_field="price",
                currency_field="currency",
                timestamp_field="observed_at",
                external_id_field="record_id",
            )
        )
    }

    adapter = RetailMarketDataAdapter(
        provider_repository=provider_repository,
        data_repository=data_repository,
        mappings=mappings,
    )

    example_record = adapter._normalize(
        tenant_id="retail-demo",
        provider_id="MARKET001",
        mapping=mappings[
            MarketDataType.COMPETITOR_PRICE
        ],
        raw={
            "record_id": "PRICE001",
            "sku": "SKU001",
            "price": "249.50",
            "currency": "INR",
            "observed_at": (
                "2026-10-28T10:00:00+05:30"
            ),
        },
    )

    print(example_record)
