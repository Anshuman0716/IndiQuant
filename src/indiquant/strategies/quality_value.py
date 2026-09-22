"""Reference quality-value composite strategy."""
from datetime import date
import pandas as pd
import structlog
from typing import List

from indiquant.store.lakehouse import Lakehouse
from indiquant.factors.base import FactorContext, registry

logger = structlog.get_logger(__name__)


def generate_quality_value_weights(
    ctx: FactorContext,
    start_date: date,
    end_date: date,
    index_name: str = "NIFTY 50",
    rebalance_freq: str = "W-MON",
    top_n: int = 5,
    quality_factors: List[str] = ["roce_ttm", "roe_ttm"],
    value_factors: List[str] = ["earnings_yield", "fcf_yield"]
) -> pd.DataFrame:
    """Generate target weights for a Quality-Value Composite strategy."""
    
    dates = pd.date_range(start_date, end_date, freq=rebalance_freq).date
    weights = []
    
    for dt in dates:
        # Retrieve active universe
        if index_name.upper() == "ALL":
            isins = None
        else:
            from indiquant.store.pit import index_constituents
            constituents = index_constituents(ctx.lakehouse, index_name, dt)
            if constituents.empty:
                continue
            isins = constituents["isin"].tolist()
            
        combined_scores = pd.DataFrame()
        
        # Calculate quality factors (higher is better for ROCE and ROE)
        for f in quality_factors:
            func = registry._factors[f].func
            scores = func(ctx, dt)
            if isins:
                scores = scores.reindex(isins)
            if not scores.empty:
                # Rank: higher score = higher rank (percentile)
                combined_scores[f] = scores.rank(pct=True, ascending=True)
                
        # Calculate value factors (higher is better for yield)
        for f in value_factors:
            func = registry._factors[f].func
            scores = func(ctx, dt)
            if isins:
                scores = scores.reindex(isins)
            if not scores.empty:
                # Rank: higher yield = higher rank (percentile)
                # If we used PE, it would be ascending=False
                direction = registry._factors[f].direction
                asc = True if direction == "Higher is Better" else False
                combined_scores[f] = scores.rank(pct=True, ascending=asc)
                
        if combined_scores.empty:
            continue
            
        # Composite score is average of ranks
        composite = combined_scores.mean(axis=1).dropna()
        if composite.empty:
            continue
            
        # Select top N
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
