import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { McpAgent } from "agents/mcp";
import { withX402, type X402Config } from "agents/x402";
import { z } from "zod";

const CHAIN = "base-demo-normalization";
const FIXTURE = "tone";
const PRICE_USD = 0.01;

const X402_CONFIG: X402Config = {
  // Wrangler vars/secrets are exposed through process.env under nodejs_compat, matching the
  // Cloudflare Agents x402 example. Production defaults to Base mainnet; testnet is explicit.
  network: (process.env.X402_NETWORK || "eip155:8453") as X402Config["network"],
  recipient: process.env.MCP_ADDRESS as `0x${string}`,
  facilitator: {
    url: process.env.X402_FACILITATOR_URL || "https://x402.org/facilitator",
  },
};

function jsonText(value: unknown): { content: [{ type: "text"; text: string }] } {
  return { content: [{ type: "text", text: JSON.stringify(value) }] };
}

/**
 * Paid Workchain surface.
 *
 * The worker never executes audio itself. It authenticates the request through x402, then calls
 * the separately hosted Workchain origin. Keeping the payment edge and the execution origin
 * separate makes the trust boundary legible and lets us move the origin to a managed runner later
 * without changing the MCP contract.
 */
export class WorkchainMCP extends McpAgent<Env> {
  server = withX402(
    new McpServer({ name: "LUFS Workchain x402", version: "0.1.0" }),
    X402_CONFIG,
  );

  async init() {
    const network = X402_CONFIG.network;

    this.server.paidTool(
      "render_verified_demo",
      "Run the allow-listed Workchain demo and return only after its output contract verifies.",
      PRICE_USD,
      {
        chain: z.literal(CHAIN).optional().default(CHAIN),
        fixture: z.literal(FIXTURE).optional().default(FIXTURE),
      },
      {},
      async ({ chain, fixture }) => {
        // Keep this guard in the paid handler even though the schema is restrictive. It makes the
        // boundary explicit if a future transport or client bypasses schema validation.
        if (chain !== CHAIN || fixture !== FIXTURE) {
          return {
            isError: true,
            ...jsonText({ verified: false, error: "demo input is not allow-listed" }),
          };
        }

        const origin = this.env.WORKCHAIN_ORIGIN_URL.replace(/\/$/, "");
        const headers: Record<string, string> = { "content-type": "application/json" };
        if (this.env.WORKCHAIN_BACKEND_TOKEN) {
          headers.authorization = `Bearer ${this.env.WORKCHAIN_BACKEND_TOKEN}`;
        }

        const response = await fetch(`${origin}/v1/render`, {
          method: "POST",
          headers,
          body: JSON.stringify({ chain, fixture }),
        });
        const payload = await response.json<{
          verified?: boolean;
          status?: string;
          [key: string]: unknown;
        }>();

        // Never turn a backend 502 or an unverified context into a successful MCP result.
        if (!response.ok || payload.verified !== true) {
          return {
            isError: true,
            ...jsonText({
              verified: false,
              error: "Workchain origin did not return a verified render",
              origin_status: response.status,
              origin_result: payload,
            }),
          };
        }

        return jsonText(payload);
      },
    );

    this.server.registerTool(
      "describe_service",
      {
        description: "Describe the paid Workchain demo without executing it.",
        inputSchema: {},
      },
      async () =>
        jsonText({
          service: "LUFS Workchain x402 demo",
          network,
          asset: "USDC (facilitator-selected exact EVM asset)",
          price_usd: PRICE_USD,
          paid_tool: "render_verified_demo",
          verification: "Workchain context.json must report every executed step as verified",
        }),
    );
  }
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext) {
    const url = new URL(request.url);

    if (url.pathname === "/mcp") {
      return WorkchainMCP.serve("/mcp", { binding: "WorkchainMCP" }).fetch(request, env, ctx);
    }

    if (url.pathname === "/healthz") {
      return Response.json({ status: "ok", service: "workchain-x402", network: env.X402_NETWORK || "eip155:8453" });
    }

    return new Response("Not found", { status: 404 });
  },
};
