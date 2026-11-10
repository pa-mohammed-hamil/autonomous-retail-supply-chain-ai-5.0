
"""
Autonomous Retail Supply Chain AI 5.0
File: ai/tools/python_tools.py

Purpose:
    Restricted numerical and analytical tools for AI agents.

Features:
    - Safe mathematical expression evaluation
    - Descriptive statistics
    - Sales analytics
    - Demand forecasting metrics
    - Inventory analytics
    - Profit and financial calculations
    - Growth rate and moving averages
    - Correlation analysis
    - Structured agent tool execution

Security:
    No eval(), exec(), subprocess, file access,
    network access, or arbitrary Python execution.

Dependencies:
    Python 3.10+ standard library only.
"""

from __future__ import annotations

import ast
import math
import operator
import statistics
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Sequence


# ============================================================
# EXCEPTIONS
# ============================================================

class ToolError(Exception):
    """Base exception for tool execution errors."""


class ToolValidationError(ToolError):
    """Raised when tool inputs are invalid."""


class ToolExecutionError(ToolError):
    """Raised when a supported calculation fails."""


# ============================================================
# VALIDATION
# ============================================================

def validate_number(
    value: Any,
    name: str = "value"
) -> float:
    """Validate and normalize a finite numeric value."""

    if isinstance(value, bool):
        raise ToolValidationError(
            f"{name} must be numeric, not boolean."
        )

    if not isinstance(value, (int, float)):
        raise ToolValidationError(
            f"{name} must be an integer or float."
        )

    try:
        number = float(value)
    except (OverflowError, ValueError) as exc:
        raise ToolValidationError(
            f"{name} cannot be converted to a float."
        ) from exc

    if not math.isfinite(number):
        raise ToolValidationError(
            f"{name} must be finite."
        )

    return number


def validate_numbers(
    values: Sequence[int | float],
    name: str = "values",
    minimum_length: int = 1
) -> list[float]:
    """Validate a sequence of numeric values."""

    if isinstance(values, (str, bytes)):
        raise ToolValidationError(
            f"{name} must be a numeric sequence."
        )

    if not isinstance(values, (list, tuple)):
        raise ToolValidationError(
            f"{name} must be a list or tuple."
        )

    if len(values) < minimum_length:
        raise ToolValidationError(
            f"{name} requires at least "
            f"{minimum_length} values."
        )

    return [
        validate_number(value, f"{name}[{index}]")
        for index, value in enumerate(values)
    ]


def validate_nonnegative(
    value: Any,
    name: str
) -> float:
    """Validate a non-negative number."""

    number = validate_number(value, name)

    if number < 0:
        raise ToolValidationError(
            f"{name} cannot be negative."
        )

    return number


def safe_divide(
    numerator: float,
    denominator: float,
    default: float | None = None
) -> float | None:
    """Safely divide two numbers."""

    numerator = validate_number(
        numerator, "numerator"
    )

    denominator = validate_number(
        denominator, "denominator"
    )

    if denominator == 0:
        return default

    return numerator / denominator


def round_result(
    value: float,
    decimals: int = 4
) -> float:
    """Round a finite numerical result."""

    if (
        isinstance(decimals, bool)
        or not isinstance(decimals, int)
        or not 0 <= decimals <= 12
    ):
        raise ToolValidationError(
            "decimals must be between 0 and 12."
        )

    return round(
        validate_number(value), decimals
    )


# ============================================================
# SAFE MATHEMATICAL EXPRESSION EVALUATOR
# ============================================================

_ALLOWED_OPERATORS: dict[
    type[ast.operator],
    Callable[[float, float], float]
] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

_ALLOWED_UNARY_OPERATORS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

_ALLOWED_FUNCTIONS: dict[str, Callable[..., Any]] = {
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "sqrt": math.sqrt,
    "ceil": math.ceil,
    "floor": math.floor,
    "log": math.log,
    "log10": math.log10,
}


