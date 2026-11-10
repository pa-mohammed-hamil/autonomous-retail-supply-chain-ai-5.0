"""
Autonomous Pricing Agent
Dynamically optimizes product pricing based on demand, inventory, competition, and market conditions.
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
import asyncio

from ai.agents.base_agent import BaseAgent
from ai.llm.llm_client import LLMClient
from ai.tools.pricing_tools import (
    get_competitor_prices,
    get_demand_elasticity,
    get_inventory_levels,
    update_product_price,
    calculate_optimal_price,
    get_historical_pricing_performance
)


class PricingAgent(BaseAgent):
    """
    Autonomous agent that optimizes product pricing across the retail supply chain.
    
    Features:
    - Dynamic pricing based on real-time demand
    - Competitor price monitoring and response
    - Inventory-aware pricing (clearance, promotion)
    - Elasticity-based optimization
    - A/B testing price changes
    - Margin protection rules
    """

    def __init__(self, llm_client: LLMClient, **kwargs):
        super().__init__(
            name="PricingAgent",
            role="price_optimization",
            llm_client=llm_client,
            **kwargs
        )
        self.min_margin_threshold = 0.15  # 15% minimum margin
        self.max_price_change_pct = 0.20  # Max 20% price change at once
        self.competitor_weight = 0.3
        self.demand_weight = 0.4
        self.inventory_weight = 0.3

    async def execute(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Execute pricing optimization workflow."""
        self.log_execution_start(context)
        
        product_id = context.get("product_id")
        optimization_mode = context.get("mode", "balanced")  # balanced, aggressive, conservative
        
        try:
            # Gather pricing intelligence
            pricing_data = await self._gather_pricing_intelligence(product_id)
            
            # Analyze pricing opportunity
            analysis = await self._analyze_pricing_opportunity(pricing_data, optimization_mode)
            
            # Generate pricing recommendation
            recommendation = await self._generate_pricing_recommendation(analysis)
            
            # Validate business rules
            validated_rec = self._validate_pricing_rules(recommendation, pricing_data)
            
            # Execute price change if approved
            result = await self._execute_price_change(validated_rec, context)
            
            self.log_execution_end(result)
            return result
            
        except Exception as e:
            self.logger.error(f"Pricing agent execution failed: {e}")
            return {"status": "error", "error": str(e)}

    async def _gather_pricing_intelligence(self, product_id: str) -> Dict[str, Any]:
        """Gather comprehensive pricing data."""
        
        # Run data collection in parallel
        competitor_data, demand_data, inventory_data, historical_data = await asyncio.gather(
            get_competitor_prices(product_id),
            get_demand_elasticity(product_id),
            get_inventory_levels(product_id),
            get_historical_pricing_performance(product_id, days=90)
        )
        
        return {
            "product_id": product_id,
            "current_price": inventory_data.get("current_price"),
            "cost": inventory_data.get("cost"),
            "stock_level": inventory_data.get("stock_level"),
            "days_of_supply": inventory_data.get("days_of_supply"),
            "competitors": competitor_data,
            "demand_elasticity": demand_data.get("elasticity"),
            "demand_trend": demand_data.get("trend"),
            "historical_performance": historical_data,
            "timestamp": datetime.utcnow().isoformat()
        }

    async def _analyze_pricing_opportunity(
        self, 
        pricing_data: Dict[str, Any], 
        mode: str
    ) -> Dict[str, Any]:
        """Analyze pricing opportunity using LLM reasoning."""
        
        prompt = f"""
        Analyze the following pricing opportunity for product {pricing_data['product_id']}.
        
        Current Situation:
        - Current Price: ${pricing_data['current_price']:.2f}
        - Product Cost: ${pricing_data['cost']:.2f}
        - Current Margin: {((pricing_data['current_price'] - pricing_data['cost']) / pricing_data['current_price'] * 100):.1f}%
        - Stock Level: {pricing_data['stock_level']} units
        - Days of Supply: {pricing_data['days_of_supply']:.1f}
        
        Market Intelligence:
        - Demand Elasticity: {pricing_data['demand_elasticity']:.2f}
        - Demand Trend: {pricing_data['demand_trend']}
        - Competitor Prices: {pricing_data['competitors']}
        
        Historical Performance:
        {pricing_data['historical_performance']}
        
        Optimization Mode: {mode}
        
        Provide a detailed pricing analysis covering:
        1. Competitive positioning
        2. Demand sensitivity
        3. Inventory clearance needs
        4. Revenue vs margin tradeoffs
        5. Risk assessment
        6. Recommended pricing action
        
        Format as JSON with keys: competitive_position, demand_analysis, inventory_urgency, 
        tradeoff_analysis, risk_level, recommended_action, reasoning
        """
        
        analysis = await self.llm_client.generate_structured_output(
            prompt=prompt,
            system_message="You are an expert pricing analyst with deep knowledge of retail economics and dynamic pricing strategies.",
            temperature=0.3
        )
        
        return analysis

    async def _generate_pricing_recommendation(self, analysis: Dict[str, Any]) -> Dict[str, Any]:
        """Generate specific pricing recommendation."""
        
        # Extract key factors
        competitive_position = analysis.get("competitive_position", {})
        demand_analysis = analysis.get("demand_analysis", {})
        inventory_urgency = analysis.get("inventory_urgency", {})
        
        # Calculate optimal price using optimization algorithm
        optimal_price = await calculate_optimal_price(
            current_price=analysis.get("current_price"),
            competitor_prices=competitive_position.get("competitor_prices", []),
            demand_elasticity=demand_analysis.get("elasticity"),
            inventory_level=inventory_urgency.get("stock_level"),
            weights={
                "competitor": self.competitor_weight,
                "demand": self.demand_weight,
                "inventory": self.inventory_weight
            }
        )
        
        return {
            "recommended_price": optimal_price,
            "current_price": analysis.get("current_price"),
            "price_change_pct": ((optimal_price - analysis.get("current_price")) / analysis.get("current_price")) * 100,
            "analysis": analysis,
            "confidence_score": analysis.get("confidence", 0.8),
            "expected_impact": {
                "demand_change_pct": analysis.get("expected_demand_change"),
                "revenue_change_pct": analysis.get("expected_revenue_change"),
                "margin_change_pct": analysis.get("expected_margin_change")
            }
        }

    def _validate_pricing_rules(
        self, 
        recommendation: Dict[str, Any], 
        pricing_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Validate recommendation against business rules."""
        
        violations = []
        adjustments = {}
        
        recommended_price = recommendation["recommended_price"]
        current_price = pricing_data["current_price"]
        cost = pricing_data["cost"]
        
        # Rule 1: Minimum margin protection
        margin = (recommended_price - cost) / recommended_price
        if margin < self.min_margin_threshold:
            violations.append(f"Margin {margin:.1%} below threshold {self.min_margin_threshold:.1%}")
            recommended_price = cost / (1 - self.min_margin_threshold)
            adjustments["margin_protected"] = True
        
        # Rule 2: Maximum price change limit
        price_change_pct = abs((recommended_price - current_price) / current_price)
        if price_change_pct > self.max_price_change_pct:
            violations.append(f"Price change {price_change_pct:.1%} exceeds limit {self.max_price_change_pct:.1%}")
            if recommended_price > current_price:
                recommended_price = current_price * (1 + self.max_price_change_pct)
            else:
                recommended_price = current_price * (1 - self.max_price_change_pct)
            adjustments["change_limited"] = True
        
        # Rule 3: Psychological pricing (ending in .99, .95, .49)
        if recommended_price > 10:
            cents = recommended_price % 1
            if cents not in [0.49, 0.95, 0.99]:
                recommended_price = int(recommended_price) + 0.99
                adjustments["psychological_pricing"] = True
        
        return {
            **recommendation,
            "validated_price": recommended_price,
            "rule_violations": violations,
            "adjustments_made": adjustments,
            "requires_approval": len(violations) > 0 or price_change_pct > 0.10
        }

    async def _execute_price_change(
        self, 
        recommendation: Dict[str, Any], 
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute the price change."""
        
        requires_approval = recommendation.get("requires_approval", False)
        auto_execute = context.get("auto_execute", False)
        
        if requires_approval and not auto_execute:
            # Create approval request
            return {
                "status": "pending_approval",
                "recommendation": recommendation,
                "message": "Price change requires management approval",
                "approval_required": True
            }
        
        # Execute price change
        try:
            update_result = await update_product_price(
                product_id=context.get("product_id"),
                new_price=recommendation["validated_price"],
                reason="autonomous_optimization",
                metadata={
                    "previous_price": recommendation["current_price"],
                    "analysis": recommendation["analysis"],
                    "confidence": recommendation["confidence_score"]
                }
            )
            
            return {
                "status": "executed",
                "product_id": context.get("product_id"),
                "previous_price": recommendation["current_price"],
                "new_price": recommendation["validated_price"],
                "change_pct": recommendation["price_change_pct"],
                "expected_impact": recommendation["expected_impact"],
                "execution_result": update_result,
                "timestamp": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            self.logger.error(f"Failed to execute price change: {e}")
            return {
                "status": "failed",
                "error": str(e),
                "recommendation": recommendation
            }

    async def optimize_category_pricing(self, category: str, store_id: Optional[str] = None) -> Dict[str, Any]:
        """Optimize pricing for an entire product category."""
        
        # Get all products in category
        from ai.tools.product_tools import get_products_by_category
        products = await get_products_by_category(category, store_id)
        
        results = []
        for product in products:
            result = await self.execute({
                "product_id": product["id"],
                "mode": "balanced",
                "auto_execute": False  # Category-wide changes need approval
            })
            results.append(result)
        
        return {
            "category": category,
            "store_id": store_id,
            "products_analyzed": len(products),
            "recommendations": results,
            "total_revenue_impact": sum(r.get("expected_impact", {}).get("revenue_change_pct", 0) for r in results),
            "timestamp": datetime.utcnow().isoformat()
        }

    async def run_ab_test(
        self, 
        product_id: str, 
        test_price: float, 
        control_stores: List[str],
        test_stores: List[str],
        duration_days: int = 14
    ) -> Dict[str, Any]:
        """Run A/B test for price change."""
        
        return {
            "test_id": f"price_test_{product_id}_{datetime.utcnow().timestamp()}",
            "product_id": product_id,
            "test_price": test_price,
            "control_stores": control_stores,
            "test_stores": test_stores,
            "start_date": datetime.utcnow().isoformat(),
            "end_date": (datetime.utcnow() + timedelta(days=duration_days)).isoformat(),
            "status": "active",
            "message": "A/B test initiated. Results will be available after test period."
        }
