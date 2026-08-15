---
title: "FAQ"
description: "Quick answers for operators, component authors, and agents — each ≤4 lines, with a link to the dedicated page. Question not answered? Open an issue."
type: faq
---

# FAQ

Answers grouped by audience. Each answer is short, points to the dedicated page for depth,
and is written for the reader who needs the answer *now*.

---

## For operators

### Why does it say "failed" when the component exited 0?

Because exit 0 only means the script ran. Verified OUT then re-measures the output against
the declared contract — if the loudness misses, the format does not match, or the file is a
44-byte header with silence, the verifier marks it `failed` and the chain halts. The component
does not get to grade its own homework.
→ [`docs/explanation/verification.md`](explanation/verification.md)

### What does "unverified" mean?

It means the component ran but has no `verify:` contract, so nothing was proved about its
output. It is not "broken" — it is honestly labeled "not proven". Verified is the tier for
components with a proved contract; certified (roadmap) adds an ed25519 signature.
→ [`docs/explanation/verification.md`](explanation/verification.md#the-honest-limits), [`llms.txt`](../llms.txt)

### Why did my run stop at step X?

The chain halts on the first failure. If the failure is before the run — a preflight check —
you see `dependency preflight FAILED`. If it is after the run — a verify check — you see
`verification FAILED` with per-check detail lines, then `Chain halted: step 'X' failed`.
Read those detail lines; they say what was measured vs what was expected.
→ [`docs/troubleshooting.md`](troubleshooting.md)

### Do I need a venv for everything?

No. Light components (normalization, format_conversion, audio_benchmark, content_hash)
need only ffmpeg and system Python 3. Heavy components, which declare `python` or `models`
in their `requirements:`, need a venv; the registry marks them `tier: heavy`. Run
`workchain components --json` or read `components/index.json` to see which are heavy today.
→ [`docs/explanation/architecture.md`](explanation/architecture.md#tiers-two-axes-one-trust-and-one-weight),
[`README.md`](../README.md)

### What's the license, really?

Apache 2.0. The format is declared unencumbered — other implementations are welcome. What is
published here and what is not, and the reasons, are in LICENSING.md.
→ [`LICENSING.md`](../LICENSING.md), [`docs/explanation/architecture.md`](explanation/architecture.md#three-interfaces-one-parser)

### Can other engines implement the format?

Yes, deliberately. The format is unencumbered; `docs/format.md` is the reference, and the
Python library in `lib/workchain_yaml.py` is the authoritative parser. "Third-party
implementations are welcome" is the closing line of the format specification.
→ [`docs/format.md`](format.md)

### How do I report a component that lied?

Bug reports are wanted — especially "it said it worked and it didn't". Open an issue with the
chain, the input, and the measured vs expected values. Include the run log.
→ [`CONTRIBUTING.md`](../CONTRIBUTING.md)

### Why no pull requests?

Not being accepted currently, for ownership reasons stated plainly in CONTRIBUTING.md. Bug
reports are the channel wanted.
→ [`CONTRIBUTING.md`](../CONTRIBUTING.md)

---

## For component authors

### My scaffold fails — is something wrong?

No — that is the intended failure. Generated scaffolds ship with a `WORKCHAIN_NOT_IMPLEMENTED=1`
sentinel in the `run.sh`, so a scaffold can never be mistaken for a working component. Remove
the sentinel only when `run.sh` really produces output and a real `verify:` block is in place.
→ [`README.md`](../README.md), [`AGENTS.md`](../AGENTS.md)

### How do I make a parameter required?

There is no `required` key in `params_schema`. A parameter is mandatory by convention: omit
`default` from its schema entry, and add an explicit guard in `run.sh` that errors when the
value is absent. Example: `format_conversion` requires `target_format` this way.
→ [`docs/format.md`](format.md#params_schema)

### What should my verify block contain?

Always use `audio_valid` on any audio output. Declare `assert` primitives (`exists`,
`non_empty`, `audio_valid`). Add post-conditions that re-measure — `audio_lufs_within`,
`audio_format_matches`, `audio_duration_matches`. Never ship an empty verify block; if you
cannot write numeric post-conditions yet, keep the structural asserts and document the gap.
→ [`docs/explanation/verification.md`](explanation/verification.md), [`AGENTS.md`](../AGENTS.md)

### My chain validates fine but the engine rejects it — what happened?

Likely a parser gotcha: a block scalar (`>`, `|`) in a `description` field, an anchor/alias
(`&name`, `*name`), an inline comment that got included in a value, or a flow collection
spanning multiple lines. On a machine without PyYAML these produce either silent garbage or
misleading errors.
→ [`docs/troubleshooting.md`](troubleshooting.md#yaml-parser-gotchas),
[`docs/format.md`](format.md#known-limitations-and-parser-gotchas)

### How do I know my verify block will catch real failures?

Write a chain that requests an unreachable target under the true-peak ceiling — like
`chains/tests/normalization_offtarget.yaml` — and run it against a real signal. If the
verifier does not catch the miss, you have found a gap.
→ [`docs/explanation/verification.md`](explanation/verification.md#the-honest-limits),
[`AGENTS.md`](../AGENTS.md)

---

## For agents

### How do I discover components without an API key?

Read `llms.txt` for the start-here index and the five discovery calls. Read `agent.json` for
the full interface contract (exit codes, capabilities, tools). Read `components/index.json`
for the generated registry with definition hashes and tiers — no service needed. Or use
MCP's `list_components`.
→ [`docs/explanation/agent-first.md`](explanation/agent-first.md#discovery-without-an-api-key)

### What are the exit codes?

`0` success, `1` execution error, `2` input error, `3` config error. Declared in
`agent.json` `io.exit_codes`. An agent can branch on these without parsing stderr.
→ [`docs/explanation/agent-first.md`](explanation/agent-first.md#exit-codes-that-mean-something),
[`agent.json`](../agent.json)

### How do I preview a run before executing?

Pass `--dry-run` to print the planned steps and resolved parameters without executing.
Also `validate --strict` before the run to catch type errors, out-of-range values, and
missing commands. Both are cheap relative to a full run.
→ [`docs/explanation/agent-first.md`](explanation/agent-first.md#preview-before-you-spend)

### Where does progress go, and where is the result?

Progress is on stderr: newline-delimited NDJSON events. The final result is on stdout: a
single well-formed JSON object. Never scrape stdout for progress — parse stderr for that,
stdout for the final answer. This is invariant across all three interfaces.
→ [`docs/explanation/agent-first.md`](explanation/agent-first.md#structured-output-always),
[`llms.txt`](../llms.txt)

### How do I know a success claim is real?

Because Verified OUT runs after `run.sh` exits 0, re-measures the output artifacts, and only
marks the step `completed` if the declared contract passes. A component that exits 0 but
fails its contract is recorded `failed` in `context.json` and the chain halts. There is no
path from "component wrote success to its log" to "the operator sees success" — the verifier
intercepts both.
→ [`docs/explanation/agent-first.md`](explanation/agent-first.md#the-part-that-matters-most-success-is-independently-checked),
[`docs/explanation/verification.md`](explanation/verification.md)

### Can I run this over MCP?

Yes. The server exposes six tools (list_components, get_step_schema, validate_chain,
run_chain, run_component, create_component) over FastMCP with stdio or streamable HTTP.
Every tool returns a JSON string. The MCP tools drive the same engine as the CLI, so
behavior is identical regardless of interface.
→ [`docs/explanation/agent-first.md`](explanation/agent-first.md#mcp-as-a-native-interface),
[`llms.txt`](../llms.txt)

---

## Question not answered?

Open an issue — bug reports are exactly wanted, especially "it said it worked and it didn't".
Include the chain, input, observed output, and what you expected.
→ [`CONTRIBUTING.md`](../CONTRIBUTING.md)