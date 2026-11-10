"""Planned module: supplier features. Implementation pending."""

"""
ai/features/sales_features.py

Autonomous Retail Supply Chain AI 5.0

Sales Feature Engineering

Features:
- Historical sales lags
- Rolling sales averages
- Rolling sales volatility
- Historical revenue averages
- Historical return rates
- Historical gross margins
- Historical stockout frequency
- Sales growth indicators
- Historical demand averages
- Multi-store and multi-SKU grouping
- CSV and JSON export

Standard library only.
Python 3.10+

Historical features use previous rows
only, not the current day's outcomes.
"""

from __future__ import annotations

import csv
import json
import math

from collections import defaultdict, deque
from datetime import date
from pathlib import Path
from statistics import mean, pstdev
from typing import Sequence


class SalesFeatureEngineer:

    def __init__(
        self,
        lags: tuple[int, ...] = (1, 7, 14),
        windows: tuple[int, ...] = (7, 14, 30),
    ):
        values = (*lags, *windows)

        if (
            not lags
            or not windows
            or any(
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 1
                for value in values
            )
        ):
            raise ValueError(
                "Lags and windows must be "
                "positive integers"
            )

        self.lags = tuple(
            sorted(set(lags))
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
    def _mean(values):
        return (
            round(mean(values), 4)
            if values else None
        )

    def transform(
        self,
        records: Sequence[dict],
    ) -> list[dict]:
        if not records:
            raise ValueError(
                "Sales dataset cannot be empty"
            )

        groups = defaultdict(list)

        for record in records:
            key = (
                str(record["store_id"]),
                str(record["sku"]),
            )

            groups[key].append(
                dict(record)
            )

        output = []

        max_history = max(
            *self.lags,
            *self.windows,
        )

        for key, rows in groups.items():
            rows.sort(
                key=lambda row: date.fromisoformat(
                    str(row["date"])
                )
            )

            seen_dates = set()

            sales_history = deque(
                maxlen=max_history
            )

            demand_history = deque(
                maxlen=max_history
            )

            revenue_history = deque(
                maxlen=max_history
            )

            return_rate_history = deque(
                maxlen=max_history
            )

            margin_history = deque(
                maxlen=max_history
            )

            stockout_history = deque(
                maxlen=max_history
            )

            for row in rows:
                current_date = date.fromisoformat(
                    str(row["date"])
                )

                if current_date in seen_dates:
                    raise ValueError(
                        "Duplicate store-SKU-date: "
                        f"{key} {current_date}"
                    )

                seen_dates.add(current_date)

                units_sold = self._number(
                    row["units_sold"],
                    "units_sold",
                )

                demand = self._number(
                    row["actual_demand"],
                    "actual_demand",
                )

                revenue = self._number(
                    row["net_revenue"],
                    "net_revenue",
                )

                returned = self._number(
                    row["returned_units"],
                    "returned_units",
                )

                gross_profit = self._number(
                    row["gross_profit"],
                    "gross_profit",
                )

                stockout = self._boolean(
                    row["stockout_occurred"]
                )

                if (
                    units_sold < 0
                    or demand < 0
                    or revenue < 0
                    or returned < 0
                    or returned > units_sold
                    or units_sold > demand
                ):
                    raise ValueError(
                        "Invalid sales quantities"
                    )

                past_sales = list(
                    sales_history
                )

                past_demand = list(
                    demand_history
                )

                past_revenue = list(
                    revenue_history
                )

                past_returns = list(
                    return_rate_history
                )

                past_margins = list(
                    margin_history
                )

                past_stockouts = list(
                    stockout_history
                )

                features = {
                    "date": row["date"],
                    "store_id": row["store_id"],
                    "sku": row["sku"],
                    "category": row.get(
                        "category"
                    ),
                    "sales_channel": row.get(
                        "sales_channel"
                    ),
                    "promotion_active": row.get(
                        "promotion_active"
                    ),
                    "discount_percent": row.get(
                        "discount_percent"
                    ),
                    "selling_price": row.get(
                        "selling_price"
                    ),
                    "history_count": len(
                        past_sales
                    ),
                }

                for lag in self.lags:
                    features[
                        f"sales_lag_{lag}"
                    ] = (
                        past_sales[-lag]
                        if len(past_sales) >= lag
                        else None
                    )

                    features[
                        f"demand_lag_{lag}"
                    ] = (
                        past_demand[-lag]
                        if len(past_demand) >= lag
                        else None
                    )

                for window in self.windows:
                    sales = (
                        past_sales[-window:]
                        if len(past_sales) >= window
                        else []
                    )

                    demands = (
                        past_demand[-window:]
                        if len(past_demand) >= window
                        else []
                    )

                    revenues = (
                        past_revenue[-window:]
                        if len(past_revenue) >= window
                        else []
                    )

                    returns = (
                        past_returns[-window:]
                        if len(past_returns) >= window
                        else []
                    )

                    margins = (
                        past_margins[-window:]
                        if len(past_margins) >= window
                        else []
                    )

                    stockouts = (
                        past_stockouts[-window:]
                        if len(past_stockouts) >= window
                        else []
                    )

                    features[
                        f"sales_rolling_mean_{window}"
                    ] = self._mean(sales)

                    features[
                        f"sales_rolling_std_{window}"
                    ] = (
                        round(
                            pstdev(sales), 4
                        )
                        if sales else None
                    )

                    features[
                        f"demand_rolling_mean_{window}"
                    ] = self._mean(demands)

                    features[
                        f"revenue_rolling_mean_{window}"
                    ] = self._mean(revenues)

                    features[
                        f"return_rate_rolling_mean_{window}"
                    ] = self._mean(returns)

                    features[
                        f"margin_rolling_mean_{window}"
                    ] = self._mean(margins)

                    features[
                        f"stockout_rate_{window}"
                    ] = self._mean(stockouts)

                if len(past_sales) >= 14:
                    recent = mean(
                        past_sales[-7:]
                    )

                    previous = mean(
                        past_sales[-14:-7]
                    )

                    growth = (
                        (recent - previous)
                        / previous * 100
                        if previous > 0
                        else None
                    )
                else:
                    growth = None

                features[
                    "historical_sales_growth_percent"
                ] = (
                    round(growth, 4)
                    if growth is not None
                    else None
                )

                output.append(features)

                return_rate = (
                    returned / units_sold
                    if units_sold > 0
                    else 0.0
                )

                margin = (
                    gross_profit / revenue
                    if revenue > 0
                    else 0.0
                )

                sales_history.append(
                    units_sold
                )

                demand_history.append(
                    demand
                )

                revenue_history.append(
                    revenue
                )

                return_rate_history.append(
                    return_rate
                )

                margin_history.append(
                    margin
                )

                stockout_history.append(
                    int(stockout)
                )

        output.sort(
            key=lambda row: (
                str(row["date"]),
                str(row["store_id"]),
                str(row["sku"]),
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
    engineer = SalesFeatureEngineer(
        lags=(1, 7, 14),
        windows=(7, 14, 30),
    )

    features = engineer.transform_csv(
        "data/synthetic/sales_dataset.csv",
        "data/features/sales_features.csv",
    )

    engineer.save_json(
        features,
        "data/features/sales_features.json",
    )

    print(
        f"Generated {len(features)} "
        "sales feature records"
    )
