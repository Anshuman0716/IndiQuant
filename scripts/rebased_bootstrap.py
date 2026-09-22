import polars as pl
import numpy as np
from indiquant.config.settings import IndiQuantSettings
from indiquant.store.lakehouse import Lakehouse
from indiquant.events.study import EventStudyEngine
from run_event_studies import get_returns, get_delivery_collapse_events

lh = Lakehouse(IndiQuantSettings())
returns = get_returns(lh)
tds = returns.select("date").unique().sort("date")
tds = tds.with_columns(pl.col("date").shift(-1).alias("next_trading_day"))

events = get_delivery_collapse_events(lh, tds)
engine = EventStudyEngine(returns)
res = engine.run(events, window_start=-20, window_end=60)
raw = res["raw_events"]

# Pivot to get CAR matrix (n_events x n_rel_days)
pivot_df = raw.pivot(values="car", index="event_id", on="rel_day").sort("event_id")

# We want the Rebased CAR from T=0. 
# Subtract the T=0 column from all columns.
t0_cars = pivot_df["0"]
rebased_df = pivot_df.drop("event_id").with_columns([
    (pl.col(c) - t0_cars).alias(c) for c in pivot_df.drop("event_id").columns
])

car_matrix = rebased_df.to_numpy()
n_ev = car_matrix.shape[0]

# Bootstrap B=1000
B = 1000
np.random.seed(42)
resampled_idx = np.random.randint(0, n_ev, size=(B, n_ev))
boot_means = car_matrix[resampled_idx].mean(axis=1)

ci_lower = np.percentile(boot_means, 2.5, axis=0)
ci_upper = np.percentile(boot_means, 97.5, axis=0)
actual_means = car_matrix.mean(axis=0)

columns = list(rebased_df.columns)
print("Rel Day | Mean Rebased CAR | 95% CI")
print("-" * 50)
for rel_day in [0, 5, 10, 20, 30, 40, 50, 60]:
    idx = columns.index(str(rel_day))
    mean_val = actual_means[idx]
    lower = ci_lower[idx]
    upper = ci_upper[idx]
    print(f"{rel_day:>7} | {mean_val:>16.4%} | [{lower:.2%} , {upper:.2%}]")
