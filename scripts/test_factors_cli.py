import structlog
from datetime import date
from indiquant.factors.base import registry, FactorContext
from indiquant.factors import momentum, quality
from indiquant.config.settings import IndiQuantSettings
from indiquant.store.lakehouse import Lakehouse

structlog.configure()
logger = structlog.get_logger()

def test_factors():
    factors = registry.list_factors()
    print("Registered Factors:")
    for f in factors:
        print(f" - {f.id} (Pillar: {f.pillar}, Dir: {f.direction})")

    settings = IndiQuantSettings()
    lakehouse = Lakehouse(settings)
    
    ctx = FactorContext(lakehouse)
    
    # Try fetching prices
    dt = date(2024, 12, 31)
    print(f"\nFetching prices for {dt}...")
    prices = ctx.get_prices(dt, lookback_days=20)
    print(f"Prices shape: {prices.shape}")
    if len(prices) > 0:
        print(prices.head(2))

    # Try fetching fundamentals smoke
    print(f"\nFetching fundamentals for {dt}...")
    try:
        funds = ctx.get_fundamentals(dt, ["revenue", "pat"])
        print(f"Fundamentals shape: {funds.shape}")
        if len(funds) > 0:
            print(funds.head(2))
    except Exception as e:
        print(f"Fundamentals fetch failed: {e}")

if __name__ == "__main__":
    test_factors()
