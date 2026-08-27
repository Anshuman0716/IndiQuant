"""Symbol-ISIN mapping table derived from bhavcopy data.

AGENTS.md Rule #3: ISIN is the primary key. Symbol is a display
attribute resolved through a validity-dated mapping table.

This module builds and queries the (symbol, isin, first_seen, last_seen)
table. It detects:
  - Symbol renames: same ISIN, different symbol across dates
  - Symbol reuse: same symbol, different ISIN across dates
"""

from __future__ import annotations

from datetime import date

import polars as pl
import structlog

logger = structlog.get_logger(__name__)


def build_symbol_isin_map(equity_daily: pl.DataFrame) -> pl.DataFrame:
    """Build symbol-ISIN mapping from bhavcopy data.

    Args:
        equity_daily: Silver equity_daily table with columns
            isin, symbol, date.

    Returns:
        DataFrame with columns:
            isin, symbol, first_seen, last_seen
        One row per (isin, symbol) pair. A rename shows up as
        two rows for the same ISIN with different symbols.
    """
    if len(equity_daily) == 0:
        return pl.DataFrame(
            schema={
                "isin": pl.Utf8,
                "symbol": pl.Utf8,
                "first_seen": pl.Utf8,
                "last_seen": pl.Utf8,
            }
        )

    mapping = (
        equity_daily.select(["isin", "symbol", "date"])
        .group_by(["isin", "symbol"])
        .agg(
            pl.col("date").min().alias("first_seen"),
            pl.col("date").max().alias("last_seen"),
        )
        .sort(["isin", "first_seen"])
    )

    # Log symbol renames (same ISIN, multiple symbols)
    isin_counts = mapping.group_by("isin").len()
    renames = isin_counts.filter(pl.col("len") > 1)
    if len(renames) > 0:
        logger.info(
            "symbol_renames_detected",
            count=len(renames),
            msg=(
                f"{len(renames)} ISINs have had symbol changes. "
                "This is expected (e.g. ONGC -> OIL_NGAS)."
            ),
        )

    # Log symbol reuse (same symbol, multiple ISINs)
    sym_counts = mapping.group_by("symbol").len()
    reuses = sym_counts.filter(pl.col("len") > 1)
    if len(reuses) > 0:
        logger.warning(
            "symbol_reuse_detected",
            count=len(reuses),
            msg=(
                f"{len(reuses)} symbols map to multiple ISINs. "
                "Always join on ISIN, never on symbol."
            ),
        )

    return mapping


def resolve_isin(
    symbol: str,
    as_of: date,
    mapping: pl.DataFrame,
) -> str | None:
    """Resolve a symbol to its ISIN as of a given date.

    Args:
        symbol: Ticker symbol to resolve.
        as_of: Date for validity check.
        mapping: Output of build_symbol_isin_map().

    Returns:
        ISIN string, or None if not found.
    """
    as_of_str = as_of.isoformat()
    matches = mapping.filter(
        (pl.col("symbol") == symbol)
        & (pl.col("first_seen") <= as_of_str)
        & (pl.col("last_seen") >= as_of_str)
    )
    if len(matches) == 0:
        return None
    # Return the most recently seen ISIN for this symbol
    return str(matches.sort("last_seen", descending=True)["isin"][0])
