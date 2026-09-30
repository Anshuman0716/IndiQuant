from datetime import date, timedelta

import pandas as pd
import structlog
from indiquant.backtest.models import BacktestResult, Position, Trade
from indiquant.costs.engine import CostEngine

from indiquant.config.settings import IndiQuantSettings
from indiquant.factors.base import FactorContext, registry
from indiquant.factors.transform import rank_normalize, winsorize, z_score
from indiquant.ingest.calendar import TradingCalendar
from indiquant.store.lakehouse import Lakehouse
from indiquant.store.pit import index_constituents
from indiquant.validation.registry import TrialRecord, TrialRegistry

logger = structlog.get_logger(__name__)


class BacktestEngine:
    """Cross-Sectional Backtesting Engine.

    Simulates periodic rebalancing over a PIT universe.
    Costs are applied explicitly via Phase 7 CostEngine.
    """

    def __init__(self, lakehouse: Lakehouse, cost_engine: CostEngine):
        self.lakehouse = lakehouse
        self.cost_engine = cost_engine
        self.calendar = TradingCalendar()
        if not self.calendar.is_loaded:
            logger.warning("TradingCalendar not loaded. Running in bootstrap mode.")

    def _get_next_trading_day(self, current_date: date) -> date:
        for i in range(1, 15):
            next_date = current_date + timedelta(days=i)
            if self.calendar.is_trading_day(next_date):
                return next_date
        raise ValueError(f"No next trading day found after {current_date}")

    def run(
        self,
        factor_id: str,
        start_date: date,
        end_date: date,
        initial_capital: float = 1_000_000.0,
        data_provenance: str = "lakehouse",
    ) -> BacktestResult:
        """Run a backtest for a single factor.

        Hard Constraints:
        - factor_id must be momentum_12_1 or roce_ttm.
        - Universe is strict NIFTY 50 PIT.
        """
        # Hard constraint #1: No composite, single real factor only.
        if factor_id not in ("momentum_12_1", "roce_ttm"):
            raise ValueError(
                f"Forbidden factor {factor_id}. Phase 9 restricts to 'momentum_12_1' or 'roce_ttm'."
            )

        ctx = FactorContext(self.lakehouse)
        factor_meta = registry.get_factor(factor_id)

        # 1. Rebalance schedule (Monthly)
        tds = self.calendar.trading_days(start_date, end_date)
        if not tds:
            raise ValueError(f"No trading days found between {start_date} and {end_date}")

        df_cal = pd.DataFrame({"date": tds})
        df_cal["date"] = pd.to_datetime(df_cal["date"])
        df_cal["ym"] = df_cal["date"].dt.to_period("M")
        rebal_dates = df_cal.groupby("ym")["date"].max().dt.date.tolist()

        capital = initial_capital
        paper_capital = initial_capital
        positions: dict[str, float] = {}  # isin -> net_value
        paper_positions: dict[str, float] = {}  # isin -> paper_value
        trades: list[Trade] = []
        portfolio_history = []
        holdings_history = {}

        prev_exec_date = None

        for rebal_date in rebal_dates:
            try:
                exec_date = self._get_next_trading_day(rebal_date)
            except ValueError:
                break

            if exec_date > end_date:
                break

            # 1. MTM existing positions using backward-adjusted prices from exec_date
            if positions and prev_exec_date:
                lookback = (exec_date - prev_exec_date).days + 15
                prices_df = ctx.get_prices(asof=exec_date, lookback_days=lookback)

                new_positions = {}
                new_paper_positions = {}
                for isin in list(positions.keys()):
                    prev_val = positions[isin]
                    prev_paper_val = paper_positions.get(isin, 0.0)
                    isin_prices = prices_df[prices_df["isin"] == isin]
                    dates = pd.to_datetime(isin_prices["date"]).dt.date
                    row_prev = isin_prices[dates == prev_exec_date]
                    row_curr = isin_prices[dates == exec_date]

                    if row_prev.empty or row_curr.empty:
                        # Delisted or missing: Hold to next rebalance and force-exit at last known close
                        if isin_prices.empty:
                            logger.warning("force_exit_no_data", isin=isin)
                            continue

                        last_row = isin_prices.iloc[-1]
                        p_prev = (
                            row_prev.iloc[0]["open"] if not row_prev.empty else last_row["close"]
                        )
                        p_curr = last_row["close"]
                        exit_date = pd.to_datetime(last_row["date"]).date()

                        ratio = float(p_curr) / float(p_prev)
                        val_at_exit = prev_val * ratio
                        paper_val_at_exit = prev_paper_val * ratio

                        cost = self.cost_engine.calculate_costs(
                            exit_date, "sell", val_at_exit, is_first_sell_of_day=True
                        )
                        capital += val_at_exit - cost["total"]
                        paper_capital += paper_val_at_exit
                        trades.append(
                            Trade(exit_date, isin, "sell", val_at_exit, float(p_curr), cost)
                        )
                        logger.info("force_exit_delisted", isin=isin, date=exit_date)
                    else:
                        p_prev = row_prev.iloc[0]["open"]
                        p_curr = row_curr.iloc[0]["open"]
                        ratio = float(p_curr) / float(p_prev)
                        new_positions[isin] = prev_val * ratio
                        new_paper_positions[isin] = prev_paper_val * ratio

                positions = new_positions
                paper_positions = new_paper_positions

            # Record MTM Value before trading
            current_value = capital + sum(positions.values())
            paper_current_value = paper_capital + sum(paper_positions.values())

            portfolio_history.append(
                {
                    "date": exec_date,
                    "capital": current_value,
                    "gross_capital": paper_current_value,
                }
            )
            holdings_history[exec_date] = [Position(isin, v, 0.0) for isin, v in positions.items()]

            # 2. Signal Generation (as known on rebal_date)
            # Hard constraint #2: Strict NIFTY 50 PIT universe
            univ_df = index_constituents(self.lakehouse, "NIFTY 50", rebal_date)
            univ_isins = univ_df["isin"].tolist() if not univ_df.empty else []
            factor_series = factor_meta.func(ctx, rebal_date)

            # Known waivers for ISINs that legitimately lack sufficient history for factors
            # (e.g. recent spin-offs like JIOFIN, or new listings added to the index early)
            MISSING_DATA_WAIVERS = {
                "INE0J1Y01017",  # JIOFIN (demerged from Reliance)
                "INE214T01019",  # LTIM (LTI + Mindtree merger)
                "INE0IG001031",  # BAJAJHLD (demerger related)
            }

            factor_series_reindexed = factor_series.reindex(univ_isins)
            missing_isins = factor_series_reindexed[factor_series_reindexed.isna()].index.tolist()

            unwaived_missing = [isin for isin in missing_isins if isin not in MISSING_DATA_WAIVERS]
            if unwaived_missing:
                raise ValueError(
                    f"Point-In-Time Violation: Constituents missing factor values on {rebal_date}: {unwaived_missing}. "
                    "All index constituents must have a valid factor score to prevent survivorship bias, "
                    "unless explicitly exempted in MISSING_DATA_WAIVERS (e.g. for recent spin-offs)."
                )

            factor_series = factor_series_reindexed.dropna()

            if factor_series.empty:
                logger.warning("empty_factor_series", date=rebal_date)
                target_isins = []
            else:
                f = winsorize(factor_series)
                f = z_score(f)
                f = rank_normalize(f)
                # Top decile long-only
                k = max(1, len(f) // 10)
                target_isins = f.nlargest(k).index.tolist()

            # Prices for tracking execution exact values
            exec_prices_df = ctx.get_prices(asof=exec_date, lookback_days=0)

            def get_exec_price(isin: str, prices_df: pd.DataFrame = exec_prices_df) -> float:
                row = prices_df[prices_df["isin"] == isin]
                return float(row.iloc[0]["open"]) if not row.empty else 0.0

            # 3. Target Weights (Equal weight within quantile)
            raw_target = current_value / len(target_isins) if target_isins else 0.0
            # Execute Sells
            sells_today = set()
            for isin in list(positions.keys()):
                curr_val = positions[isin]
                paper_curr_val = paper_positions.get(isin, 0.0)
                if isin not in target_isins:
                    # Full exit
                    is_first = isin not in sells_today
                    sells_today.add(isin)
                    cost = self.cost_engine.calculate_costs(
                        exec_date, "sell", curr_val, is_first_sell_of_day=is_first
                    )
                    capital += curr_val - cost["total"]
                    paper_capital += paper_curr_val
                    trades.append(
                        Trade(exec_date, isin, "sell", curr_val, get_exec_price(isin), cost)
                    )
                    del positions[isin]
                    if isin in paper_positions:
                        del paper_positions[isin]
                elif curr_val > raw_target:
                    # Partial exit (rebalance down)
                    to_sell = curr_val - raw_target
                    if to_sell > (0.01 * raw_target):
                        is_first = isin not in sells_today
                        sells_today.add(isin)
                        cost = self.cost_engine.calculate_costs(
                            exec_date, "sell", to_sell, is_first_sell_of_day=is_first
                        )
                        capital += to_sell - cost["total"]

                        # In paper portfolio, we exit the exact same proportion of the position to prevent weight drift.
                        sell_ratio = to_sell / curr_val
                        paper_to_sell = paper_curr_val * sell_ratio
                        if paper_to_sell > 0:
                            paper_capital += paper_to_sell
                            paper_positions[isin] = paper_curr_val - paper_to_sell

                        positions[isin] = curr_val - to_sell
                        trades.append(
                            Trade(exec_date, isin, "sell", to_sell, get_exec_price(isin), cost)
                        )

            # Execute Buys
            # Calculate total cash required (buys + estimated buy costs)
            total_cash_needed = 0.0
            buys_needed = {}
            for isin in target_isins:
                curr_val = positions.get(isin, 0.0)
                if curr_val < raw_target:
                    to_buy = raw_target - curr_val
                    if to_buy > (0.01 * raw_target):
                        est_cost = self.cost_engine.calculate_costs(exec_date, "buy", to_buy)[
                            "total"
                        ]
                        total_cash_needed += to_buy + est_cost
                        buys_needed[isin] = to_buy

            # Pro-rata scaling of the buys to fit available post-sell cash
            scaling_factor = min(1.0, capital / total_cash_needed) if total_cash_needed > 0 else 1.0

            for isin in target_isins:
                curr_val = positions.get(isin, 0.0)
                paper_curr_val = paper_positions.get(isin, 0.0)

                if isin in buys_needed:
                    actual_buy = buys_needed[isin] * scaling_factor
                    if actual_buy > 0:
                        cost = self.cost_engine.calculate_costs(exec_date, "buy", actual_buy)
                        total_outflow = actual_buy + cost["total"]

                        # Guard against floating point overflow of capital
                        if total_outflow > capital + 0.01:
                            actual_buy = capital - cost["total"]
                            total_outflow = actual_buy + cost["total"]

                        capital -= total_outflow
                        positions[isin] = curr_val + actual_buy

                        # In paper portfolio, we buy the same proportion relative to cash.
                        buy_ratio = actual_buy / (
                            capital + total_outflow
                        )  # proportion of available cash used
                        paper_actual_buy = paper_capital * buy_ratio
                        if paper_actual_buy > 0:
                            paper_actual_buy = min(paper_actual_buy, paper_capital)
                            paper_capital -= paper_actual_buy
                            paper_positions[isin] = paper_curr_val + paper_actual_buy

                        trades.append(
                            Trade(exec_date, isin, "buy", actual_buy, get_exec_price(isin), cost)
                        )

            prev_exec_date = exec_date

        df_hist = pd.DataFrame(portfolio_history)
        total_trade_val = sum(t.quantity for t in trades)

        # Calculate turnover: Total traded value / 2 / Average Portfolio Value
        # or simplified: Total traded / 2 / Initial Capital
        avg_capital = df_hist["capital"].mean() if not df_hist.empty else initial_capital
        turnover = (total_trade_val / 2.0) / avg_capital if avg_capital else 0.0

        # Invariant Check: Real Expected vs Real Actual
        # The Paper portfolio assumes perfect equal-weighting and 0 costs.
        # The Real portfolio inevitably drifts slightly from perfect equal-weighting due to
        # execution friction (scaling buys down by post-cost capital, and skipping trades < 1%).
        # This causes a tiny, mathematically unavoidable divergence in compounded returns.
        if not df_hist.empty and trades:
            paper_end = float(df_hist["gross_capital"].iloc[-1])
            real_end = float(df_hist["capital"].iloc[-1])
            compounded_cost = 0.0

            # Reconstruct the Paper portfolio's daily gross capital for compounding
            df_hist["date_dt"] = pd.to_datetime(df_hist["date"])
            for t in trades:
                t_date = pd.Timestamp(t.date)
                mask = df_hist["date_dt"] <= t_date
                if mask.any():
                    paper_t = float(df_hist[mask]["gross_capital"].iloc[-1])
                    if paper_t > 0:
                        compounded_cost += t.costs["total"] * (paper_end / paper_t)

            df_hist = df_hist.drop(columns=["date_dt"])

            real_expected = paper_end - compounded_cost
            drift = abs(real_expected - real_end)

            # Tolerance: 0.1% per year of backtest duration
            days = (end_date - start_date).days
            years = max(1.0, days / 365.25)
            tolerance = 0.001 * years * paper_end

            if drift > tolerance:
                logger.warning(
                    "invariant_divergence_exceeds_tolerance",
                    expected=real_expected,
                    actual=real_end,
                    drift=drift,
                    tolerance=tolerance,
                )

        result = BacktestResult(
            factor_id=factor_id,
            start_date=start_date,
            end_date=end_date,
            portfolio_history=df_hist,
            holdings=holdings_history,
            trades=trades,
            turnover=turnover,
            is_preliminary=True,
        )

        if data_provenance != "mock":
            try:
                trial_registry = TrialRegistry(IndiQuantSettings())

                net_return = None
                gross_return = None
                if not df_hist.empty:
                    initial = df_hist.iloc[0]["capital"]
                    final = df_hist.iloc[-1]["capital"]
                    net_return = (final / initial) - 1.0

                    paper_initial = df_hist.iloc[0]["gross_capital"]
                    paper_final = df_hist.iloc[-1]["gross_capital"]
                    gross_return = (paper_final / paper_initial) - 1.0

                record = TrialRecord(
                    strategy_name=factor_id,
                    start_date=start_date,
                    end_date=end_date,
                    data_provenance=data_provenance,
                    net_return=net_return,
                    gross_return=gross_return,
                    n_trades=len(trades),
                    turnover=turnover,
                )
                trial_registry.record_trial(record)
            except Exception as e:
                logger.error("failed_to_record_trial", error=str(e))

        return result
