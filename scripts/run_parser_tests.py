import asyncio
import pandas as pd
from datetime import date
from indiquant.config.settings import IndiQuantSettings
from indiquant.store.lakehouse import Lakehouse
from indiquant.ingest.sources.nse_participant_oi import ParticipantOiSource
from indiquant.ingest.sources.bulk_block_deals import BulkBlockDealsSource

async def main():
    lh = Lakehouse(IndiQuantSettings())
    start_date = date(2024, 1, 1)
    end_date = date(2024, 1, 31)
    dates = pd.date_range(start_date, end_date, freq='B').date
    
    sources = [ParticipantOiSource(lh), BulkBlockDealsSource(lh)]
    results = {}
    
    for source in sources:
        success_count = 0
        total_rows = 0
        gaps = []
        for dt in dates:
            try:
                raw = source.fetch(dt)
                if raw and len(raw.body) > 0:
                    df = source._parse(raw)
                    if df.height > 0:
                        df = source._promote_transform(df)
                        lh.write_silver(source.silver_table, df, dt.year)
                        success_count += 1
                        total_rows += df.height
                    else:
                        gaps.append(f"{dt} (Empty DataFrame)")
                else:
                    gaps.append(f"{dt} (Empty Body)")
            except Exception as e:
                gaps.append(f"{dt} (Error: {e})")
        results[source.name] = {"success": success_count, "total_rows": total_rows, "gaps": len(gaps), "sample_gaps": gaps[:3]}

    print("\n=== COVERAGE REPORT ===")
    for k, v in results.items():
        print(f"{k}: Successful Days: {v['success']} / {len(dates)} | Total Rows: {v['total_rows']} | Gaps: {v['gaps']} | Sample Gaps: {v['sample_gaps']}")

asyncio.run(main())
