---
title: "Architecture: a filesystem registry, one shared parser, and two contracts around every run"
description: "How LUFS Workchain is put together — components as a folder registry, the preflight → run → verify execution flow, parameter precedence, the single parser behind three interfaces, and the two tier systems. Thesis-led; the specification is docs/format.md."
type: explanation
---

# Architecture: why the pieces are shaped the way they are

Workchain exists because audio DSP almost never crashes — it produces *something*, and a
pipeline that only checks exit codes cannot tell a stretched sound from an empty file. The
architecture is the answer to that problem, in three pieces:

1. **The filesystem is the registry.** A component is a folder — there is no database, no
   hand-maintained list, nothing that can drift away from what actually ships.
2. **Every run walks the same gates.** Parse → resolve → preflight (Verified IN) → run →
   verify (Verified OUT) → hand the result to the next step. A step that fails a gate halts
   the chain.
3. **Every interface shares one parser.** The Bash engine, the Node CLI, and the Python MCP
   server all resolve YAML through the same module, so none of them can silently disagree
   about what a chain means.

This page is the "why". For the "what" — exact fields, keys, defaults — read
[`docs/format.md`](../format.md), and for the verification doctrine behind gate 2 read
[`docs/explanation/verification.md`](./verification.md).

## A component is a folder — the filesystem is the registry

```
components/<name>/
├── step.yaml   # the contract: params, outputs, requirements (Verified IN), verify (Verified OUT)
├── run.sh      # the work — `return`, never `exit`; the engine sources it
└── README.md   # measured values, edge cases, tier
```

The registry is `ls components/`. There is no database to corrupt, no service to provision,
and — critically — no second source of truth to keep in sync. The one generated artifact,
[`components/index.json`](../../components/index.json), is produced by
`lib/workchain_registry.py generate` and contains each component's name, description, tier,
params, requirements, verify summary and a SHA-256 **definition hash** over the component's
tracked source (excluding `.venv/`, `models/`, caches). It is regenerated from the folders,
never hand-edited, and `workchain registry check` fails if it is stale — that check is a CI
gate.

