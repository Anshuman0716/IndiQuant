import asyncio
import pandas as pd
from datetime import date

from indiquant.config.settings import IndiQuantSettings
from indiquant.store.lakehouse import Lakehouse
from indiquant.ingest.sources.nse_fo_bhavcopy import FoBhavcopySource

async def main():
    settings = IndiQuantSettings()
    lakehouse = Lakehouse(settings)
    
    start_date = date(2024, 1, 1)
    end_date = date(2024, 1, 31)
    dates = pd.date_range(start_date, end_date, freq='B').date
    
    source = FoBhavcopySource(lakehouse)
    
    print(f"\n--- Backfilling {source.name} ---")
    success_count = 0
    total_rows = 0
    gaps = []
    
    for dt in dates:
        print(f"Fetching {dt}...", end="\r")
        try:
            raw = source.fetch(dt)
            if raw and len(raw.body) > 0:
                df = source._parse(raw)
                if df.height > 0:
                    df = source._promote_transform(df)
                    lakehouse.write_silver(source.silver_table, df, dt.year)
                    success_count += 1
                    total_rows += df.height
                else:
                    gaps.append(f"{dt} (Empty DataFrame)")
            else:
                gaps.append(f"{dt} (Empty Body)")
        except Exception as e:
            if "404" in str(e) or "Not Found" in str(e) or "403" in str(e):
                gaps.append(f"{dt} (Status/Holiday: {e})")
            else:
                gaps.append(f"{dt} (Error: {e})")
                
    print(f"Done {source.name}: {success_count}/{len(dates)} days, {total_rows} rows.    ")

    print("\n\n=== COVERAGE REPORT ===")
    print(f"{source.name}:")
    print(f"  Successful Days: {success_count} / {len(dates)}")
    print(f"  Total Rows Ingested: {total_rows}")
    print(f"  Missing/Blocked/Holidays: {len(gaps)} days")
    if len(gaps) > 0:
        print(f"  Sample gaps: {gaps[:10]}")

if __name__ == "__main__":
    asyncio.run(main())
