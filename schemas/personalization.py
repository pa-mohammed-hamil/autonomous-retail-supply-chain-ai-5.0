"""
Pydantic schemas for Personalization API
"""

from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime
from enum import Enum


class Channel(str, Enum):
    """Channel options."""
    WEB = "web"
    MOBILE = "mobile"
    EMAIL = "email"
    IN_STORE = "in_store"
    APP = "app"


class PageType(str, Enum):
    """Page type options."""
    HOMEPAGE = "homepage"
    CATEGORY = "category"
    PRODUCT = "product"
    CART = "cart"
    CHECKOUT = "checkout"
    ACCOUNT = "account"


class InteractionType(str, Enum):
    """Interaction type options."""
    VIEW = "view"
    CLICK = "click"
    ADD_TO_CART = "add_to_cart"
    PURCHASE = "purchase"
    WISHLIST = "wishlist"


# Request Schemas

class RecommendationRequest(BaseModel):
    """Request for product recommendations."""
    customer_id: str = Field(..., description="Customer identifier")
    session_context: Optional[Dict[str, Any]] = Field(default={}, description="Current session context")
    channel: Channel = Field(Channel.WEB, description="Channel requesting recommendations")
    limit: int = Field(10, ge=1, le=50, description="Number of recommendations")
    category_filter: Optional[str] = Field(None, description="Filter by category")
    
    class Config:
        json_schema_extra = {
            "example": {
                "customer_id": "CUST-001",
                "session_context": {
                    "current_page": "homepage",
                    "viewed_products": ["PROD-123"],
                    "cart_items": []
                },
                "channel": "web",
                "limit": 10
            }
        }


class ContentPersonalizationRequest(BaseModel):
    """Request for content personalization."""
    customer_id: str = Field(..., description="Customer identifier")
    page_type: PageType = Field(..., description="Type of page to personalize")
    device_type: Optional[str] = Field("desktop", description="Device type (mobile, desktop, tablet)")
    
    class Config:
        json_schema_extra = {
            "example": {
                "customer_id": "CUST-001",
                "page_type": "homepage",
                "device_type": "mobile"
            }
        }


class ChurnPredictionRequest(BaseModel):
    """Request for churn prediction."""
    customer_id: str = Field(..., description="Customer identifier")
    
    class Config:
        json_schema_extra = {
            "example": {
                "customer_id": "CUST-001"
            }
        }


class CLVRequest(BaseModel):
    """Request for CLV calculation."""
    customer_id: str = Field(..., description="Customer identifier")
    horizon_months: int = Field(12, ge=1, le=60, description="Prediction horizon in months")
    
    class Config:
        json_schema_extra = {
            "example": {
                "customer_id": "CUST-001",
                "horizon_months": 12
            }
        }


class CustomerSegmentRequest(BaseModel):
    """Request for customer segmentation."""
    customer_id: str = Field(..., description="Customer identifier")
    
    class Config:
        json_schema_extra = {
            "example": {
                "customer_id": "CUST-001"
            }
        }


class NextBestActionRequest(BaseModel):
    """Request for next best action."""
    customer_id: str = Field(..., description="Customer identifier")
    
    class Config:
        json_schema_extra = {
            "example": {
                "customer_id": "CUST-001"
            }
        }


# Response Schemas

class ProductRecommendation(BaseModel):
    """Individual product recommendation."""
    product_id: str
    product_name: str
    category: str
    price: float
    image_url: Optional[str]
    rating: Optional[float]
    recommendation_score: float = Field(..., ge=0, le=1)
    recommendation_type: str
    reason: str
    urgency: Optional[str] = None
    related_products: Optional[List[str]] = None


class RecommendationPresentation(BaseModel):
    """How to present recommendations."""
    layout: str
    title: str
    subtitle: str
    call_to_action: str
    urgency_indicators: bool
    social_proof: bool


class RecommendationResponse(BaseModel):
    """Response with product recommendations."""
    customer_id: str
    recommendations: List[ProductRecommendation]
    presentation: RecommendationPresentation
    reasoning: Dict[str, Any]
    timestamp: datetime