def _evaluate_ast(
    node: ast.AST,
    depth: int = 0
) -> float:
    """Recursively evaluate supported arithmetic AST nodes."""

    if depth > 20:
        raise ToolValidationError(
            "Expression nesting limit exceeded."
        )

    if isinstance(node, ast.Expression):
        return _evaluate_ast(node.body, depth + 1)

    if isinstance(node, ast.Constant):
        return validate_number(node.value)

    if isinstance(node, ast.UnaryOp):
        operation = _ALLOWED_UNARY_OPERATORS.get(
            type(node.op)
        )

        if operation is None:
            raise ToolValidationError(
                "Unsupported unary operator."
            )

        operand = _evaluate_ast(
            node.operand, depth + 1
        )

        return validate_number(operation(operand))

    if isinstance(node, ast.BinOp):
        operation = _ALLOWED_OPERATORS.get(
            type(node.op)
        )

        if operation is None:
            raise ToolValidationError(
                "Unsupported binary operator."
            )

        left = _evaluate_ast(node.left, depth + 1)
        right = _evaluate_ast(node.right, depth + 1)

        if isinstance(node.op, ast.Pow):
            if abs(right) > 100 or abs(left) > 1e12:
                raise ToolValidationError(
                    "Exponentiation limit exceeded."
                )

        try:
            result = operation(left, right)

        except (
            ZeroDivisionError,
            OverflowError,
            ValueError
        ) as exc:
            raise ToolExecutionError(
                "Arithmetic operation failed."
            ) from exc

        return validate_number(result)

    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise ToolValidationError(
                "Only approved mathematical functions "
                "can be called."
            )

        function = _ALLOWED_FUNCTIONS.get(
            node.func.id
        )

        if function is None:
            raise ToolValidationError(
                f"Function '{node.func.id}' is not allowed."
            )

        if node.keywords:
            raise ToolValidationError(
                "Keyword arguments are not supported."
            )

        if len(node.args) > 20:
            raise ToolValidationError(
                "Too many function arguments."
            )

        arguments = [
            _evaluate_ast(arg, depth + 1)
            for arg in node.args
        ]

        try:
            result = function(*arguments)

        except (
            ValueError,
            TypeError,
            ZeroDivisionError,
            OverflowError
        ) as exc:
            raise ToolExecutionError(
                "Mathematical function failed."
            ) from exc

        return validate_number(result)

    raise ToolValidationError(
        f"Unsupported expression: "
        f"{type(node).__name__}"
    )


def safe_calculate(
    expression: str
) -> dict[str, Any]:
    """
    Evaluate an arithmetic expression without eval().

    Example:
        safe_calculate("(1200 * 0.18) + 500")
    """

    if not isinstance(expression, str):
        raise ToolValidationError(
            "Expression must be a string."
        )

    expression = expression.strip()

    if not expression:
        raise ToolValidationError(
            "Expression cannot be empty."
        )

    if len(expression) > 500:
        raise ToolValidationError(
            "Expression is too long."
        )

    try:
        tree = ast.parse(
            expression, mode="eval"
        )

    except SyntaxError as exc:
        raise ToolValidationError(
            "Invalid mathematical expression."
        ) from exc

    result = _evaluate_ast(tree)

    return {
        "expression": expression,
        "result": round_result(result, 6),
        "method": "restricted_ast_evaluation",
        "executed_at": datetime.now(
            timezone.utc
        ).isoformat()
    }


# ============================================================
# DESCRIPTIVE STATISTICS
# ============================================================

def calculate_statistics(
    values: Sequence[int | float]
) -> dict[str, Any]:
    """Calculate descriptive statistics."""

    numbers = validate_numbers(values)

    result = {
        "count": len(numbers),
        "sum": round_result(sum(numbers)),
        "mean": round_result(
            statistics.mean(numbers)
        ),
        "median": round_result(
            statistics.median(numbers)
        ),
        "minimum": min(numbers),
        "maximum": max(numbers),
        "range": round_result(
            max(numbers) - min(numbers)
        ),
        "variance": 0.0,
        "standard_deviation": 0.0,
    }

    if len(numbers) >= 2:
        result["variance"] = round_result(
            statistics.variance(numbers)
        )

        result["standard_deviation"] = round_result(
            statistics.stdev(numbers)
        )

    return result


def calculate_percentile(
    values: Sequence[int | float],
    percentile: float
) -> dict[str, float]:
    """Calculate a percentile using linear interpolation."""

    numbers = sorted(validate_numbers(values))

    percentile = validate_number(
        percentile, "percentile"
    )

    if not 0 <= percentile <= 100:
        raise ToolValidationError(
            "Percentile must be between 0 and 100."
        )

    position = (
        (len(numbers) - 1)
        * percentile / 100
    )

    lower = math.floor(position)
    upper = math.ceil(position)

    if lower == upper:
        result = numbers[lower]

    else:
        weight = position - lower

        result = (
            numbers[lower] * (1 - weight)
            + numbers[upper] * weight
        )

    return {
        "percentile": percentile,
        "value": round_result(result)
    }


