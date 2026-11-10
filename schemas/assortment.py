"""
Pydantic schemas for Assortment Planning API
"""

from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime
from enum import Enum


class RolloutStrategy(str, Enum):
    """Product rollout strategy options."""
    PHASED = "phased"
    BROAD = "broad"
    TARGETED = "targeted"


class OptimizationObjective(str, Enum):
    """Optimization objective options."""
    PROFIT = "profit"
    REVENUE = "revenue"
    TURNOVER = "turnover"


class ClusteringAlgorithm(str, Enum):
    """Store clustering algorithm options."""
    KMEANS = "kmeans"
    DBSCAN = "dbscan"
    HIERARCHICAL = "hierarchical"


class Season(str, Enum):
    """Season options for seasonal refresh."""
    SPRING = "spring"
    SUMMER = "summer"
    FALL = "fall"
    WINTER = "winter"


# Request Schemas

class AssortmentOptimizationRequest(BaseModel):
    """Request to optimize store assortment."""
    store_id: str = Field(..., description="Store identifier")
    category: Optional[str] = Field(None, description="Specific category to optimize (optional)")
    auto_implement: bool = Field(False, description="Automatically implement approved changes")
    
    class Config:
        json_schema_extra = {
            "example": {
                "store_id": "STORE-001",
                "category": "Produce",
                "auto_implement": False
            }
        }


class StoreClusteringRequest(BaseModel):
    """Request to cluster stores."""
    region: str = Field("all", description="Region to cluster (or 'all')")
    n_clusters: Optional[int] = Field(5, ge=2, le=20, description="Number of clusters")
    algorithm: ClusteringAlgorithm = Field(ClusteringAlgorithm.KMEANS, description="Clustering algorithm")
    
    class Config:
        json_schema_extra = {
            "example": {
                "region": "west",
                "n_clusters": 5,
                "algorithm": "kmeans"
            }
        }


class NewProductAllocationRequest(BaseModel):
    """Request to allocate new products to stores."""
    product_ids: List[str] = Field(..., description="List of new product IDs")
    strategy: RolloutStrategy = Field(RolloutStrategy.PHASED, description="Rollout strategy")
    test_duration_days: int = Field(90, ge=30, le=180, description="Test period duration")
    
    class Config:
        json_schema_extra = {
            "example": {
                "product_ids": ["PROD-001", "PROD-002"],
                "strategy": "phased",
                "test_duration_days": 90
            }
        }


class SeasonalRefreshRequest(BaseModel):
    """Request for seasonal assortment refresh."""
    season: Season = Field(..., description="Season for refresh")
    store_ids: Optional[List[str]] = Field(None, description="Specific stores (or all if None)")
    implementation_date: Optional[datetime] = Field(None, description="When to implement")
    
    class Config:
        json_schema_extra = {
            "example": {
                "season": "spring",
                "store_ids": ["STORE-001", "STORE-002"],
                "implementation_date": "2024-03-01T00:00:00"
            }
        }


class ShelfSpaceOptimizationRequest(BaseModel):
    """Request to optimize shelf space."""
    store_id: str = Field(..., description="Store identifier")
    objective: OptimizationObjective = Field(OptimizationObjective.PROFIT, description="Optimization objective")
    include_demand_response: bool = Field(False, description="Include demand response modeling")
    
    class Config:
        json_schema_extra = {
            "example": {
                "store_id": "STORE-001",
                "objective": "profit",
                "include_demand_response": True
            }
        }


# Response Schemas

class ProductChange(BaseModel):
    """Details of a product addition/removal."""
    product_id: str
    product_name: str
    category: str
    reasons: List[str]
    recommendation_score: Optional[float] = None
    estimated_weekly_sales: Optional[float] = None
    space_sqft: Optional[float] = None


class ShelfSpaceChange(BaseModel):
    """Details of shelf space adjustment."""
    product_id: str
    product_name: str
    category: str
    current_space_sqft: float
    recommended_space_sqft: float
    change_sqft: float
    reason: str


class ImpactAnalysis(BaseModel):
    """Expected business impact of assortment changes."""
    estimated_annual_revenue_impact: float
    additions_revenue: float
    removals_revenue_loss: float
    net_space_change_sqft: float
    current_sales_per_sqft: float
    projected_sales_per_sqft: float
    sales_per_sqft_improvement_pct: float
    inventory_turnover_impact: str
    confidence_level: str
    implementation_cost: Dict[str, float]


class AssortmentOptimizationResponse(BaseModel):
    """Response from assortment optimization."""
    store_id: str
    category: Optional[str]
    current_assortment: Dict[str, Any]
    recommended_assortment: Dict[str, Any]
    changes: Dict[str, List[ProductChange]]
    impact_analysis: ImpactAnalysis
    implementation_priority: str
    status: str = "pending_review"
    timestamp: datetime


class ClusterCharacteristics(BaseModel):
    """Characteristics of a store cluster."""
    median_income: float
    avg_population: float
    avg_store_size_sqft: float
    avg_sales_per_sqft: float
    avg_inventory_turnover: float
    avg_sku_count: float


class StoreCluster(BaseModel):
    """Store cluster information."""
    cluster_id: str
    name: str
    store_count: int
    stores: List[str]
    characteristics: ClusterCharacteristics
    dominant_categories: List[str]
    demographic_profile: str
    recommended_sku_count: int


class StoreClusteringResponse(BaseModel):
    """Response from store clustering."""
    region: str
    clusters_identified: int
    cluster_details: List[StoreCluster]
    total_stores_impacted: int
    timestamp: datetime


class ProductAllocation(BaseModel):
    """New product allocation to stores."""
    product_id: str
    product_name: str
    stores: List[str]
    launch_date: datetime
    evaluation_period_days: int
    success_criteria: Dict[str, float]


class NewProductAllocationResponse(BaseModel):
    """Response from new product allocation."""
    new_products_count: int
    rollout_strategy: str
    store_allocations: List[ProductAllocation]
    total_stores_receiving_products: int
    timestamp: datetime


class SeasonalRefreshPlan(BaseModel):
    """Seasonal refresh plan for a store."""
    store_id: str
    season: str
    additions: List[str]
    removals: List[str]
    featured_categories: List[str]
    implementation_date: datetime


class SeasonalRefreshResponse(BaseModel):
    """Response from seasonal refresh."""
    season: str
    stores_count: int
    refresh_plans: List[SeasonalRefreshPlan]
    total_skus_added: int
    total_skus_removed: int
    timestamp: datetime


class SpaceAllocation(BaseModel):
    """Product space allocation."""
    product_id: str
    product_name: str
    category: str
    current_space_sqft: float
    optimal_space_sqft: float
    space_change_sqft: float
    space_change_pct: float


class SpaceOptimizationPerformance(BaseModel):
    """Performance metrics for space optimization."""
    current_revenue: float
    optimal_revenue: float
    revenue_improvement: float
    revenue_improvement_pct: float
    current_profit: float
    optimal_profit: float
    profit_improvement: float
    profit_improvement_pct: float


class ShelfSpaceOptimizationResponse(BaseModel):
    """Response from shelf space optimization."""
    store_id: str
    objective: str
    products: List[SpaceAllocation]
    performance: SpaceOptimizationPerformance
    total_space_allocated: float
    space_utilization_pct: float
    optimization_status: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
