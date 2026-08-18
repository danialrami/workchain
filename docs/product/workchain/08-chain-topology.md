---
title: "Chain topology: from linear to two-input steps"
description: "The design home for chain topology in LUFS Workchain — today's strictly linear model, the two-input (`in2:`) primitive this unit ships, how provenance and verification compose, and what is deliberately not implemented yet (outputs-as-inputs, DAGs, more than two inputs)."
type: explanation
---

# Chain topology: from linear to two-input steps

This is the design document for chain topology in LUFS Workchain (the reference
behind [issue #10](https://github.com/lufs-audio/workchain/issues/10) and #22). It
records what the engine supports today, what the `in2:` primitive adds, and — just
as carefully — what it does **not** support yet. A format document that cannot say
"not yet" becomes a lie the moment someone assumes a feature that is not there.

## Today: strictly linear

A chain is an ordered list of steps. Each step's **primary input** is whatever the
engine is currently holding: the chain input, then the previous step's primary
output (`update_input_file` advances `context.json.input_file` after each verified
step). That is the whole topology — a straight line.

```
input.wav ──► step A ──► step B ──► step C ──► output
```

Per-step identity (unit 03) is the substrate the rest of this design stands on:
every step's record in `context.json` lives under its **effective id** (`id:` or
the component name), so two steps of the same component — or, later, a DAG where
one component appears several times — never overwrite each other's proof.

## The two-input primitive (`in2:`)

A step may declare a second input with `in2:` (issue #10):

```yaml
steps:
  - name: mix
    in2: "chains/examples/fixtures/in_b.wav"
```

The engine stages it — resolves the path/glob against CWD, demands exactly one real
audio file, refuses a self-reference, hashes it — and routes it to the component via
the single documented channel, the `WORKCHAIN_INPUT_2` env var. Provenance is
recorded under the step's id:

```json
"steps": {
  "mix": {
    "inputs": {
      "in":  { "path": "..." },
      "in2": { "path": "...", "sha256": "..." }
    }
  }
}
```

The full mechanics are specified in `docs/format.md` → *Second input (`in2:`)*.
The demo consumer is `components/mix/` (ffmpeg `amix`), whose verify contract
shows the two halves of two-input verification:

- an **independent re-measurement** against the primary timeline
  (`audio_duration_matches`: with `duration_mode: longest`, a second input longer
  than the primary stretches the mix and the check fails — the two-input
  prove-it-can-fail path); and
- a **component-written** facts sidecar about *both* inputs (`json_fields_within`),
  weaker and honestly labelled as such.

## Why provenance is the load-bearing piece

The moment a step has two inputs, "what did this step consume" is no longer implied
by the chain's position. A post-condition that wants to assert a fact about the
second input has to be able to *name* it. The `steps.<id>.inputs` record is that
name — each input's resolved path, plus a hash where practical. The verifier
exposes `resolve_input_path(ctx, step_key, "in"|"in2")` for exactly this; the
post-condition classes that consume it are a follow-up unit (the POST_CHECKS owner).

## Fail-closed rules

- `in2:` on a component without `accepts_second_input: true` → validation error.
- `in2:` resolving to zero or several files → stage-time error, step never runs.
- `in2:` resolving to the same file as the step's own primary input → stage-time
  error (a step cannot consume itself).
- Two steps declaring `in2:` keep separate records under their ids — the id model
  from unit 03 makes silent overwrite impossible.

## Deliberately out of scope (and where it goes)

- **Outputs as inputs to later steps** — an `in2:` referencing another step's
  output, i.e. a DAG edge. This unit's `in2:` accepts *paths/globs to files on
  disk* only. A reference form (e.g. `in2: {ref: <step-id>}`) is the natural next
  step: the provenance model already records every step's output paths, and the id
  model already keys them.
- **More than two inputs** — `in2:` is one extra file, full stop.
- **Fan-out / fan-in beyond one output flowing forward** — still linear after
  `in2:`; the mix output becomes the next step's primary input like any other.

Each of these is a deliberate, documented boundary, not an oversight: topology is
the one place where a half-specified format becomes a silent data-flow lie, and the
engine's thesis is that it refuses those.