def calculate_correlation(
    x_values: Sequence[int | float],
    y_values: Sequence[int | float]
) -> dict[str, Any]:
    """Calculate Pearson correlation."""

    x = validate_numbers(
        x_values, "x_values", 2
    )

    y = validate_numbers(
        y_values, "y_values", 2
    )

    if len(x) != len(y):
        raise ToolValidationError(
            "Both sequences must have equal length."
        )

    if (
        len(set(x)) == 1
        or len(set(y)) == 1
    ):
        return {
            "correlation": None,
            "reason": "Zero variance in input."
        }

    correlation = statistics.correlation(x, y)

    return {
        "correlation": round_result(
            correlation, 6
        ),
        "strength": (
            "strong"
            if abs(correlation) >= 0.7
            else "moderate"
            if abs(correlation) >= 0.3
            else "weak"
        )
    }


# ============================================================
# SALES ANALYTICS
# ============================================================

def calculate_sales_revenue(
    quantities: Sequence[int | float],
    prices: Sequence[int | float]
) -> dict[str, Any]:
    """Calculate revenue from product quantities and prices."""

    quantities = validate_numbers(
        quantities, "quantities"
    )

    prices = validate_numbers(
        prices, "prices"
    )

    if len(quantities) != len(prices):
        raise ToolValidationError(
            "Quantities and prices must have equal length."
        )

    for quantity in quantities:
        validate_nonnegative(
            quantity, "quantity"
        )

    for price in prices:
        validate_nonnegative(
            price, "price"
        )

    revenues = [
        quantity * price
        for quantity, price in zip(
            quantities, prices
        )
    ]

    return {
        "total_revenue": round_result(
            sum(revenues), 2
        ),
        "total_units": round_result(
            sum(quantities)
        ),
        "line_revenues": [
            round_result(value, 2)
            for value in revenues
        ],
        "currency": "INR"
    }


def calculate_growth_rate(
    previous_value: float,
    current_value: float
) -> dict[str, Any]:
    """Calculate percentage growth."""

    previous = validate_number(
        previous_value, "previous_value"
    )

    current = validate_number(
        current_value, "current_value"
    )

    if previous == 0:
        return {
            "growth_rate_percent": None,
            "reason": (
                "Growth percentage is undefined "
                "when previous value is zero."
            )
        }

    growth = (
        (current - previous)
        / abs(previous)
    ) * 100

    return {
        "previous_value": previous,
        "current_value": current,
        "growth_rate_percent": round_result(
            growth, 2
        )
    }


def calculate_sales_kpis(
    revenue: float,
    orders: int,
    units_sold: int,
    total_cost: float
) -> dict[str, Any]:
    """Calculate retail sales KPIs."""

    revenue = validate_nonnegative(
        revenue, "revenue"
    )

    total_cost = validate_nonnegative(
        total_cost, "total_cost"
    )

    orders = validate_nonnegative(
        orders, "orders"
    )

    units_sold = validate_nonnegative(
        units_sold, "units_sold"
    )

    profit = revenue - total_cost

    return {
        "revenue": round_result(revenue, 2),
        "total_cost": round_result(total_cost, 2),
        "gross_profit": round_result(profit, 2),
        "gross_margin_percent": (
            round_result(
                profit / revenue * 100, 2
            )
            if revenue > 0 else None
        ),
        "average_order_value": (
            round_result(
                revenue / orders, 2
            )
            if orders > 0 else None
        ),
        "revenue_per_unit": (
            round_result(
                revenue / units_sold, 2
            )
            if units_sold > 0 else None
        ),
        "currency": "INR"
    }


# ============================================================
# TIME SERIES AND DEMAND ANALYTICS
# ============================================================

def moving_average(
    values: Sequence[int | float],
    window: int = 3
) -> dict[str, Any]:
    """Calculate a rolling moving average."""

    numbers = validate_numbers(values)

    if (
        isinstance(window, bool)
        or not isinstance(window, int)
        or window <= 0
    ):
        raise ToolValidationError(
            "Window must be a positive integer."
        )

    if window > len(numbers):
        raise ToolValidationError(
            "Window exceeds available observations."
        )

    averages = []

    for index in range(
        window, len(numbers) + 1
    ):
        segment = numbers[
            index - window:index
        ]

        averages.append(
            round_result(
                statistics.mean(segment)
            )
        )

    return {
        "window": window,
        "moving_averages": averages,
        "latest_average": averages[-1]
    }


