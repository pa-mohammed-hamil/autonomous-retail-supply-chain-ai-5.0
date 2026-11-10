from __future__ import annotations

"""Planned module: pricing. Implementation pending."""

"""
backend/pricing.py

Autonomous Retail Supply Chain AI 5.0
Product Pricing & Price Intelligence API

Python 3.11+
Dependencies:
    fastapi
    pydantic >= 2

Features:
    - Product price records
    - Cost and profit margin calculations
    - Discount simulation
    - Competitor price comparisons
    - Rule-based price recommendations
    - Human approval of price changes
    - Price version history
    - Idempotent product price creation
    - Optimistic concurrency
    - Tenant/warehouse access control
    - Pricing analytics

Security:
    - No automatic publishing of price changes
    - Price changes require explicit approval
    - No cross-tenant access
    - Warehouse-scoped permissions
    - No external marketplace modifications

Prototype limitations:
    - In-memory storage
    - No real market price feeds
    - No payment/tax calculation
    - No currency conversion
    - No durable approval workflow
    - No real ERP/POS synchronization
"""


import asyncio
import hashlib
import json
import secrets

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum

from fastapi import (
    APIRouter,
    HTTPException,
    Query,
)

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)

from backend.permissions import (
    CurrentPrincipal,
    Permission,
    Principal,
    ResourceContext,
    permission_engine,
)


API_PREFIX = "/api/v1/pricing"

MAX_PRICE_RECORDS_PER_TENANT = 100000
MAX_HISTORY_PER_PRODUCT = 1000
MAX_PROPOSALS_PER_PRODUCT = 100
MAX_IDEMPOTENCY_KEYS = 150000
MAX_LIST_LIMIT = 200

MONEY_QUANTUM = Decimal("0.01")
PERCENT_QUANTUM = Decimal("0.01")


# ============================================================
# ENUMS
# ============================================================

class PricingStrategy(str, Enum):
    COST_PLUS = "cost_plus"
    COMPETITIVE = "competitive"
    MARGIN_TARGET = "margin_target"
    MANUAL = "manual"


class PriceStatus(str, Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"


class PriceProposalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    APPLIED = "applied"


class PriceChangeReason(str, Enum):
    COST_CHANGE = "cost_change"
    MARKET_CHANGE = "market_change"
    PROMOTION = "promotion"
    MARGIN_ADJUSTMENT = "margin_adjustment"
    MANUAL_REVIEW = "manual_review"


class PriceRiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


# ============================================================
# REQUEST SCHEMAS
# ============================================================

class PriceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    warehouse_id: str = Field(
        min_length=1,
        max_length=128,
    )

    product_id: str = Field(
        min_length=1,
        max_length=128,
    )

    currency: str = Field(
        default="INR",
        pattern=r"^[A-Z]{3}$",
    )

    cost_price: Decimal = Field(
        ge=0,
        max_digits=16,
        decimal_places=2,
    )

    selling_price: Decimal = Field(
        gt=0,
        max_digits=16,
        decimal_places=2,
    )

    minimum_margin_percent: Decimal = Field(
        default=Decimal("10"),
        ge=0,
        lt=100,
        max_digits=5,
        decimal_places=2,
    )

    maximum_discount_percent: Decimal = Field(
        default=Decimal("30"),
        ge=0,
        le=100,
        max_digits=5,
        decimal_places=2,
    )

    strategy: PricingStrategy = (
        PricingStrategy.COST_PLUS
    )

    source_request_id: str = Field(
        min_length=8,
        max_length=128,
    )


class PriceProposalCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposed_price: Decimal = Field(
        gt=0,
        max_digits=16,
        decimal_places=2,
    )

    reason: PriceChangeReason

    explanation: str = Field(
        min_length=5,
        max_length=2000,
    )

    expected_version: int = Field(ge=1)

    source_request_id: str = Field(
        min_length=8,
        max_length=128,
    )


class ProposalDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_price_version: int = Field(
        ge=1
    )

    expected_proposal_version: int = Field(
        ge=1
    )

    notes: str = Field(
        default="",
        max_length=1000,
    )


class PriceVersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)


class DiscountSimulationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    discount_percent: Decimal = Field(
        ge=0,
        le=100,
        max_digits=5,
        decimal_places=2,
    )


class CompetitorPriceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    competitor_reference: str = Field(
        min_length=1,
        max_length=128,
    )

    competitor_price: Decimal = Field(
        gt=0,
        max_digits=16,
        decimal_places=2,
    )


class CompetitorComparisonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    currency: str = Field(
        pattern=r"^[A-Z]{3}$",
    )

    competitors: list[CompetitorPriceInput] = Field(
        min_length=1,
        max_length=50,
    )


class PriceRecommendationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy: PricingStrategy

    target_margin_percent: Decimal = Field(
        default=Decimal("20"),
        ge=0,
        lt=100,
        max_digits=5,
        decimal_places=2,
    )

    markup_percent: Decimal = Field(
        default=Decimal("25"),
        ge=0,
        le=500,
        max_digits=6,
        decimal_places=2,
    )

    competitor_price: Decimal | None = Field(
        default=None,
        gt=0,
        max_digits=16,
        decimal_places=2,
    )

    @model_validator(mode="after")
    def validate_strategy(self):

        if (
            self.strategy
            == PricingStrategy.COMPETITIVE
            and self.competitor_price is None
        ):
            raise ValueError(
                "Competitive pricing requires competitor_price"
            )

        return self


# ============================================================
# RESPONSE SCHEMAS
# ============================================================

class PriceResponse(BaseModel):
    price_id: str

    warehouse_id: str
    product_id: str
    currency: str

    cost_price: Decimal
    selling_price: Decimal

    gross_profit: Decimal
    margin_percent: Decimal
    markup_percent: Decimal

    minimum_margin_percent: Decimal
    maximum_discount_percent: Decimal

    strategy: PricingStrategy
    status: PriceStatus

    version: int

    created_at: datetime
    updated_at: datetime


class PriceHistoryResponse(BaseModel):
    history_id: str
    price_id: str

    old_price: Decimal
    new_price: Decimal

    changed_by: str
    reason: PriceChangeReason

    created_at: datetime


class PriceProposalResponse(BaseModel):
    proposal_id: str
    price_id: str

    proposed_price: Decimal

    reason: PriceChangeReason
    explanation: str

    status: PriceProposalStatus

    requested_by: str
    reviewed_by: str | None

    review_notes: str | None

    version: int
    base_price_version: int

    created_at: datetime
    reviewed_at: datetime | None


class PriceDetailResponse(PriceResponse):
    proposals: list[PriceProposalResponse]
    history: list[PriceHistoryResponse]


class DiscountSimulationResponse(BaseModel):
    original_price: Decimal
    discount_percent: Decimal
    discounted_price: Decimal

    gross_profit: Decimal
    margin_percent: Decimal

    within_discount_limit: bool
    within_margin_limit: bool
    allowed: bool


class CompetitorComparisonItem(BaseModel):
    competitor_reference: str
    competitor_price: Decimal

    difference_amount: Decimal
    difference_percent: Decimal


class CompetitorComparisonResponse(BaseModel):
    product_id: str
    currency: str

    current_price: Decimal

    lowest_competitor_price: Decimal
    highest_competitor_price: Decimal
    average_competitor_price: Decimal

    comparisons: list[
        CompetitorComparisonItem
    ]


class PriceRecommendationResponse(BaseModel):
    strategy: PricingStrategy

    current_price: Decimal
    recommended_price: Decimal

    expected_profit: Decimal
    expected_margin_percent: Decimal

    risk_level: PriceRiskLevel

    explanation: str

    requires_human_approval: bool = True


class PricingAnalyticsResponse(BaseModel):
    total_products: int
    active_prices: int
    suspended_prices: int

    average_margin_percent: Decimal | None

    pending_proposals: int
    approved_proposals: int
    rejected_proposals: int
    applied_proposals: int

    below_minimum_margin_products: int


# ============================================================
# INTERNAL RECORDS
# ============================================================

@dataclass
class PriceProposalRecord:
    proposal_id: str
    price_id: str

    proposed_price: Decimal
    reason: PriceChangeReason
    explanation: str

    requested_by: str

    base_price_version: int

    status: PriceProposalStatus = (
        PriceProposalStatus.PENDING
    )

    reviewed_by: str | None = None
    review_notes: str | None = None

    version: int = 1

    created_at: datetime = field(
        default_factory=lambda: datetime.now(
            timezone.utc
        )
    )

    reviewed_at: datetime | None = None


@dataclass
class PriceRecord:
    price_id: str
    tenant_id: str

    warehouse_id: str
    product_id: str
    currency: str

    cost_price: Decimal
    selling_price: Decimal

    minimum_margin_percent: Decimal
    maximum_discount_percent: Decimal

    strategy: PricingStrategy

    status: PriceStatus = PriceStatus.ACTIVE

    proposals: dict[
        str,
        PriceProposalRecord,
    ] = field(default_factory=dict)

    history: list[
        PriceHistoryResponse
    ] = field(default_factory=list)

    version: int = 1

    created_at: datetime = field(
        default_factory=lambda: datetime.now(
            timezone.utc
        )
    )

    updated_at: datetime = field(
        default_factory=lambda: datetime.now(
            timezone.utc
        )
    )


