from __future__ import annotations

"""Planned module: response models. Implementation pending."""

"""
backend/response_models.py

Autonomous Retail Supply Chain AI 5.0

Reusable API response models.

Python 3.10+
Dependencies:
    pydantic >= 2

Design:
    - Pydantic v2
    - Typed API responses
    - Consistent timestamps
    - Pagination support
    - Tenant-aware business schemas
    - AI and RAG response schemas
    - No database operations
    - No network operations
    - No sensitive credentials in responses

Usage:
    from backend.response_models import (
        APIResponse,
        PaginatedResponse,
        ProductResponse,
        InventoryResponse,
    )
"""


from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Generic, TypeVar

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    model_validator,
)


# ============================================================
# COMMON CONFIGURATION
# ============================================================

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ResponseModel(BaseModel):
    """Base class for API output schemas."""

    model_config = ConfigDict(
        from_attributes=True,
        extra="forbid",
        use_enum_values=False,
        populate_by_name=True,
    )


DataT = TypeVar("DataT")


# ============================================================
# COMMON RESPONSE MODELS
# ============================================================

class ResponseStatus(str, Enum):
    SUCCESS = "success"
    PARTIAL = "partial"
    ERROR = "error"


class APIResponse(
    ResponseModel,
    Generic[DataT],
):
    success: bool = True
    status: ResponseStatus = ResponseStatus.SUCCESS
    message: str = "Request completed successfully"

    data: DataT | None = None

    request_id: str | None = None

    timestamp: datetime = Field(
        default_factory=utc_now
    )


class MessageResponse(ResponseModel):
    success: bool = True
    message: str
    request_id: str | None = None
    timestamp: datetime = Field(
        default_factory=utc_now
    )


class IdentifierResponse(ResponseModel):
    id: str
    created: bool = True


class ErrorItem(ResponseModel):
    field: str | None = None
    code: str
    message: str


class ErrorBody(ResponseModel):
    code: str
    message: str
    details: list[ErrorItem] = Field(
        default_factory=list
    )
    request_id: str | None = None
    timestamp: datetime = Field(
        default_factory=utc_now
    )


class StandardErrorResponse(ResponseModel):
    success: bool = False
    error: ErrorBody


# ============================================================
# PAGINATION
# ============================================================

class PaginationMeta(ResponseModel):
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    total_items: int = Field(ge=0)

    @computed_field
    @property
    def total_pages(self) -> int:
        return (
            self.total_items + self.page_size - 1
        ) // self.page_size

    @computed_field
    @property
    def has_next(self) -> bool:
        return self.page < self.total_pages

    @computed_field
    @property
    def has_previous(self) -> bool:
        return self.page > 1


class PaginatedResponse(
    ResponseModel,
    Generic[DataT],
):
    items: list[DataT] = Field(
        default_factory=list
    )

    pagination: PaginationMeta

    request_id: str | None = None

    timestamp: datetime = Field(
        default_factory=utc_now
    )


# ============================================================
# AUTHENTICATION AND USERS
# ============================================================

class UserStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"


class UserResponse(ResponseModel):
    user_id: str
    tenant_id: str

    display_name: str

    email: str | None = None

    roles: list[str] = Field(
        default_factory=list
    )

    status: UserStatus

    created_at: datetime
    updated_at: datetime | None = None


class AuthenticationResponse(ResponseModel):
    user: UserResponse
    token_type: str = "Bearer"
    expires_in_seconds: int = Field(ge=1)

    # Token delivery should preferably use
    # secure HTTP-only cookies when suitable.
    # Do not log or cache access tokens.
    access_token: str | None = Field(
        default=None,
        exclude=True,
    )


class PermissionResponse(ResponseModel):
    allowed: bool
    permission: str
    reason: str | None = None


# ============================================================
# PRODUCTS
# ============================================================

class ProductStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    INACTIVE = "inactive"
    DISCONTINUED = "discontinued"
    RECALLED = "recalled"


class ProductResponse(ResponseModel):
    product_id: str
    tenant_id: str

    sku: str
    name: str
    category: str

    description: str | None = None

    price: Decimal = Field(ge=0)
    currency: str = Field(
        default="INR",
        pattern=r"^[A-Z]{3}$",
    )

    status: ProductStatus

    version: int = Field(ge=1)

    created_at: datetime
    updated_at: datetime


class ProductSummaryResponse(ResponseModel):
    product_id: str
    sku: str
    name: str
    category: str
    price: Decimal
    currency: str
    status: ProductStatus


# ============================================================
# INVENTORY
# ============================================================

class StockStatus(str, Enum):
    IN_STOCK = "in_stock"
    LOW_STOCK = "low_stock"
    OUT_OF_STOCK = "out_of_stock"


