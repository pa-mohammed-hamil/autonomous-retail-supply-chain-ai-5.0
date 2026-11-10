"""Planned module: price features. Implementation pending."""

"""
ai/features/price_features.py

Autonomous Retail Supply Chain AI 5.0

Pricing Feature Engineering

Features:
- Retail vs competitor price gap
- Price competitiveness
- Discount indicators
- Price changes
- Historical price lag
- Rolling average price
- Historical demand statistics
- Promotion history
- Revenue per unit
- Price elasticity proxy
- Multi-product time-series grouping
- CSV and JSON export

Python 3.10+
Standard library only.

Current prices and promotions are
assumed to be known at prediction time.

Historical demand features exclude
the current observation.
"""

from __future__ import annotations

import csv
import json
import math

from collections import defaultdict, deque
from datetime import date
from pathlib import Path
from statistics import mean
from typing import Sequence


class PriceFeatureEngineer:

    def __init__(
        self,
        windows: tuple[int, ...] = (7, 14, 30),
    ):
        if (
            not windows
            or any(
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 1
                for value in windows
            )
        ):
            raise ValueError(
                "windows must contain positive integers"
            )

        self.windows = tuple(
            sorted(set(windows))
        )

    @staticmethod
    def _number(value, field):
        if isinstance(value, bool):
            raise ValueError(
                f"Invalid {field}"
            )

        try:
            result = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Invalid {field}"
            ) from exc

        if not math.isfinite(result):
            raise ValueError(
                f"{field} must be finite"
            )

        return result

    @staticmethod
    def _boolean(value):
        if isinstance(value, bool):
            return value

        if value in (0, 1):
            return bool(value)

        if isinstance(value, str):
            normalized = value.strip().lower()

            if normalized in {
                "true", "1", "yes"
            }:
                return True

            if normalized in {
                "false", "0", "no"
            }:
                return False

        raise ValueError(
            f"Invalid boolean value: {value}"
        )

    @staticmethod
    def _average(values):
        return (
            round(mean(values), 4)
            if values else None
        )

    def transform(
        self,
        records: Sequence[dict],
        product_column: str = "product_id",
        demand_column: str = "actual_demand",
    ) -> list[dict]:
        if not records:
            raise ValueError(
                "Pricing records cannot be empty"
            )

        groups = defaultdict(list)

        for row in records:
            groups[row[product_column]].append(
                dict(row)
            )

        output = []

        max_window = max(self.windows)

        for product_id, rows in groups.items():
            rows.sort(
                key=lambda row: date.fromisoformat(
                    str(row["date"])
                )
            )

            seen_dates = set()

            price_history = deque(
                maxlen=max_window
            )

            demand_history = deque(
                maxlen=max_window
            )

            promotion_history = deque(
                maxlen=max_window
            )

            previous_price = None
            previous_demand = None

            for row in rows:
                current_date = date.fromisoformat(
                    str(row["date"])
                )

                if current_date in seen_dates:
                    raise ValueError(
                        "Duplicate product-date: "
                        f"{product_id} {current_date}"
                    )

                seen_dates.add(current_date)

                price = self._number(
                    row["retail_price"],
                    "retail_price",
                )

                competitor_price = self._number(
                    row["competitor_price"],
                    "competitor_price",
                )

                demand = self._number(
                    row[demand_column],
                    demand_column,
                )

                discount = self._number(
                    row["discount_percent"],
                    "discount_percent",
                )

                promotion = self._boolean(
                    row["promotion_active"]
                )

                if (
                    price <= 0
                    or competitor_price <= 0
                    or demand < 0
                    or not 0 <= discount <= 100
                ):
                    raise ValueError(
                        "Invalid pricing or demand"
                    )

                price_gap = (
                    price - competitor_price
                )

                price_gap_percent = (
                    price_gap
                    / competitor_price
                    * 100
                )

                features = {
                    **row,
                    "price_gap": round(
                        price_gap, 4
                    ),
                    "price_gap_percent": round(
                        price_gap_percent, 4
                    ),
                    "price_to_competitor_ratio": round(
                        price / competitor_price,
                        6,
                    ),
                    "cheaper_than_competitor": int(
                        price < competitor_price
                    ),
                    "more_expensive_than_competitor": int(
                        price > competitor_price
                    ),
                    "promotion_indicator": int(
                        promotion
                    ),
                    "discount_fraction": round(
                        discount / 100,
                        4,
                    ),
                    "previous_price": (
                        previous_price
                    ),
                    "previous_demand": (
                        previous_demand
                    ),
                    "price_change_percent": (
                        round(
                            (
                                price - previous_price
                            )
                            / previous_price
                            * 100,
                            4,
                        )
                        if previous_price is not None
                        and previous_price > 0
                        else None
                    ),
                }

                prices = list(
                    price_history
                )

                demands = list(
                    demand_history
                )

                promotions = list(
                    promotion_history
                )

                for window in self.windows:
                    historical_prices = (
                        prices[-window:]
                        if len(prices) >= window
                        else []
                    )

                    historical_demands = (
                        demands[-window:]
                        if len(demands) >= window
                        else []
                    )

                    historical_promotions = (
                        promotions[-window:]
                        if len(promotions) >= window
                        else []
                    )

                    features[
                        f"price_rolling_mean_{window}"
                    ] = self._average(
                        historical_prices
                    )

                    features[
                        f"demand_rolling_mean_{window}"
                    ] = self._average(
                        historical_demands
                    )

                    features[
                        f"promotion_rate_{window}"
                    ] = self._average(
                        historical_promotions
                    )

                # A simple observational
                # elasticity proxy based on
                # consecutive observations.
                # It is not causal elasticity.
                elasticity_proxy = None

                if (
                    previous_price is not None
                    and previous_price > 0
                    and previous_demand is not None
                    and previous_demand > 0
                    and demand > 0
                    and price != previous_price
                ):
                    price_change = (
                        price - previous_price
                    ) / previous_price

                    demand_change = (
                        demand - previous_demand
                    ) / previous_demand

                    elasticity_proxy = (
                        demand_change
                        / price_change
                    )

                    if not math.isfinite(
                        elasticity_proxy
                    ):
                        elasticity_proxy = None

                # This proxy uses current demand.
                # Exclude it from same-day
                # demand forecasting features.
                features[
                    "observed_elasticity_proxy"
                ] = (
                    round(
                        elasticity_proxy, 6
                    )
                    if elasticity_proxy is not None
                    else None
                )

                output.append(features)

                price_history.append(price)
                demand_history.append(demand)
                promotion_history.append(
                    int(promotion)
                )

                previous_price = price
                previous_demand = demand

        output.sort(
            key=lambda row: (
                str(row["date"]),
                str(row[product_column]),
            )
        )

        return output

    def transform_csv(
        self,
        input_path: str,
        output_path: str,
    ) -> list[dict]:
        with open(
            input_path,
            newline="",
            encoding="utf-8-sig",
        ) as file:
            records = list(
                csv.DictReader(file)
            )

        features = self.transform(records)

        self.save_csv(
            features,
            output_path,
        )

        return features

    @staticmethod
    def save_csv(records, path):
        if not records:
            raise ValueError(
                "Cannot export empty features"
            )

        output = Path(path)
        output.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        fields = list(dict.fromkeys(
            key
            for row in records
            for key in row
        ))

        with output.open(
            "w",
            newline="",
            encoding="utf-8",
        ) as file:
            writer = csv.DictWriter(
                file,
                fieldnames=fields,
            )

            writer.writeheader()
            writer.writerows(records)

    @staticmethod
    def save_json(records, path):
        output = Path(path)
        output.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        output.write_text(
            json.dumps(
                records,
                indent=2,
                ensure_ascii=False,
                allow_nan=False,
            ),
            encoding="utf-8",
        )


if __name__ == "__main__":
    engineer = PriceFeatureEngineer(
        windows=(7, 14, 30)
    )

    features = engineer.transform_csv(
        "data/synthetic/market_trend_dataset.csv",
        "data/features/price_features.csv",
    )

    engineer.save_json(
        features,
        "data/features/price_features.json",
    )

    print(
        f"Generated {len(features)} "
        "pricing feature records"
    )
