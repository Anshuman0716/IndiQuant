import argparse
import polars as pl
from datetime import date
import numpy as np
from indiquant.config.settings import IndiQuantSettings
from indiquant.store.lakehouse import Lakehouse
from indiquant.events.study import EventStudyEngine

def get_returns(lh: Lakehouse) -> pl.DataFrame:
    df = pl.scan_parquet(str(lh.silver_dir / 'equity_daily' / '**' / '*.parquet')).select([
        "symbol", "date", "close", "prev_close"
    ]).collect()
    
    df = df.with_columns(pl.col("date").str.strptime(pl.Date, "%Y-%m-%d"))
    
    # Calculate daily returns
    df = df.with_columns(
        ((pl.col("close") / pl.col("prev_close")) - 1.0).alias("ret")
    )
    return df.drop_nulls("ret")

def get_fno_ban_entry_events(lh: Lakehouse, eq_dates: pl.DataFrame) -> pl.DataFrame:
    df = pl.scan_parquet(str(lh.silver_dir / 'fno_ban' / '**' / '*.parquet')).select([
        "symbol", "date"
    ]).collect()
    
    df = df.with_columns(pl.col("date").str.strptime(pl.Date, "%Y-%m-%d"))
    
    # fno_ban_entry is when a stock is in the ban list today, but not yesterday
    df = df.sort(["symbol", "date"])
    df = df.with_columns(
        pl.col("date").diff().over("symbol").alias("days_since_last_ban")
    )
    
    # De-cluster: we consider it an entry only if it wasn't in ban for at least 20 days prior.
    # This ensures independence and stops clustered re-triggers.
    events = df.filter(
        pl.col("days_since_last_ban").is_null() | 
        (pl.col("days_since_last_ban").dt.total_days() > 20)
    )
    
    # LOOKAHEAD FIX: The ban list is published at the END of the trading day.
    # The first tradable day (T=0) is the NEXT trading day.
    # We join with equity_daily dates to shift the event date forward by 1 trading day.
    events = events.join(eq_dates, on="date", how="left").select([
        "symbol", "next_trading_day"
    ]).rename({"next_trading_day": "date"}).drop_nulls("date")
    
    return events

def get_delivery_collapse_events(lh: Lakehouse, eq_dates: pl.DataFrame) -> pl.DataFrame:
    df = pl.scan_parquet(str(lh.silver_dir / 'mto_delivery' / '**' / '*.parquet')).select([
        "symbol", "date", "delivery_pct"
    ]).collect()
    
    df = df.with_columns(pl.col("date").str.strptime(pl.Date, "%Y-%m-%d", strict=False))
    
    # delivery_pct_collapse = delivery_pct drops significantly.
    df = df.sort(["symbol", "date"])
    df = df.with_columns(
        pl.col("delivery_pct").rolling_mean(window_size=20).over("symbol").alias("ma_20_del_pct")
    )
    events = df.filter(
        (pl.col("delivery_pct") < 20.0) & 
        (pl.col("delivery_pct") < (pl.col("ma_20_del_pct") * 0.5))
    )
    
    # De-cluster: limit to one event per 60 days per symbol
    events = events.with_columns(
        pl.col("date").diff().over("symbol").alias("days_since_last")
    )
    events = events.filter(
        pl.col("days_since_last").is_null() | 
        (pl.col("days_since_last").dt.total_days() > 60)
    )
    
    # LOOKAHEAD FIX: Delivery data is MTO, published end-of-day.
    # The first tradable day (T=0) is the NEXT trading day.
    events = events.join(eq_dates, on="date", how="left").select([
        "symbol", "next_trading_day"
    ]).rename({"next_trading_day": "date"}).drop_nulls("date")
    
    return events