def exponential_smoothing(
    values: Sequence[int | float],
    alpha: float = 0.3
) -> dict[str, Any]:
    """Calculate simple exponential smoothing."""

    numbers = validate_numbers(values)

    alpha = validate_number(
        alpha, "alpha"
    )

    if not 0 < alpha <= 1:
        raise ToolValidationError(
            "Alpha must be greater than 0 and at most 1."
        )

    smoothed = numbers[0]
    history = [round_result(smoothed)]

    for value in numbers[1:]:
        smoothed = (
            alpha * value
            + (1 - alpha) * smoothed
        )

        history.append(
            round_result(smoothed)
        )

    return {
        "alpha": alpha,
        "smoothed_values": history,
        "next_period_forecast": round_result(
            smoothed
        ),
        "method": "simple_exponential_smoothing"
    }


def calculate_forecast_metrics(
    actual: Sequence[int | float],
    predicted: Sequence[int | float]
) -> dict[str, Any]:
    """Evaluate forecasting accuracy."""

    actual = validate_numbers(
        actual, "actual"
    )

    predicted = validate_numbers(
        predicted, "predicted"
    )

    if len(actual) != len(predicted):
        raise ToolValidationError(
            "Actual and predicted lengths must match."
        )

    errors = [
        actual_value - predicted_value
        for actual_value, predicted_value
        in zip(actual, predicted)
    ]

    absolute_errors = [
        abs(error)
        for error in errors
    ]

    squared_errors = [
        error ** 2
        for error in errors
    ]

    mae = statistics.mean(
        absolute_errors
    )

    rmse = math.sqrt(
        statistics.mean(squared_errors)
    )

    actual_total = sum(
        abs(value) for value in actual
    )

    wape = (
        sum(absolute_errors)
        / actual_total * 100
        if actual_total > 0
        else None
    )

    bias = statistics.mean(errors)

    return {
        "mae": round_result(mae),
        "rmse": round_result(rmse),
        "wape_percent": (
            round_result(wape, 2)
            if wape is not None else None
        ),
        "bias": round_result(bias),
        "sample_count": len(actual)
    }


def detect_demand_spike(
    historical_demand: Sequence[int | float],
    current_demand: float,
    threshold_multiplier: float = 1.5
) -> dict[str, Any]:
    """Detect demand spikes using historical mean."""

    history = validate_numbers(
        historical_demand,
        "historical_demand",
        minimum_length=3
    )

    current = validate_nonnegative(
        current_demand, "current_demand"
    )

    multiplier = validate_number(
        threshold_multiplier,
        "threshold_multiplier"
    )

    if multiplier <= 1:
        raise ToolValidationError(
            "Threshold multiplier must exceed 1."
        )

    historical_mean = statistics.mean(history)

    threshold = historical_mean * multiplier

    is_spike = (
        current > threshold
        if historical_mean > 0
        else current > 0
    )

    return {
        "historical_average": round_result(
            historical_mean
        ),
        "current_demand": current,
        "threshold": round_result(threshold),
        "spike_detected": is_spike,
        "increase_percent": (
            round_result(
                (current - historical_mean)
                / historical_mean * 100,
                2
            )
            if historical_mean > 0 else None
        ),
        "method": "mean_multiplier_baseline"
    }


# ============================================================
# INVENTORY ANALYTICS
# ============================================================

def calculate_inventory_turnover(
    cost_of_goods_sold: float,
    average_inventory_value: float
) -> dict[str, Any]:
    """Calculate inventory turnover ratio."""

    cogs = validate_nonnegative(
        cost_of_goods_sold,
        "cost_of_goods_sold"
    )

    inventory = validate_nonnegative(
        average_inventory_value,
        "average_inventory_value"
    )

    if inventory == 0:
        return {
            "inventory_turnover": None,
            "reason": "Average inventory value is zero."
        }

    turnover = cogs / inventory

    return {
        "inventory_turnover": round_result(
            turnover
        ),
        "cost_of_goods_sold": cogs,
        "average_inventory_value": inventory
    }


def calculate_stock_coverage(
    available_stock: float,
    average_daily_demand: float
) -> dict[str, Any]:
    """Estimate how many days stock will last."""

    stock = validate_nonnegative(
        available_stock, "available_stock"
    )

    demand = validate_nonnegative(
        average_daily_demand,
        "average_daily_demand"
    )

    if demand == 0:
        return {
            "days_of_cover": None,
            "reason": "Average daily demand is zero."
        }

    return {
        "available_stock": stock,
        "average_daily_demand": demand,
        "days_of_cover": round_result(
            stock / demand, 2
        )
    }


