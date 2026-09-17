"""Base classes and registry for the factor library.

All fundamental data access must go through FactorContext to ensure
point-in-time correctness. No direct access to lakehouse tables is permitted
for factors.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Literal

import duckdb
import pandas as pd
import structlog

from indiquant.store.lakehouse import Lakehouse

logger = structlog.get_logger(__name__)

# Allowed pillars in the Tapetide Score
Pillar = Literal["QUALITY", "VALUATION", "GROWTH", "HEALTH", "MOMENTUM", "OWNERSHIP", "MICROSTRUCTURE"]


@dataclass
class FactorMetadata:
    """Introspectable metadata for a factor. Designed for MCP exposure."""
    id: str
    pillar: Pillar
    direction: int  # +1 if high is good, -1 if low is good
    min_history_days: int
    required_tables: list[str]
    unit: str
    func: Callable[..., pd.Series]


class FactorRegistry:
    """Central registry of all available factors."""

    def __init__(self) -> None:
        self._factors: dict[str, FactorMetadata] = {}

    def register(
        self,
        id: str,
        pillar: Pillar,
        direction: int,
        min_history_days: int,
        required_tables: list[str],
        unit: str,
    ) -> Callable[[Callable[..., pd.Series]], Callable[..., pd.Series]]:
        """Decorator to register a factor function."""
        def decorator(func: Callable[..., pd.Series]) -> Callable[..., pd.Series]:
            if id in self._factors:
                raise ValueError(f"Factor {id} already registered.")
            
            self._factors[id] = FactorMetadata(
                id=id,
                pillar=pillar,
                direction=direction,
                min_history_days=min_history_days,
                required_tables=required_tables,
                unit=unit,
                func=func,
            )
            return func
        return decorator

    def list_factors(self) -> list[FactorMetadata]:
        """Return all registered factors."""
        return list(self._factors.values())

    def get_factor(self, id: str) -> FactorMetadata:
        if id not in self._factors:
            raise KeyError(f"Factor {id} not found.")
        return self._factors[id]


# Global registry
registry = FactorRegistry()
factor = registry.register


class FactorContext:
    """Execution context providing safe data access for factors.

    Prevents lookahead bias by enforcing point-in-time data resolution.
    All price and fundamental data is filtered to only what was known
    on or before the requested date.
    """

    def __init__(self, lakehouse: Lakehouse) -> None:
        self.lakehouse = lakehouse
        self._prices_cache: dict[str, pd.DataFrame] = {}

    def get_prices(self, asof: date, lookback_days: int) -> pd.DataFrame:
        """Fetch equity prices from the lakehouse up to the asof date.

        Prices are known at the close of the trading day, so
        ``date <= asof`` is the correct filter (no lookahead).

        Args:
            asof: Only prices on or before this date are returned.
            lookback_days: Calendar days to look back from *asof*.
                The query fetches rows where
                ``date >= asof - lookback_days`` AND ``date <= asof``.

        Returns:
            DataFrame with columns: isin, date, open, high, low, close,
            prev_close, volume.  Sorted by (isin, date).
        """
        cache_key = f"{asof.isoformat()}_{lookback_days}"
        if cache_key in self._prices_cache:
            return self._prices_cache[cache_key]

        start_date = asof - timedelta(days=lookback_days)
        table_path = (
            self.lakehouse.silver_dir / "equity_daily" / "**/*.parquet"
        ).as_posix()

        query = f"""
        SELECT
            isin,
            date,
            open,
            high,
            low,
            close,
            prev_close,
            volume
        FROM read_parquet(
            '{table_path}',
            hive_partitioning = true,
            union_by_name = true
        )
        WHERE date >= $start AND date <= $asof
        ORDER BY isin, date
        """

        try:
            with self.lakehouse.connection() as cur:
                df = cur.execute(
                    query,
                    {"start": start_date.isoformat(), "asof": asof.isoformat()},
                ).df()
        except duckdb.IOException:
            logger.warning("get_prices_no_data", asof=asof.isoformat())
            df = pd.DataFrame()

        logger.debug(
            "get_prices_complete",
            asof=asof.isoformat(),
            lookback_days=lookback_days,
            rows=len(df),
            isins=df["isin"].nunique() if not df.empty else 0,
        )

        self._prices_cache[cache_key] = df
        return df

    def get_fundamentals(
        self,
        asof: date,
        columns: list[str],
        max_staleness_days: int = 200,
        table: str = "fundamentals_smoke",
    ) -> pd.DataFrame:
        """Fetch fundamental data as known exactly on the asof date.

        STRICT REQUIREMENT: This method routes through
        ``store.pit.as_known_on()`` to enforce point-in-time correctness.

        Missing Data Policy (Staleness):
            - Fundamentals are forward-filled up to *max_staleness_days*
              (default 200 days, approx 2 quarters) past their
              ``knowledge_date``.
            - If data is older than *max_staleness_days*, it is treated
              as missing.
            - The returned DataFrame includes ``is_stale`` and
              ``is_missing`` boolean columns for full visibility.
              Callers should inspect these rather than silently trusting
              all rows.

        Args:
            asof: Point-in-time date.  Only data with
                ``knowledge_date <= asof`` is visible.
            columns: Fundamental column names to return
                (e.g. ``["revenue", "pat"]``).
            max_staleness_days: Maximum calendar days a
                ``knowledge_date`` may lag behind *asof* before the
                row is flagged as stale.
            table: Silver table to query.  Defaults to
                ``"fundamentals_smoke"`` (the yfinance smoke-test
                table).

        Returns:
            DataFrame with columns: isin, quarter_end,
            knowledge_date, <requested columns>, is_stale, is_missing.
        """
        from indiquant.store.pit import as_known_on

        df = as_known_on(self.lakehouse, table, asof)

        if df.empty:
            logger.warning(
                "get_fundamentals_empty",
                asof=asof.isoformat(),
                table=table,
            )
            return pd.DataFrame()

        # --- staleness flags ---------------------------------------------------
        # knowledge_date may be a string; coerce to datetime for arithmetic.
        kd = pd.to_datetime(df["knowledge_date"])
        days_stale = (pd.Timestamp(asof) - kd).dt.days

        df["is_stale"] = days_stale > max_staleness_days
        df["is_missing"] = df["is_stale"]  # beyond staleness = treated as missing

        stale_count = int(df["is_stale"].sum())
        if stale_count > 0:
            logger.info(
                "fundamentals_staleness",
                asof=asof.isoformat(),
                table=table,
                total=len(df),
                stale=stale_count,
            )

        # --- select requested columns -----------------------------------------
        keep = ["isin"]
        if "quarter_end" in df.columns:
            keep.append("quarter_end")
        keep.append("knowledge_date")
        for col in columns:
            if col in df.columns:
                keep.append(col)
        keep += ["is_stale", "is_missing"]

        return df[keep]

    def get_fundamentals_history(
        self,
        asof: date,
        columns: list[str],
        lookback_years: int = 5,
        max_staleness_days: int = 200,
        table: str = "fundamentals_smoke",
    ) -> pd.DataFrame:
        """Fetch a time-series of fundamental data up to the asof date.
        
        Useful for calculating TTM (trailing twelve months), CAGRs, and 
        historical stability metrics.
        
        Args:
            asof: Point-in-time date.
            columns: Fundamental columns to return.
            lookback_years: How far back to fetch data.
            max_staleness_days: Drop rows where knowledge_date is too old.
            
        Returns:
            DataFrame sorted by ['isin', 'quarter_end'] containing all valid
            historical filings within the lookback window.
        """
        table_path = (self.lakehouse.silver_dir / table / "**/*.parquet").as_posix()
        start_date = asof - timedelta(days=lookback_years * 365)
        
        # We must select quarter_end for sorting/grouping
        select_cols = ["isin", "quarter_end", "knowledge_date"] + columns
        select_str = ", ".join(select_cols)
        
        query = f"""
        SELECT {select_str}
        FROM read_parquet(
            '{table_path}',
            hive_partitioning = true,
            union_by_name = true
        )
        WHERE knowledge_date <= $asof
          AND knowledge_date >= $start
        ORDER BY isin, quarter_end
        """
        
        try:
            with self.lakehouse.connection() as cur:
                df = cur.execute(
                    query, 
                    {"asof": asof.isoformat(), "start": start_date.isoformat()}
                ).df()
        except duckdb.IOException:
            logger.warning("get_fundamentals_history_no_data", asof=asof.isoformat())
            return pd.DataFrame()
            
        if df.empty:
            return df
            
        # Enforce staleness filter (unlike get_fundamentals which returns flags, 
        # history drops stale rows outright as they shouldn't be used in rolling sums)
        kd = pd.to_datetime(df["knowledge_date"])
        days_stale = (pd.Timestamp(asof) - kd).dt.days
        df = df[days_stale <= max_staleness_days].copy()
        
        return df.sort_values(["isin", "quarter_end"])

    def get_sectors(self, isins: pd.Series) -> pd.Series:
        """Fetch sector mappings for a given series of ISINs.
        
        Args:
            isins: A pandas Series containing ISINs.
            
        Returns:
            A pandas Series of the same length containing the sector strings.
            Unknown ISINs will have a sector of "Unknown".
        """
        mapping_path = (self.lakehouse.meta_dir / "sector_mapping" / "*.parquet").as_posix()
        
        try:
            with self.lakehouse.connection() as cur:
                mapping = cur.execute(
                    f"SELECT isin, sector FROM read_parquet('{mapping_path}')"
                ).df()
        except duckdb.IOException:
            logger.warning("sector_mapping_not_found")
            return pd.Series("Unknown", index=isins.index)
            
        # Create a dict for fast mapping
        sector_dict = dict(zip(mapping["isin"], mapping["sector"]))
        
        # Map the input series
        return isins.map(sector_dict).fillna("Unknown")
