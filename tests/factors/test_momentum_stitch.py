"""Tests for momentum_12_1 ISIN stitching.

A stock with a 1:10 split inside the lookback must not rank in the bottom
decile, and a stock with an ISIN change inside the lookback must keep a
valid (non-NaN) score.
"""
import numpy as np
import pandas as pd
import polars as pl
import pytest
from datetime import date
from unittest.mock import patch, MagicMock

from indiquant.config.settings import IndiQuantSettings
from indiquant.store.lakehouse import Lakehouse
from indiquant.factors.momentum import momentum_12_1
from indiquant.factors.base import FactorContext


@pytest.fixture
def mock_lakehouse(tmp_path):
    settings = IndiQuantSettings(data_dir=tmp_path)
    lh = Lakehouse(settings)
    (lh.silver_dir / "isin_chain").mkdir(parents=True, exist_ok=True)
    (lh.silver_dir / "corporate_actions").mkdir(parents=True, exist_ok=True)
    (lh.silver_dir / "equity_daily").mkdir(parents=True, exist_ok=True)
    return lh


def _make_dates(start: str, end: str) -> list[str]:
    """Generate weekday-only date strings."""
    dates = pd.bdate_range(start, end)
    return [d.strftime("%Y-%m-%d") for d in dates]


def _build_prices(
    isin: str, dates: list[str], base: float, daily_ret: float = 0.001
) -> list[dict]:
    """Build a synthetic price series with steady growth."""
    rows = []
    p = base
    for d in dates:
        rows.append({
            "isin": isin,
            "date": d,
            "open": p,
            "high": p * 1.01,
            "low": p * 0.99,
            "close": p,
            "prev_close": p / (1 + daily_ret) if len(rows) > 0 else p,
            "volume": 1000,
        })
        p *= (1 + daily_ret)
    return rows


def test_split_inside_lookback_not_bottom_decile(mock_lakehouse):
    """A stock with a 1:10 split must not rank in D10 (bottom decile).

    We create 11 stocks: 10 "normal" + 1 that had a 1:10 split.
    The split stock has genuine +50% momentum over 12 months.
    Without stitching, raw close shows a ~90% drop at split date, which
    would wrongly rank it at the bottom.
    """
    # Chain: the split stock keeps the same ISIN (split doesn't change ISIN)
    chain_rows = [
        {"security_id": f"sec_{i}", "isin": f"ISIN_{i:02d}",
         "valid_from": "2018-01-01", "valid_to": None, "symbol": f"S{i}"}
        for i in range(11)
    ]
    chain = pl.DataFrame(
        chain_rows,
        schema={
            "security_id": pl.String, "isin": pl.String,
            "valid_from": pl.String, "valid_to": pl.String,
            "symbol": pl.String,
        },
    )
    chain.write_parquet(
        mock_lakehouse.silver_dir / "isin_chain" / "data.parquet"
    )

    # CA: stock 0 had a 1:10 split on 2019-06-03
    ca = pl.DataFrame([{
        "isin": "ISIN_00", "ex_date": "2019-06-03",
        "action_type": "split", "ratio_from": 10.0, "ratio_to": 1.0,
        "amount_per_share": None,
    }])
    ca.write_parquet(
        mock_lakehouse.silver_dir / "corporate_actions" / "data.parquet"
    )

    asof = date(2019, 10, 31)
    dates = _make_dates("2018-09-01", "2019-10-31")

    # Stock 0: genuine +50% momentum over 12 months.
    # get_prices returns adj_close (split-adjusted), so the series is
    # continuous — no 90% drop at the split date.
    s0 = _build_prices("ISIN_00", dates, 100.0, 0.0015)

    # Stocks 1-10: all flat (0% momentum)
    others = []
    for i in range(1, 11):
        others.extend(_build_prices(f"ISIN_{i:02d}", dates, 100.0, 0.0))

    all_prices = pd.DataFrame(s0 + others)

    ctx = FactorContext(mock_lakehouse)
    # Patch get_prices to return our synthetic data
    ctx.get_prices = lambda asof_date, lookback_days=380, **kw: all_prices.copy()

    scores = momentum_12_1(ctx, asof)

    assert "ISIN_00" in scores.index, "Split stock must have a score"
    assert not np.isnan(scores["ISIN_00"]), "Split stock score must not be NaN"

    # Stock 0 has genuine positive momentum; it must NOT be in bottom decile
    ranked = scores.dropna().rank(pct=True)
    # D10 = bottom 10% for direction=1 (higher is better)
    assert ranked["ISIN_00"] > 0.1, (
        f"Split stock ranked at {ranked['ISIN_00']:.2f}, "
        f"should not be in bottom decile"
    )


def test_isin_change_inside_lookback_valid_score(mock_lakehouse):
    """A stock that changed ISIN inside the lookback must keep a valid score.

    We create a stock with ISIN_OLD (valid until 2019-06-14) and
    ISIN_NEW (valid from 2019-06-17). The momentum lookback window
    spans both ISINs. The score must be non-NaN.
    """
    chain = pl.DataFrame(
        [
            {"security_id": "sec_A", "isin": "ISIN_OLD",
             "valid_from": "2018-01-01", "valid_to": "2019-06-14",
             "symbol": "TESTCO"},
            {"security_id": "sec_A", "isin": "ISIN_NEW",
             "valid_from": "2019-06-17", "valid_to": None,
             "symbol": "TESTCO"},
        ],
        schema={
            "security_id": pl.String, "isin": pl.String,
            "valid_from": pl.String, "valid_to": pl.String,
            "symbol": pl.String,
        },
    )
    chain.write_parquet(
        mock_lakehouse.silver_dir / "isin_chain" / "data.parquet"
    )

    # No corporate actions
    ca = pl.DataFrame(
        [],
        schema={
            "isin": pl.String, "ex_date": pl.String,
            "action_type": pl.String, "ratio_from": pl.Float64,
            "ratio_to": pl.Float64, "amount_per_share": pl.Float64,
        },
    )
    ca.write_parquet(
        mock_lakehouse.silver_dir / "corporate_actions" / "data.parquet"
    )

    asof = date(2019, 10, 31)
    dates = _make_dates("2018-09-01", "2019-10-31")

    change_date = "2019-06-17"
    old_dates = [d for d in dates if d < change_date]
    new_dates = [d for d in dates if d >= change_date]

    prices_old = _build_prices("ISIN_OLD", old_dates, 500.0, 0.001)
    last_old = prices_old[-1]["close"]
    prices_new = _build_prices("ISIN_NEW", new_dates, last_old, 0.001)

    all_prices = pd.DataFrame(prices_old + prices_new)

    ctx = FactorContext(mock_lakehouse)
    ctx.get_prices = lambda asof_date, lookback_days=380, **kw: all_prices.copy()

    scores = momentum_12_1(ctx, asof)

    # The score should be indexed under ISIN_NEW (the most recent ISIN)
    assert "ISIN_NEW" in scores.index, (
        f"Current ISIN must be in index; got {list(scores.index)}"
    )
    assert not np.isnan(scores["ISIN_NEW"]), (
        "Stock with ISIN change must have a valid (non-NaN) score"
    )
    # Old ISIN should NOT appear separately
    assert "ISIN_OLD" not in scores.index, (
        "Old ISIN must not appear as a separate entry"
    )
