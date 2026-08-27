"""Dhan API adapter for reconciliation and live data.

Uses the Dhan HTTP API (v2) for:
  - Historical OHLCV candles (for reconciliation against lakehouse)
  - Instrument master (for symbol mapping)

Requires a valid Dhan API access token.
Not used for ingestion — only for validation and live feeds.

Ref: https://dhanhq.co/docs/v2/
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import httpx
import pandas as pd
import structlog

logger = structlog.get_logger(__name__)

# Dhan API base URL
_DHAN_API_BASE = "https://api.dhan.co/v2"

# Exchange segment codes
_EXCHANGE_NSE = "NSE_EQ"
_EXCHANGE_NFO = "NSE_FNO"


@dataclass(frozen=True)
class DhanConfig:
    """Dhan API configuration.

    Obtain access_token from https://dhanhq.co/
    """

    access_token: str
    client_id: str


class DhanAdapter:
    """Dhan API adapter for reconciliation.

    Wraps the Dhan historical data API. NOT a data source
    for the lakehouse — NSE archives are the source of truth.

    Usage:
        adapter = DhanAdapter(DhanConfig(access_token="...", client_id="..."))
        df = adapter.historical_ohlcv("1333", date(2024,1,1), date(2024,1,31))
    """

    def __init__(self, config: DhanConfig) -> None:
        self._config = config
        self._client: httpx.Client | None = None

    @property
    def client(self) -> httpx.Client:
        """Lazy-initialize the HTTP client with auth headers."""
        if self._client is None:
            self._client = httpx.Client(
                base_url=_DHAN_API_BASE,
                headers={
                    "access-token": self._config.access_token,
                    "client-id": self._config.client_id,
                    "Content-Type": "application/json",
                },
                timeout=30.0,
            )
            logger.info("dhan_adapter_initialized")
        return self._client

    def historical_ohlcv(
        self,
        security_id: str,
        start: date,
        end: date,
        exchange_segment: str = _EXCHANGE_NSE,
    ) -> pd.DataFrame:
        """Fetch historical daily OHLCV from Dhan API.

        Used for reconciliation: compare Dhan's data against
        the lakehouse's bhavcopy-derived values.

        Args:
            security_id: Dhan security ID (exchange-specific token).
            start: Start date (inclusive).
            end: End date (inclusive).
            exchange_segment: Exchange segment code.

        Returns:
            pandas DataFrame with columns:
                date, open, high, low, close, volume
        """
        payload = {
            "securityId": security_id,
            "exchangeSegment": exchange_segment,
            "instrument": "EQUITY",
            "expiryCode": 0,
            "fromDate": start.isoformat(),
            "toDate": end.isoformat(),
        }

        resp = self.client.post("/charts/historical", json=payload)
        resp.raise_for_status()
        data = resp.json()

        if not data or "open" not in data:
            logger.warning(
                "dhan_empty_response",
                security_id=security_id,
            )
            return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])

        df = pd.DataFrame(
            {
                "date": pd.to_datetime(data.get("timestamp", [])),
                "open": data.get("open", []),
                "high": data.get("high", []),
                "low": data.get("low", []),
                "close": data.get("close", []),
                "volume": data.get("volume", []),
            }
        )

        logger.info(
            "dhan_historical_fetched",
            security_id=security_id,
            start=start.isoformat(),
            end=end.isoformat(),
            rows=len(df),
        )
        return df
