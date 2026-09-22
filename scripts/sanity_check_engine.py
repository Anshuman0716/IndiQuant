import polars as pl
from indiquant.config.settings import IndiQuantSettings
from indiquant.store.lakehouse import Lakehouse
from indiquant.events.study import EventStudyEngine
from run_event_studies import get_returns, get_fno_ban_entry_events

lh = Lakehouse(IndiQuantSettings())
returns = get_returns(lh)
tds = returns.select("date").unique().sort("date")
tds = tds.with_columns(pl.col("date").shift(-1).alias("next_trading_day"))

events = get_fno_ban_entry_events(lh, tds)
engine = EventStudyEngine(returns)

res = engine.run(events, window_start=-5, window_end=5)
raw = res["raw_events"]

# Find ABFRL event_id that matches T=0 date 2024-01-18
# Join with returns to get the actual date for T=0
raw_with_date = raw.join(
    engine.returns.select(["symbol", "td_idx", "date"]),
    left_on=["symbol", "target_td_idx"],
    right_on=["symbol", "td_idx"],
    how="left"
)

abfrl = raw_with_date.filter((pl.col("symbol") == "ABFRL") & (pl.col("date") == pl.date(2024, 1, 18)) & (pl.col("rel_day") == 0))
if len(abfrl) > 0:
    event_id = abfrl["event_id"][0]
    specific_event = raw_with_date.filter(pl.col("event_id") == event_id)
    print("Engine Output for ABFRL event (event_id:", event_id, "):")
    for row in specific_event.sort("rel_day").to_dicts():
        if row['rel_day'] in [-1, 0, 3]:
            print(f"RelDay: {row['rel_day']}, Date: {row['date']}, Ret: {row['ret']}, CAR: {row['car']}")
else:
    print("Event not found.")
