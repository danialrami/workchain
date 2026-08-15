---
title: Inspect a Run
description: How to read a Workchain run result — the stdout JSON contract, stderr NDJSON progress stream, exit codes, context.json, verify verdicts (completed / failed / skipped / unverified), and a verification FAILED block.
type: how-to
---

# Inspect a Run

Every `workchain run` produces three things: a final JSON result on **stdout**, an NDJSON
progress stream on **stderr**, and a `context.json` in the output directory. Knowing how to
read all three is how you tell "proven correct" from "exited 0".

## The run result contract

- **stdout** — exactly one JSON document, the final result (`--json`). Never mixed with logs.
- **stderr** — newline-delimited JSON (NDJSON): one `progress` event per line.
- **exit code** — 0 / 1 / 2 / 3 (see table below).
- **`context.json`** — the engine's full run record, written to the output directory.

## A real stdout JSON result

This is the actual `status: "completed"` result from running
`workchain run chains/deliverable-voice.yaml test-dialogue.wav -o /tmp/run-out --json`
(a 10 s, 48 kHz mono dialogue tone; input integrated −24.23 LUFS):

```json
{
  "status": "completed",
  "command": "run",
  "chain": "chains/deliverable-voice.yaml",
  "input_file": "/tmp/test-dialogue.wav",
  "input_name": "test-dialogue",
  "input_ext": "wav",
  "output_dir": "/tmp/run-out",
  "duration_ms": 3787,
  "steps": {
    "format_conversion": {
      "params": { "bit_depth": 24, "channels": 1, "sample_rate": 48000, "target_format": "wav" },
      "preflight": { "component": "format_conversion", "satisfied": true, "checks": [
        { "name": "command:ffmpeg", "ok": true, "detail": "on PATH" },
        { "name": "command:ffprobe", "ok": true, "detail": "on PATH" }
      ], "failures": [], "checked_at": "2026-08-15T06:56:50Z", "resolved_params": {
        "preserve_quality": true, "bitrate": "320k", "lufs_target": -21,
        "bit_depth": 24, "channels": 1, "sample_rate": 48000, "target_format": "wav" } },
      "outputs": {
        "primary_output": { "path": "/tmp/run-out/test-dialogue_converted.wav",
          "type": "file", "exists": true, "description": "Converted audio file",
          "path_template": "{input_name}_converted.{target_format}", "target_format": "wav",
          "preserve_quality": true, "bitrate": "320k" } },
      "output": "/tmp/run-out/test-dialogue_converted.wav",
      "output_dir": "/tmp/run-out",
      "status": "completed",
      "verification": {
        "component": "format_conversion", "tier": "verified", "verified": true,
        "checks": [
          { "name": "primary_output.exists", "ok": true, "detail": "path=/tmp/run-out/test-dialogue_converted.wav" },
          { "name": "primary_output.non_empty", "ok": true, "detail": "1440102 bytes" },
          { "name": "primary_output.audio_valid", "ok": true, "detail": "audio_stream=True duration=10.000s" },
          { "name": "output_conforms_to_requested_format", "ok": true,
            "detail": "requested bit_depth=24, channels=1, sample_rate=48000; measured bit_depth=24, channels=1, sample_rate=48000 → ok" }
        ],
        "failures": [],
        "measured": { "output_conforms_to_requested_format": {
          "output": "primary_output",
          "requested": { "sample_rate": 48000, "channels": 1, "bit_depth": 24 },
          "measured": { "sample_rate": 48000, "channels": 1, "bit_depth": 24 } } },
        "verified_at": "2026-08-15T06:56:50Z" } }
  }
}
```

(The full result repeats that per-step object for `normalization` and `audio_benchmark` —
this excerpt keeps the first step complete and elides the other two. In the real output,
`normalization.verification` shows `integrated_loudness_on_target: measured -21.03 LUFS
vs target -21.0 (±1.0) → off by 0.03 LU` and the benchmark step ends the run.)

### Top-level fields

| Field | Meaning |
|-------|---------|
| `status` | `"completed"` (all steps verified), `"error"`, or `"dry_run"` |
| `command` | `"run"` (or `"run-component"` / `"run-component-batch"`) |
| `chain` | the chain name or path you passed |
| `input_file` / `input_name` / `input_ext` | the input as resolved |
| `output_dir` | where artifacts and `context.json` live |
| `duration_ms` | wall-clock run time |
| `steps` | map of step name → step record (below); disabled steps are absent |
| `warnings` | engine warnings, usually empty |
| `report_file` | present only with `--report` |

### The per-step record

Each step object carries five sections:

| Section | Contents |
|---------|----------|
| `params` | the step's own params from the chain YAML |
| `preflight` | Verified IN: `satisfied`, per-check `ok`/`detail`, `failures[]`, and `resolved_params` — the full precedence-resolved parameter set the step actually ran with |
| `outputs` | every declared output: `path`, `type`, `exists`, and component-specific metadata (e.g. `measured_lufs`) |
| `output` | the primary output path this step advances to |
| `status` | `"completed"` / `"failed"` (skipped steps are absent from `steps`) |
| `verification` | Verified OUT: `tier`, `verified`, every `checks[]` entry with `ok`/`detail`, `failures[]` (the failing checks with their measured `detail`), and `measured` — the independent measurements the verifier made |

