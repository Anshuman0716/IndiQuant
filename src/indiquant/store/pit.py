from datetime import date

import duckdb
import pandas as pd
import structlog

from indiquant.store.lakehouse import Lakehouse

logger = structlog.get_logger(__name__)


def as_known_on(
    lakehouse: Lakehouse,
    table: str,
    asof: date,
    isin: str | None = None,
) -> pd.DataFrame:
    """Return the latest row per ISIN where knowledge_date <= asof.

    This function enforces AGENTS.md Rule #1 (POINT-IN-TIME). It is the
    ONLY sanctioned way to access fundamental, shareholding, or any
    knowledge-date-gated data.

    The query:
        1. Filters to rows where knowledge_date <= asof
        2. Partitions by ISIN
        3. Ranks by knowledge_date DESC within each ISIN
        4. Returns only rank-1 rows (the most recent known data)

    Args:
        lakehouse: Lakehouse instance.
        table: Silver table name (e.g. "fundamentals").
        asof: The point-in-time date. Only data known on or before this
              date is visible.
        isin: Optional ISIN filter. If None, returns all ISINs.

    Returns:
        pandas DataFrame with the latest known row per ISIN.
    """
    logger.debug(
        "executing_pit_query",
        table=table,
        asof=asof.isoformat(),
        isin=isin,
    )

    table_path = (lakehouse.silver_dir / table / "**/*.parquet").as_posix()

    # We use union_by_name=true to handle schema evolution cleanly
    query = f"""
    WITH ranked AS (
        SELECT *,
            ROW_NUMBER() OVER (
                PARTITION BY isin
                ORDER BY knowledge_date DESC
            ) AS _rn
        FROM read_parquet(
            '{table_path}',
            hive_partitioning = true,
            union_by_name = true
        )
        WHERE knowledge_date <= $asof
          AND ($isin IS NULL OR isin = $isin)
    )
    SELECT * EXCLUDE (_rn)
    FROM ranked
    WHERE _rn = 1
    """

    try:
        with lakehouse.connection() as cur:
            df = cur.execute(query, {"asof": asof.isoformat(), "isin": isin}).df()
    except duckdb.IOException:
        logger.warning(
            "pit_query_no_files",
            table=table,
            asof=asof.isoformat(),
            isin=isin,
        )
        return pd.DataFrame()

    if df.empty:
        logger.warning(
            "pit_query_empty",
            table=table,
            asof=asof.isoformat(),
            isin=isin,
            msg="Table may legitimately have no data for this ISIN/date.",
        )
    else:
        logger.debug(
            "pit_query_complete",
            table=table,
            asof=asof.isoformat(),
            isin=isin,
            rows=len(df),
        )

    return df


def index_constituents(
    lakehouse: Lakehouse,
    index_name: str,
    asof: date,
) -> pd.DataFrame:
    """Return the ISINs constituting an index on a specific date.

    Enforces interval point-in-time constraints.
    Interval bounds: valid_from <= asof < valid_to.

    Args:
        lakehouse: Lakehouse instance.
        index_name: Index name (e.g. 'NIFTY 500').
        asof: The point-in-time date.

    Returns:
        List of ISINs.
    """
    logger.debug(
        "executing_index_constituents_query",
        index=index_name,
        asof=asof.isoformat(),
    )

    table_path = (lakehouse.silver_dir / "index_membership" / "**/*.parquet").as_posix()

    query = f"""
    SELECT DISTINCT isin
    FROM read_parquet(
        '{table_path}',
        hive_partitioning = true,
        union_by_name = true
    )
    WHERE index_name = $index
      AND valid_from <= $asof
      AND (valid_to IS NULL OR valid_to > $asof)
      AND isin IS NOT NULL
    """

    try:
        with lakehouse.connection() as cur:
            df = cur.execute(query, {"index": index_name, "asof": asof.isoformat()}).df()
            return df
    except duckdb.IOException:
        return pd.DataFrame()


