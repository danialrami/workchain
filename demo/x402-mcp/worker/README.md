# Cloudflare x402 payment edge

This Worker is the first Base-native payment slice for Workchain.

```text
MCP client ── /mcp ──> Cloudflare Agents SDK / paidTool
                         │
                         ├─ 402 Payment Required
                         ├─ x402 facilitator verifies + settles USDC
                         └─ paid handler ──HTTPS──> Workchain origin
                                                     │
                                                     └─ Bash engine → verifier → artifact
```

The Worker does **not** run FFmpeg and does not accept arbitrary user file paths. It charges for
one allow-listed tool, `render_verified_demo`, which asks the origin to generate a deterministic
tone, run `base-demo-normalization`, and return only when the `context.json` verifier records are
clean. This keeps the hosted edge auditable while the origin can later move to a dedicated runner
or container.

## Payment configuration

- Production default: `X402_NETWORK=eip155:8453` (Base mainnet).
- Fallback: `X402_NETWORK=eip155:84532` (Base Sepolia) with test USDC from the Circle faucet.
- Settlement: `https://x402.org/facilitator` by default.
- Price: `$0.01` per `render_verified_demo` call in this first slice.
- Asset: the facilitator-selected exact EVM USDC route for the configured network.
- Recipient: `MCP_ADDRESS`, supplied as a Wrangler secret or environment variable. There is no
  recipient address in this repository.

`paidTool` returns an MCP payment-required result on the first call without payment. A compliant
client signs the payment in its wallet, retries with `_meta["x402/payment"]`, and receives the tool
result plus settlement metadata after the facilitator settles it.

## Local development

The Worker and origin are two processes. Start the origin from the repository root:

```bash
python3 demo/x402-mcp/origin/src/server.py
```

Then from this directory:

```bash
cp .dev.vars.example .dev.vars
npm ci
npm run types
npm run dev
```

For a local no-wallet smoke check, call the origin directly. To test the actual 402 retry path, use
Base Sepolia first; a test wallet must hold test USDC and the Worker must use
`X402_NETWORK=eip155:84532`.

## Deploy

Install the locked dependencies, generate types, and set secrets through Wrangler. Do not put private keys in
`.env`, `wrangler.jsonc`, or Git:

```bash
npm ci
npm run types
npx wrangler secret put MCP_ADDRESS
npx wrangler secret put WORKCHAIN_ORIGIN_URL
npx wrangler secret put WORKCHAIN_BACKEND_TOKEN
npm run deploy
```

`WORKCHAIN_ORIGIN_URL` must be an HTTPS origin reachable by the Worker. `WORKCHAIN_BACKEND_TOKEN`
is optional at the origin, but should be set on both sides if the origin is publicly routable.
`MCP_ADDRESS` is the Base recipient wallet, not a buyer private key.

The production deployment is not claimed complete until all of these are true:

1. `GET /healthz` reports the expected network.
2. An unpaid `tools/call` returns the x402 payment-required response.
3. A funded Base wallet pays and retries the tool call.
4. The response carries a successful settlement result.
5. The returned payload has `verified: true` and an artifact can be fetched.
6. A deliberately broken origin response remains an MCP error; it must never become a paid false
   success.

## Version note

The code follows Cloudflare's current Agents SDK x402 MCP example and x402 v2 conventions: CAIP-2
network identifiers (`eip155:*`) and the `PAYMENT-REQUIRED`, `PAYMENT-SIGNATURE`, and
`PAYMENT-RESPONSE` flow. Pin and refresh the Worker lockfile from the package registry before a
production deploy; do not use a floating `agents` dependency in the deployed artifact.
