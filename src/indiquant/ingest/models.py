from dataclasses import dataclass
from datetime import date
from typing import Literal


@dataclass(frozen=True)
class RawPayload:
    """Raw HTTP response with provenance metadata.

    Attributes:
        source: Source identifier (e.g. "nse_equity_daily").
        date: Market date this payload covers.
        url: Full URL fetched.
        status_code: HTTP status code.
        headers: Response headers.
        body: Raw response bytes.
        fetched_at: UTC timestamp of fetch.
        raw_hash: SHA-256 hex digest of body. Used for provenance.
        from_cache: True if loaded from disk cache rather than HTTP.
    """

    source: str
    date: date
    url: str
    status_code: int
    headers: dict[str, str]
    body: bytes
    fetched_at: str
    raw_hash: str
    from_cache: bool


@dataclass(frozen=True)
class ValidationIssue:
    """A single validation failure or warning."""

    severity: Literal["error", "warning"]
    column: str | None
    check_name: str
    rows_affected: int
    message: str


@dataclass
class ValidationReport:
    """Aggregated result of validating a RawPayload or DataFrame."""

    source: str
    date: date
    total_rows: int
    issues: list[ValidationIssue]

    @property
    def passed(self) -> bool:
        """True if no error-severity issues."""
        return not any(i.severity == "error" for i in self.issues)

    @property
    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "warning")
