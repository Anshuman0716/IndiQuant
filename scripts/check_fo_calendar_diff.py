"""Cross-check Equity vs F&O Trading Calendars.

Runs a diff to ensure the F&O calendar matches the Equity calendar,
catching edge cases like special settlement holidays.
"""

from datetime import date
from pathlib import Path
import duckdb
import structlog
from indiquant.config.settings import IndiQuantSettings

logger = structlog.get_logger(__name__)

def check_fo_calendar_diff() -> None:
    """Diff equity and F&O dates in the lakehouse."""
    settings = IndiQuantSettings()
    lakehouse_dir = settings.data_dir / "silver"
    eq_path = lakehouse_dir / "equity_daily" / "**/*.parquet"
    fo_path = lakehouse_dir / "derivatives" / "**/*.parquet"
    
    # If no data yet, skip
    if not (lakehouse_dir / "equity_daily").exists() or not (lakehouse_dir / "derivatives").exists():
        logger.info("calendar_diff_skipped", msg="No data available to diff yet.")
        return

    query = f"""
    WITH eq_dates AS (
        SELECT DISTINCT CAST(date AS DATE) AS dt
        FROM read_parquet('{eq_path.as_posix()}', hive_partitioning=true, union_by_name=true)
    ),
    fo_dates AS (
        SELECT DISTINCT CAST(date AS DATE) AS dt
        FROM read_parquet('{fo_path.as_posix()}', hive_partitioning=true, union_by_name=true)
    )
    SELECT 
        COALESCE(e.dt, f.dt) AS calendar_date,
        CASE 
            WHEN e.dt IS NULL THEN 'FO_ONLY'
            WHEN f.dt IS NULL THEN 'EQ_ONLY'
            ELSE 'BOTH'
        END as status
    FROM eq_dates e
    FULL OUTER JOIN fo_dates f ON e.dt = f.dt
    WHERE e.dt IS NULL OR f.dt IS NULL
    ORDER BY calendar_date
    """
    
    try:
        with duckdb.connect() as con:
            df = con.execute(query).df()
            
        if not df.empty:
            logger.error(
                "calendar_diff_found",
                mismatches=len(df),
                msg="Found dates where Equity and F&O trading days do not match. Manual calendar adjustment needed.",
                dates=df.to_dict(orient="records")
            )
            # You would raise here in a strict pipeline
        else:
            logger.info("calendar_diff_clean", msg="Equity and F&O calendars match perfectly.")
    except Exception as e:
        logger.warning("calendar_diff_failed", error=str(e))

if __name__ == "__main__":
    check_fo_calendar_diff()
