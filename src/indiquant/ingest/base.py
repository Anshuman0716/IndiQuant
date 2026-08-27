import hashlib
import json
import time
import uuid
from abc import ABC, abstractmethod
from datetime import UTC, date, datetime

import httpx
import pandera.polars as pa
import polars as pl
import structlog
from pandera.errors import SchemaError
from tenacity import retry, stop_after_attempt, wait_exponential

from indiquant.ingest.models import RawPayload, ValidationIssue, ValidationReport
from indiquant.store.lakehouse import Lakehouse

logger = structlog.get_logger(__name__)


class Source(ABC):
    """Four-stage ingestion pipeline: fetch -> validate -> land -> promote."""

    name: str
    rate_limit_rps: float = 2.0
    prime_url: str | None = None
    schema: type[pa.DataFrameModel]
    silver_table: str
    # Minimum expected rows for a valid payload. A 200-OK response with
    # fewer rows than this is treated as a confirmed gap, not a success.
    # Override per source (e.g. bhavcopy ~1800 rows/day, set min_rows=100).
    min_rows: int = 1

    def __init__(self, lakehouse: Lakehouse) -> None:
        self.lakehouse = lakehouse
        self.cache_dir = lakehouse.data_dir / "cache"
        self._client: httpx.Client | None = None
        self._last_request_time = 0.0

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
                timeout=30.0,
            )
            if self.prime_url:
                logger.info("priming_session", source=self.name, url=self.prime_url)
                self._client.get(self.prime_url)
        return self._client

    @abstractmethod
    def _build_url(self, target_date: date) -> str:
        """Return the URL to fetch for the given date."""
        ...

    @abstractmethod
    def _parse(self, raw: RawPayload) -> pl.DataFrame:
        """Parse raw bytes into a Polars DataFrame."""
        ...

    @abstractmethod
    def _validate_rules(self, df: pl.DataFrame) -> list[ValidationIssue]:
        """Apply business rules beyond pandera schema."""
        ...

    @abstractmethod
    def _promote_transform(self, bronze: pl.DataFrame) -> pl.DataFrame:
        """Dedupe, type-coerce, join reference data for silver."""
        ...

    def _throttle(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_request_time
        required_gap = 1.0 / self.rate_limit_rps
        if elapsed < required_gap:
            time.sleep(required_gap - elapsed)
        self._last_request_time = time.monotonic()

    @retry(
        wait=wait_exponential(multiplier=1, min=1, max=60),
        stop=stop_after_attempt(5),
    )
    def _http_get(self, url: str) -> httpx.Response:
        self._throttle()
        logger.debug("http_get", source=self.name, url=url)
        resp = self.client.get(url)
        resp.raise_for_status()

        content_type = resp.headers.get("content-type", "").lower()
        if "text/html" in content_type:
            preview = resp.content[:512].lower()
            if b"<html" in preview or b"<!doctype" in preview:
                # NSE sometimes returns 200 OK with HTML error page
                raise ValueError(f"Received HTML instead of data at {url}")

        return resp

    def fetch(self, target_date: date) -> RawPayload:
        """Fetch data for a single date."""
        url = self._build_url(target_date)
        url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]

        date_str = target_date.isoformat()
        cache_base = self.cache_dir / self.name / date_str
        cache_base.mkdir(parents=True, exist_ok=True)
        raw_path = cache_base / f"{url_hash}.raw"
        meta_path = cache_base / f"{url_hash}.meta.json"

        if raw_path.exists() and meta_path.exists():
            logger.debug("fetch_cache_hit", source=self.name, date=date_str)
            meta = json.loads(meta_path.read_text())
            body = raw_path.read_bytes()
            return RawPayload(
                source=self.name,
                date=target_date,
                url=url,
                status_code=meta["status_code"],
                headers=meta["headers"],
                body=body,
                fetched_at=meta["fetched_at"],
                raw_hash=meta["raw_hash"],
                from_cache=True,
            )

        resp = self._http_get(url)
        body = resp.content
        raw_hash = hashlib.sha256(body).hexdigest()
        fetched_at = datetime.now(UTC).isoformat()

        raw_path.write_bytes(body)
        meta_path.write_text(
            json.dumps(
                {
                    "url": url,
                    "status_code": resp.status_code,
                    "headers": dict(resp.headers),
                    "fetched_at": fetched_at,
                    "raw_hash": raw_hash,
                }
            )
        )

        return RawPayload(
            source=self.name,
            date=target_date,
            url=url,
            status_code=resp.status_code,
            headers=dict(resp.headers),
            body=body,
            fetched_at=fetched_at,
            raw_hash=raw_hash,
            from_cache=False,
        )

    def validate(self, raw: RawPayload) -> ValidationReport:
        """Parse raw payload, run pandera schema + business rules."""
        issues: list[ValidationIssue] = []
        try:
            df = self._parse(raw)
        except Exception as e:
            issues.append(
                ValidationIssue(
                    severity="error",
                    column=None,
                    check_name="parse",
                    rows_affected=0,
                    message=f"Parse failed: {e}",
                )
            )
            return ValidationReport(self.name, raw.date, 0, issues)

        # Row-count sanity check: a 200-OK with an empty or truncated body
        # must be treated as a confirmed gap, not pass through as valid.
        if len(df) < self.min_rows:
            issues.append(
                ValidationIssue(
                    severity="error",
                    column=None,
                    check_name="min_rows",
                    rows_affected=len(df),
                    message=(
                        f"Parsed {len(df)} rows, expected >= {self.min_rows}. "
                        f"Likely truncated or garbage response."
                    ),
                )
            )
            return ValidationReport(self.name, raw.date, len(df), issues)

        try:
            self.schema.validate(df, lazy=True)
        except SchemaError as e:
            # We would parse the SchemaErrors here in a real impl
            issues.append(
                ValidationIssue(
                    severity="error",
                    column=None,
                    check_name="pandera",
                    rows_affected=len(df),
                    message=str(e),
                )
            )
            return ValidationReport(self.name, raw.date, len(df), issues)

        # Run custom business rules
        rules_issues = self._validate_rules(df)
        issues.extend(rules_issues)

        return ValidationReport(self.name, raw.date, len(df), issues)

    def land(self, raw: RawPayload, force: bool = False) -> pl.DataFrame:
        """Parse into typed Polars frame, write to bronze Parquet."""
        if not force and self.lakehouse.bronze_exists(self.name, self.silver_table, raw.date):
            raise FileExistsError(f"Bronze file already exists for {self.name} on {raw.date}")

        df = self._parse(raw)
        self.lakehouse.write_bronze(self.name, self.silver_table, df, raw.date, force=force)
        return df

    def promote(
        self,
        bronze: pl.DataFrame,
        target_date: date,
        report: ValidationReport,
        raw: RawPayload,
    ) -> None:
        """Dedupe, type-coerce, add provenance columns, write to silver."""
        df = self._promote_transform(bronze)

        # Add provenance
        df = df.with_columns(
            [
                pl.lit(self.name).alias("source"),
                pl.lit(datetime.now(UTC).isoformat()).alias("ingested_at"),
                pl.lit(raw.raw_hash).alias("raw_hash"),
                pl.lit(target_date.year).alias("year"),
            ]
        )

        self.lakehouse.write_silver(self.silver_table, df, target_date.year)

        # Record data quality
        run_id = str(uuid.uuid4())
        null_counts = {col: df[col].null_count() for col in df.columns if df[col].null_count() > 0}
        quality_record = {
            "source": self.name,
            "run_id": run_id,
            "run_date": datetime.now(UTC).isoformat(),
            "target_date": target_date.isoformat(),
            "row_count": len(df),
            "null_counts_json": json.dumps(null_counts),
            "validation_failures": report.error_count + report.warning_count,
            "date_gaps_json": "[]",  # Computed later across a range
            "ingested_at": datetime.now(UTC).isoformat(),
        }
        self.lakehouse.write_quality_log(quality_record)

    def run(self, target_date: date, *, force: bool = False) -> ValidationReport:
        """Execute full pipeline for one date."""
        if not force and self.lakehouse.bronze_exists(self.name, self.silver_table, target_date):
            logger.info("run_skip_exists", source=self.name, date=target_date)
            # Fetch from cache to validate and report
            raw = self.fetch(target_date)
            return self.validate(raw)

        raw = self.fetch(target_date)
        report = self.validate(raw)
        if not report.passed:
            logger.error("validation_failed", report=report)
            return report

        bronze = self.land(raw, force=force)
        self.promote(bronze, target_date, report, raw)
        return report
