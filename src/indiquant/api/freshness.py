import os
import sys
import polars as pl
from datetime import datetime, date, timedelta
from indiquant.config.settings import IndiQuantSettings
from indiquant.store.lakehouse import Lakehouse
from indiquant.ingest.calendar import TradingCalendar

def main():
    print("Checking Data Freshness...")
    settings = IndiQuantSettings()
    lh = Lakehouse(settings)
    cal = TradingCalendar()
    
    # 1. Determine what the most recent trading day *should* be
    today = date.today()
    # Assuming ingest runs at 07:00 IST for the *prior* trading day,
    # the data should be fresh as of the last trading day before today.
    
    target_date = today - timedelta(days=1)
    while not cal.is_trading_day(target_date) and target_date > date(2000, 1, 1):
        target_date -= timedelta(days=1)
        
    print(f"Target Freshness Date: {target_date}")
    
    # 2. Get the max trade date from the Lakehouse
    try:
        df = pl.scan_parquet(str(lh.silver_dir / 'equity_daily' / '**' / '*.parquet'))
        max_date = df.select(pl.max('date')).collect().item()
        
        # If it's a string, convert to date
        if isinstance(max_date, str):
            max_date = datetime.strptime(max_date, "%Y-%m-%d").date()
        elif isinstance(max_date, datetime):
            max_date = max_date.date()
            
        print(f"Lakehouse Max Date: {max_date}")
    except Exception as e:
        print(f"Error querying lakehouse: {e}")
        sys.exit(1)
        
    # 3. Alert if stale
    if max_date < target_date:
        print(f"ALERT: Data is stale! Expected {target_date}, found {max_date}.")
        # In a real environment, this might trigger PagerDuty or fail the Cloud Run Job (which alerts)
        sys.exit(1)
    
    print("Data is fresh. No alert.")
    sys.exit(0)

if __name__ == "__main__":
    main()
