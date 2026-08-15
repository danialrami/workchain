---
title: "Agent-first design: interfaces built for machines that cannot listen"
description: "Why LUFS Workchain's interfaces are designed for agents — structured output on stdout, NDJSON progress on stderr, meaningful exit codes, --dry-run and validate --strict, machine-readable discovery (llms.txt, agent.json, components/index.json), MCP as a native interface, and the part that matters most: an agent's success claim is independently checked. The canonical home for the agent-readiness rationale."
type: explanation
---

# Agent-first design

LUFS Workchain is an audio processing engine whose operator is often not a human. It is
designed, on purpose, to be driven by programs — and the design is not cosmetics. This is the
canonical home for *why the interfaces are designed for agents*; the discovery files that
realize it are [`llms.txt`](../../llms.txt), [`agent.json`](../../agent.json), and the
generated [`components/index.json`](../../components/index.json).

The surface, in one line: one engine behind three doors — a Node CLI (`workchain`), a FastMCP
server, and a Bash engine — all speaking the same conventions. All three parse chains through
the same parser (see [`docs/explanation/architecture.md`](./architecture.md)), so an agent
gets identical schemas and behavior no matter which door it walks through.

## The problem an agent has with audio

An agent cannot listen. A human operator gets the post-condition of playback for free — the
ear fires automatically and cannot be fooled by a byte count. Automation deletes that sensor.
An agent is left with an exit code, and an exit code cannot tell the difference between a
stretched sound and an empty file.

So an agent-first design has to give the agent the primitives the ear used to provide:

1. output it can parse without scraping prose;
2. a way to preview what a run will do *before* it spends compute on it;
3. failure that means something, in a form it can branch on;
4. and success it can trust, because success was checked by something other than the thing
   that reported it.

Each convention below maps to one of those four.

## Structured output, always

`--json` is on everything. The rule is simple and invariant: **stdout carries the final JSON
result; stderr carries newline-delimited NDJSON progress events.** An agent can consume
progress from stderr line-by-line without buffering, and the final result is always the last
well-formed JSON on stdout. Nothing is ever printed to stdout except that result — a corrupted
stdout is a corrupted contract, so the engine keeps it clean. (See [`AGENTS.md`](../../AGENTS.md):
"stdout is the final JSON; all logging goes to stderr.")

## Exit codes that mean something

The CLI's exit codes are part of the interface contract, declared in `agent.json`:

| Code | Meaning |
|---|---|
| `0` | success |
| `1` | execution error |
| `2` | input error |
| `3` | config error |

An agent can branch on these without parsing prose: retry on `1`, fix the input on `2`, fix
its own configuration on `3`.

## Preview before you spend

- `--dry-run` prints the plan — the chain, the steps, the resolved parameters — without
  executing it. An agent that previews first never discovers a bad parameter value at the
  bottom of a long run.
- `validate --strict` checks structural validity *plus* param types, numeric ranges, unknown
  params, and required-command availability (Verified IN) before a run. The strict validation
  path is the agent's cheap way to ask "will this even start?" without starting it.

## Discovery without an API key

An agent should be able to discover everything it needs from static, checkable files — no
service to call, no credentials to hold:

- **`llms.txt`** — the start-here index: the pitch, the prime directive, and "agent discovery
  in 5 calls" — `workchain --help`, `components --json`, `component <name> --json`,
  `chains --json`, and `run --dry-run --json`.
- **`agent.json`** — the machine contract: schema version, interfaces (CLI and MCP) with
  their io conventions and exit codes, a `capabilities` list mapping each capability to its
  CLI command and MCP tool, the verification model, and the registry rules.
- **`components/index.json`** — the generated component registry: name, description, tier,
  params, requirements, verify summary, and a SHA-256 definition hash per component — kept
  fresh by a CI gate, so it is stable and checkable. The live, always-current view is
  `workchain components --json`.

Deliberately, the component list is *not* duplicated in prose anywhere (see
[`docs/explanation/architecture.md`](./architecture.md)); the generated index is the list.

## MCP as a native interface

The MCP server is not an afterthought bolted onto the CLI — it is a first-class interface
with its own six tools (`agent.json` / `mcp-server/server.py`):

- `list_components` — everything installed;
- `get_step_schema` — a component's full schema (params with types and ranges, declared
  outputs, requirements);
- `validate_chain` — validate before running (`strict=true` by default);
- `run_chain` / `run_component` — execute a chain or a single component;
- `create_component` — scaffold a new component.

Every tool returns a JSON string, over stdio (default) or streamable HTTP. Because all six
shell out to the same engine that the CLI drives, an MCP agent sees exactly the behavior a
CLI agent sees — one parser, one flow, one verification pass.

## The part that matters most: success is independently checked

All of the above is ergonomics. The part that matters is this: **when an agent reports that a
step succeeded, that claim has been independently checked.**

After `run.sh` exits 0, `lib/workchain_verify.py` checks the step's declared `verify:`
contract against the actual artifacts — re-measuring loudness with ffmpeg, re-probing format
with ffprobe, recombining stems on disk. A component that exits 0 but fails its contract is
recorded `failed`, never `completed`, and the chain halts. There is no way for an agent's
success claim to outrun the verifier, because the verifier runs *before* the output feeds the
next step and *before* the run reports success (`agent.json`, `contract.honest_failure`).

That single property is what makes the rest of the agent-readiness worth having. Structured
output, exit codes, preview, and discovery make Workchain *easy* for an agent to operate;
independent verification makes it *safe* to believe.

- How the verification works, in depth: [`docs/explanation/verification.md`](./verification.md)
- How the pieces fit: [`docs/explanation/architecture.md`](./architecture.md)
- The pitch and the shape of the whole idea: [`README.md`](../../README.md)