# ============================================================
# CALCULATION ENGINE
# ============================================================

def money(value: Decimal) -> Decimal:

    return value.quantize(
        MONEY_QUANTUM,
        rounding=ROUND_HALF_UP,
    )


def percent(value: Decimal) -> Decimal:

    return value.quantize(
        PERCENT_QUANTUM,
        rounding=ROUND_HALF_UP,
    )


class PricingEngine:

    @staticmethod
    def gross_profit(
        selling_price: Decimal,
        cost_price: Decimal,
    ) -> Decimal:

        return money(
            selling_price - cost_price
        )

    @staticmethod
    def margin_percent(
        selling_price: Decimal,
        cost_price: Decimal,
    ) -> Decimal:

        if selling_price <= 0:
            return Decimal("0")

        return percent(
            (
                selling_price - cost_price
            )
            / selling_price
            * Decimal("100")
        )

    @staticmethod
    def markup_percent(
        selling_price: Decimal,
        cost_price: Decimal,
    ) -> Decimal:

        if cost_price <= 0:
            return Decimal("0")

        return percent(
            (
                selling_price - cost_price
            )
            / cost_price
            * Decimal("100")
        )

    @staticmethod
    def minimum_allowed_price(
        cost_price: Decimal,
        minimum_margin_percent: Decimal,
    ) -> Decimal:

        denominator = (
            Decimal("1")
            - minimum_margin_percent
            / Decimal("100")
        )

        return money(
            cost_price / denominator
        )

    @staticmethod
    def calculate_recommendation(
        record: PriceRecord,
        payload: PriceRecommendationRequest,
    ) -> PriceRecommendationResponse:

        cost = record.cost_price
        current = record.selling_price

        if payload.strategy == PricingStrategy.COST_PLUS:

            proposed = cost * (
                Decimal("1")
                + payload.markup_percent
                / Decimal("100")
            )

            explanation = (
                "Cost-plus pricing based on "
                "the requested markup percentage."
            )

        elif payload.strategy == PricingStrategy.MARGIN_TARGET:

            proposed = cost / (
                Decimal("1")
                - payload.target_margin_percent
                / Decimal("100")
            )

            explanation = (
                "Selling price calculated to target "
                "the requested gross margin."
            )

        elif payload.strategy == PricingStrategy.COMPETITIVE:

            proposed = payload.competitor_price

            explanation = (
                "Recommendation uses the supplied "
                "competitor price. Competitor data "
                "has not been independently verified."
            )

        else:

            proposed = current

            explanation = (
                "Manual pricing preserves "
                "the current selling price."
            )

        proposed = money(proposed)

        minimum_price = PricingEngine.minimum_allowed_price(
            cost,
            record.minimum_margin_percent,
        )

        if proposed < minimum_price:
            proposed = minimum_price

            explanation += (
                " Adjusted to respect "
                "the minimum margin policy."
            )

        if proposed <= 0:
            proposed = Decimal("0.01")

        margin = PricingEngine.margin_percent(
            proposed,
            cost,
        )

        change_percent = (
            abs(proposed - current)
            / current
            * Decimal("100")
        )

        if change_percent >= Decimal("25"):
            risk = PriceRiskLevel.HIGH

        elif change_percent >= Decimal("10"):
            risk = PriceRiskLevel.MEDIUM

        else:
            risk = PriceRiskLevel.LOW

        return PriceRecommendationResponse(
            strategy=payload.strategy,
            current_price=current,
            recommended_price=proposed,
            expected_profit=PricingEngine.gross_profit(
                proposed,
                cost,
            ),
            expected_margin_percent=margin,
            risk_level=risk,
            explanation=explanation,
        )


pricing_engine = PricingEngine()


# ============================================================
# HELPERS
# ============================================================

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def fingerprint(
    operation: str,
    payload: BaseModel,
    resource_id: str | None = None,
) -> str:

    canonical = json.dumps(
        {
            "operation": operation,
            "resource_id": resource_id,
            "payload": payload.model_dump(
                mode="json",
                exclude={"source_request_id"},
            ),
        },
        sort_keys=True,
        separators=(",", ":"),
    )

    return hashlib.sha256(
        canonical.encode("utf-8")
    ).hexdigest()