def get_expiry_events(lh: Lakehouse) -> pl.DataFrame:
    # Expiry events are market-wide, occurring on the last Thursday of the month.
    # We use the trading calendar from equity_daily to find actual expiry days.
    df = pl.scan_parquet(str(lh.silver_dir / 'equity_daily' / '**' / '*.parquet')).select([
        "symbol", "date"
    ]).collect()
    
    df = df.with_columns(pl.col("date").str.strptime(pl.Date, "%Y-%m-%d", strict=False))
    
    # Get unique trading days
    trading_days = df.select("date").unique().sort("date")
    
    # For each month, find the last Thursday that is a trading day.
    # If the last Thursday is a holiday, it's the preceding Wednesday, etc.
    # A robust approximation without an explicit holiday calendar is just:
    # the last trading day of the month that is <= the last Thursday of the month.
    
    import pandas as pd
    td_pandas = trading_days.to_pandas()["date"]
    
    expiry_dates = []
    for (year, month), group in td_pandas.groupby([td_pandas.dt.year, td_pandas.dt.month]):
        # Find the last Thursday of this month
        import calendar
        cal = calendar.monthcalendar(year, month)
        last_thursday_day = cal[-1][calendar.THURSDAY]
        if last_thursday_day == 0:
            last_thursday_day = cal[-2][calendar.THURSDAY]
            
        last_thursday = pd.to_datetime(date(year, month, last_thursday_day))
        
        # Find the actual trading day <= last_thursday
        valid_days = group[group <= last_thursday]
        if not valid_days.empty:
            expiry_dates.append(valid_days.max())
            
    expiry_df = pl.DataFrame({"date": expiry_dates})
    expiry_df = expiry_df.with_columns(pl.col("date").cast(pl.Date))
    
    # Cross join with all symbols to create events
    # Or just return for Nifty 50 symbols. For simplicity, we just filter returns_df later.
    # Here we just generate the event for all symbols active on that date.
    events = df.join(expiry_df, on="date", how="inner")
    
    return events.select(["symbol", "date"])

def print_study_results(event_name: str, results: dict):
    stats = results["stats"]
    print(f"\n=======================================================")
    print(f"EVENT STUDY: {event_name.upper()}")
    print(f"=======================================================")
    print("Significance Table (Key Intervals, 95% Bootstrap CI):")
    print(f"{'Rel Day':>8} | {'Mean CAR':>10} | {'Std':>8} | {'N Events':>8} | {'95% CI':>20}")
    print("-" * 65)
    
    intervals = [-20, -10, -5, 0, 5, 10, 20, 30, 40, 50, 60]
    for row in stats.iter_rows(named=True):
        if row['rel_day'] in intervals:
            ci = f"[{row['boot_ci_lower']:.2%} , {row['boot_ci_upper']:.2%}]"
            print(f"{row['rel_day']:>8} | {row['mean_car']:>10.4%} | {row['std_car']:>8.4f} | {row['n_events']:>8} | {ci:>20}")

    print("\nCAR Chart (ASCII Approximation):")
    max_car = stats["mean_car"].max()
    min_car = stats["mean_car"].min()
    rng = max_car - min_car if max_car != min_car else 1.0
    
    for row in stats.iter_rows(named=True):
        if row['rel_day'] % 5 == 0 or row['rel_day'] == 0:
            val = row['mean_car']
            normalized = (val - min_car) / rng
            bar_len = int(normalized * 40)
            marker = "*" if row['rel_day'] == 0 else "|"
            print(f"T{row['rel_day']:>3} {val:>8.2%} {marker}{'#' * bar_len}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--event", type=str, required=True)
    parser.add_argument("--window", type=int, nargs=2, default=[-20, 60])
    args = parser.parse_args()

    lh = Lakehouse(IndiQuantSettings())
    print("Loading returns data...")
    returns = get_returns(lh)
    engine = EventStudyEngine(returns)
    
    # Generate eq_dates lookup (next trading day mapping)
    tds = returns.select("date").unique().sort("date")
    tds = tds.with_columns(pl.col("date").shift(-1).alias("next_trading_day"))
    
    print(f"Detecting {args.event} events...")
    if args.event == "fno_ban_entry":
        events = get_fno_ban_entry_events(lh, tds)
    elif args.event == "delivery_pct_collapse":
        events = get_delivery_collapse_events(lh, tds)
    elif args.event == "expiry_effects":
        events = get_expiry_events(lh)
    else:
        raise ValueError(f"Unknown event: {args.event}")
        
    print(f"Found {len(events)} event occurrences. Running engine...")
    res = engine.run(events, window_start=args.window[0], window_end=args.window[1])
    
    print_study_results(args.event, res)
