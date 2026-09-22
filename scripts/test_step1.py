"""Step 1 verification: test FactorContext against live lakehouse data."""
from datetime import date
from indiquant.config.settings import IndiQuantSettings
from indiquant.store.lakehouse import Lakehouse
from indiquant.factors.base import FactorContext, registry
from indiquant.factors import momentum, quality

settings = IndiQuantSettings()
lakehouse = Lakehouse(settings)
ctx = FactorContext(lakehouse)

print("=" * 60)
print("TEST 1: get_prices()")
print("=" * 60)
prices = ctx.get_prices(asof=date(2024, 12, 31), lookback_days=300)
print(f"  Rows: {len(prices)}")
print(f"  ISINs: {prices['isin'].nunique()}")
print(f"  Columns: {list(prices.columns)}")
print(f"  Date range: {prices['date'].min()} to {prices['date'].max()}")
print(f"  Sample:")
print(prices.head(3).to_string(index=False))

print()
print("TEST 1b: get_prices() caching")
prices2 = ctx.get_prices(asof=date(2024, 12, 31), lookback_days=300)
print(f"  Cache hit (same object): {prices is prices2}")

print()
print("=" * 60)
print("TEST 2: get_fundamentals()")
print("=" * 60)
fundas = ctx.get_fundamentals(
    asof=date(2026, 8, 31),
    columns=["revenue", "pat", "total_assets", "current_liabilities", "interest", "tax"],
)
print(f"  Rows: {len(fundas)}")
print(f"  Columns: {list(fundas.columns)}")
if not fundas.empty:
    print(f"  Stale count: {fundas['is_stale'].sum()}")
    print(f"  Missing count: {fundas['is_missing'].sum()}")
    print(f"  Sample:")
    print(fundas.head(3).to_string(index=False))

print()
print("=" * 60)
print("TEST 3: Execute momentum_12_1 factor")
print("=" * 60)
try:
    mom = momentum.momentum_12_1(ctx, date(2024, 12, 31))
    print(f"  Result type: {type(mom).__name__}")
    print(f"  Non-NaN values: {mom.notna().sum()}")
    print(f"  Sample (top 5):")
    print(mom.dropna().sort_values(ascending=False).head(5))
except Exception as e:
    print(f"  FAILED: {e}")

print()
print("=" * 60)
print("TEST 4: Execute roce_ttm factor")
print("=" * 60)
try:
    roce = quality.roce_ttm(ctx, date(2026, 8, 31))
    print(f"  Result type: {type(roce).__name__}")
    print(f"  Non-NaN values: {roce.notna().sum()}")
    if roce.notna().sum() > 0:
        print(f"  Sample (top 5):")
        print(roce.dropna().sort_values(ascending=False).head(5))
except Exception as e:
    print(f"  FAILED: {e}")

print()
print("=" * 60)
print("ALL TESTS COMPLETE")
print("=" * 60)
