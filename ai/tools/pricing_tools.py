"""
Pricing Tools for Autonomous Price Optimization
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
import math


async def get_competitor_prices(product_id: str) -> Dict[str, Any]:
    """Fetch competitor pricing data for a product."""
    # TODO: Integrate with competitor price monitoring service
    return {
        "product_id": product_id,
        "competitors": [
            {"name": "Competitor A", "price": 29.99, "stock_status": "in_stock"},
            {"name": "Competitor B", "price": 31.49, "stock_status": "in_stock"},
            {"name": "Competitor C", "price": 28.99, "stock_status": "low_stock"}
        ],
        "market_average": 30.16,
        "market_min": 28.99,
        "market_max": 31.49,
        "timestamp": datetime.utcnow().isoformat()
    }


async def get_demand_elasticity(product_id: str) -> Dict[str, Any]:
    """Calculate demand elasticity for a product."""
    # TODO: Integrate with ML forecasting service
    return {
        "product_id": product_id,
        "elasticity": -1.2,  # -1.2 means 1% price increase = 1.2% demand decrease
        "trend": "stable",  # stable, increasing, decreasing
        "seasonality_factor": 1.0,
        "confidence": 0.85,
        "last_updated": datetime.utcnow().isoformat()
    }


async def get_inventory_levels(product_id: str) -> Dict[str, Any]:
    """Get current inventory levels and metrics."""
    # TODO: Integrate with inventory service
    return {
        "product_id": product_id,
        "current_price": 30.00,
        "cost": 18.00,
        "stock_level": 450,
        "days_of_supply": 22.5,
        "reorder_point": 200,
        "target_stock": 600,
        "warehouse": "WH-001",
        "timestamp": datetime.utcnow().isoformat()
    }


async def calculate_optimal_price(
    current_price: float,
    competitor_prices: List[float],
    demand_elasticity: float,
    inventory_level: int,
    weights: Dict[str, float]
) -> float:
    """
    Calculate optimal price using weighted scoring model.
    
    Factors:
    - Competitive positioning
    - Demand elasticity
    - Inventory clearance needs
    """
    
    # Competitor-based price
    if competitor_prices:
        competitor_avg = sum(competitor_prices) / len(competitor_prices)
        competitor_price = competitor_avg * 0.98  # Price slightly below average
    else:
        competitor_price = current_price
    
    # Demand-based price (elasticity-optimized)
    # Revenue = Price * Quantity, maximize by adjusting for elasticity
    elasticity_factor = 1 + (0.05 * abs(demand_elasticity))  # Slight adjustment based on elasticity
    demand_price = current_price / elasticity_factor
    
    # Inventory-based price
    # Low inventory -> maintain/increase price
    # High inventory -> reduce price for clearance
    if inventory_level < 200:  # Low stock
        inventory_price = current_price * 1.05
    elif inventory_level > 800:  # Overstock
        inventory_price = current_price * 0.92
    else:
        inventory_price = current_price
    
    # Weighted combination
    optimal_price = (
        competitor_price * weights["competitor"] +
        demand_price * weights["demand"] +
        inventory_price * weights["inventory"]
    )
    
    return round(optimal_price, 2)


async def update_product_price(
    product_id: str,
    new_price: float,
    reason: str,
    metadata: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Update product price in the system."""
    # TODO: Integrate with product service
    return {
        "product_id": product_id,
        "new_price": new_price,
        "reason": reason,
        "metadata": metadata,
        "status": "updated",
        "timestamp": datetime.utcnow().isoformat()
    }


async def get_historical_pricing_performance(product_id: str, days: int = 90) -> Dict[str, Any]:
    """Get historical pricing and performance data."""
    # TODO: Integrate with analytics service
    return {
        "product_id": product_id,
        "period_days": days,
        "average_price": 29.50,
        "price_changes": 3,
        "average_daily_sales": 20,
        "revenue_trend": "stable",
        "margin_trend": "improving",
        "best_performing_price": 31.99,
        "worst_performing_price": 27.99,
        "summary": "Product has been stable with good margins. Recent price increase of 5% had minimal impact on demand."
    }


