# Workchain x402 origin

This is the execution origin behind the Cloudflare Worker. It is deliberately separate from the
payment edge:

- the Worker owns the public MCP endpoint, x402 `paidTool`, Base network, recipient, and
  facilitator configuration;
- this origin owns the local Workchain checkout, FFmpeg, the deterministic demo fixture, and the
  post-run verification gate;
- the origin never receives a wallet private key and never trusts an exit code alone.

## Local run

From the repository root:

```bash
python3 demo/x402-mcp/origin/src/server.py
```

Health check:

```bash
curl -s http://127.0.0.1:8788/healthz
```

Render the allow-listed demo fixture:

```bash
curl -sS -X POST http://127.0.0.1:8788/v1/render \
  -H 'content-type: application/json' \
  -d '{"chain":"base-demo-normalization","fixture":"tone"}'
```

A successful response has `verified: true` and artifact URLs. Any missing verification record,
failed step, unreadable context, or non-zero engine exit is returned as an error instead.

## Configuration

- `WORKCHAIN_ROOT` — checkout root; defaults to this repository.
- `ORIGIN_HOST` / `ORIGIN_PORT` — bind address; defaults to `127.0.0.1:8788`.
- `PUBLIC_BASE_URL` — origin URL embedded in artifact links.
- `WORKCHAIN_BACKEND_TOKEN` — optional bearer token. Set the same value in the Worker secret
  `WORKCHAIN_BACKEND_TOKEN` when the origin is not private-network-only.
- `WORKCHAIN_ARTIFACT_ROOT` — artifact root; defaults to the system temp directory.
- `WORKCHAIN_RENDER_TTL_S` — cleanup window; defaults to one hour.

The first slice accepts only the deterministic tone fixture and
`base-demo-normalization`. Do not broaden this boundary until the hosted execution contract is
settled; arbitrary file uploads and arbitrary chain selection change the threat model.
