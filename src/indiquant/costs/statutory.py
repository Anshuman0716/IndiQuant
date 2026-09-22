"""Statutory transaction cost models for Indian equities and F&O.

Rates change with each Union Budget and are applied purely point-in-time
based on the trade date. NEVER use constant flat rates.
"""

from dataclasses import dataclass
from datetime import date
from typing import Literal

import pandas as pd


@dataclass
class CostRates:
    """Rates applicable for a specific segment during a specific date window."""
    effective_from: date
    effective_to: date | None
    segment: Literal["EQ_DELIVERY", "EQ_INTRADAY", "FUTURES", "OPTIONS"]
    
    stt_buy: float      # as decimal (e.g. 0.001 for 0.1%)
    stt_sell: float     # as decimal
    exch_txn: float     # as decimal
    sebi_fee: float     # as decimal
    ipft: float         # as decimal
    stamp_duty: float   # as decimal (buy side only)
    gst_rate: float     # as decimal (e.g. 0.18 for 18%)
    dp_charge: float    # flat currency amount per scrip sold (delivery only)
    
    def is_active(self, trade_date: date) -> bool:
        if trade_date < self.effective_from:
            return False
        if self.effective_to and trade_date >= self.effective_to:
            return False
        return True


# Historical rate table. New budget changes append to this list.
_RATE_HISTORY = [
    # --- EQUITY DELIVERY ---
    CostRates(
        effective_from=date(2010, 1, 1),
        effective_to=None, # Current as of 2026
        segment="EQ_DELIVERY",
        stt_buy=0.001,      # 0.10%
        stt_sell=0.001,     # 0.10%
        exch_txn=0.0000297, # ~0.00297% (NSE)
        sebi_fee=0.000001,  # 0.0001% (10 per crore)
        ipft=0.000001,      # 10 per crore
        stamp_duty=0.00015, # 0.015%
        gst_rate=0.18,      # 18%
        dp_charge=15.0,     # Rs 15 flat
    ),
    # --- FUTURES ---
    CostRates(
        effective_from=date(2010, 1, 1),
        effective_to=date(2026, 4, 1), # Pre 2026 Budget
        segment="FUTURES",
        stt_buy=0.0,
        stt_sell=0.0002,    # 0.02%
        exch_txn=0.000018,  # ~0.0018%
        sebi_fee=0.000001,
        ipft=0.000001,
        stamp_duty=0.00002, # 0.002% buy side
        gst_rate=0.18,
        dp_charge=0.0,
    ),
    CostRates(
        effective_from=date(2026, 4, 1),
        effective_to=None, # Post 2026 Budget
        segment="FUTURES",
        stt_buy=0.0,
        stt_sell=0.0005,    # 0.05% (Increased from 0.02%)
        exch_txn=0.000018,
        sebi_fee=0.000001,
        ipft=0.000001,
        stamp_duty=0.00002,
        gst_rate=0.18,
        dp_charge=0.0,
    ),
    # --- OPTIONS ---
    CostRates(
        effective_from=date(2010, 1, 1),
        effective_to=date(2026, 4, 1), # Pre 2026 Budget
        segment="OPTIONS",
        stt_buy=0.0,
        stt_sell=0.0010,    # 0.10% on premium
        exch_txn=0.000355,  # ~0.0355%
        sebi_fee=0.000001,
        ipft=0.000001,
        stamp_duty=0.00003, # 0.003% buy side
        gst_rate=0.18,
        dp_charge=0.0,
    ),
    CostRates(
        effective_from=date(2026, 4, 1),
        effective_to=None, # Post 2026 Budget
        segment="OPTIONS",
        stt_buy=0.0,
        stt_sell=0.0015,    # 0.15% (Increased from 0.10%)
        exch_txn=0.000355,
        sebi_fee=0.000001,
        ipft=0.000001,
        stamp_duty=0.00003,
        gst_rate=0.18,
        dp_charge=0.0,
    ),
]


class StatutoryCostModel:
    """Calculates granular transaction costs point-in-time."""
    
    def __init__(self, brokerage_rate: float = 0.0, flat_brokerage: float = 0.0):
        """Configure broker-specific charges.
        
        Args:
            brokerage_rate: Decimal rate (e.g. 0.0001 for 0.01%).
            flat_brokerage: Flat currency amount per executed order.
        """
        self.brokerage_rate = brokerage_rate
        self.flat_brokerage = flat_brokerage
        
    def get_rates(self, trade_date: date, segment: str = "EQ_DELIVERY") -> CostRates:
        for r in _RATE_HISTORY:
            if r.segment == segment and r.is_active(trade_date):
                return r
        raise ValueError(f"No cost rates found for {segment} on {trade_date}")

    def calculate_trade_cost(
        self,
        trade_date: date,
        side: Literal["BUY", "SELL"],
        qty: float,
        price: float,
        segment: str = "EQ_DELIVERY",
        is_first_sell_of_day: bool = True,
    ) -> dict[str, float]:
        """Calculate the total frictional cost of a single trade.
        
        Args:
            trade_date: Determines which tax regime applies.
            side: BUY or SELL.
            qty: Number of shares/contracts.
            price: Execution price.
            segment: EQ_DELIVERY, EQ_INTRADAY, FUTURES, OPTIONS.
            is_first_sell_of_day: DP charges are applied once per scrip per day on SELL.
            
        Returns:
            Dictionary mapping cost components to absolute currency amounts.
        """
        rates = self.get_rates(trade_date, segment)
        value = qty * price
        
        # 1. STT
        stt_rate = rates.stt_buy if side == "BUY" else rates.stt_sell
        stt = value * stt_rate
        
        # 2. Brokerage
        brokerage = max(value * self.brokerage_rate, self.flat_brokerage)
        
        # 3. Exchange + SEBI
        exch = value * rates.exch_txn
        sebi = value * rates.sebi_fee
        ipft = value * rates.ipft
        
        # 4. Stamp Duty (Buy only)
        stamp = value * rates.stamp_duty if side == "BUY" else 0.0
        
        # 5. GST (on Brokerage + Exchange + SEBI)
        gst = (brokerage + exch + sebi) * rates.gst_rate
        
        # 6. DP Charge (Sell delivery only)
        dp = 0.0
        if segment == "EQ_DELIVERY" and side == "SELL" and is_first_sell_of_day:
            dp = rates.dp_charge
            gst += dp * rates.gst_rate  # GST applies to DP charge
            
        total = stt + brokerage + exch + sebi + ipft + stamp + gst + dp
        
        return {
            "stt": stt,
            "brokerage": brokerage,
            "exchange": exch,
            "sebi": sebi,
            "ipft": ipft,
            "stamp": stamp,
            "gst": gst,
            "dp": dp,
            "total": total,
        }
