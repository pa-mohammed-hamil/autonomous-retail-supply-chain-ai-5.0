from __future__ import annotations

"""Planned module: constants. Implementation pending."""

"""
backend/constants.py

Autonomous Retail Supply Chain AI 5.0

Centralized application constants.

Python 3.10+

Features:
- Application metadata
- Inventory and procurement constants
- Warehouse and logistics statuses
- User roles and permissions
- Notification and alert categories
- AI agent and model identifiers
- Financial and forecasting defaults
- API and pagination limits
- Database and caching defaults

Important:
Operational thresholds are defaults.
Production values should be configurable
per tenant, product, warehouse, and policy.
"""


from enum import Enum, IntEnum
from decimal import Decimal
from typing import Final


# ==================================================
# 1. APPLICATION
# ==================================================

APP_NAME: Final[str] = (
    "Autonomous Retail Supply Chain AI"
)

APP_VERSION: Final[str] = "5.0"

API_VERSION: Final[str] = "v1"

API_PREFIX: Final[str] = "/api/v1"

DEFAULT_TIMEZONE: Final[str] = "UTC"

DEFAULT_CURRENCY: Final[str] = "INR"


class Environment(str, Enum):
    DEVELOPMENT = "development"
    TESTING = "testing"
    STAGING = "staging"
    PRODUCTION = "production"


# ==================================================
# 2. INVENTORY
# ==================================================

class InventoryStatus(str, Enum):
    AVAILABLE = "available"
    LOW_STOCK = "low_stock"
    OUT_OF_STOCK = "out_of_stock"
    RESERVED = "reserved"
    DAMAGED = "damaged"
    QUARANTINED = "quarantined"


class InventoryMovementType(str, Enum):
    RECEIVE = "receive"
    SALE = "sale"
    RETURN = "return"
    TRANSFER_IN = "transfer_in"
    TRANSFER_OUT = "transfer_out"
    ADJUSTMENT = "adjustment"
    RESERVATION = "reservation"
    RELEASE = "release"


DEFAULT_REORDER_POINT: Final[int] = 20
DEFAULT_SAFETY_STOCK: Final[int] = 10
DEFAULT_REORDER_QUANTITY: Final[int] = 100

LOW_STOCK_THRESHOLD_PERCENT: Final[
    Decimal
] = Decimal("20.0")

CRITICAL_STOCK_THRESHOLD_PERCENT: Final[
    Decimal
] = Decimal("5.0")


# ==================================================
# 3. PRODUCTS
# ==================================================

class ProductStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    DISCONTINUED = "discontinued"
    OUT_OF_STOCK = "out_of_stock"


class ProductCategory(str, Enum):
    GROCERY = "grocery"
    DAIRY = "dairy"
    BAKERY = "bakery"
    BEVERAGES = "beverages"
    SNACKS = "snacks"
    PERSONAL_CARE = "personal_care"
    HOUSEHOLD = "household"
    ELECTRONICS = "electronics"
    OTHER = "other"


MAX_PRODUCT_NAME_LENGTH: Final[int] = 200
MAX_SKU_LENGTH: Final[int] = 64


# ==================================================
# 4. SUPPLIERS
# ==================================================