class PersonalizedContent(BaseModel):
    """Personalized page content."""
    hero_section: Dict[str, Any]
    featured_categories: List[str]
    promotional_banner: Dict[str, Any]
    social_proof: Dict[str, Any]
    urgency_indicators: Dict[str, Any]


class ContentOptimization(BaseModel):
    """Content presentation optimization."""
    hero_banner: Dict[str, Any]
    category_highlights: List[str]
    promotional_banners: List[Dict[str, Any]]
    content_density: str


class ContentPersonalizationResponse(BaseModel):
    """Response from content personalization."""
    customer_id: str
    page_type: str
    content: PersonalizedContent
    optimization: ContentOptimization
    ab_test_variant: str
    timestamp: datetime


class ChurnIndicator(BaseModel):
    """Churn risk indicator."""
    indicator: str
    value: Any
    impact: str


class RetentionStrategy(BaseModel):
    """Customer retention strategy."""
    status: str
    actions: List[Dict[str, Any]]
    timing: Optional[str] = None
    expected_impact: Optional[float] = None


class ChurnPredictionResponse(BaseModel):
    """Response from churn prediction."""
    customer_id: str
    churn_probability: float = Field(..., ge=0, le=1)
    risk_level: str
    churn_indicators: List[ChurnIndicator]
    retention_strategy: RetentionStrategy
    estimated_clv_at_risk: float
    timestamp: datetime


class CLVComponents(BaseModel):
    """CLV calculation components."""
    average_order_value: float
    annual_purchase_frequency: float
    predicted_lifespan_years: float


class CLVDriver(BaseModel):
    """Factor driving CLV."""
    factor: str
    impact: str
    value: Any


class CLVResponse(BaseModel):
    """Response from CLV calculation."""
    customer_id: str
    historical_clv: float
    predicted_clv: float
    total_clv: float
    risk_adjusted_clv: float
    confidence_interval: Dict[str, float]
    clv_segment: str
    retention_probability: float
    components: Optional[CLVComponents] = None
    key_drivers: List[CLVDriver]
    timestamp: datetime


class CustomerSegment(BaseModel):
    """Customer segment information."""
    segment_id: str
    name: str
    description: str


class CampaignRecommendation(BaseModel):
    """Recommended campaign for customer."""
    campaign: str
    message: str
    timing: str
    channel: List[str]


class CustomerSegmentResponse(BaseModel):
    """Response from customer segmentation."""
    customer_id: str
    primary_segment: Optional[str]
    secondary_segments: List[str]
    segment_characteristics: Dict[str, str]
    similar_customers: List[Dict[str, Any]]
    campaign_recommendations: List[CampaignRecommendation]
    timestamp: datetime


class NextPurchasePrediction(BaseModel):
    """Next purchase prediction."""
    predicted_date: datetime
    days_until_purchase: int
    predicted_category: str
    predicted_amount: float
    confidence: float
    purchase_probability: float


class NextBestAction(BaseModel):
    """Next best action recommendation."""
    action: str
    rationale: str
    timing: str
    channel: str
    expected_impact: Dict[str, Any]


class NextBestActionResponse(BaseModel):
    """Response from next best action."""
    customer_id: str
    next_best_action: NextBestAction
    next_purchase_prediction: NextPurchasePrediction
    timestamp: datetime


class RecommendationAnalytics(BaseModel):
    """Recommendation performance analytics."""
    period_days: int
    recommendations_shown: int
    click_through_rate: float
    conversion_rate: float
    revenue_attributed: float
    avg_order_value: float
    coverage: float
    diversity: float
    timestamp: datetime


class PersonalizationMetrics(BaseModel):
    """Personalization dashboard metrics."""
    active_customers: int
    personalized_sessions_pct: float
    recommendation_ctr: float
    churn_prevention_count: int
    avg_clv: float
    clv_growth_pct: float
    segment_distribution: Dict[str, int]
    top_performing_segments: List[Dict[str, Any]]
    timestamp: datetime
