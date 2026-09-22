import pandas as pd
from datetime import date
import numpy as np

from indiquant.config.settings import IndiQuantSettings
from indiquant.store.lakehouse import Lakehouse
from indiquant.factors.base import FactorContext
from indiquant.engine.runner import run_tapetide_backtest

settings = IndiQuantSettings()
lakehouse = Lakehouse(settings)
ctx = FactorContext(lakehouse)

print("Running 2024 Break-even & Capacity Analysis...")
metrics_10L = run_tapetide_backtest(date(2024,1,1), date(2024,12,31), index_name="ALL", rebalance_freq="ME", top_n=10)
print("10 Lakh Capacity:", metrics_10L)
