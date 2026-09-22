"""Reference short-horizon mean reversion strategy."""
from datetime import date
import numpy as np
import pandas as pd
import structlog

from indiquant.store.lakehouse import Lakehouse
from indiquant.factors.base import FactorContext

logger = structlog.get_logger(__name__)


def generate_mean_reversion_weights(
    ctx: FactorContext,
    start_date: date,
    end_date: date,
    index_name: str = "NIFTY 50",
    rebalance_freq: str = "W-MON", # Weekly rebalance
    top_n: int = 5,
    lookback_days: int = 20, # 1-month
) -> pd.DataFrame:
    """Generate target weights for a short-horizon mean reversion strategy.
    
    Buys the worst performers over the short term (lookback_days).
    """
    
    dates = pd.date_range(start_date, end_date, freq=rebalance_freq).date
    weights = []
    
    for dt in dates:
        if index_name.upper() == "ALL":
            isins = None
        else:
            from indiquant.store.pit import index_constituents
            constituents = index_constituents(ctx.lakehouse, index_name, dt)
            if constituents.empty:
                continue
            isins = constituents["isin"].tolist()
            
        # Get prices for short window
        prices = ctx.get_prices(dt, lookback_days=lookback_days + 10)
        if prices.empty:
            continue
            
        prices = prices.sort_values(["isin", "date"])
        prices["rn"] = prices.groupby("isin").cumcount(ascending=False)
        
        # We need the current price and the price lookback_days ago
        p_current = prices[prices["rn"] == 0].set_index("isin")["close"]
        p_past = prices[prices["rn"] == lookback_days].set_index("isin")["close"]
        
        # Calculate short-term return
        ret = (p_current / p_past) - 1.0
        
        if isins:
            ret = ret.reindex(isins).dropna()
        else:
            ret = ret.dropna()
            
        if ret.empty:
            continue
            
        # Mean reversion: select the LOWEST returns (the losers)
        bottom = ret.nsmallest(top_n)
        if bottom.empty:
            continue
            
        # Equal weight
        w = 1.0 / len(bottom)
        
        row = {"date": dt}
        for isin in bottom.index:
            row[isin] = w
            
        weights.append(row)
        
    if not weights:
        return pd.DataFrame()
        
    df = pd.DataFrame(weights).set_index("date").fillna(0.0)
    return df