def calculate_reorder_point(
    average_daily_demand: float,
    lead_time_days: float,
    safety_stock: float = 0
) -> dict[str, Any]:
    """Calculate the inventory reorder point."""

    demand = validate_nonnegative(
        average_daily_demand,
        "average_daily_demand"
    )

    lead_time = validate_nonnegative(
        lead_time_days, "lead_time_days"
    )

    safety = validate_nonnegative(
        safety_stock, "safety_stock"
    )

    reorder_point = (
        demand * lead_time + safety
    )

    return {
        "average_daily_demand": demand,
        "lead_time_days": lead_time,
        "safety_stock": safety,
        "reorder_point": math.ceil(reorder_point)
    }


def calculate_fill_rate(
    fulfilled_units: float,
    requested_units: float
) -> dict[str, Any]:
    """Calculate order fulfillment fill rate."""

    fulfilled = validate_nonnegative(
        fulfilled_units, "fulfilled_units"
    )

    requested = validate_nonnegative(
        requested_units, "requested_units"
    )

    if fulfilled > requested:
        raise ToolValidationError(
            "Fulfilled units cannot exceed requested units."
        )

    return {
        "fill_rate_percent": (
            round_result(
                fulfilled / requested * 100, 2
            )
            if requested > 0 else None
        ),
        "fulfilled_units": fulfilled,
        "requested_units": requested
    }


# ============================================================
# FINANCIAL ANALYTICS
# ============================================================

def calculate_profit_margin(
    revenue: float,
    cost: float
) -> dict[str, Any]:
    """Calculate gross profit and margin."""

    revenue = validate_nonnegative(
        revenue, "revenue"
    )

    cost = validate_nonnegative(
        cost, "cost"
    )

    profit = revenue - cost

    return {
        "revenue": revenue,
        "cost": cost,
        "profit": round_result(profit, 2),
        "margin_percent": (
            round_result(
                profit / revenue * 100, 2
            )
            if revenue > 0 else None
        )
    }


def calculate_roi(
    investment_cost: float,
    net_return: float
) -> dict[str, Any]:
    """Calculate return on investment."""

    investment = validate_nonnegative(
        investment_cost, "investment_cost"
    )

    net_return = validate_number(
        net_return, "net_return"
    )

    if investment == 0:
        return {
            "roi_percent": None,
            "reason": "Investment cost is zero."
        }

    return {
        "investment_cost": investment,
        "net_return": net_return,
        "roi_percent": round_result(
            net_return / investment * 100,
            2
        )
    }


def calculate_break_even_units(
    fixed_cost: float,
    selling_price_per_unit: float,
    variable_cost_per_unit: float
) -> dict[str, Any]:
    """Calculate break-even sales volume."""

    fixed = validate_nonnegative(
        fixed_cost, "fixed_cost"
    )

    selling = validate_nonnegative(
        selling_price_per_unit,
        "selling_price_per_unit"
    )

    variable = validate_nonnegative(
        variable_cost_per_unit,
        "variable_cost_per_unit"
    )

    contribution = selling - variable

    if contribution <= 0:
        return {
            "break_even_units": None,
            "reason": (
                "Contribution margin must be positive."
            )
        }

    return {
        "fixed_cost": fixed,
        "contribution_per_unit": round_result(
            contribution, 2
        ),
        "break_even_units": math.ceil(
            fixed / contribution
        )
    }


# ============================================================
# AGENT TOOL REGISTRY
# ============================================================

@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    function: Callable[..., Any]


