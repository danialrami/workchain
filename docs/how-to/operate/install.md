---
title: Install Workchain
description: How to install the Workchain CLI, satisfy requirements, and verify everything works — with notes on the light vs heavy component model.
type: how-to
---

# Install Workchain

## Requirements

Before installing, ensure these are on `PATH`:

| Tool | Version | Why |
|------|---------|-----|
| Node.js | >= 18 | CLI runtime |
| Python | >= 3.10 | Engine, heavy components, and MCP server |
| ffmpeg / ffprobe | any recent | Every audio component depends on these |

Check them:

```bash
node --version          # v18+
python3 --version       # 3.10+
ffmpeg -version | head -1
ffprobe -version | head -1
```

> **GPU note:** The heavy `stem_separation` component benefits hugely from CUDA (NVIDIA) or Apple MPS. For CPU-only runs expect slow throughput — BS-RoFormer takes minutes for tens of seconds of audio.

## Install the CLI

From the workchain repository root:

```bash
npm install       # root manifest: the CLI's runtime dependencies
cd cli
npm install       # cli manifest: vitest only (test tooling)
npm link
```

This installs the `workchain` command globally. Verify:

```bash
workchain --version   # 0.1.0 (or later)
workchain --help      # all commands and exit codes
```

> **Permission denied on `npm link`?** The global npm prefix may be root-owned
> (`/usr`). Set it to a writable directory and retry:
> ```bash
> npm config set prefix ~/.local   # must be on PATH
> npm link
> ```

### Run without npm link

If you prefer not to link globally, run the local binary directly from the repo root:

```bash
node cli/bin/workchain.js --help
node cli/bin/workchain.js run deliverable-voice in.wav -o ./out --json
```

## Verify the install — `workchain doctor`

```bash
workchain doctor
```

Prints a per-component health check. Expected output on a fresh install:

```
  ✓ audio_benchmark        ok
  ✓ cdp_transform          ok
  ✓ content_hash           ok
  ✓ format_conversion      ok
  ✓ normalization          ok
  ✗ stem_separation        missing  missing: python:venv
doctor: 5 ok, 1 missing deps, 0 no-deps (of 6)
```

All light components pass. The heavy `stem_separation` component predictably reports
`missing: python:venv` — that is expected and intentional; it requires explicit provisioning
(see [Provision Heavy Components](./provision-heavy-components.md)).

Machine-readable variant:

```bash
workchain doctor --json
```

Returns a JSON object with per-component state (`ok` / `missing`) and failure reasons.

### Deep check

```bash
workchain doctor --deep
```

Also verifies model file content hashes (SHA-256). On a new install the missing-venv
components skip hash checks, so the output is the same as without `--deep`.

## Light vs heavy components

Workchain components are tiered by their install footprint:

| Tier | Components | What they need | Ships in npm core |
|------|-----------|---------------|-------------------|
| **light** | `normalization`, `format_conversion`, `audio_benchmark`, `content_hash`, `cdp_transform` | ffmpeg + system python3; `cdp_transform` additionally needs the `cdp-wasm` Node package (`npm install cdp-wasm`, or set the `cdp_wasm_dir` param / `CDP_WASM_DIR` env) | Yes — `cdp-wasm` rides as an optional dependency of the npm package |
| **heavy** | `stem_separation` | Python venv + `audio-separator` + model weights (auto-downloaded on first use) | No — explicit provisioning |

The authoritative source for which tier a component belongs to is its entry in
[components/index.json](../../../components/index.json) — read with `workchain components --json`.

> **`cdp_transform` gotcha:** it is tier `light` but its `cdp-wasm` dependency is not
> expressible in the `commands` preflight class. `transform.mjs` resolves `cdp-wasm` itself
> and fails with install instructions if it is absent (“cannot resolve the cdp-wasm
> library… Install it (npm install cdp-wasm)”). Install it at the repo root (or any
> `node_modules` above the component) once per clone.

## What next

- See the [README.md](../../../README.md) for the full architecture and design.
- [Configure Workchain](./configure.md) — set defaults, paths, and preferences.
- [Run Chains](./run-chains.md) — execute a processing chain on audio.
- [Provision Heavy Components](./provision-heavy-components.md) — set up `stem_separation`.