class SupplierStatus(str, Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    INACTIVE = "inactive"
    BLACKLISTED = "blacklisted"


class SupplierRiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


DEFAULT_SUPPLIER_LEAD_TIME_DAYS: Final[int] = 7

SUPPLIER_RISK_HIGH_THRESHOLD: Final[
    Decimal
] = Decimal("0.70")


# ==================================================
# 5. PROCUREMENT
# ==================================================

class PurchaseOrderStatus(str, Enum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    SENT = "sent"
    PARTIALLY_RECEIVED = "partially_received"
    RECEIVED = "received"
    CANCELLED = "cancelled"


class ProcurementPriority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


DEFAULT_PURCHASE_APPROVAL_LIMIT: Final[
    Decimal
] = Decimal("50000.00")


# ==================================================
# 6. WAREHOUSES
# ==================================================

class WarehouseStatus(str, Enum):
    ACTIVE = "active"
    MAINTENANCE = "maintenance"
    INACTIVE = "inactive"


class WarehouseZoneType(str, Enum):
    GENERAL = "general"
    COLD_STORAGE = "cold_storage"
    HAZARDOUS = "hazardous"
    HIGH_VALUE = "high_value"
    RETURNS = "returns"


WAREHOUSE_WARNING_UTILIZATION: Final[
    Decimal
] = Decimal("80.0")

WAREHOUSE_CRITICAL_UTILIZATION: Final[
    Decimal
] = Decimal("90.0")


# ==================================================
# 7. LOGISTICS
# ==================================================

class ShipmentStatus(str, Enum):
    CREATED = "created"
    ASSIGNED = "assigned"
    DISPATCHED = "dispatched"
    IN_TRANSIT = "in_transit"
    DELAYED = "delayed"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    FAILED = "failed"


class TransportMode(str, Enum):
    ROAD = "road"
    RAIL = "rail"
    AIR = "air"
    SEA = "sea"


DEFAULT_DELIVERY_DELAY_HOURS: Final[int] = 24


# ==================================================
# 8. USERS AND SECURITY
# ==================================================

class UserRole(str, Enum):
    ADMIN = "admin"
    WAREHOUSE_MANAGER = "warehouse_manager"
    INVENTORY_MANAGER = "inventory_manager"
    PROCUREMENT_MANAGER = "procurement_manager"
    LOGISTICS_MANAGER = "logistics_manager"
    ANALYST = "analyst"
    VIEWER = "viewer"


class UserStatus(str, Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DISABLED = "disabled"


class Permission(str, Enum):
    PRODUCT_READ = "product:read"
    PRODUCT_WRITE = "product:write"

    INVENTORY_READ = "inventory:read"
    INVENTORY_WRITE = "inventory:write"

    SUPPLIER_READ = "supplier:read"
    SUPPLIER_WRITE = "supplier:write"

    PROCUREMENT_READ = "procurement:read"
    PROCUREMENT_WRITE = "procurement:write"
    PROCUREMENT_APPROVE = "procurement:approve"

    WAREHOUSE_READ = "warehouse:read"
    WAREHOUSE_WRITE = "warehouse:write"

    LOGISTICS_READ = "logistics:read"
    LOGISTICS_WRITE = "logistics:write"

    ANALYTICS_READ = "analytics:read"

    USER_MANAGE = "user:manage"
    AUDIT_READ = "audit:read"


# Illustrative permissions only.
# Authorization services must enforce
# actual policies and tenant restrictions.

ROLE_PERMISSIONS: Final[
    dict[UserRole, frozenset[Permission]]
] = {
    UserRole.ADMIN: frozenset(Permission),

    UserRole.WAREHOUSE_MANAGER: frozenset({
        Permission.INVENTORY_READ,
        Permission.INVENTORY_WRITE,
        Permission.WAREHOUSE_READ,
        Permission.WAREHOUSE_WRITE,
        Permission.LOGISTICS_READ,
    }),

    UserRole.INVENTORY_MANAGER: frozenset({
        Permission.PRODUCT_READ,
        Permission.INVENTORY_READ,
        Permission.INVENTORY_WRITE,
        Permission.WAREHOUSE_READ,
        Permission.ANALYTICS_READ,
    }),

    UserRole.PROCUREMENT_MANAGER: frozenset({
        Permission.SUPPLIER_READ,
        Permission.PROCUREMENT_READ,
        Permission.PROCUREMENT_WRITE,
        Permission.PROCUREMENT_APPROVE,
        Permission.ANALYTICS_READ,
    }),

    UserRole.LOGISTICS_MANAGER: frozenset({
        Permission.LOGISTICS_READ,
        Permission.LOGISTICS_WRITE,
        Permission.WAREHOUSE_READ,
        Permission.ANALYTICS_READ,
    }),

    UserRole.ANALYST: frozenset({
        Permission.ANALYTICS_READ,
        Permission.PRODUCT_READ,
        Permission.INVENTORY_READ,
    }),

    UserRole.VIEWER: frozenset({
        Permission.PRODUCT_READ,
        Permission.INVENTORY_READ,
    }),
}


# ==================================================
# 9. NOTIFICATIONS
# ==================================================

class NotificationChannel(str, Enum):
    DASHBOARD = "dashboard"
    EMAIL = "email"
    SMS = "sms"
    PUSH = "push"
    WORKPLACE = "workplace"


class NotificationSeverity(str, Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class NotificationCategory(str, Enum):
    INVENTORY = "inventory"
    STOCKOUT = "stockout"
    SUPPLIER = "supplier"
    WAREHOUSE = "warehouse"
    QUALITY = "quality"
    LOGISTICS = "logistics"
    FINANCE = "finance"
    SECURITY = "security"
    INCIDENT = "incident"
    ESCALATION = "escalation"
    GENERAL = "general"


# ==================================================
# 10. ALERTS
# ==================================================

class AlertStatus(str, Enum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    CLOSED = "closed"


class AlertSeverity(IntEnum):
    INFO = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


# ==================================================
# 11. AI AGENTS
# ==================================================

class AgentType(str, Enum):
    SUPERVISOR = "supervisor"
    INVENTORY = "inventory"
    DEMAND_FORECASTING = "demand_forecasting"
    PROCUREMENT = "procurement"
    SUPPLIER_RISK = "supplier_risk"
    WAREHOUSE = "warehouse"
    LOGISTICS = "logistics"
    ROUTE_OPTIMIZATION = "route_optimization"
    PRICING = "pricing"
    CUSTOMER_INTELLIGENCE = "customer_intelligence"
    FINANCIAL = "financial"
    PRODUCT_QUALITY = "product_quality"
    REPLENISHMENT = "replenishment"
    STOCKOUT_PREVENTION = "stockout_prevention"
    MARKET_RESEARCH = "market_research"
    REPORTING = "reporting"
    INCIDENT_RESPONSE = "incident_response"
    RAG_KNOWLEDGE = "rag_knowledge"
    APPROVAL = "approval"
    NOTIFICATION = "notification"


class AgentExecutionStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# ==================================================
# 12. MACHINE LEARNING
# ==================================================

class MLTaskType(str, Enum):
    CLASSIFICATION = "classification"
    REGRESSION = "regression"
    FORECASTING = "forecasting"
    ANOMALY_DETECTION = "anomaly_detection"
    RANKING = "ranking"


class ModelLifecycleStatus(str, Enum):
    DEVELOPMENT = "development"
    VALIDATION = "validation"
    STAGING = "staging"
    PRODUCTION = "production"
    ARCHIVED = "archived"


DEFAULT_FORECAST_HORIZON_DAYS: Final[int] = 30
DEFAULT_TRAIN_TEST_SPLIT: Final[float] = 0.2
DEFAULT_RANDOM_SEED: Final[int] = 42


# ==================================================
# 13. RAG AND LLM
# ==================================================

class RetrievalMode(str, Enum):
    DENSE = "dense"
    SPARSE = "sparse"
    HYBRID = "hybrid"


DEFAULT_RAG_TOP_K: Final[int] = 5
MAX_RAG_TOP_K: Final[int] = 50
DEFAULT_CHUNK_SIZE: Final[int] = 800
DEFAULT_CHUNK_OVERLAP: Final[int] = 120

DEFAULT_LLM_TEMPERATURE: Final[float] = 0.2


# ==================================================
# 14. FINANCIAL
# ==================================================

class FinancialTransactionType(str, Enum):
    REVENUE = "revenue"
    EXPENSE = "expense"
    REFUND = "refund"
    ADJUSTMENT = "adjustment"


MONEY_PRECISION: Final[
    Decimal
] = Decimal("0.01")

DEFAULT_TAX_RATE: Final[
    Decimal
] = Decimal("0.00")


# ==================================================
# 15. DATABASE
# ==================================================

DEFAULT_DB_POOL_SIZE: Final[int] = 10
DEFAULT_DB_MAX_OVERFLOW: Final[int] = 20
DEFAULT_DB_POOL_TIMEOUT: Final[int] = 30
DEFAULT_DB_POOL_RECYCLE: Final[int] = 1800

DEFAULT_TRANSACTION_RETRIES: Final[int] = 3
DEFAULT_STATEMENT_TIMEOUT_MS: Final[int] = 30000


# ==================================================
# 16. REDIS CACHE
# ==================================================

DEFAULT_CACHE_TTL_SECONDS: Final[int] = 300
PRODUCT_CACHE_TTL_SECONDS: Final[int] = 600
SUPPLIER_CACHE_TTL_SECONDS: Final[int] = 300
INVENTORY_CACHE_TTL_SECONDS: Final[int] = 10
ANALYTICS_CACHE_TTL_SECONDS: Final[int] = 120
FORECAST_CACHE_TTL_SECONDS: Final[int] = 1800


# ==================================================
# 17. API AND PAGINATION
# ==================================================

DEFAULT_PAGE_SIZE: Final[int] = 50
MAX_PAGE_SIZE: Final[int] = 500

DEFAULT_REQUEST_TIMEOUT_SECONDS: Final[int] = 30

MAX_BATCH_SIZE: Final[int] = 1000


# ==================================================
# 18. AUDIT AND EVENT TYPES
# ==================================================

class AuditAction(str, Enum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    LOGIN = "login"
    LOGOUT = "logout"
    APPROVE = "approve"
    REJECT = "reject"
    EXPORT = "export"
    ACCESS_DENIED = "access_denied"


class EventType(str, Enum):
    PRODUCT_CREATED = "product.created"
    INVENTORY_LOW = "inventory.low"
    INVENTORY_STOCKOUT = "inventory.stockout"
    INVENTORY_TRANSFERRED = "inventory.transferred"
    SUPPLIER_DELAYED = "supplier.delayed"
    PURCHASE_ORDER_CREATED = "purchase_order.created"
    PURCHASE_ORDER_APPROVED = "purchase_order.approved"
    SHIPMENT_DELAYED = "shipment.delayed"
    SHIPMENT_DELIVERED = "shipment.delivered"
    INCIDENT_CREATED = "incident.created"
    INCIDENT_RESOLVED = "incident.resolved"
    FORECAST_COMPLETED = "forecast.completed"


# ==================================================
# 19. HELPERS
# ==================================================

def has_permission(
    role: UserRole,
    permission: Permission,
) -> bool:
    """
    Static permission lookup.

    Does not replace authenticated,
    tenant-scoped authorization.
    """
    return permission in ROLE_PERMISSIONS.get(
        role,
        frozenset(),
    )


def is_critical_alert(
    severity: AlertSeverity,
) -> bool:
    return severity >= AlertSeverity.CRITICAL


def validate_page_size(
    page_size: int,
) -> int:
    if (
        isinstance(page_size, bool)
        or not isinstance(page_size, int)
        or page_size < 1
    ):
        raise ValueError(
            "page_size must be a positive integer"
        )

    return min(page_size, MAX_PAGE_SIZE)
