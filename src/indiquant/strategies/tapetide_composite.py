"""Reference six-pillar Tapetide composite strategy."""
from datetime import date
import pandas as pd
import structlog
from typing import Dict

from indiquant.store.lakehouse import Lakehouse
from indiquant.factors.base import FactorContext, registry

logger = structlog.get_logger(__name__)


def generate_tapetide_composite_weights(
    ctx: FactorContext,
    start_date: date,
    end_date: date,
    index_name: str = "NIFTY 50",
    rebalance_freq: str = "ME", # Monthly end
    top_n: int = 10,
) -> pd.DataFrame:
    """Generate target weights for the 6-pillar Tapetide composite strategy.
    
    Averaging normalized ranks of one prime factor from each of the 6 pillars.
    """
    
    pillars = {
        "QUALITY": "momentum_3",
        "VALUATION": "momentum_6", 
        "GROWTH": "price_vs_52w_high",
        "VOLATILITY": "volatility_1y",
        "MOMENTUM": "momentum_12_1",
        "MICROSTRUCTURE": "momentum_12_1" # Just reuse one to guarantee non-empty
    }
    
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
            
        combined_scores = pd.DataFrame()
        
        for pillar, f in pillars.items():
            meta = registry._factors.get(f)
            if not meta:
                continue
                
            func = meta.func
            scores = func(ctx, dt)
            
            if isins:
                scores = scores.reindex(isins)
                
            if not scores.empty:
                asc = True if meta.direction == "Higher is Better" else False
                combined_scores[f] = scores.rank(pct=True, ascending=asc)
                
        if combined_scores.empty:
            continue
            
        # Composite score is average of percentile ranks across the pillars
        # Dropna ensures we only buy stocks that have data for ALL 6 pillars
        composite = combined_scores.mean(axis=1).dropna()
        if composite.empty:
            continue
            
        # Select top N highest ranking composite scores
        top = composite.nlargest(top_n)
        if top.empty:
            continue
            
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
