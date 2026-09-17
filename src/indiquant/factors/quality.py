"""Quality factors."""

from datetime import date, timedelta
import duckdb
import numpy as np
import pandas as pd
import structlog

from indiquant.factors.base import FactorContext, factor

logger = structlog.get_logger(__name__)


@factor(
    id="roce_ttm",
    pillar="QUALITY",
    direction=1,
    min_history_days=365,
    required_tables=["fundamentals"],
    unit="%",
)
def roce_ttm(ctx: FactorContext, asof: date) -> pd.Series:
    """Return on Capital Employed (Trailing Twelve Months).
    
    Formula: EBIT_TTM / Capital_Employed
    where EBIT = PAT + Interest + Tax (approximation from available columns)
    and   Capital_Employed = Total Assets - Current Liabilities
    
    This factor needs the last 4 quarterly filings per ISIN, not just the
    latest one.  It therefore queries the fundamentals table directly
    (still respecting ``knowledge_date <= asof``) rather than using
    ``as_known_on()`` which returns only the single latest row.

    Missing data policy:
        Requires at least 4 quarters of fundamentals.
        If trailing 12m data is incomplete, returns NaN.
    """
    fundas = ctx.get_fundamentals_history(
        asof,
        columns=["revenue", "pat", "total_assets", "current_liabilities", "interest", "tax"],
        lookback_years=2,  # Only need 1 year (4 quarters) for TTM, fetch 2 to be safe
    )

    if fundas.empty:
        return pd.Series(dtype=float)

    fundas = fundas.sort_values(["isin", "quarter_end"])

    # EBIT = PAT + interest + tax
    fundas["ebit"] = fundas["pat"].fillna(0) + fundas["interest"].fillna(0) + fundas["tax"].fillna(0)

    # Capital Employed = Total Assets - Current Liabilities
    fundas["capital_employed"] = fundas["total_assets"].fillna(0) - fundas["current_liabilities"].fillna(0)

    # TTM EBIT: rolling sum of last 4 quarters per ISIN
    fundas["ebit_ttm"] = (
        fundas.groupby("isin")["ebit"]
        .rolling(4, min_periods=4)
        .sum()
        .reset_index(level=0, drop=True)
    )

    # Get the latest row per ISIN (which now has TTM sums)
    latest = fundas.groupby("isin").last()

    # ROCE = EBIT_TTM / Capital_Employed * 100
    roce = (latest["ebit_ttm"] / latest["capital_employed"]) * 100.0

    # Clean infinities (division by zero capital employed)
    roce = roce.replace([np.inf, -np.inf], np.nan)

    # Filter out cases where capital_employed was 0 or negative
    roce = roce.where(latest["capital_employed"] > 0, np.nan)

    dropped = int(roce.isna().sum())
    if dropped > 0:
        logger.info("factor_missing_data", factor="roce_ttm", dropped=dropped)

    return roce


@factor(
    id="roe_ttm",
    pillar="QUALITY",
    direction=1,
    min_history_days=365,
    required_tables=["fundamentals"],
    unit="%",
)
def roe_ttm(ctx: FactorContext, asof: date) -> pd.Series:
    """Return on Equity (Trailing Twelve Months).
    
    Formula: PAT_TTM / Total_Equity
    where Total_Equity = Total Assets - Total Liabilities
    
    Missing data policy: Requires 4 quarters of PAT.
    """
    fundas = ctx.get_fundamentals_history(
        asof,
        columns=["pat", "total_assets", "current_liabilities", "non_current_liabilities"],
        lookback_years=2,
    )
    if fundas.empty:
        return pd.Series(dtype=float)

    fundas["total_liabilities"] = fundas["current_liabilities"].fillna(0) + fundas.get("non_current_liabilities", 0)
    fundas["equity"] = fundas["total_assets"].fillna(0) - fundas["total_liabilities"]
    
    fundas["pat_ttm"] = (
        fundas.groupby("isin")["pat"]
        .rolling(4, min_periods=4)
        .sum()
        .reset_index(level=0, drop=True)
    )

    latest = fundas.groupby("isin").last()
    roe = (latest["pat_ttm"] / latest["equity"]) * 100.0
    roe = roe.replace([np.inf, -np.inf], np.nan)
    
    # Filter negative/zero equity
    return roe.where(latest["equity"] > 0, np.nan)


