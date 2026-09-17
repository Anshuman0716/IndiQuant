"""Momentum factors."""

from datetime import date
import numpy as np
import pandas as pd
import structlog

from indiquant.factors.base import FactorContext, factor

logger = structlog.get_logger(__name__)


@factor(
    id="momentum_12_1",
    pillar="MOMENTUM",
    direction=1,
    min_history_days=252,
    required_tables=["equity_daily"],
    unit="%",
)
def momentum_12_1(ctx: FactorContext, asof: date) -> pd.Series:
    """12-month momentum, excluding the most recent 1 month (12-1).
    
    Formula: (Price_{T-1m} / Price_{T-12m}) - 1
    
    Uses ``close`` price (not adjusted — corporate-action adjustments
    are a separate concern handled upstream by ``universe.adjust``).

    Missing data policy:
        Requires valid prices at approximately 1 month and 12 months ago.
        If either is missing, returns NaN.
    """
    # Fetch 380 calendar days to ensure we have a full 12 months (365 days)
    # plus a buffer for weekends/holidays around the edges.
    prices = ctx.get_prices(asof, lookback_days=380)
    
    if prices.empty:
        return pd.Series(dtype=float)

    # Coerce both to us resolution to avoid merge_asof type errors
    prices["date"] = pd.to_datetime(prices["date"]).dt.as_unit("us")

    asof_dt = pd.Timestamp(asof).as_unit("us")
    t_1m_target = asof_dt - pd.DateOffset(months=1)
    t_12m_target = asof_dt - pd.DateOffset(years=1)

    isins = prices["isin"].unique()
    
    target_1m = pd.DataFrame({"isin": isins, "target_date": t_1m_target})
    target_1m["target_date"] = target_1m["target_date"].dt.as_unit("us")
    
    target_12m = pd.DataFrame({"isin": isins, "target_date": t_12m_target})
    target_12m["target_date"] = target_12m["target_date"].dt.as_unit("us")
    
    # merge_asof requires the right side to be strictly sorted by the merge key
    prices = prices.sort_values("date")
    
    p_1m = pd.merge_asof(
        target_1m.sort_values("target_date"),
        prices[["isin", "date", "close"]],
        left_on="target_date",
        right_on="date",
        by="isin",
        direction="backward",
        tolerance=pd.Timedelta(days=7),
    ).set_index("isin")["close"].rename("p_1m")
    
    p_12m = pd.merge_asof(
        target_12m.sort_values("target_date"),
        prices[["isin", "date", "close"]],
        left_on="target_date",
        right_on="date",
        by="isin",
        direction="backward",
        tolerance=pd.Timedelta(days=7),
    ).set_index("isin")["close"].rename("p_12m")

    df = pd.concat([p_1m, p_12m], axis=1)

    mom = (df["p_1m"] / df["p_12m"]) - 1.0
    mom = mom.replace([np.inf, -np.inf], np.nan)

    dropped = int(mom.isna().sum())
    if dropped > 0:
        logger.info("factor_missing_data", factor="momentum_12_1", dropped=dropped)

    return mom


@factor(
    id="momentum_6",
    pillar="MOMENTUM",
    direction=1,
    min_history_days=126,
    required_tables=["equity_daily"],
    unit="%",
)
def momentum_6(ctx: FactorContext, asof: date) -> pd.Series:
    """6-month momentum.
    
    Formula: (Price_{T} / Price_{T-6m}) - 1
    """
    prices = ctx.get_prices(asof, lookback_days=200)
    if prices.empty:
        return pd.Series(dtype=float)

    prices["date"] = pd.to_datetime(prices["date"]).dt.as_unit("us")
    asof_dt = pd.Timestamp(asof).as_unit("us")
    t_6m_target = asof_dt - pd.DateOffset(months=6)

    isins = prices["isin"].unique()
    
    target_6m = pd.DataFrame({"isin": isins, "target_date": t_6m_target})
    target_6m["target_date"] = target_6m["target_date"].dt.as_unit("us")
    
    prices = prices.sort_values("date")
    
    # Get current price
    p_current = prices.groupby("isin").last()["close"].rename("p_curr")
    
    # Get 6m price
    p_6m = pd.merge_asof(
        target_6m.sort_values("target_date"),
        prices[["isin", "date", "close"]],
        left_on="target_date",
        right_on="date",
        by="isin",
        direction="backward",
        tolerance=pd.Timedelta(days=7),
    ).set_index("isin")["close"].rename("p_6m")

    df = pd.concat([p_current, p_6m], axis=1)

    mom = (df["p_curr"] / df["p_6m"]) - 1.0
    return mom.replace([np.inf, -np.inf], np.nan)


@factor(
    id="momentum_3",
    pillar="MOMENTUM",
    direction=1,
    min_history_days=63,
    required_tables=["equity_daily"],
    unit="%",
)
def momentum_3(ctx: FactorContext, asof: date) -> pd.Series:
    """3-month momentum.
    
    Formula: (Price_{T} / Price_{T-3m}) - 1
    """
    prices = ctx.get_prices(asof, lookback_days=100)
    if prices.empty:
        return pd.Series(dtype=float)

    prices["date"] = pd.to_datetime(prices["date"]).dt.as_unit("us")
    asof_dt = pd.Timestamp(asof).as_unit("us")
    t_3m_target = asof_dt - pd.DateOffset(months=3)

    isins = prices["isin"].unique()
    
    target_3m = pd.DataFrame({"isin": isins, "target_date": t_3m_target})
    target_3m["target_date"] = target_3m["target_date"].dt.as_unit("us")
    
    prices = prices.sort_values("date")
    
    p_current = prices.groupby("isin").last()["close"].rename("p_curr")
    
    p_3m = pd.merge_asof(
        target_3m.sort_values("target_date"),
        prices[["isin", "date", "close"]],
        left_on="target_date",
        right_on="date",
        by="isin",
        direction="backward",
        tolerance=pd.Timedelta(days=7),
    ).set_index("isin")["close"].rename("p_3m")

    df = pd.concat([p_current, p_3m], axis=1)

    mom = (df["p_curr"] / df["p_3m"]) - 1.0
    return mom.replace([np.inf, -np.inf], np.nan)


@factor(
    id="price_vs_52w_high",
    pillar="MOMENTUM",
    direction=1,
    min_history_days=252,
    required_tables=["equity_daily"],
    unit="%",
)
def price_vs_52w_high(ctx: FactorContext, asof: date) -> pd.Series:
    """Price vs 52-Week High.
    
    Formula: Current Price / Highest High over past 252 trading days.
    """
    prices = ctx.get_prices(asof, lookback_days=365)
    if prices.empty:
        return pd.Series(dtype=float)
        
    prices = prices.sort_values(["isin", "date"])
    
    # We want exactly the last 252 available rows per ISIN to represent 52 trading weeks
    prices["rn"] = prices.groupby("isin").cumcount(ascending=False)
    prices_1yr = prices[prices["rn"] < 252]
    
    # Current close
    p_current = prices_1yr.groupby("isin").first()["close"]
    # 52w High (using the 'high' column, not 'close')
    high_52w = prices_1yr.groupby("isin")["high"].max()
    
    ratio = p_current / high_52w
    
    # Drop ISINs with fewer than 200 trading days
    counts = prices_1yr.groupby("isin").size()
    ratio = ratio.where(counts >= 200, np.nan)
    
    return ratio.replace([np.inf, -np.inf], np.nan)
