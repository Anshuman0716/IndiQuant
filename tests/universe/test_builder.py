from datetime import date
from typing import Any

import polars as pl

from indiquant.store.lakehouse import Lakehouse
from indiquant.universe.builder import build_universe


def _write_mock_membership(lakehouse: Lakehouse, rows: list[dict[str, Any]]) -> None:
    df = pl.DataFrame(rows)
    if "year" not in df.columns:
        df = df.with_columns(pl.lit(2016).alias("year"))
    lakehouse.write_silver("index_membership", df, year=2016)


def _write_mock_equity(lakehouse: Lakehouse, rows: list[dict[str, Any]]) -> None:
    df = pl.DataFrame(rows)
    if "year" not in df.columns:
        df = df.with_columns(pl.lit(2016).alias("year"))
    lakehouse.write_silver("equity_daily", df, year=2016)


def test_universe_is_survivorship_free(tmp_lakehouse: Lakehouse) -> None:
    """Acceptance test for survivorship-free universe construction.

    Target: 2016-06-30 for NIFTY 500.
    Must return at least 3 delisted names.
    """
    asof = date(2016, 6, 30)

    # Mock index membership: 5 active names on 2016-06-30
    _write_mock_membership(
        tmp_lakehouse,
        [
            {
                "index_name": "NIFTY 500",
                "isin": "INE_LIVE1",
                "valid_from": "2015-01-01",
                "valid_to": None,
            },
            {
                "index_name": "NIFTY 500",
                "isin": "INE_LIVE2",
                "valid_from": "2015-01-01",
                "valid_to": None,
            },
            {
                "index_name": "NIFTY 500",
                "isin": "INE_DEAD1",
                "valid_from": "2010-01-01",
                "valid_to": "2018-01-01",
            },
            {
                "index_name": "NIFTY 500",
                "isin": "INE_DEAD2",
                "valid_from": "2012-01-01",
                "valid_to": "2017-01-01",
            },
            {
                "index_name": "NIFTY 500",
                "isin": "INE_DEAD3",
                "valid_from": "2014-01-01",
                "valid_to": "2019-01-01",
            },
        ],
    )

    # Mock equity daily
    # To pass liquidity, they need at least 60 rows, but we can lower the gate in the test
    # We will generate a few rows for each, ensuring the dead ones stop early.
    prices = []

    # Generate 65 days of data before 2016-06-30 for all so they pass listing days.
    import pandas as pd

    dates = pd.date_range("2016-04-01", "2016-06-30")
    for d in dates:
        for isin in ["INE_LIVE1", "INE_LIVE2", "INE_DEAD1", "INE_DEAD2", "INE_DEAD3"]:
            prices.append(
                {
                    "isin": isin,
                    "date": d.strftime("%Y-%m-%d"),
                    "close": 100.0,
                    "volume": 100000,
                }
            )

    # Add a recent date for live ones so max_market_date is 'today'
    prices.append({"isin": "INE_LIVE1", "date": "2024-01-01", "close": 150.0, "volume": 100000})
    prices.append({"isin": "INE_LIVE2", "date": "2024-01-01", "close": 150.0, "volume": 100000})

    # Dead ones delist at various dates
    prices.append({"isin": "INE_DEAD1", "date": "2018-01-01", "close": 50.0, "volume": 100000})
    prices.append({"isin": "INE_DEAD2", "date": "2017-01-01", "close": 20.0, "volume": 100000})
    prices.append({"isin": "INE_DEAD3", "date": "2019-01-01", "close": 10.0, "volume": 100000})

    _write_mock_equity(tmp_lakehouse, prices)

    # Mock nse_delisting records
    delistings = [
        {
            "isin": "INE_DEAD1",
            "symbol": "DEAD1",
            "delisting_date": "2018-01-01",
            "reason": "compulsory",
        },
        {
            "isin": "INE_DEAD2",
            "symbol": "DEAD2",
            "delisting_date": "2017-01-01",
            "reason": "unknown",
        },
        {
            "isin": "INE_DEAD3",
            "symbol": "DEAD3",
            "delisting_date": "2019-01-01",
            "reason": "merger_acquisition",
        },
    ]
    df_delist = pl.DataFrame(delistings)
    df_delist = df_delist.with_columns(pl.lit(2016).alias("year"))
    tmp_lakehouse.write_silver("delistings", df_delist, year=2016)

    # Build universe
    snap = build_universe(
        lakehouse=tmp_lakehouse,
        index_name="NIFTY 500",
        asof=asof,
        min_price=10.0,
        min_turnover=10000.0,
    )

    # Ensure all 5 are in the snapshot (survivorship-free)
    assert len(snap.members) == 5

    # Count delisted
    delisted = [m for m in snap.members if m.delisting_date is not None]
    assert len(delisted) == 3, f"Expected 3 delisted names, found {len(delisted)}"

    # Ensure they got haircuts (except M&A)
    for d in delisted:
        if d.delisting_reason == "merger_acquisition":
            assert d.terminal_haircut == 0.0
        else:
            assert d.terminal_haircut == -0.30

    print(f"Test passed! Found {len(delisted)} delisted names: {[d.isin for d in delisted]}")
