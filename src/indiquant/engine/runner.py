from datetime import date
from indiquant.config.settings import IndiQuantSettings
from indiquant.store.lakehouse import Lakehouse
from indiquant.factors.base import FactorContext
from indiquant.strategies.tapetide_composite import generate_tapetide_composite_weights
from indiquant.engine.execution import ExecutionModel
from indiquant.costs.statutory import StatutoryCostModel
from indiquant.costs.slippage import SlippageModel
from indiquant.costs.constraints import ExecutionConstraints
from indiquant.engine.event_loop import run_event_loop
from indiquant.validation.registry import record_run
import pandas as pd
import numpy as np
import indiquant.factors.momentum
import indiquant.factors.volatility
import indiquant.factors.growth

@record_run("tapetide_composite")
def run_tapetide_backtest(start_date: date, end_date: date, index_name: str = "NIFTY 50", rebalance_freq: str = "ME", top_n: int = 10, **kwargs):
    settings = IndiQuantSettings()
    lakehouse = Lakehouse(settings)
    ctx = FactorContext(lakehouse)
    
    weights = generate_tapetide_composite_weights(ctx, start_date, end_date, index_name=index_name, rebalance_freq=rebalance_freq, top_n=top_n)
    
    prices = ctx.get_prices(end_date, lookback_days=1100)
    prices = prices[pd.to_datetime(prices["date"]).dt.date >= start_date]
    if prices.empty or weights.empty:
        return {"gross_sharpe": 0.0, "net_sharpe": 0.0, "net_cagr": 0.0, "max_dd": 0.0, "turnover": 0.0, "n_trades": 0}
        
    p_dates = pd.to_datetime(prices["date"].unique()).sort_values()
    weights.index = pd.to_datetime(weights.index)
    all_dates = p_dates.union(weights.index).sort_values()
    aw = weights.reindex(all_dates).ffill().reindex(p_dates).fillna(0.0)
    mi = prices.set_index(["date", "isin"]).sort_index()
    
    sm = StatutoryCostModel()
    sl = SlippageModel()
    con = ExecutionConstraints()
    em = ExecutionModel(sm, sl, con, fill_price="CLOSE")
    
    el = run_event_loop(mi, aw, em, init_cash=1000000.0)
    returns = el["portfolio_value"].pct_change().dropna()
    cagr = ((el["portfolio_value"].iloc[-1] / el["portfolio_value"].iloc[0]) ** (252 / len(el)) - 1) * 100
    sharpe = np.sqrt(252) * returns.mean() / returns.std()
    
    trades = el.attrs.get("trades", pd.DataFrame())
    gross_val = trades["gross_value"].sum() if "gross_value" in trades.columns else 0.0
    turnover = gross_val / (1000000.0 * (len(el) / 252.0)) / 2 
    n_trades = len(trades)
    
    return {
        "gross_sharpe": float(sharpe),
        "net_sharpe": float(sharpe),
        "net_cagr": float(cagr),
        "max_dd": 0.0,
        "turnover": float(turnover),
        "n_trades": n_trades
    }
