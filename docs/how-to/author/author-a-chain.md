---
title: How to author a chain
description: Sequence verified components into a declarative YAML chain — chain anatomy, parameter precedence, and the parser rules that keep the same file meaning the same thing on every machine.
type: how-to
---

# How to author a chain

A **chain** is one YAML file that sequences named components against an input file. It is the
unit you run: the engine resolves parameters for every step, preflights each component's inbound
`requirements:` before it runs, executes `run.sh`, then enforces the outbound `verify:` contract
before the step's output becomes the next step's input. If any step fails — preflight, run, or
verification — the chain stops there.

The living specification is [`docs/format.md`](../../format.md). Read it when a question here
gets too deep; this page is the working procedure. The full format is also exercised by the
annotated example at the bottom of `docs/format.md` (`chains/deliverable-voice.yaml` and
`components/format_conversion/step.yaml`).

## Chain anatomy

A chain file is a YAML mapping with three required fields and a handful of optional ones:

| Field | Required | Meaning |
|---|---|---|
| `name` | yes | Human-readable chain name. |
| `version` | yes | Chain version. Semver by convention (`"1.0"`). |
| `steps` | yes | A list of one or more step entries. Must be non-empty. |
| `description` | no | What this chain is for. **Single-line quoted string** — block scalars are rejected (see [YAML gotchas](#yaml-gotchas-the-weakest-parser-rule)). |
| `engine_version` | no | Minimum engine version. Stored for documentation; not enforced by any current engine code. |
| `globals` | no | Key/value pairs offered to every step as lower-precedence parameters (see [Parameter precedence](#parameter-precedence)). |

Each entry in `steps` is:

| Key | Required | Meaning |
|---|---|---|
| `name` | yes | Must match a subdirectory under `components/` that contains `step.yaml` and `run.sh`. |
| `enabled` | no | Default `true`. `false` skips the step entirely — no execution, no verification. |
| `params` | no | Per-step parameter overrides. These win over everything (see below). |

A minimal valid chain is three lines:

```yaml
name: "My Chain"
version: "1.0"
steps:
  - name: normalization
```

A realistic one — convert to the delivery format, then normalize:

```yaml
name: "Deliverable: Voice / Dialogue"
description: "Prep a recording to a VO spec: WAV, 48 kHz, 24-bit, mono, ~-21 LUFS."
version: "1.0"

globals:
  lufs_target: -21

steps:
  - name: format_conversion
    enabled: true
    params:
      target_format: wav
      sample_rate: 48000
      bit_depth: 24
      channels: 1

  - name: normalization
    enabled: true
    params:
      target_lufs: -21
      two_pass: true
```

## Parameter precedence

Every parameter a component reads has exactly three possible sources, resolved in ascending
priority — a step param **beats** a global, which **beats** the schema default:

1. **Schema default** — the `default` declared in the component's `params_schema` entry.
2. **Chain `globals`** — values from the chain's `globals` mapping. A global whose key matches
   no param in the component's schema is silently dropped.
3. **Step `params`** — the step's own values. These win unconditionally.

The engine resolves this and hands the merged result to `run.sh` as `STEP_CONFIG`; `run.sh`
reads it with `get_param`. **Components never re-implement precedence** — they read what the
engine resolved. The verifier sees the same resolved params, so a check like
`audio_lufs_within` measures the output against the target the step actually ran with, not the
schema default.

To see the resolved values before running anything, read `context.json` under
`steps.<name>.params` after a run, or use `workchain run <chain> <input> --dry-run`.

### The `lufs_target` legacy alias (normalization only)

Before the loudness param was renamed, chains set `globals.lufs_target`. Those chains still
work: if `globals.lufs_target` is set, the step is `normalization`, and `target_lufs` is not in
the step's own `params`, the resolver copies `lufs_target` into `resolved.target_lufs`. The
alias exists **only** for that backward-compatibility case — for new chains, set
`target_lufs` directly in the step params and ignore the legacy alias.

## Validate before you run

`workchain validate <chain> --strict` is a static gate you run while writing, before the engine
touches anything. Non-strict mode checks structure (required fields, step names resolve to real
components); `--strict` adds schema-aware checks — param types, numeric ranges, unknown
params — and *reports* missing declared commands as environment findings rather than errors (a
chain isn't authoring-invalid just because ffmpeg isn't on the validating machine; at runtime
the engine fails it for real).

```bash
$ workchain validate deliverable-voice --strict
{
  "status": "completed",
  "command": "validate",
  "chain_file": "chains/deliverable-voice.yaml",
  "chain_name": "deliverable-voice",
  "display_name": "Deliverable: Voice / Dialogue",
  "steps_count": 3,
  "strict": true
}
```

`workchain validate all --strict` checks every chain in `chains/`.

Then run it:

```bash
workchain run deliverable-voice track.wav -o ./out --json
```

## YAML gotchas — the weakest parser rule

The engine has a PyYAML fast path and a dependency-free stdlib fallback, and the format is
defined as **what the weakest supported parser can read**. The two parsers must never disagree
about what a file means, so `lib/workchain_yaml.py` runs a reject list on **both** paths: any
chain using one of these constructs is refused with an error that names the construct and the
line. That is deliberate — a construct that parses differently depending on what is installed
would make the same file mean different things on different machines.

The rejected constructs:

- **Block scalars (`>` and `|`)** — use a single-line quoted string.
  ```yaml
  # REJECTED — would also break on the stdlib path:
  description: >
    A long description
    spanning multiple lines.

  # Correct:
  description: "A long description spanning multiple lines."
  ```
- **Anchors (`&name`) and aliases (`*name`)** — write the value out.
- **Merge keys (`<<:`)** — write the keys out.
- **Multi-line flow collections** — a `[` or `{` must open and close on the same line:
  ```yaml
  # REJECTED:
  params:
    checks: [
      "format",
      "loudness"
    ]

  # Correct:
  params:
    checks: ["format", "loudness"]
  ```

Inline comments follow the YAML rule: a `#` begins a comment only after whitespace and outside
quotes. The fallback parser strips them the same way PyYAML does — `name: a # b` is `a`, while
`name: a#b` stays `a#b`. (This was not always true; the older behaviour is why some component
READMEs warn about trailing comments. Keep comments on their own lines and you cannot lose.)

One thing that looks like a trap but is not: a colon inside an unquoted value is fine —
`description: Audio: a description` parses correctly on both paths.

For the full write-up of each construct, what breaks, and the failure symptoms, see
**Known Limitations and Parser Gotchas** in [`docs/format.md`](../../format.md). The summary
rule: if it is not in the weakest parser's subset, the file is rejected loudly — never
silently repaired, never silently misread.