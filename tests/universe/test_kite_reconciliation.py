"""Reconciliation tests for adjusted prices."""

from datetime import date
from typing import Any

import pandas as pd
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
    if not df_prices.is_empty() and "year" not in df_prices.columns:
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


def test_kite_adjusted_close_reconciliation(tmp_lakehouse: Lakehouse) -> None:
    """Reconcile our adjustment logic against typical broker (Kite) logic.
    
    Checks that total return index (adj_tot_close) matches within 5bps.
    Checks that technical adjusted close matches within 5bps.
    """
    # E.g. a stock has a 1:2 split and a Rs 5 dividend on the same day.
    # Pre-event price = 100. Split makes it 50. Dividend makes it 45.
    
    _write_mock_data(
        tmp_lakehouse,
        prices=[
            {"isin": "INE123", "date": "2024-05-13", "open": 100.0, "high": 105.0, "low": 95.0, "close": 100.0, "volume": 1000},
            {"isin": "INE123", "date": "2024-05-14", "open": 45.0, "high": 48.0, "low": 42.0, "close": 45.0, "volume": 2000},
        ],
        actions=[
            {
                "isin": "INE123", "ex_date": "2024-05-14", "action_type": "split",
                "ratio_from": 10.0, "ratio_to": 5.0, "amount_per_share": None,
            },
            {
                "isin": "INE123", "ex_date": "2024-05-14", "action_type": "dividend",
                "ratio_from": None, "ratio_to": None, "amount_per_share": 5.0,
            }
        ],
    )
    
    df = adjusted_prices(
        tmp_lakehouse,
        ["INE123"],
        date(2024, 5, 13),
        date(2024, 5, 14),
    )
    
    row_13 = df[df["date"] == "2024-05-13"].iloc[0]
    
    # Technical adj close (split only) should be 100 * (5/10) = 50.0
    assert abs(row_13["adj_close"] - 50.0) / 50.0 <= 0.0005  # 5 bps
    
    # Total return adj close (split + dividend)
    # The dividend factor = (prev_close - div) / prev_close = (100 - 5) / 100 = 0.95
    # Total multiplier = 0.5 * 0.95 = 0.475
    # adj_tot_close = 100 * 0.475 = 47.5
    assert abs(row_13["adj_tot_close"] - 47.5) / 47.5 <= 0.0005  # 5 bps
    
    # Adj High/Low test (technical only)
    assert abs(row_13["adj_high"] - 52.5) / 52.5 <= 0.0005
    assert abs(row_13["adj_low"] - 47.5) / 47.5 <= 0.0005