@factor(
    id="gross_profitability",
    pillar="QUALITY",
    direction=1,
    min_history_days=90,
    required_tables=["fundamentals"],
    unit="%",
)
def gross_profitability(ctx: FactorContext, asof: date) -> pd.Series:
    """Gross Profitability (Novy-Marx).
    
    Formula: (Revenue - COGS) / Total Assets
    Since true COGS isn't always available in standard Indian reporting without
    deep parsing, we approximate Gross Profit as (Revenue - Raw Material Cost).
    If Raw Material Cost is unavailable, we fall back to generic Operating Profit.
    """
    fundas = ctx.get_fundamentals(
        asof,
        columns=["revenue", "raw_material_cost", "total_assets", "pat", "interest", "tax"]
    )
    if fundas.empty:
        return pd.Series(dtype=float)
        
    fundas = fundas[~fundas["is_missing"]].set_index("isin")
    
    # Calculate GP. Default to Revenue - Raw Material Cost.
    if "raw_material_cost" in fundas.columns:
        gp = fundas["revenue"] - fundas["raw_material_cost"].fillna(0)
        # If RM cost was truly NaN, fallback to EBIT
        has_rm = fundas["raw_material_cost"].notna()
    else:
        gp = pd.Series(np.nan, index=fundas.index)
        has_rm = pd.Series(False, index=fundas.index)
        
    ebit = fundas["pat"].fillna(0) + fundas["interest"].fillna(0) + fundas["tax"].fillna(0)
    
    # Use GP if we have raw material cost, otherwise use EBIT
    gp = gp.where(has_rm, ebit)
        
    gp_ratio = (gp / fundas["total_assets"]) * 100.0
    return gp_ratio.replace([np.inf, -np.inf], np.nan).where(fundas["total_assets"] > 0, np.nan)


@factor(
    id="opm_stability_5y",
    pillar="QUALITY",
    direction=-1,  # Lower std dev is better
    min_history_days=365 * 5,
    required_tables=["fundamentals"],
    unit="std",
)
def opm_stability_5y(ctx: FactorContext, asof: date) -> pd.Series:
    """Stability of Operating Profit Margin over 5 years.
    
    Formula: Standard deviation of (EBIT / Revenue) over 20 quarters.
    Requires at least 16 quarters of data within the 5 year window.
    """
    fundas = ctx.get_fundamentals_history(
        asof,
        columns=["revenue", "pat", "interest", "tax"],
        lookback_years=5,
    )
    if fundas.empty:
        return pd.Series(dtype=float)
        
    fundas["ebit"] = fundas["pat"].fillna(0) + fundas["interest"].fillna(0) + fundas["tax"].fillna(0)
    fundas["opm"] = fundas["ebit"] / fundas["revenue"]
    fundas["opm"] = fundas["opm"].replace([np.inf, -np.inf], np.nan)
    
    # Calculate std dev per ISIN, requiring at least 16 non-null quarters
    stability = fundas.groupby("isin")["opm"].agg(lambda x: x.std() if x.notna().sum() >= 16 else np.nan)
    return stability


@factor(
    id="cfo_pat_ratio",
    pillar="QUALITY",
    direction=1,
    min_history_days=365,
    required_tables=["fundamentals"],
    unit="x",
)
def cfo_pat_ratio(ctx: FactorContext, asof: date) -> pd.Series:
    """Cash Flow from Operations to Profit After Tax (Earnings Quality).
    
    Formula: CFO_TTM / PAT_TTM
    Values > 1 indicate high quality earnings (cash backed).
    """
    fundas = ctx.get_fundamentals_history(
        asof,
        columns=["operating_cash_flow", "pat"],
        lookback_years=2,
    )
    if fundas.empty or "operating_cash_flow" not in fundas.columns:
        return pd.Series(dtype=float)
        
    fundas["cfo_ttm"] = fundas.groupby("isin")["operating_cash_flow"].rolling(4, min_periods=4).sum().reset_index(level=0, drop=True)
    fundas["pat_ttm"] = fundas.groupby("isin")["pat"].rolling(4, min_periods=4).sum().reset_index(level=0, drop=True)
    
    latest = fundas.groupby("isin").last()
    
    ratio = latest["cfo_ttm"] / latest["pat_ttm"]
    # If PAT is negative, the ratio interpretation flips (negative CFO / negative PAT = positive ratio, which is bad)
    # We enforce that both must be evaluated carefully, but standard is just reporting the ratio
    # and dropping negative PAT cases to avoid confusion in ranking.
    ratio = ratio.where(latest["pat_ttm"] > 0, np.nan)
    
    return ratio.replace([np.inf, -np.inf], np.nan)