class InventoryResponse(ResponseModel):
    inventory_id: str

    product_id: str
    warehouse_id: str

    quantity_on_hand: int = Field(ge=0)
    quantity_reserved: int = Field(ge=0)

    reorder_point: int = Field(
        default=0,
        ge=0,
    )

    safety_stock: int = Field(
        default=0,
        ge=0,
    )

    version: int = Field(ge=1)

    updated_at: datetime

    @model_validator(mode="after")
    def validate_stock(self):
        if (
            self.quantity_reserved
            > self.quantity_on_hand
        ):
            raise ValueError(
                "Reserved quantity exceeds "
                "on-hand quantity"
            )
        return self

    @computed_field
    @property
    def quantity_available(self) -> int:
        return (
            self.quantity_on_hand
            - self.quantity_reserved
        )

    @computed_field
    @property
    def stock_status(self) -> StockStatus:
        if self.quantity_available == 0:
            return StockStatus.OUT_OF_STOCK

        if (
            self.quantity_available
            <= self.reorder_point
        ):
            return StockStatus.LOW_STOCK

        return StockStatus.IN_STOCK


class InventoryMovementResponse(ResponseModel):
    movement_id: str

    product_id: str
    warehouse_id: str

    movement_type: str

    quantity_delta: int

    reference_id: str | None = None

    occurred_at: datetime


# ============================================================
# WAREHOUSES
# ============================================================

class WarehouseResponse(ResponseModel):
    warehouse_id: str
    tenant_id: str

    name: str
    code: str

    city: str | None = None
    region: str | None = None

    active: bool = True

    capacity_units: int | None = Field(
        default=None,
        ge=0,
    )

    utilized_units: int | None = Field(
        default=None,
        ge=0,
    )

    updated_at: datetime


# ============================================================
# SUPPLIERS
# ============================================================

class SupplierStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"


class SupplierResponse(ResponseModel):
    supplier_id: str
    tenant_id: str

    name: str
    supplier_code: str

    status: SupplierStatus

    reliability_score: float | None = Field(
        default=None,
        ge=0,
        le=1,
        allow_inf_nan=False,
    )

    risk_score: float | None = Field(
        default=None,
        ge=0,
        le=1,
        allow_inf_nan=False,
    )

    average_lead_time_days: float | None = Field(
        default=None,
        ge=0,
        allow_inf_nan=False,
    )

    updated_at: datetime


# ============================================================
# PROCUREMENT
# ============================================================

