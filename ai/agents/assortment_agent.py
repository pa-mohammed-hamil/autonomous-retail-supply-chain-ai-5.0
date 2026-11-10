"""
Autonomous Assortment Planning Agent
Optimizes product assortment by store/region based on demand, demographics, and space constraints.
"""

from typing import Dict, Any, List, Optional, Set
from datetime import datetime, timedelta
import asyncio

from ai.agents.base_agent import BaseAgent
from ai.llm.llm_client import LLMClient
from ai.tools.assortment_tools import (
    get_store_demographics,
    get_store_performance_data,
    get_category_constraints,
    get_product_catalog,
    calculate_space_to_sales_ratio,
    cluster_stores_by_similarity,
    get_seasonal_assortment_rules,
    optimize_shelf_allocation,
    validate_assortment_constraints
)


class AssortmentAgent(BaseAgent):
    """
    Autonomous agent for intelligent product assortment planning.
    
    Features:
    - Local demand-based assortment optimization
    - Store clustering for similar assortments
    - Space-to-sales ratio optimization
    - New product introduction planning
    - Seasonal assortment adjustments
    - Category-level shelf space allocation
    - Performance-based SKU rationalization
    """

    def __init__(self, llm_client: LLMClient, **kwargs):
        super().__init__(
            name="AssortmentAgent",
            role="assortment_optimization",
            llm_client=llm_client,
            **kwargs
        )
        self.min_sku_count = 100  # Minimum SKUs per store
        self.max_sku_count = 5000  # Maximum SKUs per store
        self.new_product_test_percentage = 0.05  # 5% of assortment for testing

    async def execute(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Execute assortment planning workflow."""
        self.log_execution_start(context)
        
        action = context.get("action", "optimize_store")
        
        try:
            if action == "optimize_store":
                result = await self._optimize_store_assortment(context)
            elif action == "cluster_stores":
                result = await self._cluster_and_assign_assortments(context)
            elif action == "new_product_allocation":
                result = await self._allocate_new_products(context)
            elif action == "seasonal_refresh":
                result = await self._seasonal_assortment_refresh(context)
            elif action == "sku_rationalization":
                result = await self._rationalize_underperforming_skus(context)
            elif action == "shelf_allocation":
                result = await self._optimize_shelf_space_allocation(context)
            else:
                result = {"status": "error", "message": f"Unknown action: {action}"}
            
            self.log_execution_end(result)
            return result
            
        except Exception as e:
            self.logger.error(f"Assortment agent execution failed: {e}")
            return {"status": "error", "error": str(e)}

    async def _optimize_store_assortment(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Optimize product assortment for a specific store."""
        
        store_id = context.get("store_id")
        category = context.get("category")  # Optional: optimize specific category
        
        # Gather comprehensive store intelligence
        store_data = await self._gather_store_intelligence(store_id, category)
        
        # Analyze assortment opportunity using LLM reasoning
        analysis = await self._analyze_assortment_opportunity(store_data)
        
        # Generate assortment recommendations
        recommendations = await self._generate_assortment_recommendations(
            store_data, 
            analysis,
            category
        )
        
        # Validate against business constraints
        validated_recommendations = await self._validate_assortment_plan(
            recommendations,
            store_data
        )
        
        # Calculate expected impact
        impact_analysis = await self._calculate_assortment_impact(
            validated_recommendations,
            store_data
        )
        
        return {
            "store_id": store_id,
            "category": category,
            "current_assortment": store_data["current_assortment"],
            "recommended_assortment": validated_recommendations,
            "changes": {
                "products_to_add": validated_recommendations["additions"],
                "products_to_remove": validated_recommendations["removals"],
                "products_to_expand": validated_recommendations["expansions"],
                "products_to_reduce": validated_recommendations["reductions"]
            },
            "impact_analysis": impact_analysis,
            "implementation_priority": analysis.get("priority", "medium"),
            "timestamp": datetime.utcnow().isoformat()
        }

    async def _gather_store_intelligence(
        self, 
        store_id: str, 
        category: Optional[str] = None
    ) -> Dict[str, Any]:
        """Gather comprehensive data about the store."""
        
        # Run data collection in parallel
        demographics, performance, catalog, constraints = await asyncio.gather(
            get_store_demographics(store_id),
            get_store_performance_data(store_id, days=90),
            get_product_catalog(category),
            get_category_constraints(store_id, category)
        )
        
        current_assortment = performance.get("current_skus", [])
        
        return {
            "store_id": store_id,
            "store_type": demographics.get("store_type"),
            "location": demographics.get("location"),
            "demographics": demographics,
            "total_space_sqft": constraints.get("total_space_sqft", 5000),
            "category_space_sqft": constraints.get("category_space_sqft", {}),
            "current_assortment": current_assortment,
            "sku_count": len(current_assortment),
            "performance_metrics": performance,
            "available_products": catalog,
            "constraints": constraints,
            "timestamp": datetime.utcnow().isoformat()
        }

    async def _analyze_assortment_opportunity(
        self, 
        store_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Analyze assortment optimization opportunity using LLM reasoning."""
        
        performance = store_data["performance_metrics"]
        demographics = store_data["demographics"]
        
        prompt = f"""
        Analyze the following product assortment opportunity for Store {store_data['store_id']}.
        
        Store Profile:
        - Type: {store_data['store_type']}
        - Location: {store_data['location']}
        - Total Space: {store_data['total_space_sqft']:,} sq ft
        - Current SKU Count: {store_data['sku_count']}
        
        Demographics:
        - Population: {demographics.get('population', 'N/A')}
        - Median Income: ${demographics.get('median_income', 0):,}
        - Age Distribution: {demographics.get('age_distribution', {})}
        - Household Size: {demographics.get('avg_household_size', 'N/A')}
        
        Performance (Last 90 Days):
        - Sales per Sq Ft: ${performance.get('sales_per_sqft', 0):.2f}
        - Inventory Turnover: {performance.get('inventory_turnover', 0):.2f}x
        - Stock-out Rate: {performance.get('stockout_rate', 0):.1f}%
        - Slow-Moving SKUs: {performance.get('slow_moving_count', 0)} ({performance.get('slow_moving_pct', 0):.1f}%)
        - Category Mix: {performance.get('category_sales_mix', {})}
        
        Top Performing Products (by revenue):
        {performance.get('top_products', [])}
        
        Underperforming Products (by sales velocity):
        {performance.get('bottom_products', [])}
        
        Local Market Trends:
        {demographics.get('market_trends', 'Standard retail market')}
        
        Provide a detailed assortment analysis covering:
        1. Assortment gaps (unmet customer needs)
        2. Over-assortment issues (too many SKUs in categories)
        3. Local demographic fit assessment
        4. Space utilization efficiency
        5. Category balance recommendations
        6. Competitive positioning
        7. Priority level (high/medium/low) for optimization
        
        Format as JSON with keys: gaps, over_assortment, demographic_fit, 
        space_efficiency, category_recommendations, competitive_position, 
        priority, reasoning
        """
        
        analysis = await self.llm_client.generate_structured_output(
            prompt=prompt,
            system_message="You are an expert retail category manager with deep knowledge of assortment planning, space optimization, and local market analysis.",
            temperature=0.4
        )
        
        return analysis

    async def _generate_assortment_recommendations(
        self,
        store_data: Dict[str, Any],
        analysis: Dict[str, Any],
        category: Optional[str] = None
    ) -> Dict[str, Any]:
        """Generate specific SKU-level assortment recommendations."""
        
        current_skus = set(sku["product_id"] for sku in store_data["current_assortment"])
        available_products = store_data["available_products"]
        performance = store_data["performance_metrics"]
        
        # Products to add (address gaps)
        additions = self._recommend_products_to_add(
            analysis.get("gaps", []),
            available_products,
            current_skus,
            store_data
        )
        
        # Products to remove (rationalize underperformers)
        removals = self._recommend_products_to_remove(
            performance.get("bottom_products", []),
            analysis.get("over_assortment", {}),
            store_data
        )
        
        # Shelf space adjustments
        expansions = self._recommend_shelf_expansions(
            performance.get("top_products", []),
            store_data
        )
        
        reductions = self._recommend_shelf_reductions(
            performance.get("bottom_products", []),
            store_data
        )
        
        return {
            "additions": additions,
            "removals": removals,
            "expansions": expansions,
            "reductions": reductions,
            "net_sku_change": len(additions) - len(removals),
            "estimated_space_freed_sqft": sum(r.get("space_sqft", 0) for r in removals),
            "estimated_space_needed_sqft": sum(a.get("space_sqft", 0) for a in additions)
        }

    def _recommend_products_to_add(
        self,
        gaps: List[Dict[str, Any]],
        available_products: List[Dict[str, Any]],
        current_skus: Set[str],
        store_data: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Recommend products to add based on identified gaps."""
        
        additions = []
        demographics = store_data["demographics"]
        
        # Filter available products not currently in assortment
        candidates = [p for p in available_products if p["product_id"] not in current_skus]
        
        # Score and rank candidates (simplified scoring)
        for product in candidates[:50]:  # Top 50 candidates
            score = 0
            reasons = []
            
            # Demographic fit
            if product.get("target_demographic") == demographics.get("primary_segment"):
                score += 30
                reasons.append("Strong demographic fit")
            
            # Category gap filling
            product_category = product.get("category")
            if any(gap.get("category") == product_category for gap in gaps):
                score += 25
                reasons.append("Fills identified category gap")
            
            # Historical performance in similar stores
            similar_store_performance = product.get("similar_store_sales_rank", 100)
            if similar_store_performance <= 20:
                score += 20
                reasons.append("Top performer in similar stores")
            
            # Margin contribution
            if product.get("margin_pct", 0) > 25:
                score += 15
                reasons.append("High margin product")
            
            # Trending/growing demand
            if product.get("demand_trend") == "growing":
                score += 10
                reasons.append("Growing demand trend")
            
            if score >= 40:  # Threshold for recommendation
                additions.append({
                    "product_id": product["product_id"],
                    "product_name": product["name"],
                    "category": product_category,
                    "recommendation_score": score,
                    "reasons": reasons,
                    "estimated_weekly_sales": product.get("estimated_weekly_sales", 0),
                    "space_sqft": product.get("space_requirement_sqft", 2.0),
                    "initial_stock_units": product.get("recommended_initial_stock", 20)
                })
        
        # Sort by score and return top recommendations
        additions.sort(key=lambda x: x["recommendation_score"], reverse=True)
        return additions[:20]  # Top 20 additions

    def _recommend_products_to_remove(
        self,
        bottom_products: List[Dict[str, Any]],
        over_assortment: Dict[str, Any],
        store_data: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Recommend products to remove based on poor performance."""
        
        removals = []
        
        for product in bottom_products:
            reasons = []
            should_remove = False
            
            # Very low sales velocity
            if product.get("weekly_sales", 0) < 2:
                reasons.append("Low sales velocity (< 2 units/week)")
                should_remove = True
            
            # Poor space productivity
            sales_per_sqft = product.get("sales_per_sqft", 0)
            if sales_per_sqft < 50:  # Below threshold
                reasons.append(f"Low space productivity (${sales_per_sqft:.2f}/sq ft)")
                should_remove = True
            
            # Category over-assortment
            category = product.get("category")
            if category in over_assortment.get("categories", []):
                reasons.append(f"Category {category} is over-assorted")
                should_remove = True
            
            # Declining demand
            if product.get("demand_trend") == "declining":
                reasons.append("Declining demand trend")
                should_remove = True
            
            if should_remove and len(reasons) >= 2:  # At least 2 reasons
                removals.append({
                    "product_id": product["product_id"],
                    "product_name": product["name"],
                    "category": category,
                    "reasons": reasons,
                    "weekly_sales": product.get("weekly_sales", 0),
                    "space_sqft": product.get("space_sqft", 2.0),
                    "estimated_impact": "low"  # Removing low performers = low impact
                })
        
        return removals[:15]  # Top 15 removals

    def _recommend_shelf_expansions(
        self,
        top_products: List[Dict[str, Any]],
        store_data: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Recommend shelf space expansions for top performers."""
        
        expansions = []
        
        for product in top_products[:10]:  # Top 10 products
            current_space = product.get("current_space_sqft", 4.0)
            stockout_frequency = product.get("stockout_frequency", 0)
            
            # High stockout frequency = need more space
            if stockout_frequency > 0.15:  # >15% of days
                recommended_expansion = current_space * 0.25  # 25% increase
                
                expansions.append({
                    "product_id": product["product_id"],
                    "product_name": product["name"],
                    "category": product.get("category"),
                    "current_space_sqft": current_space,
                    "recommended_space_sqft": current_space + recommended_expansion,
                    "expansion_sqft": recommended_expansion,
                    "reason": f"Frequent stockouts ({stockout_frequency:.1%})",
                    "expected_sales_lift_pct": 15
                })
        
        return expansions

    def _recommend_shelf_reductions(
        self,
        bottom_products: List[Dict[str, Any]],
        store_data: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Recommend shelf space reductions for underperformers."""
        
        reductions = []
        
        for product in bottom_products[:10]:
            current_space = product.get("current_space_sqft", 4.0)
            
            if current_space > 2.0:  # Has space to reduce
                recommended_reduction = current_space * 0.30  # 30% reduction
                
                reductions.append({
                    "product_id": product["product_id"],
                    "product_name": product["name"],
                    "category": product.get("category"),
                    "current_space_sqft": current_space,
                    "recommended_space_sqft": current_space - recommended_reduction,
                    "reduction_sqft": recommended_reduction,
                    "reason": "Low sales velocity",
                    "risk_level": "low"
                })
        
        return reductions

    async def _validate_assortment_plan(
        self,
        recommendations: Dict[str, Any],
        store_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Validate recommendations against business constraints."""
        
        validation_result = await validate_assortment_constraints(
            recommendations,
            store_data["constraints"]
        )
        
        if not validation_result["valid"]:
            # Adjust recommendations to meet constraints
            recommendations = self._adjust_for_constraints(
                recommendations,
                validation_result["violations"],
                store_data
            )
        
        return recommendations

    def _adjust_for_constraints(
        self,
        recommendations: Dict[str, Any],
        violations: List[str],
        store_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Adjust recommendations to satisfy constraints."""
        
        # Simple adjustment: if too many additions, keep only top-scored ones
        constraints = store_data["constraints"]
        max_skus = constraints.get("max_sku_count", self.max_sku_count)
        
        current_count = store_data["sku_count"]
        net_change = recommendations["net_sku_change"]
        
        if current_count + net_change > max_skus:
            # Reduce additions
            allowed_additions = max_skus - current_count + len(recommendations["removals"])
            recommendations["additions"] = recommendations["additions"][:allowed_additions]
            recommendations["net_sku_change"] = len(recommendations["additions"]) - len(recommendations["removals"])
        
        return recommendations

    async def _calculate_assortment_impact(
        self,
        recommendations: Dict[str, Any],
        store_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Calculate expected business impact of assortment changes."""
        
        # Estimate revenue impact
        additions_revenue = sum(
            p.get("estimated_weekly_sales", 0) * 52  # Annualized
            for p in recommendations["additions"]
        )
        
        removals_revenue = sum(
            p.get("weekly_sales", 0) * 52  # Annualized
            for p in recommendations["removals"]
        )
        
        net_revenue_impact = additions_revenue - removals_revenue
        
        # Space utilization improvement
        space_freed = recommendations["estimated_space_freed_sqft"]
        space_needed = recommendations["estimated_space_needed_sqft"]
        net_space_change = space_needed - space_freed
        
        # Calculate sales per sq ft improvement
        current_sales_per_sqft = store_data["performance_metrics"].get("sales_per_sqft", 200)
        
        if net_space_change != 0:
            new_sales_per_sqft = (
                (current_sales_per_sqft * store_data["total_space_sqft"] + net_revenue_impact) /
                (store_data["total_space_sqft"] + net_space_change)
            )
        else:
            new_sales_per_sqft = current_sales_per_sqft + (net_revenue_impact / store_data["total_space_sqft"])
        
        improvement_pct = ((new_sales_per_sqft - current_sales_per_sqft) / current_sales_per_sqft) * 100
        
        return {
            "estimated_annual_revenue_impact": round(net_revenue_impact, 2),
            "additions_revenue": round(additions_revenue, 2),
            "removals_revenue_loss": round(removals_revenue, 2),
            "net_space_change_sqft": round(net_space_change, 2),
            "current_sales_per_sqft": round(current_sales_per_sqft, 2),
            "projected_sales_per_sqft": round(new_sales_per_sqft, 2),
            "sales_per_sqft_improvement_pct": round(improvement_pct, 2),
            "inventory_turnover_impact": "Expected to improve by reducing slow-movers",
            "confidence_level": "medium",
            "implementation_cost": self._estimate_implementation_cost(recommendations)
        }

    def _estimate_implementation_cost(self, recommendations: Dict[str, Any]) -> Dict[str, Any]:
        """Estimate cost of implementing assortment changes."""
        
        # Labor costs for planogram changes
        total_changes = (
            len(recommendations["additions"]) +
            len(recommendations["removals"]) +
            len(recommendations["expansions"]) +
            len(recommendations["reductions"])
        )
        
        labor_hours = total_changes * 0.5  # 30 min per change
        labor_cost = labor_hours * 25  # $25/hour
        
        # Initial inventory cost for new products
        inventory_cost = sum(
            p.get("initial_stock_units", 20) * p.get("cost", 10)
            for p in recommendations["additions"]
        )
        
        return {
            "labor_hours": round(labor_hours, 1),
            "labor_cost": round(labor_cost, 2),
            "initial_inventory_cost": round(inventory_cost, 2),
            "total_cost": round(labor_cost + inventory_cost, 2)
        }

    async def _cluster_and_assign_assortments(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Cluster stores by similarity and assign optimal assortments."""
        
        region = context.get("region", "all")
        
        # Cluster stores based on demographics and performance
        clusters = await cluster_stores_by_similarity(region)
        
        assortment_plans = []
        
        for cluster in clusters:
            # Generate master assortment for cluster
            cluster_plan = await self._generate_cluster_assortment(cluster)
            assortment_plans.append(cluster_plan)
        
        return {
            "region": region,
            "clusters_identified": len(clusters),
            "cluster_details": clusters,
            "assortment_plans": assortment_plans,
            "total_stores_impacted": sum(len(c["stores"]) for c in clusters),
            "timestamp": datetime.utcnow().isoformat()
        }

    async def _generate_cluster_assortment(self, cluster: Dict[str, Any]) -> Dict[str, Any]:
        """Generate master assortment plan for a store cluster."""
        
        return {
            "cluster_id": cluster["cluster_id"],
            "cluster_name": cluster["name"],
            "store_count": len(cluster["stores"]),
            "stores": cluster["stores"],
            "characteristics": cluster["characteristics"],
            "recommended_sku_count": cluster.get("optimal_sku_count", 800),
            "core_assortment": cluster.get("core_skus", []),
            "optional_assortment": cluster.get("optional_skus", []),
            "test_products": cluster.get("test_products", [])
        }

    async def _allocate_new_products(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Allocate new product introductions across stores."""
        
        new_products = context.get("new_products", [])
        rollout_strategy = context.get("strategy", "phased")  # phased, broad, targeted
        
        store_allocations = []
        
        for product in new_products:
            allocation = await self._determine_new_product_allocation(product, rollout_strategy)
            store_allocations.append(allocation)
        
        return {
            "new_products_count": len(new_products),
            "rollout_strategy": rollout_strategy,
            "store_allocations": store_allocations,
            "total_stores_receiving_products": len(set(
                store_id 
                for alloc in store_allocations 
                for store_id in alloc["stores"]
            )),
            "timestamp": datetime.utcnow().isoformat()
        }

    async def _determine_new_product_allocation(
        self,
        product: Dict[str, Any],
        strategy: str
    ) -> Dict[str, Any]:
        """Determine which stores should receive a new product."""
        
        # Simplified allocation logic
        if strategy == "phased":
            # Start with 20% of stores (test group)
            test_stores = ["STORE-001", "STORE-015", "STORE-023"]
        elif strategy == "broad":
            # All stores except very small ones
            test_stores = ["STORE-" + str(i).zfill(3) for i in range(1, 51)]
        else:  # targeted
            # Only stores matching target demographic
            test_stores = ["STORE-005", "STORE-018", "STORE-032"]
        
        return {
            "product_id": product["product_id"],
            "product_name": product["name"],
            "stores": test_stores,
            "launch_date": (datetime.utcnow() + timedelta(days=14)).isoformat(),
            "evaluation_period_days": 90,
            "success_criteria": {
                "min_weekly_sales": 10,
                "min_margin_pct": 20,
                "max_stockout_rate": 0.10
            }
        }

    async def _seasonal_assortment_refresh(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Perform seasonal assortment refresh."""
        
        season = context.get("season", "spring")
        store_ids = context.get("store_ids", [])
        
        seasonal_rules = await get_seasonal_assortment_rules(season)
        
        refresh_plans = []
        
        for store_id in store_ids:
            plan = await self._generate_seasonal_refresh_plan(store_id, season, seasonal_rules)
            refresh_plans.append(plan)
        
        return {
            "season": season,
            "stores_count": len(store_ids),
            "refresh_plans": refresh_plans,
            "total_skus_added": sum(len(p["additions"]) for p in refresh_plans),
            "total_skus_removed": sum(len(p["removals"]) for p in refresh_plans),
            "timestamp": datetime.utcnow().isoformat()
        }

    async def _generate_seasonal_refresh_plan(
        self,
        store_id: str,
        season: str,
        rules: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Generate seasonal refresh plan for a store."""
        
        return {
            "store_id": store_id,
            "season": season,
            "additions": rules.get("products_to_add", []),
            "removals": rules.get("products_to_remove", []),
            "featured_categories": rules.get("featured_categories", []),
            "implementation_date": rules.get("start_date")
        }

    async def _rationalize_underperforming_skus(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Identify and rationalize underperforming SKUs across stores."""
        
        threshold_weeks = context.get("threshold_weeks", 12)
        min_sales_velocity = context.get("min_sales_velocity", 2)  # units per week
        
        # TODO: Query database for underperformers
        underperformers = []
        
        rationalization_plan = {
            "analysis_period_weeks": threshold_weeks,
            "threshold_sales_velocity": min_sales_velocity,
            "underperforming_skus": len(underperformers),
            "recommended_actions": underperformers,
            "total_space_to_free_sqft": sum(p.get("space_sqft", 0) for p in underperformers),
            "estimated_inventory_reduction": sum(p.get("current_stock", 0) for p in underperformers),
            "timestamp": datetime.utcnow().isoformat()
        }
        
        return rationalization_plan

    async def _optimize_shelf_space_allocation(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Optimize shelf space allocation across categories."""
        
        store_id = context.get("store_id")
        
        optimization_result = await optimize_shelf_allocation(store_id)
        
        return optimization_result
