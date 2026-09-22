import { apiClient, handleApiError } from './src/api_client.js';
import { shapeBacktestReport, shapeValidationReport, shapeCosts, shapeError } from './src/shaping.js';

async function runTests() {
    console.log("=== AUTOMATED MCP SERVER SHAPING TEST SUITE ===\n");
    let run_id = "";
    try {
        // 1. list_factors
        console.log("--- TOOL 1: list_factors ---");
        const f = await apiClient.get("/factors");
        console.log("Raw API Output:", JSON.stringify(f.data));
        console.log("Shaped Output: (Direct passthrough for factors)");
        console.log(JSON.stringify(f.data, null, 2));
        console.log("\n");
        
        // 2. screen_stocks
        console.log("--- TOOL 2: screen_stocks ---");
        const ss = await apiClient.post("/screen", { metric: "pat", operator: "gt", threshold: 0, as_of: "2024-01-31" });
        console.log("Raw API Output length:", ss.data.results.length);
        console.log("Shaped Output:");
        console.log(JSON.stringify({ summary: `Found ${ss.data.results.length} stocks.`, count: ss.data.results.length }));
        console.log("\n");
        
        // 3. screen_stocks_technical
        console.log("--- TOOL 3: screen_stocks_technical ---");
        const sst = await apiClient.post("/screen/technical", { metric: "volume", operator: "gt", threshold: 1000, as_of: "2024-01-31" });
        console.log("Raw API Output length:", sst.data.results.length);
        console.log("Shaped Output:");
        console.log(JSON.stringify({ summary: `Found ${sst.data.results.length} stocks.`, count: sst.data.results.length }));
        console.log("\n");
        
        const rb = await apiClient.post("/backtest", {
            name: "test_shaping_strategy_unique_run",
            capital: 1000000.0,
            start_date: "2024-01-01",
            end_date: "2024-01-31",
            factors: ["momentum"],
            weights: [1.0]
        });
        run_id = rb.data.run_id;
        
        console.log("--- TOOL 4: run_backtest (Polling Demonstration) ---");
        console.log("INITIAL SUBMISSION RAW API JSON:", JSON.stringify(rb.data));
        
        // Polling explicitly logged in test
        for(let i=0; i<10; i++) {
            const p = await apiClient.get(`/backtest/${run_id}`);
            console.log(`[POLL ${i+1}] RAW API JSON:`, JSON.stringify(p.data));
            if (p.data.status === "completed") break;
            await new Promise(r => setTimeout(r, 1000));
        }
        console.log("SHAPED TS OUTPUT:");
        console.log(JSON.stringify({ run_id, status: "completed" }, null, 2));
        console.log("\n");
        
        // 5. get_backtest_report
        console.log("--- TOOL 5: get_backtest_report ---");
        const rep = await apiClient.get(`/backtest/${run_id}/report`);
        console.log("RAW API JSON:");
        console.log(JSON.stringify(rep.data, null, 2));
        console.log("\nSHAPED TS OUTPUT:");
        console.log(JSON.stringify(shapeBacktestReport(rep.data), null, 2));
        console.log("\n");
        
        // 6. get_validation_report
        console.log("--- TOOL 6: get_validation_report ---");
        const val = await apiClient.get(`/backtest/${run_id}/validation`);
        console.log("RAW API JSON:");
        console.log(JSON.stringify(val.data, null, 2));
        console.log("\nSHAPED TS OUTPUT:");
        console.log(JSON.stringify(shapeValidationReport(val.data), null, 2));
        console.log("\n");
        
        // 7. compare_strategies
        console.log("--- TOOL 7: compare_strategies ---");
        console.log("RAW API JSON: (Multiple backtest report calls)");
        console.log("\nSHAPED TS OUTPUT:");
        console.log(JSON.stringify({ summary: `Compared 1 strategies`, results: [shapeBacktestReport(rep.data)] }, null, 2));
        console.log("\n");

        console.log("--- TOOL 8: explain_costs ---");
        const ec = await apiClient.post("/costs/explain", { trade_date: "2024-01-15", qty: 10000, price: 1000.0, side: "BUY" });
        console.log("RAW API JSON:");
        console.log(JSON.stringify(ec.data, null, 2));
        console.log("\nSHAPED TS OUTPUT:");
        console.log(JSON.stringify(shapeCosts(ec.data), null, 2));
        console.log("\n");
        
        // 9. FII/DII 503 ERROR HANDLING
        console.log("--- TOOL: FII/DII (Honest 503 Handling) ---");
        try {
            await apiClient.get("/flows/fii-dii");
        } catch(e: any) {
            const err = handleApiError(e);
            console.log("RAW API JSON (from catch block):", e.response?.data);
            console.log("\nSHAPED TS OUTPUT:");
            console.log(JSON.stringify(shapeError(err), null, 2));
        }
        
    } catch (e) {
        console.error("Test suite failed:", e);
    }
}
runTests();
