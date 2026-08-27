"""Zerodha Kite Connect adapter for reconciliation and live data.

Uses the Kite Connect API (v3) for:
  - Historical OHLCV candles (for reconciliation against lakehouse)
  - Instrument master (for symbol-token mapping)

Requires a valid Kite API key and access token.
Not used for ingestion — only for validation and live feeds.

Ref: https://kite.trade/docs/connect/v3/
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import pandas as pd
import structlog

logger = structlog.get_logger(__name__)

# Kite Connect API base URL
_KITE_API_BASE = "https://api.kite.trade"

# Exchange segment codes
_EXCHANGE_NSE = "NSE"
_EXCHANGE_NFO = "NFO"

# Candle interval for daily OHLCV reconciliation
_INTERVAL_DAY = "day"


@dataclass(frozen=True)
class KiteConfig:
    """Kite Connect API configuration.

    Obtain api_key from https://developers.kite.trade/
    access_token is generated per-session via the login flow.
    """

    api_key: str
    access_token: str


class KiteAdapter:
    """Zerodha Kite Connect adapter.

    This adapter wraps the Kite Connect historical data API
    for reconciliation purposes. It is NOT a data source for
    the lakehouse — NSE archives are the source of truth.

    Usage:
        adapter = KiteAdapter(KiteConfig(api_key="...", access_token="..."))
        df = adapter.historical_ohlcv("RELIANCE", date(2024,1,1), date(2024,1,31))
    """

    def __init__(self, config: KiteConfig) -> None:
        self._config = config
        self._client: Any = None
        self._instruments: pd.DataFrame | None = None

    @property
    def client(self) -> Any:
        """Lazy-initialize the Kite Connect client.

        Requires kiteconnect package: pip install kiteconnect
        """
        if self._client is None:
            try:
                from kiteconnect import KiteConnect  # type: ignore[import-not-found]
            except ImportError as e:
                msg = "kiteconnect package not installed. Install with: pip install kiteconnect"
                raise ImportError(msg) from e

            self._client = KiteConnect(api_key=self._config.api_key)
            self._client.set_access_token(self._config.access_token)
            logger.info("kite_adapter_initialized")
        return self._client

    def instruments(self, exchange: str = _EXCHANGE_NSE) -> pd.DataFrame:
        """Fetch instrument master for the given exchange.

        Returns:
            DataFrame with columns: instrument_token, tradingsymbol,
            name, isin, exchange, lot_size, etc.
        """
        if self._instruments is None:
            raw = self.client.instruments(exchange)
            self._instruments = pd.DataFrame(raw)
            logger.info(
                "kite_instruments_loaded",
                exchange=exchange,
                count=len(self._instruments),
            )
        return self._instruments

    def resolve_token(self, symbol: str, exchange: str = _EXCHANGE_NSE) -> int | None:
        """Resolve a trading symbol to its instrument token.

        Args:
            symbol: NSE trading symbol (e.g. "RELIANCE").
            exchange: Exchange segment (default: NSE).

        Returns:
            Instrument token, or None if not found.
        """
        instruments = self.instruments(exchange)
        match = instruments[instruments["tradingsymbol"] == symbol]
        if match.empty:
            return None
        return int(match.iloc[0]["instrument_token"])

    def historical_ohlcv(
        self,
        symbol: str,
        start: date,
        end: date,
        exchange: str = _EXCHANGE_NSE,
    ) -> pd.DataFrame:
        """Fetch historical daily OHLCV from Kite Connect.

        Used for reconciliation: compare Kite's adjusted close
        against the lakehouse's bhavcopy-derived close.

        Args:
            symbol: NSE trading symbol.
            start: Start date (inclusive).
            end: End date (inclusive).
            exchange: Exchange segment.

        Returns:
            pandas DataFrame with columns:
                date, open, high, low, close, volume
            Prices are adjusted for corporate actions by Kite.
        """
        token = self.resolve_token(symbol, exchange)
        if token is None:
            msg = f"Symbol {symbol} not found on {exchange}"
            raise ValueError(msg)

        from_dt = datetime.combine(start, datetime.min.time())
        to_dt = datetime.combine(end, datetime.min.time())

        raw = self.client.historical_data(
            instrument_token=token,
            from_date=from_dt,
            to_date=to_dt,
            interval=_INTERVAL_DAY,
        )

        df = pd.DataFrame(raw)
        if df.empty:
            return df

        df = df.rename(
            columns={
                "date": "date",
                "open": "open",
                "high": "high",
                "low": "low",
                "close": "close",
                "volume": "volume",
            }
        )

        logger.info(
            "kite_historical_fetched",
            symbol=symbol,
            start=start.isoformat(),
            end=end.isoformat(),
            rows=len(df),
        )
        return df
