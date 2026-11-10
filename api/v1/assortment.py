"""
Assortment Planning API Endpoints
RESTful API for autonomous assortment optimization.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from typing import List, Optional
from datetime import datetime

from backend.schemas.assortment import (
    AssortmentOptimizationRequest,
    AssortmentOptimizationResponse,
    StoreClusteringRequest,
    StoreClusteringResponse,
    NewProductAllocationRequest,
    NewProductAllocationResponse,
    SeasonalRefreshRequest,
    SeasonalRefreshResponse,
    ShelfSpaceOptimizationRequest,
    ShelfSpaceOptimizationResponse
)
from backend.services.assortment_service import AssortmentService
from backend.api.dependencies import get_current_user, get_assortment_service
from backend.core.permissions import require_permission

router = APIRouter(prefix="/assortment", tags=["assortment"])


@router.post(
    "/optimize-store",
    response_model=AssortmentOptimizationResponse,
    summary="Optimize Store Assortment"
)
async def optimize_store_assortment(
    request: AssortmentOptimizationRequest,
    background_tasks: BackgroundTasks,
    service: AssortmentService = Depends(get_assortment_service),
    current_user = Depends(get_current_user)
):
    """
    Optimize product assortment for a specific store.
    
    Analyzes current assortment and recommends:
    - Products to add
    - Products to remove
    - Shelf space adjustments
    - Expected business impact
    """
    
    require_permission(current_user, "assortment:optimize")
    
    result = await service.optimize_store_assortment(
        store_id=request.store_id,
        category=request.category,
        auto_implement=request.auto_implement,
        user_id=current_user.id
    )
    
    # Schedule background task for implementation if auto_implement=True
    if request.auto_implement and result["status"] == "approved":
        background_tasks.add_task(
            service.implement_assortment_changes,
            store_id=request.store_id,
            changes=result["changes"]
        )
    
    return result


@router.post(
    "/cluster-stores",
    response_model=StoreClusteringResponse,
    summary="Cluster Stores by Similarity"
)
async def cluster_stores(
    request: StoreClusteringRequest,
    service: AssortmentService = Depends(get_assortment_service),
    current_user = Depends(get_current_user)
):
    """
    Group stores by demand patterns and demographics.
    
    Useful for creating standardized assortments for similar stores.
    """
    
    require_permission(current_user, "assortment:analyze")
    
    result = await service.cluster_stores(
        region=request.region,
        n_clusters=request.n_clusters,
        algorithm=request.algorithm
    )
    
    return result


@router.post(
    "/allocate-new-products",
    response_model=NewProductAllocationResponse,
    summary="Allocate New Products to Stores"
)
async def allocate_new_products(
    request: NewProductAllocationRequest,
    service: AssortmentService = Depends(get_assortment_service),
    current_user = Depends(get_current_user)
):
    """
    Determine which stores should receive new product introductions.
    
    Supports phased rollout, broad launch, and targeted strategies.
    """
    
    require_permission(current_user, "assortment:manage")
    
    result = await service.allocate_new_products(
        new_product_ids=request.product_ids,
        rollout_strategy=request.strategy,
        test_duration_days=request.test_duration_days
    )
    
    return result


@router.post(
    "/seasonal-refresh",
    response_model=SeasonalRefreshResponse,
    summary="Execute Seasonal Assortment Refresh"
)
async def seasonal_refresh(
    request: SeasonalRefreshRequest,
    background_tasks: BackgroundTasks,
    service: AssortmentService = Depends(get_assortment_service),
    current_user = Depends(get_current_user)
):
    """
    Perform seasonal assortment refresh across stores.
    
    Automatically adjusts assortment for spring, summer, fall, winter.
    """
    
    require_permission(current_user, "assortment:manage")
    
    result = await service.seasonal_refresh(
        season=request.season,
        store_ids=request.store_ids,
        implementation_date=request.implementation_date
    )
    
    # Schedule implementation
    background_tasks.add_task(
        service.schedule_seasonal_refresh,
        refresh_plan=result,
        implementation_date=request.implementation_date
    )
    
    return result


@router.post(
    "/optimize-shelf-space",
    response_model=ShelfSpaceOptimizationResponse,
    summary="Optimize Shelf Space Allocation"
)
async def optimize_shelf_space(
    request: ShelfSpaceOptimizationRequest,
    service: AssortmentService = Depends(get_assortment_service),
    current_user = Depends(get_current_user)
):
    """
    Optimize shelf space allocation across categories and products.
    
    Uses mathematical optimization to maximize revenue or profit.
    """
    
    require_permission(current_user, "assortment:optimize")
    
    result = await service.optimize_shelf_space(
        store_id=request.store_id,
        objective=request.objective,
        include_demand_response=request.include_demand_response
    )
    
    return result


@router.get(
    "/store/{store_id}/current",
    summary="Get Current Store Assortment"
)
async def get_current_assortment(
    store_id: str,
    category: Optional[str] = None,
    service: AssortmentService = Depends(get_assortment_service),
    current_user = Depends(get_current_user)
):
    """Get current product assortment for a store."""
    
    assortment = await service.get_store_assortment(
        store_id=store_id,
        category=category
    )
    
    return assortment


@router.get(
    "/store/{store_id}/performance",
    summary="Get Assortment Performance Metrics"
)
async def get_assortment_performance(
    store_id: str,
    days: int = Query(90, ge=7, le=365),
    service: AssortmentService = Depends(get_assortment_service),
    current_user = Depends(get_current_user)
):
    """Get performance metrics for store's current assortment."""
    
    performance = await service.get_assortment_performance(
        store_id=store_id,
        days=days
    )
    
    return performance