class PurchaseOrderStatus(str, Enum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    ORDERED = "ordered"
    PARTIALLY_RECEIVED = "partially_received"
    RECEIVED = "received"
    CANCELLED = "cancelled"


class PurchaseOrderLineResponse(ResponseModel):
    product_id: str

    quantity: int = Field(gt=0)

    unit_price: Decimal = Field(ge=0)

    @computed_field
    @property
    def line_total(self) -> Decimal:
        return self.quantity * self.unit_price


class PurchaseOrderResponse(ResponseModel):
    purchase_order_id: str

    supplier_id: str
    warehouse_id: str

    status: PurchaseOrderStatus

    currency: str = "INR"

    lines: list[PurchaseOrderLineResponse] = Field(
        default_factory=list
    )

    approved_by: str | None = None

    created_at: datetime
    updated_at: datetime

    @computed_field
    @property
    def total_amount(self) -> Decimal:
        return sum(
            (
                line.line_total
                for line in self.lines
            ),
            Decimal("0"),
        )


# ============================================================
# LOGISTICS
# ============================================================

class ShipmentStatus(str, Enum):
    CREATED = "created"
    READY_FOR_PICKUP = "ready_for_pickup"
    PICKED_UP = "picked_up"
    IN_TRANSIT = "in_transit"
    OUT_FOR_DELIVERY = "out_for_delivery"
    DELIVERED = "delivered"
    DELIVERY_FAILED = "delivery_failed"
    RETURNING = "returning"
    RETURNED = "returned"
    CANCELLED = "cancelled"


class ShipmentResponse(ResponseModel):
    shipment_id: str
    warehouse_id: str

    carrier_id: str | None = None

    status: ShipmentStatus

    estimated_delivery_at: datetime | None = None
    delivered_at: datetime | None = None

    route_disrupted: bool = False
    proof_of_delivery_verified: bool = False

    version: int = Field(ge=1)

    updated_at: datetime


class ETAResponse(ResponseModel):
    shipment_id: str

    predicted_delivery_at: datetime

    confidence: float | None = Field(
        default=None,
        ge=0,
        le=1,
        allow_inf_nan=False,
    )

    model_version: str | None = None

    generated_at: datetime = Field(
        default_factory=utc_now
    )


# ============================================================
# DEMAND FORECASTING
# ============================================================

class DemandForecastPoint(ResponseModel):
    forecast_date: datetime

    predicted_units: float = Field(
        ge=0,
        allow_inf_nan=False,
    )

    lower_bound: float | None = Field(
        default=None,
        ge=0,
        allow_inf_nan=False,
    )

    upper_bound: float | None = Field(
        default=None,
        ge=0,
        allow_inf_nan=False,
    )


class DemandForecastResponse(ResponseModel):
    product_id: str
    warehouse_id: str

    horizon_days: int = Field(
        ge=1,
        le=365,
    )

    model_version: str

    forecasts: list[DemandForecastPoint]

    generated_at: datetime = Field(
        default_factory=utc_now
    )


class StockoutPredictionResponse(ResponseModel):
    product_id: str
    warehouse_id: str

    probability: float = Field(
        ge=0,
        le=1,
        allow_inf_nan=False,
    )

    horizon_days: int = Field(ge=1)

    risk_level: str

    model_version: str


# ============================================================
# AI AGENTS
# ============================================================

class AgentExecutionStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AgentExecutionResponse(ResponseModel):
    execution_id: str
    agent_type: str

    status: AgentExecutionStatus

    progress_percent: float = Field(
        default=0,
        ge=0,
        le=100,
        allow_inf_nan=False,
    )

    result: dict[str, Any] | None = None

    error_code: str | None = None

    started_at: datetime | None = None
    completed_at: datetime | None = None


class AgentActionResponse(ResponseModel):
    action_id: str
    execution_id: str

    action_type: str

    requires_approval: bool = False
    approved: bool = False
    executed: bool = False

    message: str


# ============================================================
# RAG AND KNOWLEDGE
# ============================================================

class CitationResponse(ResponseModel):
    source_id: str

    title: str | None = None

    document_id: str | None = None

    page_number: int | None = Field(
        default=None,
        ge=1,
    )

    section: str | None = None

    excerpt: str | None = None


class RAGAnswerResponse(ResponseModel):
    query_id: str

    answer: str

    citations: list[CitationResponse] = Field(
        default_factory=list
    )

    grounded: bool

    confidence: float | None = Field(
        default=None,
        ge=0,
        le=1,
        allow_inf_nan=False,
    )

    model_name: str | None = None

    retrieval_latency_ms: float | None = Field(
        default=None,
        ge=0,
        allow_inf_nan=False,
    )

    generation_latency_ms: float | None = Field(
        default=None,
        ge=0,
        allow_inf_nan=False,
    )


# ============================================================
# ANALYTICS
# ============================================================

class MetricResponse(ResponseModel):
    name: str
    value: float = Field(
        allow_inf_nan=False
    )

    unit: str | None = None

    previous_value: float | None = Field(
        default=None,
        allow_inf_nan=False,
    )

    measured_at: datetime


class AnalyticsDashboardResponse(ResponseModel):
    dashboard_id: str
    title: str

    metrics: list[MetricResponse] = Field(
        default_factory=list
    )

    generated_at: datetime = Field(
        default_factory=utc_now
    )


# ============================================================
# ALERTS AND NOTIFICATIONS
# ============================================================

class AlertSeverity(str, Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AlertStatus(str, Enum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


class AlertResponse(ResponseModel):
    alert_id: str

    category: str

    severity: AlertSeverity
    status: AlertStatus

    title: str
    message: str

    resource_id: str | None = None

    created_at: datetime
    updated_at: datetime


class NotificationResponse(ResponseModel):
    notification_id: str

    recipient_id: str

    channel: str

    title: str
    message: str

    read: bool = False

    created_at: datetime


# ============================================================
# FEEDBACK
# ============================================================

class FeedbackResponse(ResponseModel):
    feedback_id: str

    source: str
    category: str

    rating: int | None = Field(
        default=None,
        ge=1,
        le=5,
    )

    sentiment: str

    status: str

    created_at: datetime


# ============================================================
# REPORTING
# ============================================================

class ReportStatus(str, Enum):
    QUEUED = "queued"
    GENERATING = "generating"
    COMPLETED = "completed"
    FAILED = "failed"


class ReportResponse(ResponseModel):
    report_id: str
    report_type: str

    status: ReportStatus

    generated_at: datetime | None = None

    # Only issue URLs after checking
    # authorization and expiry.
    download_url: str | None = None


# ============================================================
# SYSTEM HEALTH
# ============================================================

class ServiceHealthStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class HealthResponse(ResponseModel):
    service: str

    status: ServiceHealthStatus

    timestamp: datetime = Field(
        default_factory=utc_now
    )


# ============================================================
# EXPORTS
# ============================================================

__all__ = [
    "APIResponse",
    "MessageResponse",
    "IdentifierResponse",
    "ErrorItem",
    "ErrorBody",
    "StandardErrorResponse",
    "PaginationMeta",
    "PaginatedResponse",
    "UserResponse",
    "AuthenticationResponse",
    "PermissionResponse",
    "ProductResponse",
    "ProductSummaryResponse",
    "InventoryResponse",
    "InventoryMovementResponse",
    "WarehouseResponse",
    "SupplierResponse",
    "PurchaseOrderLineResponse",
    "PurchaseOrderResponse",
    "ShipmentResponse",
    "ETAResponse",
    "DemandForecastPoint",
    "DemandForecastResponse",
    "StockoutPredictionResponse",
    "AgentExecutionResponse",
    "AgentActionResponse",
    "CitationResponse",
    "RAGAnswerResponse",
    "MetricResponse",
    "AnalyticsDashboardResponse",
    "AlertResponse",
    "NotificationResponse",
    "FeedbackResponse",
    "ReportResponse",
    "HealthResponse",
]
