// Shaping logic enforces token budget, summarizes numbers, formats them
import { ApiError } from './api_client';

export function formatINR(val: number): string {
    return `₹${val.toFixed(2)}`;
}

export function formatPct(val: number): string {
    return `${(val * 100).toFixed(2)}%`;
}

export function shapeBacktestReport(rawReport: any) {
    if (!rawReport || !rawReport.metrics) return rawReport;
    const m = rawReport.metrics;
    
    // Explicit summary generation preventing raw array dumps
    const summaryStr = `Strategy generated a net CAGR of ${formatPct(m.net_cagr)} and net Sharpe of ${m.net_sharpe.toFixed(2)} with a max drawdown of ${formatPct(m.max_dd)}. Trading incurred ${formatINR(m.cost_breakdown.Slippage)} in slippage and ${formatINR(m.cost_breakdown.STT)} in STT.`;
    
    return {
        run_id: rawReport.run_id,
        summary: summaryStr,
        metrics: {
            net_sharpe: m.net_sharpe,
            net_cagr: formatPct(m.net_cagr),
            max_drawdown: formatPct(m.max_dd),
            turnover: m.turnover,
            n_trades: m.n_trades
        },
        costs: {
            total_stt: formatINR(m.cost_breakdown.STT),
            total_brokerage: formatINR(m.cost_breakdown.Brokerage),
            total_slippage: formatINR(m.cost_breakdown.Slippage)
        },
        detail_url: `http://127.0.0.1:8000/v1/backtest/${rawReport.run_id}/report`,
        data_as_of: rawReport.data_as_of,
        note: "Warning: Backtest uses unadjusted raw prices. Engine currently lacks corporate action adjustments, so multi-month returns spanning a stock split/bonus will contain artificial price drop artifacts."
    };
}

export function shapeValidationReport(rawReport: any) {
    if (!rawReport) return rawReport;
    
    const is_valid = rawReport.is_valid;
    const dsr = rawReport.deflated_sharpe_at_total_trials;
    const trials = rawReport.total_historical_trials;
    const prov = rawReport.trial_provenance;
    
    // Hard requirement: MUST explicitly state conditionality
    const summaryStr = `Strategy is ${is_valid ? 'VALID' : 'INVALID'}. The Deflated Sharpe Ratio (DSR) is ${dsr.toFixed(4)} when accounting for ${trials} trials (${prov}). Note: DSR ranges from ${rawReport.sensitivity_table[0].deflated_sharpe.toFixed(4)} to ${rawReport.sensitivity_table[4].deflated_sharpe.toFixed(4)} depending on assumed trial count (see detail_url for full table). Result is only significant if fewer trials were run.`;
    
    return {
        run_id: rawReport.run_id,
        is_valid: is_valid,
        summary: summaryStr,
        deflated_sharpe: dsr,
        assumed_trials: trials,
        detail_url: `http://127.0.0.1:8000/v1/backtest/${rawReport.run_id}/validation`,
    };
}

export function shapeCosts(rawCosts: any) {
    if (!rawCosts) return rawCosts;
    const summary = `Executing ${rawCosts.target_qty} shares at ${formatINR(rawCosts.price)} (${rawCosts.side}) costs ${formatINR(rawCosts.total_frictional_cost)} total, with STT making up ${formatINR(rawCosts.cost_breakdown.STT)}.`;
    return {
        summary,
        total_cost: formatINR(rawCosts.total_frictional_cost),
        stt: formatINR(rawCosts.cost_breakdown.STT),
        slippage: formatINR(rawCosts.cost_breakdown.Slippage),
        detail_url: `http://127.0.0.1:8000/v1/costs/explain`,
        note: "cost estimate uses a synthetic ±2% intraday range, not actual market data for trade_date"
    };
}

export function shapeError(err: ApiError) {
    return {
        error: true,
        error_code: err.error_code,
        message: err.message,
        suggestion: err.suggestion
    };
}
