"""NSE corporate actions: splits, bonuses, dividends, rights.

Fetches from NSE's corporate actions API, parses the free-text `subject`
field to extract structured action types, and maps to ISIN via symbol.

knowledge_date = ex_date (the date the action takes effect on price).
"""

import re
from datetime import date, datetime

import polars as pl
import structlog

from indiquant.ingest.base import Source
from indiquant.ingest.models import RawPayload, ValidationIssue

logger = structlog.get_logger(__name__)

# NSE corporate actions API limits date range per request.
# We chunk into 3-month windows.
_CHUNK_MONTHS = 3


def _parse_subject(subject: str) -> dict[str, object]:
    """Extract structured action type from NSE's free-text subject field.

    NSE encodes action types (dividends, splits, bonuses, rights) as
    human-readable text. We use regex to extract structured data.

    Args:
        subject: Raw subject string from NSE API.

    Returns:
        Dict with keys: action_type, ratio_from, ratio_to, amount_per_share.
        Values are None for fields not applicable to the action type.
    """
    subject_lower = subject.lower().strip()

    # Split / Sub-Division: "Stock Split From Rs 10/- to Rs 2/-"
    split_match = re.search(
        r"(?:split|sub[- ]?division).*?"
        r"(?:rs\.?|inr|face\s+value)\s*(\d+(?:\.\d+)?)"
        r".*?to.*?"
        r"(?:rs\.?|inr|face\s+value)\s*(\d+(?:\.\d+)?)",
        subject_lower,
    )
    if split_match:
        return {
            "action_type": "split",
            "ratio_from": float(split_match.group(1)),
            "ratio_to": float(split_match.group(2)),
            "amount_per_share": None,
        }

    # Bonus: "Bonus 1:1" or "Bonus Issue 3:2"
    bonus_match = re.search(
        r"bonus.*?(\d+)\s*:\s*(\d+)",
        subject_lower,
    )
    if bonus_match:
        return {
            "action_type": "bonus",
            "ratio_from": float(bonus_match.group(1)),
            "ratio_to": float(bonus_match.group(2)),
            "amount_per_share": None,
        }

    # Dividend: "Dividend - Rs 10 Per Share" or "Final Dividend Rs.5.50/-"
    div_match = re.search(
        r"dividend.*?(?:rs\.?|inr)\s*(\d+(?:\.\d+)?)",
        subject_lower,
    )
    if div_match:
        return {
            "action_type": "dividend",
            "ratio_from": None,
            "ratio_to": None,
            "amount_per_share": float(div_match.group(1)),
        }

    # Rights: "Rights Issue 1:5 @ Rs 100"
    rights_match = re.search(
        r"rights.*?(\d+)\s*:\s*(\d+)",
        subject_lower,
    )
    if rights_match:
        return {
            "action_type": "rights",
            "ratio_from": float(rights_match.group(1)),
            "ratio_to": float(rights_match.group(2)),
            "amount_per_share": None,
        }

    return {
        "action_type": "other",
        "ratio_from": None,
        "ratio_to": None,
        "amount_per_share": None,
    }


