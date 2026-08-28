import "dotenv/config";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";
import { ExactEvmScheme } from "@x402/evm/exact/client";
import { createx402MCPClient } from "@x402/mcp";
import { privateKeyToAccount } from "viem/accounts";

const privateKey = process.env.EVM_PRIVATE_KEY;
const serverUrl = (process.env.MCP_SERVER_URL || "http://127.0.0.1:8787").replace(/\/$/, "");
const network = process.env.X402_NETWORK || "eip155:84532";
const autoApprove = process.env.AUTO_APPROVE === "true";

if (!privateKey) {
  console.error("EVM_PRIVATE_KEY is required; keep it in a local .env file, never in Git or chat.");
  process.exit(2);
}

const account = privateKeyToAccount(privateKey);
console.log(`Connecting to ${serverUrl}/mcp`);
console.log(`Buyer wallet: ${account.address}`);
console.log(`Network: ${network}`);
console.log(`Automatic payment approval: ${autoApprove ? "enabled" : "disabled"}`);

const client = createx402MCPClient({
  name: "lufs-workchain-x402-demo-client",
  version: "0.1.0",
  schemes: [{ network, client: new ExactEvmScheme(account) }],
  autoPayment: true,
  onPaymentRequested: async ({ toolName, paymentRequired }) => {
    const requirement = paymentRequired.accepts[0];
    console.log("402 payment required");
    console.log(JSON.stringify({
      tool: toolName,
      amount: requirement?.amount,
      asset: requirement?.asset,
      network: requirement?.network,
      payTo: requirement?.payTo,
    }, null, 2));
    if (!autoApprove) {
      console.error("Refusing to sign. Set AUTO_APPROVE=true only for an intentional demo run.");
    }
    return autoApprove;
  },
});

const transport = new StreamableHTTPClientTransport(new URL(`${serverUrl}/mcp`));
try {
  await client.connect(transport);
  console.log("Connected; discovering tools...");
  const listed = await client.listTools();
  console.log(JSON.stringify(listed.tools.map(({ name, description }) => ({ name, description })), null, 2));

  console.log("Calling the paid verified render tool...");
  const result = await client.callTool("render_verified_demo", {
    chain: "base-demo-normalization",
    fixture: "tone",
  });
  console.log(JSON.stringify(result, null, 2));

  if (result.isError) {
    console.error("Paid demo did not return a successful MCP result.");
    process.exitCode = 1;
  } else {
    console.log("Verified Workchain render returned.");
  }
} catch (error) {
  console.error(JSON.stringify({
    status: "error",
    error: error instanceof Error ? error.message : String(error),
  }, null, 2));
  process.exitCode = 1;
} finally {
  await client.close().catch(() => {});
}
