# Recordable x402 buyer

This is the buyer-side script for the demo. It uses the current x402 v2 TypeScript client to:

1. connect to the Workchain MCP endpoint;
2. discover the paid tool;
3. receive and print the payment-required challenge;
4. sign an exact EVM payment when explicitly approved;
5. retry the call and print the settlement receipt plus the verified Workchain result.

## Setup

```bash
cp .env.example .env
# Put a funded buyer key in .env locally; do not paste it into chat or commit it.
npm ci
```

For a safe connection/discovery check, leave `AUTO_APPROVE=false`. For an intentional Base Sepolia
run, fund the wallet with test USDC, set `X402_NETWORK=eip155:84532`, and set `AUTO_APPROVE=true`.
For the production demo, use `X402_NETWORK=eip155:8453` and a wallet with real USDC only after the
team has reviewed the recipient, price, and origin URL.

```bash
npm run run
```

The output is designed to be screen-shareable: it labels the 402 challenge, network, amount,
payment recipient, transaction/settlement response, and the final `verified: true` result. A
payment rejection or an unverified origin result exits non-zero.
