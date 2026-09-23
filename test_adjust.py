from datetime import date
from indiquant.config.settings import IndiQuantSettings
from indiquant.store.lakehouse import Lakehouse
from indiquant.factors.base import FactorContext
import pandas as pd
import duckdb

lh = Lakehouse(IndiQuantSettings())
ctx = FactorContext(lh)

asof = date(2016, 9, 15)
df = ctx.get_prices(asof, 15)
baj = df[df['isin'] == 'INE296A01016']

raw_query = f"""
SELECT date, close as raw_close
FROM read_parquet('{lh.silver_dir}/equity_daily/**/*.parquet')
WHERE isin = 'INE296A01016' AND date >= '2016-09-01' AND date <= '2016-09-15'
ORDER BY date
"""
raw_df = duckdb.query(raw_query).df()
raw_df['date'] = pd.to_datetime(raw_df['date']).dt.date
baj['date'] = pd.to_datetime(baj['date']).dt.date

merged = pd.merge(raw_df, baj[['date', 'close', 'adj_tot_close']], on='date', how='inner')
merged = merged.rename(columns={'close': 'adj_close'})
print(merged.to_string())