@factor(
    id="accruals_ratio",
    pillar="QUALITY",
    direction=-1, # Lower is better (fewer accruals)
    min_history_days=365,
    required_tables=["fundamentals"],
    unit="%",
)
def accruals_ratio(ctx: FactorContext, asof: date) -> pd.Series:
    """Balance Sheet Accruals Ratio.
    
    Formula: (PAT_TTM - CFO_TTM) / Total_Assets
    Measures the non-cash component of earnings.
    """
    fundas = ctx.get_fundamentals_history(
        asof,
        columns=["operating_cash_flow", "pat", "total_assets"],
        lookback_years=2,
    )
    if fundas.empty or "operating_cash_flow" not in fundas.columns:
        return pd.Series(dtype=float)
        
    fundas["cfo_ttm"] = fundas.groupby("isin")["operating_cash_flow"].rolling(4, min_periods=4).sum().reset_index(level=0, drop=True)
    fundas["pat_ttm"] = fundas.groupby("isin")["pat"].rolling(4, min_periods=4).sum().reset_index(level=0, drop=True)
    
    latest = fundas.groupby("isin").last()
    
    accruals = (latest["pat_ttm"] - latest["cfo_ttm"]) / latest["total_assets"]
    return (accruals * 100.0).replace([np.inf, -np.inf], np.nan).where(latest["total_assets"] > 0, np.nan)


@factor(
    id="piotroski_f_score",
    pillar="QUALITY",
    direction=1,
    min_history_days=730, # Needs YoY comparison (current TTM vs prev TTM)
    required_tables=["fundamentals"],
    unit="pts",
)
def piotroski_f_score(ctx: FactorContext, asof: date) -> pd.Series:
    """Piotroski F-Score (Proxy).
    
    Scores 1 point each for:
    1. Positive ROA (TTM)
    2. Positive CFO (TTM)
    3. ROA (TTM) > ROA (Prev TTM)
    4. CFO (TTM) > PAT (TTM)
    5. Lower Long-Term Debt / Assets (YoY)
    6. Higher Current Ratio (YoY)
    7. No new shares issued (YoY)
    8. Higher Gross Margin (YoY)
    9. Higher Asset Turnover (YoY)
    
    Due to data availability, we implement a subset (the first 4 profitability/cash metrics)
    and scale to a 0-9 equivalent.
    """
    fundas = ctx.get_fundamentals_history(
        asof,
        columns=["pat", "operating_cash_flow", "total_assets"],
        lookback_years=3, # Need 8 quarters for 2 years of TTM
    )
    if fundas.empty or "operating_cash_flow" not in fundas.columns:
        return pd.Series(dtype=float)
        
    # Calculate TTMs
    for col in ["pat", "operating_cash_flow"]:
        fundas[f"{col}_ttm"] = fundas.groupby("isin")[col].rolling(4, min_periods=4).sum().reset_index(level=0, drop=True)
        
    # Need to compare latest quarter to 4 quarters ago
    # We add a row number descending to easily grab current vs -1yr
    fundas["rn"] = fundas.groupby("isin").cumcount(ascending=False)
    
    current = fundas[fundas["rn"] == 0].set_index("isin")
    prev_yr = fundas[fundas["rn"] == 4].set_index("isin")
    
    # Combine
    df = pd.DataFrame(index=current.index)
    
    # 1. Positive ROA
    roa_current = current["pat_ttm"] / current["total_assets"]
    df["f1"] = (roa_current > 0).astype(int)
    
    # 2. Positive CFO
    df["f2"] = (current["operating_cash_flow_ttm"] > 0).astype(int)
    
    # 3. Higher ROA
    roa_prev = prev_yr["pat_ttm"] / prev_yr["total_assets"]
    df["f3"] = (roa_current > roa_prev).astype(int)
    
    # 4. CFO > PAT
    df["f4"] = (current["operating_cash_flow_ttm"] > current["pat_ttm"]).astype(int)
    
    # Sum and scale to 9 (since we only have 4 factors here, multiply by 9/4)
    raw_score = df["f1"] + df["f2"] + df["f3"] + df["f4"]
    f_score = raw_score * (9.0 / 4.0)
    
    # Only return for ISINs that had both current and prev_yr data
    valid_isins = current.index.intersection(prev_yr.index)
    
    return f_score.reindex(valid_isins)
