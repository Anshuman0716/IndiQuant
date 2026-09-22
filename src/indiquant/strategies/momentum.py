"""Reference momentum strategy."""
from datetime import date
import pandas as pd
import structlog

from indiquant.store.lakehouse import Lakehouse
from indiquant.factors.base import FactorContext, FactorRegistry

logger = structlog.get_logger(__name__)


def generate_momentum_weights(
    ctx: FactorContext,
    start_date: date,
    end_date: date,
    index_name: str = "NIFTY 50",
    rebalance_freq: str = "W-MON", # Weekly on Monday
    top_n: int = 5,
) -> pd.DataFrame:
    """Generate target weights for 12-1 momentum strategy."""
    
    dates = pd.date_range(start_date, end_date, freq=rebalance_freq).date
    
    weights = []
    
    from indiquant.factors.base import registry
    meta = registry._factors["momentum_12_1"]
    func = meta.func
    
    for dt in dates:
        scores = func(ctx, dt)
        if scores.empty:
            continue
            
        if index_name.upper() == "ALL":
            isins = scores.index.tolist()
        else:
            from indiquant.store.pit import index_constituents
            constituents = index_constituents(ctx.lakehouse, index_name, dt)
            if constituents.empty:
                continue
            isins = constituents["isin"].tolist()
            
        scores = scores.reindex(isins).dropna()
        if scores.empty:
            continue
            
        # Select top N
        top = scores.nlargest(top_n)
        
        # Equal weight
        w = 1.0 / len(top)
        
        row = {"date": dt}
        for isin in top.index:
            row[isin] = w
            
        weights.append(row)
        
    if not weights:
        return pd.DataFrame()
        
    df = pd.DataFrame(weights).set_index("date").fillna(0.0)
    return df
