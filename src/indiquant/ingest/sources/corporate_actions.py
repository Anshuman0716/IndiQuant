import re
from datetime import UTC, date, datetime

import polars as pl
import structlog

from indiquant.ingest.base import Source
from indiquant.ingest.models import RawPayload, ValidationIssue

logger = structlog.get_logger(__name__)


def _parse_subject(subject: str) -> dict[str, object]:
    subject_lower = subject.lower().strip()

    split_match = re.search(
        r"(?:split|sub[- ]?division).*?"
        r"(?:rs\.?|re\.?|inr|face\s+value)\s*(\d+(?:\.\d+)?)"
        r".*?to.*?"
        r"(?:rs\.?|re\.?|inr|face\s+value)\s*(\d+(?:\.\d+)?)",
        subject_lower,
    )
    if split_match:
        return {
            "action_type": "split",
            "ratio_from": float(split_match.group(1)),
            "ratio_to": float(split_match.group(2)),
            "amount_per_share": None,
        }

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

    div_match = re.search(
        r"dividend.*?(?:rs\.?|re\.?|inr)\s*(\d+(?:\.\d+)?)",
        subject_lower,
    )
    if div_match:
        return {
            "action_type": "dividend",
            "ratio_from": None,
            "ratio_to": None,
            "amount_per_share": float(div_match.group(1)),
        }

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
    natural_keys = ["ex_date", "symbol", "action_type", "subject"]
    natural_keys = ["ex_date", "symbol", "action_type", "subject"]
    name = "nse_corporate_actions"
    prime_url = "https://www.nseindia.com"
    silver_table = "corporate_actions"
    rate_limit_rps = 1.0
    min_rows = 1

    from indiquant.store.schemas import CorporateActionsSchema
    schema = CorporateActionsSchema  # type: ignore[assignment]

    def _build_url(self, target_date: date) -> str:
        ds = target_date.strftime("%d-%m-%Y")
        return (
            f"https://www.nseindia.com/api/corporates-corporateActions"
            f"?index=equities&from_date={ds}&to_date={ds}"
        )


    def validate(self, raw: RawPayload):
        from indiquant.ingest.models import ValidationStatus
        report = super().validate(raw)
        import json
        try:
            data = json.loads(raw.body)
            if isinstance(data, list) and len(data) == 0:
                # It is genuinely empty
                if report.status == ValidationStatus.FAILED:
                    report.issues = [i for i in report.issues if i.code != 'MIN_ROWS']
                    if not report.issues:
                        report.status = ValidationStatus.PASSED
        except Exception:
            pass
        return report

    def _parse(self, raw: RawPayload) -> pl.DataFrame:
        import json

        try:
            data = json.loads(raw.body)
        except json.JSONDecodeError:
                        return pl.DataFrame(schema={
                'symbol': pl.Utf8, 'series': pl.Utf8, 'isin': pl.Utf8,
                'date': pl.Utf8, 'ex_date': pl.Utf8, 'record_date': pl.Utf8,
                'broadcast_date': pl.Utf8, 'subject': pl.Utf8,
                'action_type': pl.Utf8, 'ratio_from': pl.Float64,
                'ratio_to': pl.Float64, 'amount_per_share': pl.Float64,
                'face_value': pl.Float64
            })

        if not isinstance(data, list) or len(data) == 0:
                        return pl.DataFrame(schema={
                'symbol': pl.Utf8, 'series': pl.Utf8, 'isin': pl.Utf8,
                'date': pl.Utf8, 'ex_date': pl.Utf8, 'record_date': pl.Utf8,
                'broadcast_date': pl.Utf8, 'subject': pl.Utf8,
                'action_type': pl.Utf8, 'ratio_from': pl.Float64,
                'ratio_to': pl.Float64, 'amount_per_share': pl.Float64,
                'face_value': pl.Float64
            })

        records: list[dict[str, object]] = []
        for item in data:
            subject = item.get("subject") or ""
            parsed = _parse_subject(subject)

            ex_date_str = _parse_nse_date(item.get("exDate") or "-")
            if ex_date_str is None:
                continue

            records.append(
                {
                    "symbol": (item.get("symbol") or "").strip(),
                    "series": (item.get("series") or "EQ").strip(),
                    "isin": "",
                    "date": raw.date.isoformat(),
                    "ex_date": ex_date_str,
                    "record_date": _parse_nse_date(item.get("recDate") or "-"),
                    "broadcast_date": _parse_nse_date(item.get("caBroadcastDate") or "-"),
                    "subject": subject,
                    "action_type": parsed["action_type"],
                    "ratio_from": parsed["ratio_from"],
                    "ratio_to": parsed["ratio_to"],
                    "amount_per_share": parsed["amount_per_share"],
                    "face_value": float(item.get("faceVal", 0) or 0) if item.get("faceVal") else None,
                }
            )

        if not records:
                        return pl.DataFrame(schema={
                'symbol': pl.Utf8, 'series': pl.Utf8, 'isin': pl.Utf8,
                'date': pl.Utf8, 'ex_date': pl.Utf8, 'record_date': pl.Utf8,
                'broadcast_date': pl.Utf8, 'subject': pl.Utf8,
                'action_type': pl.Utf8, 'ratio_from': pl.Float64,
                'ratio_to': pl.Float64, 'amount_per_share': pl.Float64,
                'face_value': pl.Float64
            })

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
                return mapped_df.group_by(["symbol", "action_type", "ex_date", "subject"]).first()
        except duckdb.IOException:
            return parsed_df

    def _validate_rules(self, df: pl.DataFrame) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
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
        if len(bronze) == 0:
            return bronze
            
        bronze = bronze.with_columns(pl.col("ex_date").alias("knowledge_date"))
        
        # RE-PARSE the subject during promotion because bronze was saved with an older classifier
        parsed_structs = []
        for subject in bronze["subject"].to_list():
            parsed = _parse_subject(subject)
            parsed_structs.append(parsed)
            
        bronze = bronze.with_columns([
            pl.Series("new_action_type", [p["action_type"] for p in parsed_structs]),
            pl.Series("new_ratio_from", [p["ratio_from"] for p in parsed_structs], dtype=pl.Float64),
            pl.Series("new_ratio_to", [p["ratio_to"] for p in parsed_structs], dtype=pl.Float64),
            pl.Series("new_amount_per_share", [p["amount_per_share"] for p in parsed_structs], dtype=pl.Float64)
        ])
        
        bronze = bronze.with_columns([
            pl.when(pl.col("new_action_type") != "other").then(pl.col("new_action_type")).otherwise(pl.col("action_type")).alias("action_type"),
            pl.when(pl.col("new_action_type") != "other").then(pl.col("new_ratio_from")).otherwise(pl.col("ratio_from")).alias("ratio_from"),
            pl.when(pl.col("new_action_type") != "other").then(pl.col("new_ratio_to")).otherwise(pl.col("ratio_to")).alias("ratio_to"),
            pl.when(pl.col("new_action_type") != "other").then(pl.col("new_amount_per_share")).otherwise(pl.col("amount_per_share")).alias("amount_per_share"),
        ]).drop(["new_action_type", "new_ratio_from", "new_ratio_to", "new_amount_per_share"])

        import pandas as pd
        override_file = self.lakehouse.data_dir / "overrides" / "corporate_actions.csv"
        if override_file.exists():
            overrides = pl.from_pandas(pd.read_csv(override_file, dtype={"isin": str, "ex_date": str, "action_type": str, "ratio_from": float, "ratio_to": float, "source": str, "reason": str}))
            if not overrides.is_empty():
                if "source" not in bronze.columns:
                    bronze = bronze.with_columns(pl.lit(self.name).alias("source"))
                    
                for row in overrides.iter_rows(named=True):
                    # Find if a row exists with same ISIN, ex_date, and action_type
                    mask = (pl.col("isin") == row["isin"]) & (pl.col("ex_date") == row["ex_date"]) & (pl.col("action_type") == row["action_type"])
                    has_row = bronze.filter(mask).height > 0
                    
                    if has_row:
                        bronze = bronze.with_columns(
                            [
                                pl.when(mask).then(pl.lit(row["ratio_from"])).otherwise(pl.col("ratio_from")).alias("ratio_from"),
                                pl.when(mask).then(pl.lit(row["ratio_to"])).otherwise(pl.col("ratio_to")).alias("ratio_to"),
                                pl.when(mask).then(pl.lit(row.get("reason", "Manual Override"))).otherwise(pl.col("subject")).alias("subject"),
                                pl.when(mask).then(pl.lit(row.get("source", "manual"))).otherwise(pl.col("source")).alias("source"),
                            ]
                        )
                    else:
                        # Append new row
                        new_row = pl.DataFrame({
                            "isin": [row["isin"]],
                            "ex_date": [row["ex_date"]],
                            "knowledge_date": [row["ex_date"]],
                            "subject": [row.get("reason", "Manual Override")],
                            "source": [row.get("source", "manual")],
                            "action_type": [row["action_type"]],
                            "ratio_from": [row["ratio_from"]],
                            "ratio_to": [row["ratio_to"]],
                            "amount_per_share": [None]
                        })
                        # Ensure schema matches
                        for col in bronze.columns:
                            if col not in new_row.columns:
                                new_row = new_row.with_columns(pl.lit(None).alias(col))
                        new_row = new_row.select(bronze.columns)
                        bronze = pl.concat([bronze, new_row])

        bronze = bronze.with_columns(pl.col("subject").str.to_lowercase().str.strip_chars().alias("norm_subject"))
        bronze = bronze.unique(subset=["isin", "ex_date", "action_type", "ratio_from", "ratio_to", "amount_per_share", "norm_subject"], keep="first")
        bronze = bronze.drop("norm_subject")
        return bronze

    def promote(self, bronze, target_date, report, raw) -> None:
        pass

    def rebuild_silver(self) -> None:
        import shutil
        from datetime import datetime

        silver_dir = self.lakehouse.silver_dir / "corporate_actions"
        if silver_dir.exists():
            shutil.rmtree(silver_dir)
        silver_dir.mkdir(parents=True)

        bronze_dir = self.lakehouse.bronze_dir / self.name
        files = list(bronze_dir.rglob("*.parquet"))

        all_dfs = []
        for p in files:
            try:
                df = pl.read_parquet(p)
                if df.height > 0:
                    all_dfs.append(df)
            except Exception:
                pass

        if not all_dfs:
            return

        final = pl.concat(all_dfs, how="diagonal_relaxed")
        final = self._promote_transform(final)

        for col in ["broadcast_date", "ex_date", "record_date", "date", "symbol", "series", "isin", "subject", "action_type"]:
            if col in final.columns:
                final = final.with_columns(pl.col(col).cast(pl.Utf8))

        if "source" not in final.columns:
            final = final.with_columns(pl.lit(self.name).alias("source"))
        else:
            final = final.with_columns(pl.col("source").fill_null(pl.lit(self.name)))
            
        final = final.with_columns([
            pl.lit(datetime.now(UTC).isoformat()).alias("ingested_at"),
            pl.lit("batch_rebuild").alias("raw_hash"),
            pl.lit(2000).alias("year"),
        ])
        
        final = self.schema.validate(final)
        out = silver_dir / "data.parquet"
        final.write_parquet(out, compression="zstd")
