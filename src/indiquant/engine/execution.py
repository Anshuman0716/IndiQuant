"""Execution model integrating statutory costs, slippage, and constraints."""

from datetime import date
from typing import Literal

from indiquant.costs.statutory import StatutoryCostModel
from indiquant.costs.slippage import SlippageModel
from indiquant.costs.constraints import ExecutionConstraints, apply_circuit_filter, apply_whole_shares


class ExecutionModel:
    """Simulates the fill of a target order on a given day."""
    
    def __init__(
        self,
        statutory: StatutoryCostModel,
        slippage: SlippageModel,
        constraints: ExecutionConstraints,
        fill_price: Literal["OPEN", "CLOSE", "VWAP"] = "CLOSE",
    ):
        self.statutory = statutory
        self.slippage = slippage
        self.constraints = constraints
        self.fill_price = fill_price
        
    def simulate_fill(
        self,
        trade_date: date,
        side: Literal["BUY", "SELL"],
        target_qty: float,
        mkt_open: float,
        mkt_high: float,
        mkt_low: float,
        mkt_close: float,
        mkt_prev_close: float,
        mkt_volume: float,
        daily_volatility: float = 0.02, # 2% default if not provided
        mcap_rank_pct: float = 0.10,    # Large cap default
        is_first_sell_of_day: bool = True,
    ) -> dict[str, float]:
        """Simulate execution of an order."""
        if target_qty <= 0:
            return {"filled_qty": 0.0, "net_cash_flow": 0.0, "total_frictional_cost": 0.0}
            
        # 1. Base Fill Price
        if self.fill_price == "OPEN":
            base_price = mkt_open
        elif self.fill_price == "VWAP":
            # Simple VWAP proxy if true VWAP isn't available
            base_price = (mkt_high + mkt_low + mkt_close) / 3.0
        else:
            base_price = mkt_close
            
        # 2. Apply Circuit Filter Constraint
        allowed_qty = target_qty
        if self.constraints.enforce_circuits:
            allowed_qty = apply_circuit_filter(
                order_qty=target_qty,
                side=side,
                execution_price=base_price,
                high=mkt_high,
                low=mkt_low,
                close=mkt_close,
                prev_close=mkt_prev_close,
            )
            
        if allowed_qty <= 0:
            return {"filled_qty": 0.0, "net_cash_flow": 0.0, "total_frictional_cost": 0.0}
            
        # 3. Apply Whole Share Constraint
        if self.constraints.enforce_whole_shares:
            allowed_qty = apply_whole_shares(allowed_qty)
            
        if allowed_qty <= 0:
            return {"filled_qty": 0.0, "net_cash_flow": 0.0, "total_frictional_cost": 0.0}
            
        # 4. Calculate Slippage (Market Impact + Spread)
        slip_res = self.slippage.calculate_slippage(
            order_qty=allowed_qty,
            adv=mkt_volume, # Using daily volume as proxy for ADV for simplicity here
            daily_volatility=daily_volatility,
            mcap_rank_pct=mcap_rank_pct,
        )
        filled_qty = slip_res["filled_qty"]
        if self.constraints.enforce_whole_shares:
            filled_qty = apply_whole_shares(filled_qty)
            
        if filled_qty <= 0:
             return {"filled_qty": 0.0, "net_cash_flow": 0.0, "total_frictional_cost": 0.0}
             
        slip_bps = slip_res["total_slippage_bps"]
        slip_dec = slip_bps / 10000.0
        
        # Adjust price based on slippage
        # Buy: price increases. Sell: price decreases.
        exec_price = base_price * (1 + slip_dec) if side == "BUY" else base_price * (1 - slip_dec)
        
        # 5. Calculate Statutory Costs
        stat_costs = self.statutory.calculate_trade_cost(
            trade_date=trade_date,
            side=side,
            qty=filled_qty,
            price=exec_price,
            segment="EQ_DELIVERY",
            is_first_sell_of_day=is_first_sell_of_day,
        )
        
        total_statutory = stat_costs["total"]
        
        # 6. Total Cash Flow
        gross_value = filled_qty * exec_price
        
        if side == "BUY":
            net_cash_flow = -1.0 * (gross_value + total_statutory)
        else:
            net_cash_flow = gross_value - total_statutory
            
        # Return breakdown
        res = {
            "filled_qty": filled_qty,
            "exec_price": exec_price,
            "base_price": base_price,
            "gross_value": gross_value,
            "net_cash_flow": net_cash_flow,
            "total_frictional_cost": total_statutory + (abs(exec_price - base_price) * filled_qty),
            "statutory_cost": total_statutory,
            "slippage_cost": abs(exec_price - base_price) * filled_qty,
        }
        res.update({f"cost_{k}": v for k, v in stat_costs.items() if k != "total"})
        return res
