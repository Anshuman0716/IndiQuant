"""Slippage and market impact models.

Estimates execution friction beyond statutory taxes. Includes bid-ask spread
crossing and market impact (square-root law).
"""
import numpy as np


class SlippageModel:
    """Models spread cost, market impact, and participation caps."""
    
    def __init__(
        self,
        impact_c: float = 1.0,
        max_pct_adv: float = 0.08,
    ):
        """
        Args:
            impact_c: Calibration constant for square-root market impact law.
            max_pct_adv: Maximum participation rate (e.g. 0.08 = 8% of ADV).
        """
        self.impact_c = impact_c
        self.max_pct_adv = max_pct_adv
        
    def estimate_spread_bps(self, mcap_rank_pct: float) -> float:
        """Estimate half-spread in basis points based on market cap rank.
        
        Using a liquidity bucketed lookup:
        Top 10% (Large)  ~ 4 bps
        Next 40% (Mid)   ~ 15 bps
        Bottom 50% (Sml) ~ 50 bps
        
        Args:
            mcap_rank_pct: Percentile rank of market cap (0.0 = largest, 1.0 = smallest).
            
        Returns:
            Half-spread in bps (e.g. 4.0).
        """
        if mcap_rank_pct <= 0.10:
            return 4.0
        elif mcap_rank_pct <= 0.50:
            return 15.0
        else:
            return 50.0

    def calculate_slippage(
        self,
        order_qty: float,
        adv: float,
        daily_volatility: float,
        mcap_rank_pct: float,
    ) -> dict[str, float]:
        """Calculate slippage components for an order.
        
        Args:
            order_qty: Number of shares to execute.
            adv: Average daily volume in shares.
            daily_volatility: Daily return volatility (as decimal, e.g. 0.02 for 2%).
            mcap_rank_pct: Market cap percentile for spread lookup.
            
        Returns:
            Dictionary with slippage bps and filled quantities.
        """
        # 1. Participation Cap
        max_shares = adv * self.max_pct_adv
        filled_qty = min(order_qty, max_shares)
        unfilled_qty = max(0.0, order_qty - filled_qty)
        
        if filled_qty <= 0:
            return {
                "filled_qty": 0.0,
                "unfilled_qty": order_qty,
                "spread_bps": 0.0,
                "impact_bps": 0.0,
                "total_slippage_bps": 0.0,
            }
            
        # 2. Spread Cost
        spread_bps = self.estimate_spread_bps(mcap_rank_pct)
        
        # 3. Market Impact (Square-root law)
        # impact_bps = c * daily_vol * sqrt(qty / ADV)
        # Assuming daily_vol is provided as a decimal, multiply by 10000 for bps
        vol_bps = daily_volatility * 10000.0
        impact_bps = self.impact_c * vol_bps * np.sqrt(filled_qty / adv)
        
        return {
            "filled_qty": filled_qty,
            "unfilled_qty": unfilled_qty,
            "spread_bps": spread_bps,
            "impact_bps": impact_bps,
            "total_slippage_bps": spread_bps + impact_bps,
        }
