import polars as pl
import pandas as pd
import numpy as np
from datetime import date
from indiquant.config.settings import IndiQuantSettings
from indiquant.store.lakehouse import Lakehouse
from indiquant.costs.statutory import StatutoryCostModel
from indiquant.costs.slippage import SlippageModel
from indiquant.costs.constraints import ExecutionConstraints
from indiquant.engine.execution import ExecutionModel
from indiquant.engine.event_loop import run_event_loop

settings = IndiQuantSettings()
lh = Lakehouse(settings)

# 1. Load sample equity data
df = pl.scan_parquet(str(lh.silver_dir / 'equity_daily' / 'year=2024' / '*.parquet'))
df = df.with_columns(pl.col("date").cast(pl.Date))
df = df.filter(
    (pl.col("date") >= pl.lit(date(2024, 1, 1))) & 
    (pl.col("date") <= pl.lit(date(2024, 1, 31))) &
    (pl.col("series") == "EQ")
).collect()

if df.height == 0:
    print("No data")
    exit(1)

# Pick top 5 symbols by volume on first day
first_day = df["date"].min()
top_symbols = df.filter(pl.col("date") == first_day).sort("volume", descending=True).head(5)["symbol"].to_list()

df_subset = df.filter(pl.col("symbol").is_in(top_symbols)).to_pandas()
df_subset = df_subset.drop(columns=["isin"]).rename(columns={"symbol": "isin"})
df_subset = df_subset.drop_duplicates(subset=["date", "isin"])
df_subset["date"] = pd.to_datetime(df_subset["date"]).dt.date

# 2. Build prices DataFrame (MultiIndex: date, isin)
prices = df_subset.set_index(["date", "isin"])[["open", "high", "low", "close", "prev_close", "volume"]]

# 3. Build target_weights (equal weight daily rebalance)
dates = sorted(df_subset["date"].unique())
weights_list = []
for dt in dates:
    day_df = df_subset[df_subset["date"] == dt]
    symbols = day_df["isin"].tolist()
    w = 1.0 / len(symbols) if len(symbols) > 0 else 0.0
    for sym in symbols:
        weights_list.append({"date": dt, "isin": sym, "weight": w})

target_weights = pd.DataFrame(weights_list).set_index(["date", "isin"]).unstack("isin").fillna(0.0)
target_weights.columns = target_weights.columns.droplevel(0)

# 4. Setup Execution Model
statutory = StatutoryCostModel(brokerage_rate=0.0001, flat_brokerage=0.0)
slippage = SlippageModel()
constraints = ExecutionConstraints(enforce_circuits=False, enforce_whole_shares=True)
exec_model = ExecutionModel(statutory, slippage, constraints)

# 5. Run Event Loop
print("Running event loop...")
res = run_event_loop(prices, target_weights, exec_model, init_cash=100000.0)

# 6. Extract Metrics
trades = res.attrs["trades"]

cost_breakdown = {
    "Brokerage": round(trades["cost_brokerage"].sum(), 2),
    "STT": round(trades["cost_stt"].sum(), 2),
    "Exchange Charges": round(trades["cost_exchange"].sum(), 2),
    "GST": round(trades["cost_gst"].sum(), 2),
    "Stamp Duty": round(trades["cost_stamp"].sum(), 2),
    "Slippage": round(trades["slippage_cost"].sum(), 2),
}
print(cost_breakdown)

# Compute performance
daily_returns = res["portfolio_value"].pct_change().dropna()
gross_returns = (res["portfolio_value"] + res["cumulative_costs"]).pct_change().dropna()

net_cagr = (res["portfolio_value"].iloc[-1] / res["portfolio_value"].iloc[0]) ** (252 / len(res)) - 1
gross_cagr = ((res["portfolio_value"].iloc[-1] + res["cumulative_costs"].iloc[-1]) / res["portfolio_value"].iloc[0]) ** (252 / len(res)) - 1

net_sharpe = daily_returns.mean() / daily_returns.std() * np.sqrt(252) if daily_returns.std() > 0 else 0.0
gross_sharpe = gross_returns.mean() / gross_returns.std() * np.sqrt(252) if gross_returns.std() > 0 else 0.0

roll_max = res["portfolio_value"].cummax()
drawdown = res["portfolio_value"] / roll_max - 1
max_dd = drawdown.min()

turnover = (trades["gross_value"].sum() / 2) / res["portfolio_value"].mean()

print(f"Net CAGR: {net_cagr}")
print(f"Gross CAGR: {gross_cagr}")
print(f"Net Sharpe: {net_sharpe}")
print(f"Gross Sharpe: {gross_sharpe}")
print(f"Max DD: {max_dd}")
print(f"Turnover: {turnover}")
print(f"Trades: {len(trades)}")