def is_index_member(
    lakehouse: Lakehouse,
    isin: str,
    index_name: str,
    asof: date,
) -> bool:
    """Check if an ISIN was part of an index on a specific date.

    Args:
        lakehouse: Lakehouse instance.
        isin: The ISIN to check.
        index_name: Index name.
        asof: The point-in-time date.

    Returns:
        True if the ISIN was a member on the given date, False otherwise.
    """
    table_path = (lakehouse.silver_dir / "index_membership" / "**/*.parquet").as_posix()

    query = f"""
    SELECT 1
    FROM read_parquet(
        '{table_path}',
        hive_partitioning = true,
        union_by_name = true
    )
    WHERE index_name = $index
      AND isin = $isin
      AND valid_from <= $asof
      AND (valid_to IS NULL OR valid_to > $asof)
    LIMIT 1
    """

    try:
        with lakehouse.connection() as cur:
            df = cur.execute(
                query, {"index": index_name, "isin": isin, "asof": asof.isoformat()}
            ).df()
            return not df.empty
    except duckdb.IOException:
        return False


def get_adjusted_prices(
    lakehouse: Lakehouse,
    isin: str,
    start_date: date,
    end_date: date,
    asof: date,
) -> pd.DataFrame:
    """Return point-in-time adjusted prices for an ISIN.
    
    Prices are backward-adjusted for splits and bonuses that have an 
    ex_date <= asof. This ensures no lookahead bias in returns.
    
    Args:
        lakehouse: Lakehouse instance.
        isin: The ISIN to fetch prices for.
        start_date: History start date.
        end_date: History end date.
        asof: The point-in-time knowledge date. Only corporate actions
              on or before this date are applied.
              
    Returns:
        DataFrame with date, isin, close, volume (adjusted).
    """
    logger.debug(
        "executing_pit_price_adjustment",
        isin=isin,
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
        asof=asof.isoformat(),
    )
    
    eq_path = (lakehouse.silver_dir / "equity_daily" / "**/*.parquet").as_posix()
    ca_path = (lakehouse.silver_dir / "corporate_actions" / "**/*.parquet").as_posix()
    chain_path = (lakehouse.silver_dir / "isin_chain" / "**/*.parquet").as_posix()
    
    query = f"""
    WITH target_sec AS (
        SELECT DISTINCT security_id, symbol
        FROM read_parquet('{chain_path}')
        WHERE security_id = (
            SELECT security_id 
            FROM read_parquet('{chain_path}') 
            WHERE isin = $isin 
            LIMIT 1
        )
    ),
    raw_prices AS (
        SELECT p.date, p.isin, p.open, p.high, p.low, p.close, p.prev_close, p.volume
        FROM read_parquet(
            '{eq_path}',
            hive_partitioning = true,
            union_by_name = true
        ) p
        JOIN target_sec ts ON p.symbol = ts.symbol
        WHERE p.date >= $start_date 
          AND p.date <= $end_date
    ),
    valid_cas AS (
        SELECT c.ex_date, c.action_type, c.ratio_from, c.ratio_to
        FROM read_parquet('{ca_path}') c
        JOIN target_sec ts ON c.symbol = ts.symbol
        WHERE c.ex_date <= $asof
          AND c.ex_date > $start_date
          AND c.action_type IN ('split', 'bonus')
    ),
    cum_factors AS (
        -- Split and Bonus Backward Adjustment Logic:
        -- 
        -- 1. Splits (action_type='split'): NSE stores splits as ratio_from (new shares) : ratio_to (old shares).
        --    e.g., A 5-for-1 split (1 old share becomes 5 new shares) is stored as ratio_from=5, ratio_to=1.
        --    The price multiplier is ratio_to / ratio_from (e.g. 1/5 = 0.2).
        --    The volume multiplier is ratio_from / ratio_to (e.g. 5/1 = 5.0).
        -- 
        -- 2. Bonuses (action_type='bonus'): NSE stores bonuses as ratio_from (new free shares) : ratio_to (existing shares held).
        --    e.g., A 1:2 bonus (1 new share for every 2 held) is stored as ratio_from=1, ratio_to=2.
        --    Total shares become ratio_from + ratio_to (e.g. 1 + 2 = 3).
        --    The price multiplier is ratio_to / (ratio_from + ratio_to) (e.g. 2/3 = 0.666).
        --    The volume multiplier is (ratio_from + ratio_to) / ratio_to (e.g. 3/2 = 1.5).
        SELECT 
            ex_date,
            CASE 
                WHEN action_type = 'split' THEN ratio_to / ratio_from
                WHEN action_type = 'bonus' THEN ratio_to / (ratio_from + ratio_to)
                ELSE 1.0 
            END as adj_factor
        FROM valid_cas
    ),
    date_factors AS (
        SELECT 
            p.date,
            EXP(SUM(LN(COALESCE(c.adj_factor, 1.0)))) as cumulative_adj
        FROM raw_prices p
        LEFT JOIN cum_factors c ON p.date < c.ex_date
        GROUP BY p.date
    )
    SELECT 
        r.date, 
        r.isin, 
        r.open * COALESCE(f.cumulative_adj, 1.0) AS open,
        r.high * COALESCE(f.cumulative_adj, 1.0) AS high,
        r.low * COALESCE(f.cumulative_adj, 1.0) AS low,
        r.close * COALESCE(f.cumulative_adj, 1.0) AS close,
        r.prev_close * COALESCE(f.cumulative_adj, 1.0) AS prev_close,
        r.volume / COALESCE(f.cumulative_adj, 1.0) AS volume
    FROM raw_prices r
    LEFT JOIN date_factors f ON r.date = f.date
    ORDER BY r.date
    """
    
    try:
        with lakehouse.connection() as cur:
            df = cur.execute(
                query, 
                {
                    "isin": isin, 
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                    "asof": asof.isoformat()
                }
            ).df()
            # Handle the case where df is completely empty (e.g., IPO after start_date)
            # or completely NaN (e.g., no prices found).
            return df
    except duckdb.IOException:
        return pd.DataFrame()


