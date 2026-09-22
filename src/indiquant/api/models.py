from pydantic import BaseModel, Field
from typing import List, Optional, Literal, Any, Dict
from datetime import date, datetime

# RFC 7807 Error Model
class ErrorResponse(BaseModel):
    type: str = "about:blank"
    title: str
    status: int
    detail: str
    instance: Optional[str] = None
    data_as_of: Optional[datetime] = None

class BaseApiResponse(BaseModel):
    data_as_of: Optional[datetime] = None

class FactorResponse(BaseApiResponse):
    factors: List[str]

class FactorHistoryResponse(BaseApiResponse):
    factor_id: str
    history: List[Dict[str, Any]]

class ScreenRequest(BaseModel):
    metric: str
    operator: Literal["gt", "lt", "between", "pct_change_over", "crosses_above", "crosses_below"]
    threshold: float
    threshold_upper: Optional[float] = None
    as_of: date

class ScreenResponse(BaseApiResponse):
    results: List[Dict[str, Any]]

class BacktestRequest(BaseModel):
    name: str = "API Backtest"
    capital: float = 100_000.0
    start_date: str
    end_date: str
    factors: List[str]
    weights: List[float]
    top_n: int = 20

class BacktestAccepted(BaseModel):
    run_id: str
    status: str = "accepted"

class BacktestStatus(BaseApiResponse):
    run_id: str
    status: str
    result: Optional[Dict[str, Any]] = None

class BacktestValidation(BaseApiResponse):
    run_id: str
    is_valid: bool
    trial_provenance: str
    total_historical_trials: int
    deflated_sharpe_at_total_trials: float
    sensitivity_table: List[Dict[str, Any]]

class BacktestReport(BaseApiResponse):
    run_id: str
    metrics: Dict[str, Any]
    
class UniverseResponse(BaseApiResponse):
    index: str
    as_of: date
    constituents: List[str]

class OIBuildupResponse(BaseApiResponse):
    symbol: str
    buildups: List[Dict[str, Any]]
