---
title: Run Chains
description: How to execute Workchain chains on audio — the run command, --dry-run, --timeout, -o, --json, --report, and the delivered chains and what each guarantees.
type: how-to
---

# Run Chains

## Execute a chain

```bash
workchain run <chain> <input.wav> -o ./out
```

`<chain>` is either a chain name (resolved against `chains/`, including nested names
like `tests/normalization_offtarget`) or a path to a chain YAML file. `<input>` is the
audio file to process.

Example — prep a recording to the voice/dialogue delivery spec:

```bash
workchain run deliverable-voice take-07.wav -o ./out
```

Produces, in `./out`:

```
out/
├── context.json                 # full run record: steps, params, verify verdicts
├── logs/
│   ├── normalization.json       # LUFS / LRA / true-peak measurements
│   └── audio_benchmark.json     # per-check benchmark results
├── take-07_converted.wav        # step 1: conformed to spec
├── take-07_converted_normalized.wav   # step 2: loudness matched (final audio)
└── take-07_converted_original.wav
```

Without `-o`, the output goes to a timestamped directory `./output_YYYYMMDD_HHMMSS`.

### What "success" means

A green exit code is only the start. Each step carries a declared `verify:` contract that
the engine re-measures independently (ffprobe re-probes the audio, ffmpeg re-measures LUFS).
A step that produces the wrong format, the wrong loudness, or silence **fails** — the chain
halts and reports the measured facts. If the run exits 0, every step is `completed` and
`verified`. See [Inspect a Run](./inspect-a-run.md) for how to read that proof.

## Preview without running — `--dry-run`

```bash
workchain run deliverable-voice take-07.wav --dry-run
```

Prints the chain, each step with its component description and declared outputs, and
`No files were processed.` Nothing touches the input — a dry run is valid even before the
input file exists, so an agent can preview the plan first.

Machine-readable plan:

```bash
workchain run deliverable-voice take-07.wav --dry-run --json
```

Returns `status: "dry_run"`, `step_count`, and the steps list.

## Limit runtime — `--timeout`

```bash
workchain run deliverable-voice long_song.wav --timeout 7200
```

Seconds; default 3600. On timeout the run exits 1 with a `Chain timed out` error.

## Choose the output directory — `-o`

```bash
workchain run deliverable-voice take-07.wav -o /tmp/vo-session
```

## Machine-readable output — `--json`

```bash
workchain run deliverable-voice take-07.wav -o ./out --json
```

The final result JSON goes to **stdout**; progress events stream as NDJSON to **stderr**.
See [Inspect a Run](./inspect-a-run.md) for the full shape.

## HTML report — `--report`

```bash
workchain run deliverable-voice take-07.wav -o ./out --report
```

Generates `out/take-07_report.html` (a self-contained page summarizing steps, outputs, and
verification). With `--json`, the report path appears in the result as `report_file`.

## Run a chain from a raw YAML path

```bash
workchain run ./my-chain.yaml /path/to/input.mp3 -o /tmp/out
```

Any YAML that validates works, whether it lives in `chains/` or elsewhere.

## The delivered chains, and what each guarantees

All four delivered chains follow the same shape: **conform the format first**, then
**normalize loudness**, then **audit the result against the spec** — so loudness is
measured on the audio that actually ships, and the final audit proves both format and
loudness independently.

| Chain | Spec it delivers | Globals | Steps |
|-------|-----------------|---------|-------|
| `deliverable-voice` | WAV, 48 kHz, 24-bit, true mono, −22…−20 LUFS, true peak < −3 dBFS | `lufs_target: -21` | `format_conversion` (wav/48000/24/1) → `normalization` (−21 LUFS, two-pass, LRA 7, TP −3.0) → `audio_benchmark` (spec `24/48000/1`) |
| `deliverable-broadcast` | WAV, 48 kHz, 24-bit, stereo, −23 LUFS, TP < −1.0 dBTP (EBU R128) | `lufs_target: -23` | same shape; normalization TP −1.0; benchmark spec `24/48000/2` |
| `deliverable-streaming` | WAV, 48 kHz, 24-bit, stereo, −14 LUFS, TP ≤ −1.0 dBTP | `lufs_target: -14` | same shape; benchmark spec `24/48000/2` (no `noise_floor` check — see YAML) |
| `cdp-spectral-wash` | a long spectral wash from a short sound, at −18 LUFS, TP −1.5 | `lufs_target: -18` | `cdp_transform` (`stretch.time` ×4) → `normalization` (−18 LUFS) |

`simple-test.yaml` also ships (normalize −14 → benchmark) and is used by the test suite.

Run them all by name:

```bash
workchain validate all --strict   # every shipped + test chain is valid
workchain chains                  # list with descriptions
workchain run deliverable-voice in.wav -o ./out --json
workchain run deliverable-broadcast in.wav -o ./out --json
workchain run deliverable-streaming in.wav -o ./out --json
workchain run cdp-spectral-wash short.wav -o ./out --json
```

> The first three deliverable chains use only `normalization`, `format_conversion` and
> `audio_benchmark` — light, no extra install. `cdp-spectral-wash` additionally needs the
> `cdp-wasm` Node package (see [Install Workchain](./install.md)). The heavier
> `chains/tests/stem_separation_*` chains require provisioning first — see
> [Provision Heavy Components](./provision-heavy-components.md).

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | Chain completed (every step verified) — or dry-run plan generated |
| 1 | Execution error: a step failed its `verify:` contract, a component errored, or a timeout |
| 2 | Input error: input file or chain not found |
| 3 | Configuration error: workchain root not found |

## What next

- [Inspect a Run](./inspect-a-run.md) — read stdout JSON, stderr NDJSON, `context.json`, and verify verdicts.
- [Run Components](./run-components.md) — skip the chain, run one component directly.
- [Use the Shipped Chains](./use-the-shipped-chains.md) — step-by-step walkthrough of each delivered chain.