def get_fo_contracts(
    lakehouse: Lakehouse,
    isin: str,
    start_date: date,
    end_date: date,
    asof: date,
) -> pd.DataFrame:
    """Return point-in-time derivatives contracts for an ISIN.
    
    This resolves the provided ISIN to its underlying continuous security_id,
    and then fetches all F&O rows for any symbol historically associated 
    with that security_id within the requested date range, safely bridging 
    symbol changes.
    
    Args:
        lakehouse: Lakehouse instance.
        isin: The ISIN to fetch contracts for.
        start_date: History start date.
        end_date: History end date.
        asof: The point-in-time knowledge date (currently only limits 
              isin_chain resolution bounds).
              
    Returns:
        DataFrame with F&O rows.
    """
    logger.debug(
        "executing_pit_fo_contracts",
        isin=isin,
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
        asof=asof.isoformat(),
    )
    
    fo_path = (lakehouse.silver_dir / "derivatives" / "**/*.parquet").as_posix()
    chain_path = (lakehouse.silver_dir / "isin_chain" / "**/*.parquet").as_posix()
    
    query = f"""
    WITH target_sec AS (
        SELECT DISTINCT security_id, symbol
        FROM read_parquet('{chain_path}')
        WHERE security_id = (
            SELECT security_id 
            FROM read_parquet('{chain_path}') 
            WHERE isin = $isin 
              AND valid_from <= $asof
              AND (valid_to IS NULL OR valid_to > $asof)
            LIMIT 1
        )
    )
    SELECT d.*
    FROM read_parquet(
        '{fo_path}',
        hive_partitioning = true,
        union_by_name = true
    ) d
    JOIN target_sec ts ON d.symbol = ts.symbol
    WHERE d.date >= $start_date 
      AND d.date <= $end_date
    ORDER BY d.date, d.expiry, d.strike, d.option_type
    """
    
    try:
        with lakehouse.connection() as cur:
            df = cur.execute(
                query, 
                {
                    "isin": isin, 
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                    "asof": asof.isoformat()
                }
            ).df()
            return df
    except duckdb.IOException:
        return pd.DataFrame()