def require_pricing_access(
    principal: Principal,
    warehouse_id: str,
    *,
    write: bool,
) -> None:

    # Temporary mapping to existing permissions.
    #
    # Production should define:
    # PRICING_READ
    # PRICING_WRITE
    # PRICING_APPROVE

    permission = (
        Permission.PRODUCT_WRITE
        if write
        else Permission.PRODUCT_READ
    )

    if (
        principal.allowed_warehouse_ids is not None
        and warehouse_id
        not in principal.allowed_warehouse_ids
    ):
        raise HTTPException(
            status_code=403,
            detail="Warehouse access denied",
        )

    decision = permission_engine.evaluate(
        principal,
        permission,
        ResourceContext(
            tenant_id=principal.tenant_id,
            warehouse_id=warehouse_id,
        ),
    )

    if not decision.allowed:
        raise HTTPException(
            status_code=403,
            detail="Pricing access denied",
        )


def to_price(
    record: PriceRecord,
) -> PriceResponse:

    return PriceResponse(
        price_id=record.price_id,
        warehouse_id=record.warehouse_id,
        product_id=record.product_id,
        currency=record.currency,
        cost_price=record.cost_price,
        selling_price=record.selling_price,
        gross_profit=pricing_engine.gross_profit(
            record.selling_price,
            record.cost_price,
        ),
        margin_percent=pricing_engine.margin_percent(
            record.selling_price,
            record.cost_price,
        ),
        markup_percent=pricing_engine.markup_percent(
            record.selling_price,
            record.cost_price,
        ),
        minimum_margin_percent=(
            record.minimum_margin_percent
        ),
        maximum_discount_percent=(
            record.maximum_discount_percent
        ),
        strategy=record.strategy,
        status=record.status,
        version=record.version,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def to_proposal(
    record: PriceProposalRecord,
) -> PriceProposalResponse:

    return PriceProposalResponse(
        proposal_id=record.proposal_id,
        price_id=record.price_id,
        proposed_price=record.proposed_price,
        reason=record.reason,
        explanation=record.explanation,
        status=record.status,
        requested_by=record.requested_by,
        reviewed_by=record.reviewed_by,
        review_notes=record.review_notes,
        version=record.version,
        base_price_version=record.base_price_version,
        created_at=record.created_at,
        reviewed_at=record.reviewed_at,
    )


def to_detail(
    record: PriceRecord,
) -> PriceDetailResponse:

    return PriceDetailResponse(
        **to_price(record).model_dump(),
        proposals=[
            to_proposal(proposal)
            for proposal in record.proposals.values()
        ],
        history=list(record.history),
    )


# ============================================================
# PRICING STORE
# ============================================================

class PricingStore:

    def __init__(self):

        self._prices: dict[
            str,
            PriceRecord,
        ] = {}

        self._product_index: dict[
            tuple[str, str, str],
            str,
        ] = {}

        self._idempotency: dict[
            tuple[str, str, str],
            tuple[str, str],
        ] = {}

        self._lock = asyncio.Lock()

    def _get(
        self,
        principal: Principal,
        price_id: str,
        *,
        write: bool,
    ) -> PriceRecord:

        record = self._prices.get(
            price_id
        )

        if (
            record is None
            or record.tenant_id
            != principal.tenant_id
        ):
            raise HTTPException(
                status_code=404,
                detail="Price record not found",
            )

        require_pricing_access(
            principal,
            record.warehouse_id,
            write=write,
        )

        return record

    @staticmethod
    def _check_version(
        actual: int,
        expected: int,
    ) -> None:

        if actual != expected:
            raise HTTPException(
                status_code=409,
                detail="Version conflict",
            )

    @staticmethod
    def _check_margin(
        record: PriceRecord,
        proposed_price: Decimal,
    ) -> None:

        margin = pricing_engine.margin_percent(
            proposed_price,
            record.cost_price,
        )

        if margin < record.minimum_margin_percent:
            raise HTTPException(
                status_code=422,
                detail="Price violates minimum margin",
            )

    async def create(
        self,
        *,
        principal: Principal,
        payload: PriceCreate,
    ) -> PriceResponse:

        require_pricing_access(
            principal,
            payload.warehouse_id,
            write=True,
        )

        key = (
            principal.tenant_id,
            principal.principal_id,
            payload.source_request_id,
        )

        request_hash = fingerprint(
            "create_price",
            payload,
        )

        product_key = (
            principal.tenant_id,
            payload.warehouse_id,
            payload.product_id,
        )

        async with self._lock:

            previous = self._idempotency.get(
                key
            )

            if previous:

                old_hash, price_id = previous

                if old_hash != request_hash:
                    raise HTTPException(
                        status_code=409,
                        detail="Idempotency conflict",
                    )

                return to_price(
                    self._get(
                        principal,
                        price_id,
                        write=False,
                    )
                )

            if product_key in self._product_index:
                raise HTTPException(
                    status_code=409,
                    detail="Product already has a price record",
                )

            tenant_count = sum(
                record.tenant_id
                == principal.tenant_id
                for record in self._prices.values()
            )

            if (
                tenant_count
                >= MAX_PRICE_RECORDS_PER_TENANT
                or len(self._idempotency)
                >= MAX_IDEMPOTENCY_KEYS
            ):
                raise HTTPException(
                    status_code=503,
                    detail="Pricing capacity reached",
                )

            record = PriceRecord(
                price_id=secrets.token_urlsafe(20),
                tenant_id=principal.tenant_id,
                warehouse_id=payload.warehouse_id,
                product_id=payload.product_id,
                currency=payload.currency,
                cost_price=payload.cost_price,
                selling_price=payload.selling_price,
                minimum_margin_percent=(
                    payload.minimum_margin_percent
                ),
                maximum_discount_percent=(
                    payload.maximum_discount_percent
                ),
                strategy=payload.strategy,
            )

            self._check_margin(
                record,
                record.selling_price,
            )

            self._prices[
                record.price_id
            ] = record

            self._product_index[
                product_key
            ] = record.price_id

            self._idempotency[key] = (
                request_hash,
                record.price_id,
            )

            return to_price(record)

    async def get(
        self,
        *,
        principal: Principal,
        price_id: str,
    ) -> PriceDetailResponse:

        async with self._lock:

            return to_detail(
                self._get(
                    principal,
                    price_id,
                    write=False,
                )
            )

    async def list_prices(
        self,
        *,
        principal: Principal,
        warehouse_id: str | None,
        limit: int,
    ) -> list[PriceResponse]:

        if warehouse_id is not None:
            require_pricing_access(
                principal,
                warehouse_id,
                write=False,
            )

        async with self._lock:

            records = [
                record
                for record in self._prices.values()
                if (
                    record.tenant_id
                    == principal.tenant_id
                    and (
                        warehouse_id is None
                        or record.warehouse_id
                        == warehouse_id
                    )
                )
            ]

            records.sort(
                key=lambda item: item.created_at,
                reverse=True,
            )

            results = []

            for record in records:

                try:
                    require_pricing_access(
                        principal,
                        record.warehouse_id,
                        write=False,
                    )

                except HTTPException:
                    continue

                results.append(
                    to_price(record)
                )

                if len(results) >= limit:
                    break

            return results

    async def create_proposal(
        self,
        *,
        principal: Principal,
        price_id: str,
        payload: PriceProposalCreate,
    ) -> PriceProposalResponse:

        key = (
            principal.tenant_id,
            principal.principal_id,
            payload.source_request_id,
        )

        request_hash = fingerprint(
            "create_price_proposal",
            payload,
            price_id,
        )

        async with self._lock:

            record = self._get(
                principal,
                price_id,
                write=True,
            )

            previous = self._idempotency.get(
                key
            )

            if previous:

                old_hash, proposal_id = previous

                if old_hash != request_hash:
                    raise HTTPException(
                        status_code=409,
                        detail="Idempotency conflict",
                    )

                return to_proposal(
                    record.proposals[proposal_id]
                )

            self._check_version(
                record.version,
                payload.expected_version,
            )

            if record.status != PriceStatus.ACTIVE:
                raise HTTPException(
                    status_code=409,
                    detail="Price record is suspended",
                )

            if (
                len(record.proposals)
                >= MAX_PROPOSALS_PER_PRODUCT
            ):
                raise HTTPException(
                    status_code=503,
                    detail="Proposal capacity reached",
                )

            if (
                len(self._idempotency)
                >= MAX_IDEMPOTENCY_KEYS
            ):
                raise HTTPException(
                    status_code=503,
                    detail="Idempotency capacity reached",
                )

            self._check_margin(
                record,
                payload.proposed_price,
            )

            proposal = PriceProposalRecord(
                proposal_id=secrets.token_urlsafe(20),
                price_id=price_id,
                proposed_price=payload.proposed_price,
                reason=payload.reason,
                explanation=payload.explanation,
                requested_by=principal.principal_id,
                base_price_version=record.version,
            )

            record.proposals[
                proposal.proposal_id
            ] = proposal

            self._idempotency[key] = (
                request_hash,
                proposal.proposal_id,
            )

            return to_proposal(proposal)

    async def decide_proposal(
        self,
        *,
        principal: Principal,
        price_id: str,
        proposal_id: str,
        payload: ProposalDecision,
        approve: bool,
    ) -> PriceProposalResponse:

        async with self._lock:

            record = self._get(
                principal,
                price_id,
                write=True,
            )

            proposal = record.proposals.get(
                proposal_id
            )

            if proposal is None:
                raise HTTPException(
                    status_code=404,
                    detail="Proposal not found",
                )

            self._check_version(
                record.version,
                payload.expected_price_version,
            )

            self._check_version(
                proposal.version,
                payload.expected_proposal_version,
            )

            if proposal.status != PriceProposalStatus.PENDING:
                raise HTTPException(
                    status_code=409,
                    detail="Proposal is not pending",
                )

            if (
                proposal.requested_by
                == principal.principal_id
            ):
                raise HTTPException(
                    status_code=403,
                    detail="Requester cannot approve own proposal",
                )

            # Production must enforce PRICING_APPROVE
            # and record an external approval decision.

            proposal.status = (
                PriceProposalStatus.APPROVED
                if approve
                else PriceProposalStatus.REJECTED
            )

            proposal.reviewed_by = (
                principal.principal_id
            )

            proposal.review_notes = payload.notes
            proposal.reviewed_at = utc_now()

            proposal.version += 1

            return to_proposal(proposal)

    async def apply_proposal(
        self,
        *,
        principal: Principal,
        price_id: str,
        proposal_id: str,
        expected_version: int,
    ) -> PriceResponse:

        async with self._lock:

            record = self._get(
                principal,
                price_id,
                write=True,
            )

            proposal = record.proposals.get(
                proposal_id
            )

            if proposal is None:
                raise HTTPException(
                    status_code=404,
                    detail="Proposal not found",
                )

            self._check_version(
                record.version,
                expected_version,
            )

            if proposal.status != PriceProposalStatus.APPROVED:
                raise HTTPException(
                    status_code=409,
                    detail="Proposal has not been approved",
                )

            if record.status != PriceStatus.ACTIVE:
                raise HTTPException(
                    status_code=409,
                    detail="Price record is suspended",
                )

            if (
                proposal.base_price_version
                != record.version
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Proposal is stale",
                )

            if (
                len(record.history)
                >= MAX_HISTORY_PER_PRODUCT
            ):
                raise HTTPException(
                    status_code=503,
                    detail="Price history capacity reached",
                )

            self._check_margin(
                record,
                proposal.proposed_price,
            )

            old_price = record.selling_price

            record.selling_price = (
                proposal.proposed_price
            )

            record.history.append(
                PriceHistoryResponse(
                    history_id=secrets.token_urlsafe(20),
                    price_id=price_id,
                    old_price=old_price,
                    new_price=proposal.proposed_price,
                    changed_by=principal.principal_id,
                    reason=proposal.reason,
                    created_at=utc_now(),
                )
            )

            proposal.status = (
                PriceProposalStatus.APPLIED
            )

            proposal.version += 1

            record.version += 1
            record.updated_at = utc_now()

            return to_price(record)

    async def simulate_discount(
        self,
        *,
        principal: Principal,
        price_id: str,
        payload: DiscountSimulationRequest,
    ) -> DiscountSimulationResponse:

        async with self._lock:

            record = self._get(
                principal,
                price_id,
                write=False,
            )

            discounted_price = money(
                record.selling_price
                * (
                    Decimal("1")
                    - payload.discount_percent
                    / Decimal("100")
                )
            )

            if discounted_price <= 0:
                raise HTTPException(
                    status_code=422,
                    detail="Discount produces a non-positive price",
                )

            margin = pricing_engine.margin_percent(
                discounted_price,
                record.cost_price,
            )

            within_discount = (
                payload.discount_percent
                <= record.maximum_discount_percent
            )

            within_margin = (
                margin
                >= record.minimum_margin_percent
            )

            return DiscountSimulationResponse(
                original_price=record.selling_price,
                discount_percent=payload.discount_percent,
                discounted_price=discounted_price,
                gross_profit=pricing_engine.gross_profit(
                    discounted_price,
                    record.cost_price,
                ),
                margin_percent=margin,
                within_discount_limit=within_discount,
                within_margin_limit=within_margin,
                allowed=(
                    within_discount
                    and within_margin
                ),
            )

    async def compare_competitors(
        self,
        *,
        principal: Principal,
        price_id: str,
        payload: CompetitorComparisonRequest,
    ) -> CompetitorComparisonResponse:

        async with self._lock:

            record = self._get(
                principal,
                price_id,
                write=False,
            )

            if payload.currency != record.currency:
                raise HTTPException(
                    status_code=422,
                    detail="Currency mismatch; FX conversion unavailable",
                )

            prices = [
                item.competitor_price
                for item in payload.competitors
            ]

            comparisons = []

            for item in payload.competitors:

                difference = (
                    record.selling_price
                    - item.competitor_price
                )

                difference_percent = percent(
                    difference
                    / item.competitor_price
                    * Decimal("100")
                )

                comparisons.append(
                    CompetitorComparisonItem(
                        competitor_reference=(
                            item.competitor_reference
                        ),
                        competitor_price=(
                            item.competitor_price
                        ),
                        difference_amount=money(
                            difference
                        ),
                        difference_percent=(
                            difference_percent
                        ),
                    )
                )

            return CompetitorComparisonResponse(
                product_id=record.product_id,
                currency=record.currency,
                current_price=record.selling_price,
                lowest_competitor_price=min(prices),
                highest_competitor_price=max(prices),
                average_competitor_price=money(
                    sum(prices)
                    / Decimal(len(prices))
                ),
                comparisons=comparisons,
            )

    async def recommend(
        self,
        *,
        principal: Principal,
        price_id: str,
        payload: PriceRecommendationRequest,
    ) -> PriceRecommendationResponse:

        async with self._lock:

            record = self._get(
                principal,
                price_id,
                write=False,
            )

            return pricing_engine.calculate_recommendation(
                record,
                payload,
            )

    async def analytics(
        self,
        *,
        principal: Principal,
        warehouse_id: str,
    ) -> PricingAnalyticsResponse:

        require_pricing_access(
            principal,
            warehouse_id,
            write=False,
        )

        async with self._lock:

            records = [
                record
                for record in self._prices.values()
                if (
                    record.tenant_id
                    == principal.tenant_id
                    and record.warehouse_id
                    == warehouse_id
                )
            ]

            proposals = [
                proposal
                for record in records
                for proposal in record.proposals.values()
            ]

            margins = [
                pricing_engine.margin_percent(
                    record.selling_price,
                    record.cost_price,
                )
                for record in records
            ]

            average_margin = (
                percent(
                    sum(margins)
                    / Decimal(len(margins))
                )
                if margins
                else None
            )

            return PricingAnalyticsResponse(
                total_products=len(records),
                active_prices=sum(
                    record.status == PriceStatus.ACTIVE
                    for record in records
                ),
                suspended_prices=sum(
                    record.status == PriceStatus.SUSPENDED
                    for record in records
                ),
                average_margin_percent=average_margin,
                pending_proposals=sum(
                    proposal.status
                    == PriceProposalStatus.PENDING
                    for proposal in proposals
                ),
                approved_proposals=sum(
                    proposal.status
                    == PriceProposalStatus.APPROVED
                    for proposal in proposals
                ),
                rejected_proposals=sum(
                    proposal.status
                    == PriceProposalStatus.REJECTED
                    for proposal in proposals
                ),
                applied_proposals=sum(
                    proposal.status
                    == PriceProposalStatus.APPLIED
                    for proposal in proposals
                ),
                below_minimum_margin_products=sum(
                    pricing_engine.margin_percent(
                        record.selling_price,
                        record.cost_price,
                    )
                    < record.minimum_margin_percent
                    for record in records
                ),
            )


pricing_store = PricingStore()


# ============================================================
# SERVICE
# ============================================================

class PricingService:

    def __init__(
        self,
        store: PricingStore,
    ):
        self.store = store

    async def create(
        self,
        principal: Principal,
        payload: PriceCreate,
    ) -> PriceResponse:

        return await self.store.create(
            principal=principal,
            payload=payload,
        )


pricing_service = PricingService(
    pricing_store
)


# ============================================================
# FASTAPI ROUTER
# ============================================================

router = APIRouter(
    prefix=API_PREFIX,
    tags=["Pricing Management"],
)


@router.post(
    "",
    response_model=PriceResponse,
    status_code=201,
)
async def create_price(
    payload: PriceCreate,
    principal: CurrentPrincipal,
):
    return await pricing_service.create(
        principal,
        payload,
    )


@router.get(
    "",
    response_model=list[PriceResponse],
)
async def list_prices(
    principal: CurrentPrincipal,
    warehouse_id: str | None = None,
    limit: int = Query(
        default=50,
        ge=1,
        le=MAX_LIST_LIMIT,
    ),
):
    return await pricing_store.list_prices(
        principal=principal,
        warehouse_id=warehouse_id,
        limit=limit,
    )


@router.get(
    "/analytics/{warehouse_id}",
    response_model=PricingAnalyticsResponse,
)
async def pricing_analytics(
    warehouse_id: str,
    principal: CurrentPrincipal,
):
    return await pricing_store.analytics(
        principal=principal,
        warehouse_id=warehouse_id,
    )


@router.get(
    "/{price_id}",
    response_model=PriceDetailResponse,
)
async def get_price(
    price_id: str,
    principal: CurrentPrincipal,
):
    return await pricing_store.get(
        principal=principal,
        price_id=price_id,
    )


@router.post(
    "/{price_id}/proposals",
    response_model=PriceProposalResponse,
    status_code=201,
)
async def create_price_proposal(
    price_id: str,
    payload: PriceProposalCreate,
    principal: CurrentPrincipal,
):
    return await pricing_store.create_proposal(
        principal=principal,
        price_id=price_id,
        payload=payload,
    )


@router.post(
    "/{price_id}/proposals/{proposal_id}/approve",
    response_model=PriceProposalResponse,
)
async def approve_price_proposal(
    price_id: str,
    proposal_id: str,
    payload: ProposalDecision,
    principal: CurrentPrincipal,
):
    return await pricing_store.decide_proposal(
        principal=principal,
        price_id=price_id,
        proposal_id=proposal_id,
        payload=payload,
        approve=True,
    )


@router.post(
    "/{price_id}/proposals/{proposal_id}/reject",
    response_model=PriceProposalResponse,
)
async def reject_price_proposal(
    price_id: str,
    proposal_id: str,
    payload: ProposalDecision,
    principal: CurrentPrincipal,
):
    return await pricing_store.decide_proposal(
        principal=principal,
        price_id=price_id,
        proposal_id=proposal_id,
        payload=payload,
        approve=False,
    )


@router.post(
    "/{price_id}/proposals/{proposal_id}/apply",
    response_model=PriceResponse,
)
async def apply_price_proposal(
    price_id: str,
    proposal_id: str,
    payload: PriceVersionRequest,
    principal: CurrentPrincipal,
):
    return await pricing_store.apply_proposal(
        principal=principal,
        price_id=price_id,
        proposal_id=proposal_id,
        expected_version=payload.expected_version,
    )


@router.post(
    "/{price_id}/discount/simulate",
    response_model=DiscountSimulationResponse,
)
async def simulate_price_discount(
    price_id: str,
    payload: DiscountSimulationRequest,
    principal: CurrentPrincipal,
):
    return await pricing_store.simulate_discount(
        principal=principal,
        price_id=price_id,
        payload=payload,
    )


@router.post(
    "/{price_id}/competitors/compare",
    response_model=CompetitorComparisonResponse,
)
async def compare_competitor_prices(
    price_id: str,
    payload: CompetitorComparisonRequest,
    principal: CurrentPrincipal,
):
    return await pricing_store.compare_competitors(
        principal=principal,
        price_id=price_id,
        payload=payload,
    )


@router.post(
    "/{price_id}/recommend",
    response_model=PriceRecommendationResponse,
)
async def recommend_product_price(
    price_id: str,
    payload: PriceRecommendationRequest,
    principal: CurrentPrincipal,
):
    return await pricing_store.recommend(
        principal=principal,
        price_id=price_id,
        payload=payload,
    )


__all__ = [
    "PricingStrategy",
    "PriceStatus",
    "PriceProposalStatus",
    "PriceChangeReason",
    "PriceRiskLevel",
    "PriceCreate",
    "PriceProposalCreate",
    "ProposalDecision",
    "PriceVersionRequest",
    "DiscountSimulationRequest",
    "CompetitorPriceInput",
    "CompetitorComparisonRequest",
    "PriceRecommendationRequest",
    "PriceResponse",
    "PriceHistoryResponse",
    "PriceProposalResponse",
    "PriceDetailResponse",
    "DiscountSimulationResponse",
    "CompetitorComparisonResponse",
    "PriceRecommendationResponse",
    "PricingAnalyticsResponse",
    "PricingEngine",
    "pricing_engine",
    "PricingStore",
    "PricingService",
    "pricing_store",
    "pricing_service",
    "router",
]
