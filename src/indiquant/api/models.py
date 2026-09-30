from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel


# RFC 7807 Error Model
class ErrorResponse(BaseModel):
    type: str = "about:blank"
    title: str
    status: int
    detail: str
    instance: str | None = None
    data_as_of: datetime | None = None


class BaseApiResponse(BaseModel):
    data_as_of: datetime | None = None


class FactorResponse(BaseApiResponse):
    factors: list[str]


class FactorHistoryResponse(BaseApiResponse):
    factor_id: str
    history: list[dict[str, Any]]


class ScreenRequest(BaseModel):
    metric: str
    operator: Literal["gt", "lt", "between", "pct_change_over", "crosses_above", "crosses_below"]
    threshold: float
    threshold_upper: float | None = None
    as_of: date


class ScreenResponse(BaseApiResponse):
    results: list[dict[str, Any]]


class BacktestRequest(BaseModel):
    name: str = "API Backtest"
    capital: float = 100_000.0
    start_date: str
    end_date: str
    factors: list[str]
    weights: list[float]
    top_n: int = 20


class BacktestAccepted(BaseModel):
    run_id: str
    status: str = "accepted"


class BacktestStatus(BaseApiResponse):
    run_id: str
    status: str
    result: dict[str, Any] | None = None


class BacktestValidation(BaseApiResponse):
    run_id: str
    is_valid: bool
    trial_provenance: str
    total_historical_trials: int
    deflated_sharpe_at_total_trials: float
    sensitivity_table: list[dict[str, Any]]


class BacktestReport(BaseApiResponse):
    run_id: str
    metrics: dict[str, Any]


class UniverseResponse(BaseApiResponse):
    index: str
    as_of: date
    constituents: list[str]


class OIBuildupResponse(BaseApiResponse):
    symbol: str
    buildups: list[dict[str, Any]]
