---
title: "Porting the personal Workchain tree"
description: "Provenance, scope, repairs, and exclusions for the personal component port into the current Workchain fork."
type: explanation
---

# Porting the personal Workchain tree

This fork keeps the current upstream release as its base and reintroduces the runtime additions
from the older personal tree as a reviewable, portable layer.

## Base and provenance

- Upstream/fork base: `fb8274676d3ad09c2f15fd8be30ea50b91d1e870`.
- Personal source snapshot: `487b46526c0938eab87391de3dc862f372e4902c`.
- The two histories were squashed independently, so this is a tree port rather than a clean
  commit-range cherry-pick.
- Overlapping `lib/`, `engine/`, `cli/`, and `mcp-server/` files remain upstream-first. The port
  does not replace the newer parser, verifier, CLI, or MCP implementation wholesale.

## Ported runtime additions

- Fifteen self-contained components: acoustic encode/decode, archive indexing, artwork, Canvas,
  catalog, lightweight and CLAP embeddings, feature extraction, hook rendering, probing,
  protection, seeded randomness, setup, and the parameterized FX scaffold.
- The personal archive-ingest and asset chains, plus their chain fixtures.
- Decode-integrity and contract regression tests. The large historical audio fixture is generated
  by the tests or CI instead of being copied into the public tree.
- The Base x402 demo: a deterministic verified-normalization chain, a standard-library HTTP
  origin, a Cloudflare Agents SDK paid MCP Worker, and a recordable x402 buyer.

## Port repairs made while proving the tree

- Fixed three legacy shell-quoting defects in the archive/embed wrappers so every new shell file
  passes `bash -n`.
- Replaced an absolute developer checkout path in artwork generation with portable local/global
  lookup and a deterministic fallback.
- Kept the FX scaffold honest with an executable not-implemented sentinel; it fails until real
  processing exists instead of registering a phantom output.
- Made setup persist `logs/setup.json` and added a real structural verification contract.
- Removed personal hostnames, local checkout paths, and stale CLI names from the port.
- Regenerated `components/index.json` from the filesystem registry.

## Deliberate exclusions

Historical private planning/session notes, reference screenshots, the old personal dependency
lock, and the 61 MB audio fixture are not copied into this public-facing fork. They are not needed
to run the components or the demo, and carrying them forward would publish stale environment
assumptions rather than provenance that helps an operator.