Why a definition hash at all? Because a component's *identity* must include what it does, not
just what it is called. The hash is what `certified` will eventually sign (see
[Tiers](#tiers-two-axes-one-trust-one-weight)).

Workchain used to carry a hand-written component list in `llms.txt`. It drifted — it went
stale the first time a component was added and silently under-reported what the registry
actually held. It was removed rather than corrected: *an enumeration that can drift eventually
will*. If you find yourself wanting to list components in prose, resist — point at the index
instead.

## Chain execution flow

A chain is a YAML file: `name`, `version`, optional `globals`, and `steps[]`. Each step names
a component and optional per-step `params`. Execution is one pass, and the pass looks like
this for every step:

1. **Parse & resolve.** The chain is parsed and every step's effective parameters are
   resolved. See [Parameter precedence](#parameter-precedence).
2. **Verified IN — preflight.** `lib/workchain_preflight.py` checks the step's declared
   `requirements:` (commands, python, node, models, env) *before* `run.sh` executes. A
   missing dependency halts the step with a clear message instead of letting it half-run.
3. **Run.** The engine sources `run.sh` with the resolved config. Logging goes to stderr;
   stdout stays clean.
4. **Verified OUT — verify.** After a clean exit, `lib/workchain_verify.py` checks the
   step's declared `verify:` contract against the actual artifacts on disk. A step that
   exits 0 but fails its contract is recorded `failed`, not `completed`, and the chain
   halts.
5. **Handoff.** The step's outputs are registered into `context.json`; the primary output
   becomes the next step's input. Wrap around to step 1.

Two flow details worth knowing:

- A step with `enabled: false` is skipped entirely — no execution, no verification.
- The chain halts on the first failure. Output like `Chain halted: step 'normalization'
  failed` is not a warning; it is the engine refusing to feed a failed step's output into the
  next one.

The concrete, runnable examples of this flow are the test chains under
[`chains/tests/`](../../chains/tests/) — each is a real chain exercises both gates.

## Context handoff

Each step reads and writes a shared `context.json` in the output directory. It carries the
input file name, the output directory, per-step resolved params, registered outputs, and
verification reports. `run.sh` reads its config from `context.json`; the verifier reads the
resolved params from the same place — which is how the verifier knows the *target* of a
loudness check without trusting the component's own logs.

## Parameter precedence

A component declares its parameters in `params_schema` with types, defaults, and ranges.
Three sources can supply a value, and they resolve in ascending priority:

| Priority | Source | Notes |
|---|---|---|
| 1 | schema `default` | The baseline. |
| 2 | chain `globals` | Filtered to keys the component actually declares; unmatched keys are silently dropped. |
| 3 | step `params` | Win over globals and defaults unconditionally. |

The resolution happens in one place — `lib/workchain_yaml.py` — and the merged result is what
the component sees. Components must never re-implement precedence, because two implementations
of precedence is the same defect class as two parsers (see below). One legacy wrinkle exists
and is documented rather than hidden: `globals.lufs_target` is aliased to `target_lufs` for
the `normalization` step only, for backward compatibility with pre-rename chains.
See [`docs/format.md`](../format.md) for the full rules.

## Three interfaces, one parser

```
engine/       Bash        ./engine/workchain-engine.sh -c chain.yaml in.wav -o out/
cli/          Node        workchain run <chain> <input> --json
mcp-server/   Python      list_components · get_step_schema · validate_chain · run_chain · run_component · create_component
```

All three parse chains, resolve parameters, and validate schemas through
`lib/workchain_yaml.py`. There is no fourth parser, and **adding one is the architectural
mistake this layout exists to prevent**: three interfaces that disagree about what a chain
means are three different products.

The single parser is also a portability story. On machines without PyYAML the same module
falls back to a dependency-free stdlib parser, and `_reject_unsupported()` refuses — on both
paths — any YAML construct the weakest parser cannot read (block scalars, anchors/aliases,
merge keys). The governing rule: *the format is what the weakest supported parser can read*.
A chain that loads here loads everywhere. A chain that would parse differently on another
machine is refused loudly at validation time rather than executed with different meaning.

The same fail-closed instinct removed a whole class of gate: `engine/chain-validator.sh` used
to be a second, independent, grep-based validator. When it disagreed with the Python
validator it failed **open** — reporting "Chain validation passed" for a file the engine
would reject — which is the worst direction for a gate. It is now a thin delegate to the
Python validator and holds no validation logic of its own. Two implementations of "is this
chain valid?" is the same defect class as a component that exits 0 while producing silence.

Known parser limitations and how to avoid them are catalogued in
[`docs/format.md`](../format.md), and as symptom → cause → fix entries in
[`docs/troubleshooting.md`](../troubleshooting.md).

## Tiers: two axes, one trust and one weight

Workchain has two independent tier systems, and confusing them is a common source of wrong
expectations:

- **Registry tiers — `light` / `heavy`** are about *weight*: `heavy` if the component's
  `requirements` declares `python` or `models`, else `light`. Light components ship in the
  lean npm core and run on ffmpeg + system python3 alone. Heavy components are provisioned
  separately (`uv sync`). Which components are heavy changes over time — read
  `components/index.json`, don't trust a list written in prose.
- **Verification tiers — `unverified` / `verified` / `certified`** are about *trust*:
  `unverified` means "ran, but no contract proved it", `verified` means "fell off its own
  declared contract in an automated run". `certified` — an ed25519 signature over the
  component's definition hash — is on the roadmap, not yet implemented. See
  [`docs/explanation/verification.md`](./verification.md).

## What the layout buys you

One registry (no drift), one parser (no disagreement), one execution flow (no skipped gates),
two contracts per component (no unproven success claims). Everything else in the repo —
including why the three interfaces are designed for agents — hangs off those four decisions.

- Specification: [`docs/format.md`](../format.md)
- Verification doctrine: [`docs/explanation/verification.md`](./verification.md)
- Agent-first rationale: [`docs/explanation/agent-first.md`](./agent-first.md)
- The pitch: [`README.md`](../../README.md) · agent operating notes: [`AGENTS.md`](../../AGENTS.md)