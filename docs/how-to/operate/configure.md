---
title: Configure Workchain
description: How to manage Workchain CLI configuration — set the repository root, backend, and defaults. Config keys, subcommands, where config lives on disk, and env-var overrides.
type: how-to
---

# Configure Workchain

## Configuration keys

The config schema declares five keys:

| Key | Default | Description |
|-----|---------|-------------|
| `workchainRoot` | — (auto-discovered) | Path to the workchain repository. Auto-detected by walking up from the CLI binary; set this to pin it explicitly. |
| `server` | `"local"` | Backend. `"local"` for local execution; reserved for a hosted MCP tier. |
| `defaultChain` | `"deliverable-voice"` | Declared in the schema as the default chain for `run`; **reserved — `run` currently requires a chain argument** (see below). |
| `outputDir` | `"./output"` | Declared in the schema as a default output directory; **reserved — without `-o`, `run` writes to a fresh `./output_YYYYMMDD_HHMMSS` dir** (see below). |
| `concurrency` | CPU count − 1 (min 1) | Max parallel chains; **reserved for future use** — execution is currently sequential. |

> **Honest note:** `defaultChain` and `outputDir` are declared in `cli/lib/config.js` but the
> current CLI does not read them yet. `workchain run` takes the chain as a positional
> argument, and the default output directory when `-o` is omitted is timestamped
> (`./output_20260815_070108`), not `./output`. Treat those two keys as forward
> declarations, not live behavior.

## Subcommands

### Set a value

```bash
workchain config set workchainRoot /path/to/workchain
workchain config set server local
```

`workchainRoot` is the one you will actually need, and only when the CLI cannot
auto-discover the repo (for example a globally installed binary with no repo above it).

### Get a value

```bash
workchain config get workchainRoot   # prints the path
```

### List all values

```bash
workchain config list
```

Output:

```
workchainRoot:
server: local
defaultChain: deliverable-voice
outputDir: ./output
concurrency: 1
---
Config file: /path/to/.config/workchain-nodejs/config.json
```

Machine-readable:

```bash
workchain config list --json
```

### Delete a key

```bash
workchain config delete outputDir
```

The key reverts to its schema default.

### Reset

```bash
workchain config reset
```

Clears all overrides; every key returns to its default.

### Invalid key

An unknown key exits with code 2 and a message listing the valid keys:

```
Warning: Invalid config key: "bogusKey". Valid keys: workchainRoot, server, defaultChain, outputDir, concurrency
```

## Where config lives on disk

The config file is managed by [`Conf`](https://github.com/sindresorhus/conf) via
[`env-paths`](https://github.com/sindresorhus/env-paths), project `workchain-nodejs`:

| OS | Config path |
|----|------------|
| Linux | `$XDG_CONFIG_HOME/workchain-nodejs/config.json` (default `~/.config/workchain-nodejs/config.json`) |
| macOS | `~/Library/Preferences/workchain-nodejs/config.json` |
| Windows | `%APPDATA%\workchain-nodejs\Config\config.json` |

`workchain config list` prints the resolved path under `Config file:`.

## Environment variable overrides

These override config keys without touching the config file (handy in CI or per session):

| Env var | Overrides |
|---------|-----------|
| `LUFS_WORKCHAIN_ROOT` | `workchainRoot` |
| `LUFS_WORKCHAIN_SERVER` | `server` |
| `LUFS_WORKCHAIN_DEFAULT_CHAIN` | `defaultChain` |
| `LUFS_WORKCHAIN_CONCURRENCY` | `concurrency` |

Env vars take precedence over the config file. Active overrides are listed in
`workchain config list --json` under `_envOverrides`.

## Resolving the workchain root

The CLI finds the repository root in this order:

1. `LUFS_WORKCHAIN_ROOT` env var (must contain `engine/workchain-engine.sh`)
2. `workchainRoot` config key
3. Walking up from the CLI binary's own location

If none succeed, the CLI exits with code 3 and a message telling you how to set it
(`workchain config set workchainRoot /path/to/workchain`).

## What next

- [Run Chains](./run-chains.md) — execute a processing chain on audio (this is where output directories are actually chosen).
- [Run Components](./run-components.md) — run a single component standalone, batch-process a directory.