TOOL_REGISTRY: dict[str, ToolDefinition] = {
    "safe_calculate": ToolDefinition(
        "safe_calculate",
        "Evaluate a restricted arithmetic expression.",
        safe_calculate
    ),
    "calculate_statistics": ToolDefinition(
        "calculate_statistics",
        "Calculate descriptive statistics.",
        calculate_statistics
    ),
    "calculate_percentile": ToolDefinition(
        "calculate_percentile",
        "Calculate a numerical percentile.",
        calculate_percentile
    ),
    "calculate_correlation": ToolDefinition(
        "calculate_correlation",
        "Calculate Pearson correlation.",
        calculate_correlation
    ),
    "calculate_sales_revenue": ToolDefinition(
        "calculate_sales_revenue",
        "Calculate sales revenue.",
        calculate_sales_revenue
    ),
    "calculate_growth_rate": ToolDefinition(
        "calculate_growth_rate",
        "Calculate percentage growth.",
        calculate_growth_rate
    ),
    "calculate_sales_kpis": ToolDefinition(
        "calculate_sales_kpis",
        "Calculate retail sales KPIs.",
        calculate_sales_kpis
    ),
    "moving_average": ToolDefinition(
        "moving_average",
        "Calculate rolling moving averages.",
        moving_average
    ),
    "exponential_smoothing": ToolDefinition(
        "exponential_smoothing",
        "Forecast with exponential smoothing.",
        exponential_smoothing
    ),
    "calculate_forecast_metrics": ToolDefinition(
        "calculate_forecast_metrics",
        "Evaluate demand forecasts.",
        calculate_forecast_metrics
    ),
    "detect_demand_spike": ToolDefinition(
        "detect_demand_spike",
        "Detect unusual demand increases.",
        detect_demand_spike
    ),
    "calculate_inventory_turnover": ToolDefinition(
        "calculate_inventory_turnover",
        "Calculate inventory turnover.",
        calculate_inventory_turnover
    ),
    "calculate_stock_coverage": ToolDefinition(
        "calculate_stock_coverage",
        "Calculate days of inventory cover.",
        calculate_stock_coverage
    ),
    "calculate_reorder_point": ToolDefinition(
        "calculate_reorder_point",
        "Calculate inventory reorder point.",
        calculate_reorder_point
    ),
    "calculate_fill_rate": ToolDefinition(
        "calculate_fill_rate",
        "Calculate order fulfillment rate.",
        calculate_fill_rate
    ),
    "calculate_profit_margin": ToolDefinition(
        "calculate_profit_margin",
        "Calculate profit and margin.",
        calculate_profit_margin
    ),
    "calculate_roi": ToolDefinition(
        "calculate_roi",
        "Calculate return on investment.",
        calculate_roi
    ),
    "calculate_break_even_units": ToolDefinition(
        "calculate_break_even_units",
        "Calculate break-even sales volume.",
        calculate_break_even_units
    ),
}


def list_available_tools() -> list[dict[str, str]]:
    """List tools available to AI agents."""

    return [
        {
            "name": tool.name,
            "description": tool.description
        }
        for tool in TOOL_REGISTRY.values()
    ]


def execute_tool(
    tool_name: str,
    arguments: dict[str, Any]
) -> dict[str, Any]:
    """
    Execute an allowlisted analytical tool.

    Example:
        execute_tool(
            "calculate_profit_margin",
            {"revenue": 10000, "cost": 7000}
        )
    """

    if tool_name not in TOOL_REGISTRY:
        return {
            "success": False,
            "tool": tool_name,
            "error": "Unknown or unauthorized tool."
        }

    if not isinstance(arguments, dict):
        return {
            "success": False,
            "tool": tool_name,
            "error": "Arguments must be a dictionary."
        }

    tool = TOOL_REGISTRY[tool_name]

    try:
        result = tool.function(**arguments)

        return {
            "success": True,
            "tool": tool_name,
            "result": result,
            "executed_at": datetime.now(
                timezone.utc
            ).isoformat()
        }

    except (
        ToolError,
        TypeError,
        ValueError,
        OverflowError,
        ZeroDivisionError,
        statistics.StatisticsError
    ) as exc:
        return {
            "success": False,
            "tool": tool_name,
            "error": str(exc)
        }


# ============================================================
# DEMONSTRATION
# ============================================================

if __name__ == "__main__":

    examples = [
        (
            "safe_calculate",
            {"expression": "(1200 * 0.18) + 500"}
        ),
        (
            "calculate_statistics",
            {"values": [100, 120, 140, 160, 180]}
        ),
        (
            "calculate_sales_revenue",
            {
                "quantities": [10, 20, 15],
                "prices": [100, 250, 180]
            }
        ),
        (
            "moving_average",
            {
                "values": [100, 120, 110, 150, 170],
                "window": 3
            }
        ),
        (
            "calculate_reorder_point",
            {
                "average_daily_demand": 25,
                "lead_time_days": 5,
                "safety_stock": 40
            }
        ),
        (
            "calculate_profit_margin",
            {
                "revenue": 100000,
                "cost": 72000
            }
        ),
        (
            "detect_demand_spike",
            {
                "historical_demand": [
                    100, 105, 98, 110, 102
                ],
                "current_demand": 180
            }
        ),
    ]

    for tool_name, arguments in examples:
        print(
            execute_tool(tool_name, arguments)
        )