async def calculate_price_elasticity(
    product_id: str,
    price_history: List[Dict[str, Any]],
    sales_history: List[Dict[str, Any]]
) -> float:
    """
    Calculate price elasticity of demand from historical data.
    Elasticity = (% Change in Quantity) / (% Change in Price)
    """
    
    if len(price_history) < 2 or len(sales_history) < 2:
        return -1.0  # Default elasticity
    
    # Simple calculation from two most recent price changes
    p1, p2 = price_history[-2]["price"], price_history[-1]["price"]
    q1, q2 = sales_history[-2]["quantity"], sales_history[-1]["quantity"]
    
    if p1 == 0 or q1 == 0:
        return -1.0
    
    pct_price_change = (p2 - p1) / p1
    pct_quantity_change = (q2 - q1) / q1
    
    if pct_price_change == 0:
        return -1.0
    
    elasticity = pct_quantity_change / pct_price_change
    
    return round(elasticity, 2)


async def simulate_price_change_impact(
    product_id: str,
    current_price: float,
    proposed_price: float,
    demand_elasticity: float,
    current_volume: int,
    cost: float
) -> Dict[str, Any]:
    """Simulate the impact of a price change."""
    
    price_change_pct = (proposed_price - current_price) / current_price
    
    # Estimate demand change using elasticity
    demand_change_pct = demand_elasticity * price_change_pct
    new_volume = int(current_volume * (1 + demand_change_pct))
    
    # Calculate revenue and margin impact
    current_revenue = current_price * current_volume
    new_revenue = proposed_price * new_volume
    revenue_change = new_revenue - current_revenue
    revenue_change_pct = (revenue_change / current_revenue) * 100
    
    current_margin = ((current_price - cost) / current_price) * 100
    new_margin = ((proposed_price - cost) / proposed_price) * 100
    margin_change_pct = new_margin - current_margin
    
    current_profit = (current_price - cost) * current_volume
    new_profit = (proposed_price - cost) * new_volume
    profit_change = new_profit - current_profit
    profit_change_pct = (profit_change / current_profit) * 100 if current_profit > 0 else 0
    
    return {
        "product_id": product_id,
        "current_price": current_price,
        "proposed_price": proposed_price,
        "price_change_pct": round(price_change_pct * 100, 2),
        "current_volume": current_volume,
        "projected_volume": new_volume,
        "volume_change_pct": round(demand_change_pct * 100, 2),
        "current_revenue": round(current_revenue, 2),
        "projected_revenue": round(new_revenue, 2),
        "revenue_change": round(revenue_change, 2),
        "revenue_change_pct": round(revenue_change_pct, 2),
        "current_margin_pct": round(current_margin, 2),
        "projected_margin_pct": round(new_margin, 2),
        "margin_change_pct": round(margin_change_pct, 2),
        "current_profit": round(current_profit, 2),
        "projected_profit": round(new_profit, 2),
        "profit_change": round(profit_change, 2),
        "profit_change_pct": round(profit_change_pct, 2),
        "recommendation": "approve" if profit_change > 0 else "reject"
    }


def calculate_psychological_price(price: float) -> float:
    """Convert price to psychological pricing (ending in .99, .95, .49)."""
    
    if price < 1:
        return round(price, 2)
    
    base = math.floor(price)
    
    # For prices over $100, use .99
    if price >= 100:
        return base + 0.99
    
    # For prices $10-$100, use .99 or .95
    if price >= 10:
        if price - base > 0.5:
            return base + 0.99
        else:
            return base + 0.49
    
    # For prices under $10, use .99, .95, or .49
    decimal = price - base
    if decimal > 0.75:
        return base + 0.99
    elif decimal > 0.50:
        return base + 0.95
    else:
        return base + 0.49
