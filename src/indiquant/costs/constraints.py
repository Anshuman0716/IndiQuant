"""Execution constraints.

Models path-dependent friction like circuit breakers, settlement delays,
and whole-share sizing limits.
"""
from dataclasses import dataclass
from typing import Literal


@dataclass
class ExecutionConstraints:
    """Configures which constraints are active in the backtest."""
    enforce_circuits: bool = True
    settlement_t_plus: int = 1
    enforce_whole_shares: bool = True
    reject_asm_gsm: bool = True


def apply_circuit_filter(
    order_qty: float,
    side: Literal["BUY", "SELL"],
    execution_price: float,
    high: float,
    low: float,
    close: float,
    prev_close: float,
) -> float:
    """Determines if an order is rejected due to hitting a circuit limit.
    
    If trying to BUY and the stock is locked at upper circuit (high == close == upper_limit),
    there are no sellers, so the order must be rejected (returns 0).
    
    In a daily backtest, if close == high and the return is >= 4.9%, we heuristically
    assume it hit the upper circuit.
    
    Args:
        order_qty: Intended quantity.
        side: Direction.
        execution_price: The price the order is trying to fill at.
        high: Daily high.
        low: Daily low.
        close: Daily close.
        prev_close: Previous close.
        
    Returns:
        Allowed fill quantity (0 if rejected, order_qty if allowed).
    """
    if prev_close <= 0 or order_qty <= 0:
        return 0.0
        
    daily_ret = (close / prev_close) - 1.0
    
    # Heuristics for hitting upper circuit (locked in upper circuit)
    if side == "BUY":
        # If close is at the high of the day AND return is near a standard circuit (5%, 10%, 20%)
        # Note: 0.049 accounts for floating point / inexact band math
        if (high == close) and (daily_ret >= 0.049):
            return 0.0 # Rejected, no sellers
            
    # Heuristics for hitting lower circuit (locked in lower circuit)
    if side == "SELL":
        if (low == close) and (daily_ret <= -0.049):
            return 0.0 # Rejected, no buyers
            
    return order_qty


def apply_whole_shares(qty: float, lot_size: int = 1) -> float:
    """Truncate quantity to exact lot multiples (1 for equity)."""
    return float(int(qty // lot_size) * lot_size)
