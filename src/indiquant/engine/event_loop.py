"""Event-driven backtest loop handling path-dependent friction.

Designed for readability and accurate modeling of Indian statutory costs,
T+1 settlement, and capacity constraints that vectorbt cannot natively express.
"""
from datetime import date
import numpy as np
import pandas as pd
import structlog

from indiquant.engine.execution import ExecutionModel

logger = structlog.get_logger(__name__)


def run_event_loop(
    prices: pd.DataFrame,
    target_weights: pd.DataFrame,
    execution_model: ExecutionModel,
    init_cash: float = 1_000_000.0,
) -> pd.DataFrame:
    """Run an event-driven backtest.
    
    Args:
        prices: MultiIndex DataFrame (date, isin) with columns: 
                open, high, low, close, prev_close, volume.
        target_weights: DataFrame index=date, columns=isin.
        execution_model: Configured execution model.
        init_cash: Initial capital.
        
    Returns:
        DataFrame of daily portfolio value and metrics.
    """
    if prices.empty or target_weights.empty:
        return pd.DataFrame()
        
    dates = sorted(prices.index.get_level_values("date").unique())
    
    cash = init_cash
    positions = {} # isin -> shares
    
    # T+1 Settlement tracking
    # List of (settlement_date, cash_amount)
    pending_cash = []
    
    # For reporting
    history = []
    total_frictional_costs = 0.0
    detailed_costs = []
    
    current_weights = pd.Series(dtype=float)
    
    for dt in dates:
        dt_date = pd.Timestamp(dt).date()
        day_prices = prices.xs(dt, level="date")
        
        # 1. Settle pending cash (T+1)
        settled_this_day = 0.0
        remaining_pending = []
        for settle_dt, amount in pending_cash:
            if dt_date >= settle_dt:
                cash += amount
                settled_this_day += amount
            else:
                remaining_pending.append((settle_dt, amount))
        pending_cash = remaining_pending
        
        # 2. Update current portfolio value to calculate target shares
        port_val = cash + sum(a for _, a in pending_cash)
        for isin, shares in positions.items():
            if isin in day_prices.index:
                port_val += shares * day_prices.loc[isin, "close"]
                
        # 3. Handle Rebalance (if target weights provided for this day)
        if dt in target_weights.index:
            current_weights = target_weights.loc[dt].dropna()
            
            # Identify orders (diff between target and current)
            orders = {}
            
            # Sells first to free up cash
            for isin, shares in list(positions.items()):
                target_w = current_weights.get(isin, 0.0)
                target_shares = (port_val * target_w) / day_prices.loc[isin, "close"] if isin in day_prices.index else 0.0
                if target_shares < shares:
                    orders[isin] = target_shares - shares # negative = sell
                    
            # Buys next
            for isin, target_w in current_weights.items():
                if target_w > 0 and isin in day_prices.index:
                    curr_shares = positions.get(isin, 0.0)
                    target_shares = (port_val * target_w) / day_prices.loc[isin, "close"]
                    if target_shares > curr_shares:
                        orders[isin] = target_shares - curr_shares # positive = buy
                        
            # Execute Sells
            first_sell_flag = set()
            for isin, diff in orders.items():
                if diff >= 0: continue
                sell_qty = abs(diff)
                
                if isin not in day_prices.index:
                    continue
                
                res = execution_model.simulate_fill(
                    trade_date=dt_date,
                    side="SELL",
                    target_qty=sell_qty,
                    mkt_open=day_prices.loc[isin, "open"],
                    mkt_high=day_prices.loc[isin, "high"],
                    mkt_low=day_prices.loc[isin, "low"],
                    mkt_close=day_prices.loc[isin, "close"],
                    mkt_prev_close=day_prices.loc[isin, "prev_close"],
                    mkt_volume=day_prices.loc[isin, "volume"],
                    is_first_sell_of_day=(isin not in first_sell_flag)
                )
                
                filled = res["filled_qty"]
                if filled > 0:
                    first_sell_flag.add(isin)
                    positions[isin] -= filled
                    if positions[isin] <= 0:
                        del positions[isin]
                        
                    # T+1 Settlement: cash arrives next trading day
                    if execution_model.constraints.settlement_t_plus == 0:
                        cash += res["net_cash_flow"]
                    else:
                        settle_date = dt_date + pd.Timedelta(days=execution_model.constraints.settlement_t_plus)
                        pending_cash.append((settle_date, res["net_cash_flow"]))
                    
                    total_frictional_costs += res["total_frictional_cost"]
                    res["date"] = dt_date
                    res["isin"] = isin
                    res["side"] = "SELL"
                    detailed_costs.append(res)
                    
            # Execute Buys (requires immediate cash)
            for isin, diff in orders.items():
                if diff <= 0: continue
                buy_qty = diff
                
                # Check cash constraint
                est_cost = buy_qty * day_prices.loc[isin, "close"] * 1.01 # 1% buffer
                if est_cost > cash:
                    # Scale down buy order to available cash
                    buy_qty = (cash / 1.01) / day_prices.loc[isin, "close"]
                    
                if buy_qty <= 0: continue
                
                res = execution_model.simulate_fill(
                    trade_date=dt_date,
                    side="BUY",
                    target_qty=buy_qty,
                    mkt_open=day_prices.loc[isin, "open"],
                    mkt_high=day_prices.loc[isin, "high"],
                    mkt_low=day_prices.loc[isin, "low"],
                    mkt_close=day_prices.loc[isin, "close"],
                    mkt_prev_close=day_prices.loc[isin, "prev_close"],
                    mkt_volume=day_prices.loc[isin, "volume"],
                )
                
                filled = res["filled_qty"]
                if filled > 0:
                    positions[isin] = positions.get(isin, 0.0) + filled
                    cash += res["net_cash_flow"] # net_cash_flow is negative for buys
                    total_frictional_costs += res["total_frictional_cost"]
                    
                    res["date"] = dt_date
                    res["isin"] = isin
                    res["side"] = "BUY"
                    detailed_costs.append(res)
                    
        # End of day reporting
        eod_port_val = cash + sum(a for _, a in pending_cash)
        for isin, shares in positions.items():
            if isin in day_prices.index:
                eod_port_val += shares * day_prices.loc[isin, "close"]
                
        history.append({
            "date": dt_date,
            "portfolio_value": eod_port_val,
            "cash": cash,
            "positions_count": len(positions),
            "cumulative_costs": total_frictional_costs,
        })
        
    df = pd.DataFrame(history).set_index("date")
    # Attach detailed costs as an attribute for reporting
    df.attrs["trades"] = pd.DataFrame(detailed_costs)
    return df
