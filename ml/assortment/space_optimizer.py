"""
Shelf Space Optimization
Optimize shelf space allocation across categories and products using mathematical optimization.
"""

import numpy as np
import pandas as pd
from typing import Dict, Any, List, Optional, Tuple
from scipy.optimize import linprog, minimize
import logging

logger = logging.getLogger(__name__)


class ShelfSpaceOptimizer:
    """
    Optimize shelf space allocation to maximize revenue, profit, or other objectives.
    
    Uses linear programming to solve the space allocation problem with constraints:
    - Total space constraint
    - Minimum/maximum space per category
    - Minimum display quantity per product
    - Shelf capacity constraints
    """
    
    def __init__(
        self,
        objective: str = "profit",  # profit, revenue, turnover
        include_cross_effects: bool = False
    ):
        self.objective = objective
        self.include_cross_effects = include_cross_effects
        self.optimization_result = None
        
    def optimize(
        self,
        products: pd.DataFrame,
        total_space: float,
        constraints: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Optimize space allocation for products.
        
        Args:
            products: DataFrame with columns:
                - product_id
                - category
                - current_space (sq ft)
                - sales_per_sqft
                - margin_pct
                - min_space (optional)
                - max_space (optional)
            total_space: Total available space in sq ft
            constraints: Additional constraints (category limits, etc.)
            
        Returns:
            Dict with optimal space allocation and expected performance
        """
        
        logger.info(f"Optimizing space for {len(products)} products")
        logger.info(f"Total space: {total_space} sq ft")
        logger.info(f"Objective: {self.objective}")
        
        # Prepare optimization problem
        n_products = len(products)
        
        # Objective function coefficients (what we're maximizing)
        if self.objective == "profit":
            # Maximize: sum(sales_per_sqft * margin_pct * space)
            c = -(products["sales_per_sqft"] * products["margin_pct"] / 100).values
        elif self.objective == "revenue":
            # Maximize: sum(sales_per_sqft * space)
            c = -products["sales_per_sqft"].values
        elif self.objective == "turnover":
            # Maximize inventory turnover (approximate)
            c = -(products["sales_per_sqft"] / products.get("avg_inventory_value_per_sqft", 100)).values
        else:
            raise ValueError(f"Unknown objective: {self.objective}")
        
        # Inequality constraints (A_ub * x <= b_ub)
        A_ub = []
        b_ub = []
        
        # Constraint 1: Total space <= available space
        A_ub.append(np.ones(n_products))
        b_ub.append(total_space)
        
        # Constraint 2: Maximum space per product
        if "max_space" in products.columns:
            for i, max_space in enumerate(products["max_space"]):
                if pd.notna(max_space):
                    constraint = np.zeros(n_products)
                    constraint[i] = 1
                    A_ub.append(constraint)
                    b_ub.append(max_space)
        
        # Constraint 3: Category-level space limits
        if constraints and "category_max_space" in constraints:
            category_max = constraints["category_max_space"]
            for category, max_space in category_max.items():
                category_mask = (products["category"] == category).values.astype(float)
                A_ub.append(category_mask)
                b_ub.append(max_space)
        
        # Bounds on variables (min and max space per product)
        bounds = []
        for _, product in products.iterrows():
            min_space = product.get("min_space", 1.0)  # Minimum 1 sq ft
            max_space = product.get("max_space", total_space)
            bounds.append((min_space, max_space))
        
        # Equality constraints (A_eq * x = b_eq)
        A_eq = []
        b_eq = []
        
        # Constraint: Category minimum space
        if constraints and "category_min_space" in constraints:
            category_min = constraints["category_min_space"]
            for category, min_space in category_min.items():
                category_mask = (products["category"] == category).values.astype(float)
                # Convert to inequality: -sum(space) <= -min_space
                A_ub.append(-category_mask)
                b_ub.append(-min_space)
        
        # Convert to numpy arrays
        A_ub = np.array(A_ub) if A_ub else None
        b_ub = np.array(b_ub) if b_ub else None
        
        # Solve optimization problem
        result = linprog(
            c=c,
            A_ub=A_ub,
            b_ub=b_ub,
            bounds=bounds,
            method="highs",  # Use HiGHS solver (fast and robust)
            options={"disp": False}
        )
        
        if not result.success:
            logger.warning(f"Optimization failed: {result.message}")
            # Fall back to proportional allocation
            return self._fallback_allocation(products, total_space)
        
        # Extract optimal allocation
        optimal_space = result.x
        products["optimal_space"] = optimal_space
        products["space_change"] = optimal_space - products["current_space"]
        products["space_change_pct"] = (
            (optimal_space - products["current_space"]) / products["current_space"] * 100
        )
        
        # Calculate performance metrics
        performance = self._calculate_performance(products, optimal_space)
        
        self.optimization_result = {
            "products": products.to_dict("records"),
            "performance": performance,
            "total_space_allocated": optimal_space.sum(),
            "space_utilization_pct": (optimal_space.sum() / total_space) * 100,
            "optimization_status": result.message,
            "objective_value": -result.fun,  # Negate because we minimized negative
            "constraints_satisfied": True
        }
        
        return self.optimization_result
    
    def _calculate_performance(
        self,
        products: pd.DataFrame,
        optimal_space: np.ndarray
    ) -> Dict[str, Any]:
        """Calculate expected performance with optimal allocation."""
        
        current_revenue = (products["current_space"] * products["sales_per_sqft"]).sum()
        optimal_revenue = (optimal_space * products["sales_per_sqft"]).sum()
        
        current_profit = (
            products["current_space"] * 
            products["sales_per_sqft"] * 
            products["margin_pct"] / 100
        ).sum()
        
        optimal_profit = (
            optimal_space * 
            products["sales_per_sqft"] * 
            products["margin_pct"] / 100
        ).sum()
        
        return {
            "current_revenue": round(current_revenue, 2),
            "optimal_revenue": round(optimal_revenue, 2),
            "revenue_improvement": round(optimal_revenue - current_revenue, 2),
            "revenue_improvement_pct": round(
                ((optimal_revenue - current_revenue) / current_revenue * 100), 2
            ) if current_revenue > 0 else 0,
            "current_profit": round(current_profit, 2),
            "optimal_profit": round(optimal_profit, 2),
            "profit_improvement": round(optimal_profit - current_profit, 2),
            "profit_improvement_pct": round(
                ((optimal_profit - current_profit) / current_profit * 100), 2
            ) if current_profit > 0 else 0
        }
    
    def _fallback_allocation(
        self,
        products: pd.DataFrame,
        total_space: float
    ) -> Dict[str, Any]:
        """
        Fallback allocation strategy when optimization fails.
        
        Uses proportional allocation based on current sales performance.
        """
        
        logger.info("Using fallback proportional allocation")
        
        # Allocate space proportional to revenue contribution
        revenue = products["current_space"] * products["sales_per_sqft"]
        total_revenue = revenue.sum()
        
        if total_revenue > 0:
            space_proportion = revenue / total_revenue
            optimal_space = space_proportion * total_space
        else:
            # Equal allocation if no revenue data
            optimal_space = np.full(len(products), total_space / len(products))
        
        # Apply min/max constraints
        optimal_space = np.clip(
            optimal_space,
            products.get("min_space", 1.0),
            products.get("max_space", total_space)
        )
        
        # Normalize to total space
        optimal_space = optimal_space * (total_space / optimal_space.sum())
        
        products["optimal_space"] = optimal_space
        products["space_change"] = optimal_space - products["current_space"]
        
        performance = self._calculate_performance(products, optimal_space)
        
        return {
            "products": products.to_dict("records"),
            "performance": performance,
            "total_space_allocated": optimal_space.sum(),
            "space_utilization_pct": 100.0,
            "optimization_status": "fallback_proportional",
            "constraints_satisfied": True
        }
    
    def optimize_with_demand_response(
        self,
        products: pd.DataFrame,
        total_space: float,
        elasticity: float = -0.3
    ) -> Dict[str, Any]:
        """
        Optimize considering demand response to space changes.
        
        Uses nonlinear optimization to account for the relationship:
        sales = base_sales * (space / base_space) ^ elasticity
        
        Args:
            products: Product data
            total_space: Available space
            elasticity: Space elasticity of sales (typically negative)
        """
        
        logger.info("Optimizing with demand response model")
        
        base_space = products["current_space"].values
        base_sales = products["sales_per_sqft"].values * base_space
        margins = products["margin_pct"].values / 100
        
        def objective(x):
            """Objective: maximize profit with demand response."""
            # sales(x) = base_sales * (x / base_space) ^ elasticity
            sales = base_sales * np.power(x / base_space, elasticity)
            profit = (sales * margins).sum()
            return -profit  # Minimize negative profit
        
        def constraint_total_space(x):
            """Constraint: sum of space <= total_space."""
            return total_space - x.sum()
        
        # Initial guess: current allocation
        x0 = base_space.copy()
        
        # Bounds
        bounds = [(1.0, total_space) for _ in range(len(products))]
        
        # Constraints
        constraints = [
            {"type": "ineq", "fun": constraint_total_space}
        ]
        
        # Solve
        result = minimize(
            objective,
            x0,
            method="SLSQP",
            bounds=bounds,
            constraints=constraints,
            options={"ftol": 1e-6, "disp": False}
        )
        
        if result.success:
            optimal_space = result.x
            products["optimal_space"] = optimal_space
            products["space_change"] = optimal_space - products["current_space"]
            
            # Calculate expected sales with demand response
            products["expected_sales_change_pct"] = (
                (np.power(optimal_space / base_space, elasticity) - 1) * 100
            )
            
            performance = self._calculate_performance(products, optimal_space)
            
            return {
                "products": products.to_dict("records"),
                "performance": performance,
                "total_space_allocated": optimal_space.sum(),
                "space_utilization_pct": (optimal_space.sum() / total_space) * 100,
                "optimization_status": "success_with_demand_response",
                "elasticity_used": elasticity
            }
        else:
            logger.warning("Demand response optimization failed, using standard optimization")
            return self.optimize(products, total_space)


def calculate_optimal_facings(
    product: Dict[str, Any],
    shelf_width: float = 48.0,  # inches
    target_days_of_supply: float = 3.0
) -> int:
    """
    Calculate optimal number of product facings on shelf.
    
    Facings = how many units wide the product should be displayed
    
    Args:
        product: Product data including unit_width, daily_sales
        shelf_width: Width of shelf in inches
        target_days_of_supply: How many days of inventory to display
        
    Returns:
        Optimal number of facings
    """
    
    unit_width = product.get("unit_width_inches", 4.0)
    daily_sales = product.get("daily_sales", 10)
    units_per_facing = product.get("units_per_facing", 6)  # Depth of shelf
    
    # Calculate required facings for target days of supply
    required_units = daily_sales * target_days_of_supply
    required_facings = np.ceil(required_units / units_per_facing)
    
    # Check if it fits on shelf
    max_facings = int(shelf_width / unit_width)
    
    optimal_facings = int(min(required_facings, max_facings))
    optimal_facings = max(optimal_facings, 1)  # At least 1 facing
    
    return optimal_facings


def simulate_space_scenarios(
    products: pd.DataFrame,
    total_space: float,
    scenarios: List[Dict[str, Any]]
) -> pd.DataFrame:
    """
    Simulate different space allocation scenarios and compare outcomes.
    
    Args:
        products: Product data
        total_space: Available space
        scenarios: List of scenario configurations
        
    Returns:
        DataFrame comparing scenario outcomes
    """
    
    results = []
    
    for scenario in scenarios:
        optimizer = ShelfSpaceOptimizer(
            objective=scenario.get("objective", "profit")
        )
        
        result = optimizer.optimize(
            products=products.copy(),
            total_space=total_space,
            constraints=scenario.get("constraints")
        )
        
        results.append({
            "scenario_name": scenario.get("name", "Unnamed"),
            "objective": scenario.get("objective"),
            "revenue": result["performance"]["optimal_revenue"],
            "profit": result["performance"]["optimal_profit"],
            "revenue_improvement_pct": result["performance"]["revenue_improvement_pct"],
            "profit_improvement_pct": result["performance"]["profit_improvement_pct"]
        })
    
    return pd.DataFrame(results)