## The stderr NDJSON progress stream

`--json` keeps stderr as a clean stream of one JSON object per line:

```json
{"progress":{"step":"format_conversion","status":"running"}}
{"progress":{"step":"format_conversion","status":"completed"}}
{"progress":{"step":"normalization","status":"running"}}
{"progress":{"step":"normalization","status":"completed"}}
{"progress":{"step":"audio_benchmark","status":"running"}}
{"progress":{"step":"audio_benchmark","status":"completed"}}
{"progress":{"status":"workchain_completed"}}
```

Event shapes:

| Event | Meaning |
|-------|---------|
| `{"progress":{"step":"<name>","status":"running"}}` | step started |
| `{"progress":{"step":"<name>","status":"completed"}}` | step finished and passed |
| `{"progress":{"step":"<name>","status":"failed","error":"verification","checks":[...]}}` | step failed its verify contract; `checks` carries the failed check details |
| `{"progress":{"status":"chain_halted","step":"<name>"}}` | chain stopped at the failed step |
| `{"progress":{"status":"workchain_completed"}}` | all steps done |

Use `--verbose` to also see the raw engine log lines on stderr alongside the NDJSON.

## Reading a verification FAILED block

The tool's whole reason to exist is that a component can exit 0 and still be wrong. Here is
a real failure — `chains/tests/normalization_offtarget.yaml` asks for −5 LUFS with a
−1.5 dBTP ceiling; the loudness is unreachable under that ceiling, so the normalizer
produces −12.74 LUFS, and the verifier catches it:

```
✖ Chain halted: step 'normalization' failed verification
    normalization — unverified (1 of 8 checks failed)
      ✗ integrated_loudness_on_target: measured -12.74 LUFS vs target -5.0 (±1.0) → off by 7.74 LU
    chain: chains/tests/normalization_offtarget.yaml
    input_file: /tmp/test-dialogue.wav
```

The equivalent `--json` result:

```json
{
  "status": "error",
  "command": "run",
  "code": 1,
  "message": "Chain halted: step 'normalization' failed verification",
  "failures": [
    {
      "step": "normalization",
      "tier": "unverified",
      "total_checks": 8,
      "failed_checks": [
        { "name": "integrated_loudness_on_target",
          "detail": "measured -12.74 LUFS vs target -5.0 (±1.0) → off by 7.74 LU" }
      ]
    }
  ]
}
```

Everything you need is in `failures[].failed_checks[].detail` — the measured fact that
stopped the run. Note the same fact in the stderr stream:

```json
{"progress":{"step":"normalization","status":"failed","error":"verification","checks":["integrated_loudness_on_target: measured -12.74 LUFS vs target -5.0 (±1.0) → off by 7.74 LU"]}}
{"progress":{"status":"chain_halted","step":"normalization"}}
```

### Why the tier says "unverified"

A failing step is labeled `tier: "unverified"` — the contract it declared is **not** what
happened, so it cannot claim the `verified` tier. Tiers progress `unverified` → `verified`
→ `certified` (signed; roadmap). `context.json` also records `verification_failed: true`
for that step. The run exits 1; the chain does not continue to later steps.

## Verify verdicts

Per step, the verdict is the run state plus the verification outcome:

| Verdict | Meaning |
|---------|---------|
| `completed` + `verified: true` | ran, and its declared verify contract passed — measured independently |
| `failed` + `verification_failed: true` | ran (maybe exited 0!) but a declared check measured something wrong |
| `unverified` | ran with no `verify:` contract — honestly labeled, never silently trusted |
| `skipped` | `enabled: false` in the chain — the engine logs `Skipping disabled step` and moves on; a skipped step is **not executed and not verified**, and does not appear in the result JSON's `steps` map at all |

A step with no verify contract reports `tier: "unverified"` and passes non-blockingly; see
[docs/format.md](../../format.md) for the contract rules. The engine's run log (a file under
`~/.workchain/runs/`, shown at the start of `--verbose` output) records the skip reason.

## context.json

`context.json` in the output directory is the engine's raw run record and the source the
CLI's result JSON is built from:

```json
{
  "chain_file": "...deliverable-voice.yaml",
  "chain_name": "deliverable-voice",
  "status": "completed",
  "start_time": "...", "end_time": "...",
  "input_file": "/tmp/run-out/test-dialogue_converted_normalized.wav",
  "input_name": "test-dialogue",
  "input_ext": "wav",
  "output_dir": "/tmp/run-out",
  "globals": { "lufs_target": -21 },
  "steps": { ...same per-step records as the stdout JSON... }
}
```

Two notes for readers:

- `input_file` is updated as the chain advances — after the final step it points at the
  **last step's primary output**, not your original upload. `input_name`/`input_ext` keep
  the original names.
- `globals` holds the chain's globals; per-step `params` in `steps.<name>.params` are the
  step's own; the effective set (precedence resolved) is in
  `steps.<name>.preflight.resolved_params`.

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | success (or dry-run plan generated) |
| 1 | execution error (step failed its verify contract, component error, timeout) |
| 2 | input error (file not found, chain/component not found, bad config key) |
| 3 | configuration error (workchain root not found / invalid) |

## What next

- [Run Chains](./run-chains.md) — where results come from.
- [Use the Shipped Chains](./use-the-shipped-chains.md) — what the delivered chains promise and deliver.