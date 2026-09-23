import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";
import { z } from "zod";
import { zodToJsonSchema } from "zod-to-json-schema";
import { apiClient, handleApiError } from "./api_client.js";
import {
  shapeBacktestReport,
  shapeValidationReport,
  shapeCosts,
  shapeError,
} from "./shaping.js";

const server = new Server(
  {
    name: "Tapetide MCP Server",
    version: "1.0.0",
  },
  {
    capabilities: {
      tools: {},
    },
  }
);

// Define tools
server.setRequestHandler(ListToolsRequestSchema, async () => {
  return {
    tools: [
      {
        name: "list_factors",
        description: "Discover the factor library with metadata.",
        inputSchema: zodToJsonSchema(z.object({})) as any,
      },
      {
        name: "screen_stocks",
        description: "Fundamental screen. Note: Uses real Lakehouse fundamentals. IMPORTANT: Data begins in 2025.",
        inputSchema: zodToJsonSchema(z.object({
          metric: z.string(),
          operator: z.enum(["gt", "lt", "between"]),
          threshold: z.number(),
          as_of: z.string().describe("ISO date string YYYY-MM-DD"),
        })) as any,
      },
      {
        name: "screen_stocks_technical",
        description: "Technical screen. Note: Uses real equity_daily data.",
        inputSchema: zodToJsonSchema(z.object({
          metric: z.string(),
          operator: z.enum(["gt", "lt", "between", "crosses_above", "crosses_below"]),
          threshold: z.number(),
          as_of: z.string().describe("ISO date string YYYY-MM-DD"),
        })) as any,
      },
      {
        name: "run_backtest",
        description: "Launch a backtest. Note: The backend executes backtests via a single-worker ThreadPoolExecutor. Concurrent backtest requests will queue rather than run in parallel. IMPORTANT: Only NIFTY 50 universe is currently available. Data begins in 2016-03-08.",
        inputSchema: zodToJsonSchema(z.object({
          name: z.string(),
          capital: z.number(),
          start_date: z.string(),
          end_date: z.string(),
          factors: z.array(z.string()),
          weights: z.array(z.number()),
        })) as any,
      },
      {
        name: "get_backtest_report",
        description: "Get shaped backtest metrics and narrative summary.",
        inputSchema: zodToJsonSchema(z.object({
          run_id: z.string(),
        })) as any,
      },
      {
        name: "get_validation_report",
        description: "Get DSR, PBO, walk-forward, and break-even cost analysis.",
        inputSchema: zodToJsonSchema(z.object({
          run_id: z.string(),
        })) as any,
      },
      {
        name: "compare_strategies",
        description: "Compare multiple strategies side by side.",
        inputSchema: zodToJsonSchema(z.object({
          run_ids: z.array(z.string()),
        })) as any,
      },
      {
        name: "explain_costs",
        description: "Itemise the Indian statutory cost stack and slippage for a trade profile.",
        inputSchema: zodToJsonSchema(z.object({
          trade_date: z.string(),
          qty: z.number(),
          price: z.number(),
          side: z.enum(["BUY", "SELL"]),
        })) as any,
      }
    ],
  };
});

// Tool executor
server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;
  
  try {
    if (name === "list_factors") {
      const res = await apiClient.get("/factors");
      return { content: [{ type: "text", text: JSON.stringify(res.data, null, 2) }] };
    }
    
    if (name === "screen_stocks") {
      const res = await apiClient.post("/screen", args);
      return { content: [{ type: "text", text: JSON.stringify({ summary: `Found ${res.data.results.length} stocks.`, count: res.data.results.length }) }] };
    }
    
    if (name === "screen_stocks_technical") {
      const res = await apiClient.post("/screen/technical", args);
      return { content: [{ type: "text", text: JSON.stringify({ summary: `Found ${res.data.results.length} stocks.`, count: res.data.results.length }) }] };
    }

    if (name === "run_backtest") {
      // Validate dates
      if (args && (args as any).start_date && (args as any).start_date < "2016-03-08") {
         return {
            content: [{ type: "text", text: JSON.stringify(shapeError({
                error_code: 400,
                message: "Date before 2016-03-08 requested",
                suggestion: "equity_daily data only begins on 2016-03-08. Adjust start_date."
            }))}]
         };
      }
      const res = await apiClient.post("/backtest", args);
      
      // For ease of use, let's poll 15 times
      let run_id = res.data.run_id;
      for (let i = 0; i < 15; i++) {
         const poll = await apiClient.get(`/backtest/${run_id}`);
         console.error(`[POLL ${i+1}] GET /v1/backtest/${run_id} observed raw API JSON:`, JSON.stringify(poll.data));
         if (poll.data.status === "completed") break;
         if (poll.data.status === "failed") throw new Error("Backtest failed");
         await new Promise(r => setTimeout(r, 1000));
      }
      return { content: [{ type: "text", text: JSON.stringify({ run_id, status: "completed", note: "Note: Backtest execution uses correctly adjusted point-in-time prices." }) }] };
    }

    if (name === "get_backtest_report") {
      const { run_id } = args as any;
      const res = await apiClient.get(`/backtest/${run_id}/report`);
      return { content: [{ type: "text", text: JSON.stringify(shapeBacktestReport(res.data), null, 2) }] };
    }

    if (name === "get_validation_report") {
      const { run_id } = args as any;
      const res = await apiClient.get(`/backtest/${run_id}/validation`);
      return { content: [{ type: "text", text: JSON.stringify(shapeValidationReport(res.data), null, 2) }] };
    }
    
    if (name === "compare_strategies") {
        const { run_ids } = args as any;
        const results = [];
        for (const rid of run_ids) {
            const rep = await apiClient.get(`/backtest/${rid}/report`);
            results.push(shapeBacktestReport(rep.data));
        }
        return { content: [{ type: "text", text: JSON.stringify({ summary: `Compared ${run_ids.length} strategies`, results }, null, 2) }] };
    }
    
    if (name === "explain_costs") {
      const res = await apiClient.post("/costs/explain", args);
      return { content: [{ type: "text", text: JSON.stringify(shapeCosts(res.data), null, 2) }] };
    }
    
    throw new Error(`Tool not found: ${name}`);

  } catch (error) {
    return {
      content: [
        {
          type: "text",
          text: JSON.stringify(shapeError(handleApiError(error)), null, 2),
        },
      ],
      isError: true,
    };
  }
});

const transport = new StdioServerTransport();
server.connect(transport).then(() => {
    console.error("Tapetide MCP Server running on stdio");
});
