"""
Personalization API Endpoints
RESTful API for personalized customer experiences.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from typing import List, Optional
from datetime import datetime

from backend.schemas.personalization import (
    RecommendationRequest,
    RecommendationResponse,
    ContentPersonalizationRequest,
    ContentPersonalizationResponse,
    ChurnPredictionRequest,
    ChurnPredictionResponse,
    CLVRequest,
    CLVResponse,
    CustomerSegmentRequest,
    CustomerSegmentResponse,
    NextBestActionRequest,
    NextBestActionResponse
)
from backend.services.personalization_service import PersonalizationService
from backend.api.dependencies import get_current_user, get_personalization_service
from backend.core.permissions import require_permission

router = APIRouter(prefix="/personalization", tags=["personalization"])


@router.post(
    "/recommendations",
    response_model=RecommendationResponse,
    summary="Get Personalized Product Recommendations"
)
async def get_recommendations(
    request: RecommendationRequest,
    service: PersonalizationService = Depends(get_personalization_service),
    current_user = Depends(get_current_user)
):
    """
    Generate personalized product recommendations.
    
    Uses hybrid approach combining:
    - Collaborative filtering
    - Content-based filtering
    - Popularity trends
    - LLM-enhanced reasoning
    """
    
    require_permission(current_user, "personalization:view")
    
    recommendations = await service.generate_recommendations(
        customer_id=request.customer_id,
        session_context=request.session_context,
        channel=request.channel,
        limit=request.limit,
        category_filter=request.category_filter
    )
    
    return recommendations


@router.post(
    "/content/personalize",
    response_model=ContentPersonalizationResponse,
    summary="Personalize Page Content"
)
async def personalize_content(
    request: ContentPersonalizationRequest,
    service: PersonalizationService = Depends(get_personalization_service),
    current_user = Depends(get_current_user)
):
    """
    Personalize website/app content for a customer.
    
    Customizes:
    - Hero banners
    - Featured categories
    - Promotional messages
    - Layout and presentation
    """
    
    require_permission(current_user, "personalization:view")
    
    content = await service.personalize_content(
        customer_id=request.customer_id,
        page_type=request.page_type,
        device_type=request.device_type
    )
    
    return content


@router.post(
    "/churn/predict",
    response_model=ChurnPredictionResponse,
    summary="Predict Customer Churn Risk"
)
async def predict_churn(
    request: ChurnPredictionRequest,
    background_tasks: BackgroundTasks,
    service: PersonalizationService = Depends(get_personalization_service),
    current_user = Depends(get_current_user)
):
    """
    Predict churn risk and generate retention strategy.
    
    Analyzes:
    - Purchase patterns
    - Engagement metrics
    - Support interactions
    - Competitive signals
    """
    
    require_permission(current_user, "personalization:analyze")
    
    churn_prediction = await service.predict_churn(
        customer_id=request.customer_id
    )
    
    # If high risk, trigger retention workflow
    if churn_prediction['risk_level'] == 'high':
        background_tasks.add_task(
            service.trigger_retention_workflow,
            customer_id=request.customer_id,
            churn_prediction=churn_prediction
        )
    
    return churn_prediction


@router.post(
    "/clv/calculate",
    response_model=CLVResponse,
    summary="Calculate Customer Lifetime Value"
)
async def calculate_clv(
    request: CLVRequest,
    service: PersonalizationService = Depends(get_personalization_service),
    current_user = Depends(get_current_user)
):
    """
    Calculate customer lifetime value.
    
    Provides:
    - Historical CLV
    - Predicted future CLV
    - Risk-adjusted CLV
    - Key value drivers
    """
    
    require_permission(current_user, "personalization:analyze")
    
    clv_result = await service.calculate_clv(
        customer_id=request.customer_id,
        prediction_horizon_months=request.horizon_months
    )
    
    return clv_result


@router.post(
    "/segment",
    response_model=CustomerSegmentResponse,
    summary="Segment Customer"
)
async def segment_customer(
    request: CustomerSegmentRequest,
    service: PersonalizationService = Depends(get_personalization_service),
    current_user = Depends(get_current_user)
):
    """
    Assign customer to segments for targeted campaigns.
    
    Segments based on:
    - RFM analysis
    - Behavioral patterns
    - Demographics
    - Preferences
    """
    
    require_permission(current_user, "personalization:analyze")
    
    segmentation = await service.segment_customer(
        customer_id=request.customer_id
    )
    
    return segmentation


@router.post(
    "/next-best-action",
    response_model=NextBestActionResponse,
    summary="Determine Next Best Action"
)
async def get_next_best_action(
    request: NextBestActionRequest,
    service: PersonalizationService = Depends(get_personalization_service),
    current_user = Depends(get_current_user)
):
    """
    Determine optimal next action for customer engagement.
    
    Considers:
    - Current journey stage
    - Predicted next purchase
    - Engagement history
    - Business goals
    """
    
    require_permission(current_user, "personalization:view")
    
    nba = await service.determine_next_best_action(
        customer_id=request.customer_id
    )
    
    return nba


@router.get(
    "/customer/{customer_id}/profile",
    summary="Get Customer Profile"
)
async def get_customer_profile(
    customer_id: str,
    service: PersonalizationService = Depends(get_personalization_service),
    current_user = Depends(get_current_user)
):
    """Get comprehensive customer profile."""
    
    profile = await service.get_customer_profile(customer_id)
    
    if not profile:
        raise HTTPException(status_code=404, detail=f"Customer {customer_id} not found")
    
    return profile


@router.get(
    "/customer/{customer_id}/journey",
    summary="Get Customer Journey"
)
async def get_customer_journey(
    customer_id: str,
    days: int = Query(30, ge=1, le=365),
    service: PersonalizationService = Depends(get_personalization_service),
    current_user = Depends(get_current_user)
):
    """Get customer journey map and touchpoints."""
    
    journey = await service.get_customer_journey(
        customer_id=customer_id,
        days=days
    )
    
    return journey


@router.get(
    "/customer/{customer_id}/similar",
    summary="Find Similar Customers"
)
async def find_similar_customers(
    customer_id: str,
    top_n: int = Query(10, ge=1, le=50),
    service: PersonalizationService = Depends(get_personalization_service),
    current_user = Depends(get_current_user)
):
    """Find customers with similar profiles and behavior."""
    
    similar_customers = await service.find_similar_customers(
        customer_id=customer_id,
        top_n=top_n
    )
    
    return similar_customers


@router.post(
    "/product/{product_id}/similar",
    summary="Find Similar Products"
)
async def find_similar_products(
    product_id: str,
    top_n: int = Query(10, ge=1, le=50),
    service: PersonalizationService = Depends(get_personalization_service),
    current_user = Depends(get_current_user)
):
    """Find products similar to a given product."""
    
    similar_products = await service.find_similar_products(
        product_id=product_id,
        top_n=top_n
    )
    
    return similar_products


@router.post(
    "/track/interaction",
    summary="Track Recommendation Interaction"
)
async def track_interaction(
    customer_id: str,
    product_id: str,
    interaction_type: str,  # view, click, add_to_cart, purchase
    recommendation_context: dict,
    service: PersonalizationService = Depends(get_personalization_service),
    current_user = Depends(get_current_user)
):
    """
    Track customer interaction with recommendations.
    
    Used for:
    - Model training
    - Recommendation optimization
    - A/B testing analysis
    """
    
    await service.track_interaction(
        customer_id=customer_id,
        product_id=product_id,
        interaction_type=interaction_type,
        context=recommendation_context
    )
    
    return {"status": "tracked"}


@router.get(
    "/segments",
    summary="List Customer Segments"
)
async def list_segments(
    service: PersonalizationService = Depends(get_personalization_service),
    current_user = Depends(get_current_user)
):
    """Get all customer segments with characteristics."""
    
    segments = await service.get_all_segments()
    
    return segments


@router.get(
    "/analytics/recommendations",
    summary="Recommendation Analytics"
)
async def get_recommendation_analytics(
    days: int = Query(30, ge=1, le=365),
    service: PersonalizationService = Depends(get_personalization_service),
    current_user = Depends(get_current_user)
):
    """
    Get recommendation performance analytics.
    
    Metrics:
    - Click-through rate
    - Conversion rate
    - Revenue impact
    - Coverage and diversity
    """
    
    analytics = await service.get_recommendation_analytics(days)
    
    return analytics


@router.get(
    "/analytics/personalization",
    summary="Personalization Impact Analytics"
)
async def get_personalization_analytics(
    days: int = Query(30, ge=1, le=365),
    service: PersonalizationService = Depends(get_personalization_service),
    current_user = Depends(get_current_user)
):
    """
    Get overall personalization impact metrics.
    
    Includes:
    - Engagement lift
    - Revenue lift
    - Retention improvement
    - Customer satisfaction impact
    """
    
    analytics = await service.get_personalization_analytics(days)
    
    return analytics


@router.post(
    "/ab-test/assign",
    summary="Assign A/B Test Variant"
)
async def assign_ab_test(
    customer_id: str,
    test_id: str,
    service: PersonalizationService = Depends(get_personalization_service),
    current_user = Depends(get_current_user)
):
    """Assign customer to A/B test variant."""
    
    assignment = await service.assign_ab_test(
        customer_id=customer_id,
        test_id=test_id
    )
    
    return assignment


@router.post(
    "/email/personalize",
    summary="Generate Personalized Email"
)
async def personalize_email(
    customer_id: str,
    email_type: str,
    context: dict,
    service: PersonalizationService = Depends(get_personalization_service),
    current_user = Depends(get_current_user)
):
    """
    Generate personalized email content.
    
    Optimizes:
    - Subject line
    - Product recommendations
    - Messaging tone
    - Send time
    """
    
    require_permission(current_user, "personalization:campaigns")
    
    email = await service.personalize_email(
        customer_id=customer_id,
        email_type=email_type,
        context=context
    )
    
    return email


@router.get(
    "/dashboard/metrics",
    summary="Personalization Dashboard Metrics"
)
async def get_dashboard_metrics(
    time_period_days: int = Query(30, ge=1, le=365),
    service: PersonalizationService = Depends(get_personalization_service),
    current_user = Depends(get_current_user)
):
    """
    Get key personalization metrics for dashboard.
    
    Includes:
    - Active personalization features
    - Recommendation performance
    - Churn prevention impact
    - CLV growth
    """
    
    metrics = await service.get_dashboard_metrics(time_period_days)
    
    return metrics
