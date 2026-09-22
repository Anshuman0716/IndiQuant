import polars as pl
from indiquant.config.settings import IndiQuantSettings
from indiquant.store.lakehouse import Lakehouse

lh = Lakehouse(IndiQuantSettings())
# 1. Get one FNO Ban event
fno_ban = pl.scan_parquet(str(lh.silver_dir / 'fno_ban' / '**' / '*.parquet')).select(["symbol", "date"]).collect()
fno_ban = fno_ban.with_columns(pl.col("date").str.strptime(pl.Date, "%Y-%m-%d")).sort(["symbol", "date"])
fno_ban = fno_ban.with_columns(pl.col("date").diff().over("symbol").alias("diff"))
events = fno_ban.filter(pl.col("diff").is_null() | (pl.col("diff").dt.total_days() > 3))

print("Total raw fno_ban events:", len(events))
if len(events) == 0:
    print("No events found!")
    exit()

ev = events.row(0, named=True)
print(f"Selected Event: {ev['symbol']} on {ev['date']} (This is the day it was reported in ban)")

# 2. Get the trading calendar to find the next trading day (T=0)
eq = pl.scan_parquet(str(lh.silver_dir / 'equity_daily' / '**' / '*.parquet')).select(["symbol", "date", "close", "prev_close"]).collect()
eq = eq.with_columns(pl.col("date").str.strptime(pl.Date, "%Y-%m-%d")).sort(["symbol", "date"])

tds = eq.select("date").unique().sort("date")
td_list = tds["date"].to_list()
idx = td_list.index(ev['date'])
t0_date = td_list[idx + 1]
print(f"Shifted T=0 Date: {t0_date}")

# 3. Get the returns for this symbol around T=0
sym_data = eq.filter(pl.col("symbol") == ev['symbol']).with_columns(
    ((pl.col("close") / pl.col("prev_close")) - 1.0).alias("ret")
).sort("date")

# Find the row for T=0
t0_idx = sym_data.with_row_index().filter(pl.col("date") == t0_date)["index"][0]

print("\nManual CAR Calculation (T=-5 to T=+5):")
print(f"{'RelDay':>6} | {'Date':>12} | {'Close':>8} | {'Ret':>8} | {'CAR':>8}")
car_from_minus_5 = 0.0
for rel_day in range(-5, 6):
    r = sym_data.row(t0_idx + rel_day, named=True)
    car_from_minus_5 += r['ret']
    print(f"{rel_day:>6} | {str(r['date']):>12} | {r['close']:>8.2f} | {r['ret']:>8.4%} | {car_from_minus_5:>8.4%}")