@router.get(
    "/clusters",
    response_model=List[dict],
    summary="List Store Clusters"
)
async def list_clusters(
    service: AssortmentService = Depends(get_assortment_service),
    current_user = Depends(get_current_user)
):
    """Get all store clusters and their characteristics."""
    
    clusters = await service.get_all_clusters()
    
    return clusters


@router.get(
    "/cluster/{cluster_id}/recommended-assortment",
    summary="Get Recommended Assortment for Cluster"
)
async def get_cluster_assortment(
    cluster_id: str,
    service: AssortmentService = Depends(get_assortment_service),
    current_user = Depends(get_current_user)
):
    """Get recommended master assortment for a store cluster."""
    
    assortment = await service.get_cluster_assortment(cluster_id)
    
    if not assortment:
        raise HTTPException(status_code=404, detail=f"Cluster {cluster_id} not found")
    
    return assortment


@router.post(
    "/rationalize-underperformers",
    summary="Rationalize Underperforming SKUs"
)
async def rationalize_underperformers(
    threshold_weeks: int = Query(12, ge=4, le=52),
    min_sales_velocity: float = Query(2.0, ge=0.1),
    service: AssortmentService = Depends(get_assortment_service),
    current_user = Depends(get_current_user)
):
    """
    Identify and recommend removal of chronically underperforming SKUs.
    """
    
    require_permission(current_user, "assortment:manage")
    
    rationalization = await service.rationalize_underperformers(
        threshold_weeks=threshold_weeks,
        min_sales_velocity=min_sales_velocity
    )
    
    return rationalization


@router.get(
    "/store/{store_id}/similar-stores",
    summary="Find Similar Stores"
)
async def get_similar_stores(
    store_id: str,
    top_n: int = Query(5, ge=1, le=20),
    service: AssortmentService = Depends(get_assortment_service),
    current_user = Depends(get_current_user)
):
    """
    Find stores most similar to the given store.
    
    Useful for benchmarking and best practice sharing.
    """
    
    similar_stores = await service.get_similar_stores(
        store_id=store_id,
        top_n=top_n
    )
    
    return similar_stores


@router.post(
    "/simulate-scenarios",
    summary="Simulate Assortment Scenarios"
)
async def simulate_scenarios(
    store_id: str,
    scenarios: List[dict],
    service: AssortmentService = Depends(get_assortment_service),
    current_user = Depends(get_current_user)
):
    """
    Simulate multiple assortment scenarios and compare outcomes.
    
    Useful for what-if analysis before committing to changes.
    """
    
    require_permission(current_user, "assortment:analyze")
    
    simulation_results = await service.simulate_assortment_scenarios(
        store_id=store_id,
        scenarios=scenarios
    )
    
    return simulation_results
