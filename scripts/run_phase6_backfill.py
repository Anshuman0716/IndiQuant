import asyncio
import pandas as pd
from datetime import date
import sys

from indiquant.config.settings import IndiQuantSettings
from indiquant.store.lakehouse import Lakehouse
from indiquant.ingest.sources.fno_ban import FnoBanSource
from indiquant.ingest.sources.mto_delivery import MtoDeliverySource
from indiquant.ingest.sources.bulk_block_deals import BulkBlockDealsSource
from indiquant.ingest.sources.fii_dii import FiiDiiSource
from indiquant.ingest.sources.nse_participant_oi import ParticipantOiSource

async def main():
    settings = IndiQuantSettings()
    lakehouse = Lakehouse(settings)
    
    # 1 Month backfill to quickly prove historical coverage
    start_date = date(2024, 1, 1)
    end_date = date(2024, 1, 31)
    dates = pd.date_range(start_date, end_date, freq='B').date
    
    sources = [
        FnoBanSource(lakehouse),
        MtoDeliverySource(lakehouse),
        BulkBlockDealsSource(lakehouse),
        FiiDiiSource(lakehouse),
        ParticipantOiSource(lakehouse)
    ]
    
    results = {}
    
    # Limit parallelism to avoid hammering NSE and getting IP blocked
    # We will just run them sequentially per source, parallel by date
    for source in sources:
        print(f"\n--- Backfilling {source.name} ---")
        success_count = 0
        total_rows = 0
        gaps = []
        
        for dt in dates:
            print(f"Fetching {dt}...", end="\r")
            try:
                # Bypass runner queue for raw fetch to collect custom stats easily
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
                if "404" in str(e) or "Not Found" in str(e):
                    gaps.append(f"{dt} (404/Holiday)")
                else:
                    gaps.append(f"{dt} (Error: {e})")
                    
        results[source.name] = {
            "success_days": success_count,
            "total_rows": total_rows,
            "gaps": len(gaps),
            "sample_gaps": gaps[:5]
        }
        print(f"Done {source.name}: {success_count}/{len(dates)} days, {total_rows} rows.")

    print("\n\n=== COVERAGE REPORT ===")
    for k, v in results.items():
        print(f"{k}:")
        print(f"  Successful Days: {v['success_days']} / {len(dates)}")
        print(f"  Total Rows Ingested: {v['total_rows']}")
        print(f"  Missing/Blocked/Holidays: {v['gaps']} days")
        if v['gaps'] > 0:
            print(f"  Sample gaps: {v['sample_gaps']}")

if __name__ == "__main__":
    asyncio.run(main())