def _parse_nse_date(date_str: str) -> str | None:
    """Parse NSE date formats (DD-Mon-YYYY or DD-MM-YYYY) to ISO format."""
    date_str = date_str.strip()
    if date_str in ("-", "", "NA"):
        return None

    for fmt in ("%d-%b-%Y", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(date_str, fmt).date().isoformat()
        except ValueError:
            continue
    return None


class CorporateActionsSource(Source):
    """NSE corporate actions: splits, bonuses, dividends, rights.

    Uses the NSE corporate actions API which returns JSON.
    Date range is chunked into 3-month windows to avoid timeouts.
    """

    name = "nse_corporate_actions"
    prime_url = "https://www.nseindia.com"
    silver_table = "corporate_actions"
    rate_limit_rps = 1.0
    min_rows = 1  # Some days genuinely have no corporate actions

    # We don't have a pandera schema for this yet — use a minimal one
    # TODO: Define CorporateActionsSchema in schemas.py
    class _MinimalSchema:
        """Placeholder until full schema is defined."""

        @classmethod
        def validate(cls, df: pl.DataFrame, lazy: bool = False) -> pl.DataFrame:
            return df

    schema = _MinimalSchema  # type: ignore[assignment]

    def _build_url(self, target_date: date) -> str:
        """Build NSE corporate actions API URL.

        The API takes a date range, so we query a single day at a time
        to align with the Source.run(target_date) contract.
        """
        ds = target_date.strftime("%d-%m-%Y")
        return (
            f"https://www.nseindia.com/api/corporates-corporateActions"
            f"?index=equities&from_date={ds}&to_date={ds}"
        )

    def _parse(self, raw: RawPayload) -> pl.DataFrame:
        """Parse JSON response into structured DataFrame."""
        import json

        try:
            data = json.loads(raw.body)
        except json.JSONDecodeError:
            # Might be CSV format or error page
            return pl.DataFrame()

        if not isinstance(data, list) or len(data) == 0:
            return pl.DataFrame()

        records: list[dict[str, object]] = []
        for item in data:
            subject = item.get("subject", "")
            parsed = _parse_subject(subject)

            ex_date_str = _parse_nse_date(item.get("exDate", "-"))
            if ex_date_str is None:
                continue

            records.append(
                {
                    "symbol": item.get("symbol", "").strip(),
                    "series": item.get("series", "EQ").strip(),
                    "isin": "",  # Will be resolved via symbol_isin_map
                    "date": raw.date.isoformat(),
                    "ex_date": ex_date_str,
                    "record_date": _parse_nse_date(item.get("recDate", "-")),
                    "broadcast_date": _parse_nse_date(item.get("caBroadcastDate", "-")),
                    "subject": subject,
                    "action_type": parsed["action_type"],
                    "ratio_from": parsed["ratio_from"],
                    "ratio_to": parsed["ratio_to"],
                    "amount_per_share": parsed["amount_per_share"],
                    "face_value": float(item.get("faceVal", 0) or 0),
                }
            )

        if not records:
            return pl.DataFrame()

        parsed_df = pl.DataFrame(records)
        import duckdb
        try:
            with self.lakehouse.connection() as cur:
                eq_path = (self.lakehouse.silver_dir / "equity_daily" / "**/*.parquet").as_posix()
                mapping_query = f"""
                WITH mapping AS (
                    SELECT isin, symbol, MIN(date) as first_seen, MAX(date) as last_seen
                    FROM read_parquet('{eq_path}', hive_partitioning = true, union_by_name = true)
                    GROUP BY isin, symbol
                )
                SELECT p.* EXCLUDE(isin), COALESCE(m.isin, '') AS isin
                FROM parsed_df p
                LEFT JOIN mapping m
                  ON p.symbol = m.symbol
                 AND p.ex_date >= m.first_seen
                 AND p.ex_date <= m.last_seen
                """
                mapped_df = cur.execute(mapping_query).pl()
                # Deduplicate if overlapping reuses
                return mapped_df.group_by(["symbol", "action_type", "ex_date", "subject"]).first()
        except duckdb.IOException:
            return parsed_df

    def _validate_rules(self, df: pl.DataFrame) -> list[ValidationIssue]:
        """Validate corporate action data."""
        issues: list[ValidationIssue] = []

        # Check that split ratios are positive
        if "ratio_from" in df.columns and "ratio_to" in df.columns:
            splits = df.filter(
                (pl.col("action_type") == "split")
                & ((pl.col("ratio_from") <= 0) | (pl.col("ratio_to") <= 0))
            )
            if len(splits) > 0:
                issues.append(
                    ValidationIssue(
                        severity="error",
                        column="ratio_from/ratio_to",
                        check_name="positive_split_ratio",
                        rows_affected=len(splits),
                        message=f"{len(splits)} splits have non-positive ratios",
                    )
                )

        return issues

    def _promote_transform(self, bronze: pl.DataFrame) -> pl.DataFrame:
        """Add knowledge_date = ex_date for PIT compliance."""
        if len(bronze) == 0:
            return bronze

        return bronze.with_columns(
            pl.col("ex_date").alias("knowledge_date"),
        )
