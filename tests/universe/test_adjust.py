from datetime import date
from typing import Any

import polars as pl
import pytest

from indiquant.store.lakehouse import Lakehouse
from indiquant.universe.adjust import adjusted_prices


def _write_mock_data(
    lakehouse: Lakehouse,
    prices: list[dict[str, Any]],
    actions: list[dict[str, Any]],
) -> None:
    df_prices = pl.DataFrame(prices)
    if "year" not in df_prices.columns:
        df_prices = df_prices.with_columns(pl.lit(2024).alias("year"))
    lakehouse.write_silver("equity_daily", df_prices, year=2024)

    if not actions:
        df_ca = pl.DataFrame(
            schema={
                "isin": pl.Utf8,
                "ex_date": pl.Utf8,
                "action_type": pl.Utf8,
                "ratio_from": pl.Float64,
                "ratio_to": pl.Float64,
                "amount_per_share": pl.Float64,
                "year": pl.Int32,
            }
        )
    else:
        df_ca = pl.DataFrame(actions)
        if "year" not in df_ca.columns:
            df_ca = df_ca.with_columns(pl.lit(2024).alias("year"))
    lakehouse.write_silver("corporate_actions", df_ca, year=2024)


def test_split_adjustment(tmp_lakehouse: Lakehouse) -> None:
    """Test a 1:5 stock split.

    Example: Split from face value 10 to 2 (ratio_from=10, ratio_to=2).
    A pre-split price of 100 should become 20.
    A pre-split volume of 1000 should become 5000.
    """
    _write_mock_data(
        tmp_lakehouse,
        prices=[
            {"isin": "INE123", "date": "2024-05-13", "open": 100.0, "high": 105.0, "low": 95.0, "close": 100.0, "volume": 1000},
            {"isin": "INE123", "date": "2024-05-14", "open": 102.0, "high": 104.0, "low": 98.0, "close": 100.0, "volume": 1000},
            # Ex-date: price drops by 5x naturally, volume 5x naturally
            {"isin": "INE123", "date": "2024-05-15", "open": 20.0, "high": 21.0, "low": 19.0, "close": 20.0, "volume": 5000},
        ],
        actions=[
            {
                "isin": "INE123",
                "ex_date": "2024-05-15",
                "action_type": "split",
                "ratio_from": 10.0,
                "ratio_to": 2.0,
                "amount_per_share": None,
            }
        ],
    )

    df = adjusted_prices(
        tmp_lakehouse,
        ["INE123"],
        date(2024, 5, 13),
        date(2024, 5, 15),
        adjust_for=["split"],
    )
    
    assert len(df) == 3
    # Pre-split date (13th)
    row_13 = df.filter(pl.col("date") == "2024-05-13").row(0, named=True)
    assert row_13["adj_close"] == 20.0
    assert row_13["adj_volume"] == 5000
    
    # Pre-split date (14th)
    row_14 = df.filter(pl.col("date") == "2024-05-14").row(0, named=True)
    assert row_14["adj_close"] == 20.0
    assert row_14["adj_volume"] == 5000

    # Post-split date (15th) -> factor is 1.0
    row_15 = df.filter(pl.col("date") == "2024-05-15").row(0, named=True)
    assert row_15["adj_close"] == 20.0
    assert row_15["adj_volume"] == 5000


def test_bonus_adjustment(tmp_lakehouse: Lakehouse) -> None:
    """Test a 3:2 bonus issue.

    Example: 3 bonus shares for every 2 held.
    Total shares = 5 for every 2 (factor = 5/2 = 2.5).
    Pre-bonus price of 100 should become 40.
    Pre-bonus volume of 1000 should become 2500.
    """
    _write_mock_data(
        tmp_lakehouse,
        prices=[
            {"isin": "INE456", "date": "2024-05-14", "open": 100.0, "high": 105.0, "low": 95.0, "close": 100.0, "volume": 1000},
            {"isin": "INE456", "date": "2024-05-15", "open": 40.0, "high": 42.0, "low": 38.0, "close": 40.0, "volume": 2500},
        ],
        actions=[
            {
                "isin": "INE456",
                "ex_date": "2024-05-15",
                "action_type": "bonus",
                "ratio_from": 3.0,
                "ratio_to": 2.0,
                "amount_per_share": None,
            }
        ],
    )

    df = adjusted_prices(
        tmp_lakehouse,
        ["INE456"],
        date(2024, 5, 14),
        date(2024, 5, 15),
        adjust_for=["bonus"],
    )
    
    assert len(df) == 2
    row_14 = df.filter(pl.col("date") == "2024-05-14").row(0, named=True)
    assert row_14["adj_close"] == 40.0
    assert row_14["adj_volume"] == 2500
