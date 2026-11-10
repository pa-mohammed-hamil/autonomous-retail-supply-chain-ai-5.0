"""Planned module: promotion features. Implementation pending."""

"""
ai/features/promotion_features.py

Autonomous Retail Supply Chain AI 5.0

Promotion Feature Engineering

Features:
- Promotion and discount indicators
- Discount intensity
- Historical promotion frequency
- Days since previous promotion
- Consecutive promotion streak
- Previous promotional demand
- Previous non-promotional demand
- Historical promotion uplift proxy
- Rolling promotion and discount statistics
- Time-aware feature generation
- CSV and JSON export

Standard library only.
Python 3.10+

Assumptions:
- Current promotion and discount are known
  before the day's sales occur.
- Current demand is used only to update
  history after generating that day's features.
- Historical uplift is observational, not
  a causal estimate of campaign impact.
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


class PromotionFeatureEngineer:

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
                f"{field} must be numeric"
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

        if isinstance(value, (int, float)):
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
                "Promotion dataset cannot be empty"
            )

        groups = defaultdict(list)

        for record in records:
            groups[
                str(record[product_column])
            ].append(dict(record))

        output = []
        max_window = max(self.windows)

        for product_id, rows in groups.items():
            rows.sort(
                key=lambda row: date.fromisoformat(
                    str(row["date"])
                )
            )

            seen_dates = set()

            promotion_history = deque(
                maxlen=max_window
            )

            discount_history = deque(
                maxlen=max_window
            )

            promoted_demands = []
            regular_demands = []

            last_promotion_date = None
            previous_date = None
            promotion_streak = 0

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

                promotion = self._boolean(
                    row["promotion_active"]
                )

                discount = self._number(
                    row["discount_percent"],
                    "discount_percent",
                )

                demand = self._number(
                    row[demand_column],
                    demand_column,
                )

                if (
                    discount < 0
                    or discount > 100
                    or demand < 0
                ):
                    raise ValueError(
                        "Invalid discount or demand"
                    )

                previous_promoted_average = (
                    mean(promoted_demands)
                    if promoted_demands
                    else None
                )

                previous_regular_average = (
                    mean(regular_demands)
                    if regular_demands
                    else None
                )

                uplift_proxy = None

                if (
                    previous_promoted_average
                    is not None
                    and previous_regular_average
                    is not None
                    and previous_regular_average > 0
                ):
                    uplift_proxy = (
                        previous_promoted_average
                        / previous_regular_average
                        - 1
                    ) * 100

                days_since_promotion = (
                    (
                        current_date
                        - last_promotion_date
                    ).days
                    if last_promotion_date
                    else None
                )

                is_consecutive_day = (
                    previous_date is not None
                    and (
                        current_date - previous_date
                    ).days == 1
                )

                if promotion:
                    current_streak = (
                        promotion_streak + 1
                        if is_consecutive_day
                        else 1
                    )
                else:
                    current_streak = 0

                features = {
                    **row,
                    "promotion_indicator": int(
                        promotion
                    ),
                    "discount_fraction": round(
                        discount / 100,
                        4,
                    ),
                    "days_since_previous_promotion": (
                        days_since_promotion
                    ),
                    "current_promotion_streak": (
                        current_streak
                    ),
                    "historical_promoted_demand_mean": (
                        self._average(
                            promoted_demands
                        )
                    ),
                    "historical_regular_demand_mean": (
                        self._average(
                            regular_demands
                        )
                    ),
                    "historical_promotion_uplift_percent": (
                        round(uplift_proxy, 4)
                        if uplift_proxy is not None
                        else None
                    ),
                }

                past_promotions = list(
                    promotion_history
                )

                past_discounts = list(
                    discount_history
                )

                for window in self.windows:
                    promotions = (
                        past_promotions[-window:]
                        if len(past_promotions) >= window
                        else []
                    )

                    discounts = (
                        past_discounts[-window:]
                        if len(past_discounts) >= window
                        else []
                    )

                    features[
                        f"promotion_rate_{window}"
                    ] = self._average(
                        promotions
                    )

                    features[
                        f"average_discount_{window}"
                    ] = self._average(
                        discounts
                    )

                output.append(features)

                promotion_history.append(
                    int(promotion)
                )

                discount_history.append(
                    discount
                )

                if promotion:
                    promoted_demands.append(demand)
                    last_promotion_date = current_date
                else:
                    regular_demands.append(demand)

                promotion_streak = current_streak
                previous_date = current_date

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
        product_column: str = "product_id",
        demand_column: str = "actual_demand",
    ) -> list[dict]:
        with open(
            input_path,
            newline="",
            encoding="utf-8-sig",
        ) as file:
            records = list(
                csv.DictReader(file)
            )

        features = self.transform(
            records,
            product_column=product_column,
            demand_column=demand_column,
        )

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
    engineer = PromotionFeatureEngineer(
        windows=(7, 14, 30)
    )

    features = engineer.transform_csv(
        "data/synthetic/market_trend_dataset.csv",
        "data/features/promotion_features.csv",
    )

    engineer.save_json(
        features,
        "data/features/promotion_features.json",
    )

    print(
        f"Generated {len(features)} "
        "promotion feature records"
    )
