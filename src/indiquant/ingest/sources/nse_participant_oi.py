"""NSE participant-wise open interest data.

URL: nsearchives.nseindia.com/content/nsccl/fao_participant_oi_DDMMYYYY.csv
"""

import io
from datetime import date

import polars as pl

from indiquant.ingest.base import Source
from indiquant.ingest.models import RawPayload, ValidationIssue


class _MinimalSchema:
    """Placeholder until ParticipantOiSchema is extended."""

    @classmethod
    def validate(cls, df: pl.DataFrame, lazy: bool = False) -> pl.DataFrame:
        return df


class ParticipantOiSource(Source):
    """NSE Participant open interest source."""

    name = "nse_participant_oi"
    prime_url = "https://www.nseindia.com"
    silver_table = "participant_oi"
    min_rows = 1
    rate_limit_rps = 1.5
    schema = _MinimalSchema  # type: ignore[assignment]

    def _build_url(self, target_date: date) -> str:
        """Build URL for NSE participant OI."""
        date_str = target_date.strftime("%d%m%Y")
        return f"https://nsearchives.nseindia.com/content/nsccl/fao_participant_oi_{date_str}.csv"

    def _parse(self, raw: RawPayload) -> pl.DataFrame:
        """Parse the participant OI CSV."""
        text = raw.body.decode("utf-8", errors="replace")
        # The file has a junk title row, skip it.
        # Sometimes there's a blank line or tabs inside the columns.
        lines = text.split("\n")
        # Find the line that starts with Client Type
        header_idx = 0
        for i, line in enumerate(lines):
            if "Client Type" in line:
                header_idx = i
                break
        
        csv_data = "\n".join(lines[header_idx:])
        csv_data = csv_data.replace("\t", " ")
        
        df = pl.read_csv(
            io.StringIO(csv_data),
            infer_schema_length=0,
            ignore_errors=True,
        )
        if len(df) == 0:
            return df

        df = df.rename({col: col.strip() for col in df.columns})

        df = df.select(
            [
                pl.lit(raw.date.isoformat()).alias("date"),
                pl.col("Client Type").str.strip_chars().alias("client_type"),
                pl.col("Future Index Long").str.strip_chars().cast(pl.Int64).alias("fut_idx_long"),
                pl.col("Future Index Short")
                .str.strip_chars()
                .cast(pl.Int64)
                .alias("fut_idx_short"),
                pl.col("Future Stock Long").str.strip_chars().cast(pl.Int64).alias("fut_stk_long"),
                pl.col("Future Stock Short")
                .str.strip_chars()
                .cast(pl.Int64)
                .alias("fut_stk_short"),
                pl.col("Option Index Call Long")
                .str.strip_chars()
                .cast(pl.Int64)
                .alias("opt_idx_call_long"),
                pl.col("Option Index Put Long")
                .str.strip_chars()
                .cast(pl.Int64)
                .alias("opt_idx_put_long"),
                pl.col("Option Index Call Short")
                .str.strip_chars()
                .cast(pl.Int64)
                .alias("opt_idx_call_short"),
                pl.col("Option Index Put Short")
                .str.strip_chars()
                .cast(pl.Int64)
                .alias("opt_idx_put_short"),
                pl.col("Option Stock Call Long")
                .str.strip_chars()
                .cast(pl.Int64)
                .alias("opt_stk_call_long"),
                pl.col("Option Stock Put Long")
                .str.strip_chars()
                .cast(pl.Int64)
                .alias("opt_stk_put_long"),
                pl.col("Option Stock Call Short")
                .str.strip_chars()
                .cast(pl.Int64)
                .alias("opt_stk_call_short"),
                pl.col("Option Stock Put Short")
                .str.strip_chars()
                .cast(pl.Int64)
                .alias("opt_stk_put_short"),
                pl.col("Total Long Contracts").str.strip_chars().cast(pl.Int64).alias("total_long"),
                pl.col("Total Short Contracts")
                .str.strip_chars()
                .cast(pl.Int64)
                .alias("total_short"),
            ]
        )

        return df

    def _validate_rules(self, df: pl.DataFrame) -> list[ValidationIssue]:
        """Validate OI metrics."""
        issues: list[ValidationIssue] = []
        if len(df) == 0:
            return issues

        numeric_cols = [
            "fut_idx_long",
            "fut_idx_short",
            "fut_stk_long",
            "fut_stk_short",
            "opt_idx_call_long",
            "opt_idx_put_long",
            "opt_idx_call_short",
            "opt_idx_put_short",
            "opt_stk_call_long",
            "opt_stk_put_long",
            "opt_stk_call_short",
            "opt_stk_put_short",
            "total_long",
            "total_short",
        ]

        for col in numeric_cols:
            neg_rows = df.filter(pl.col(col) < 0)
            if len(neg_rows) > 0:
                issues.append(
                    ValidationIssue(
                        severity="error",
                        column=col,
                        check_name="non_negative_oi",
                        rows_affected=len(neg_rows),
                        message=f"{len(neg_rows)} rows have negative {col}",
                    )
                )

        return issues

    def _promote_transform(self, bronze: pl.DataFrame) -> pl.DataFrame:
        """Add metadata."""
        if len(bronze) == 0:
            return bronze

        return bronze.with_columns(pl.col("date").alias("knowledge_date"))
