---
title: How to author a component
description: Build a verified Workchain component from scaffold to green — the two contracts (requirements and verify), run.sh discipline, and proving the test can fail.
type: how-to
---

# How to author a component

A component is a folder: `step.yaml` (the contract) + `run.sh` (the implementation) +
`README.md` (the documentation). The filesystem is the registry — there is no database, and a
component exists because its directory exists.

**Definition of done is not "it runs." It is "it proves what it produced."** A component that
exits 0 with the wrong output is worse than one that fails, because it lies to whatever is
operating it — and by the time anyone notices, the wrong audio is three steps downstream. Every
step below exists to close that gap.

This guide is the human form of the doctrine in
[`.agents/skills/authoring-a-component/SKILL.md`](../../../.agents/skills/authoring-a-component/SKILL.md) —
same rules, no new ones. The schema reference is
[`components/_template/step.yaml`](../../../components/_template/step.yaml), the canonical worked
example is [`components/normalization/`](../../../components/normalization/README.md), and
[`components/content_hash/`](../../../components/content_hash/README.md) is the perfect-verification
example. Read `docs/format.md` for the full `step.yaml` specification.

We will build a working component end-to-end: `sample_normalize`, a light component that
normalizes audio to a target integrated LUFS. Every command and response below is real, captured
against a 3-second 440 Hz sine tone (`ffmpeg -f lavfi -i sine=frequency=440:duration=3 -ac 1 -ar 44100 tone.wav`).

## 1. Scaffold

```bash
workchain generate component --name sample_normalize \
  --description "Normalizes audio to a target integrated LUFS (two-pass)" \
  --type audio --commands ffmpeg,ffprobe \
  --params '[{"name":"target_lufs","type":"number","default":-16,"description":"Target integrated loudness in LUFS","min":-60,"max":0}]'
```

The generator emits a complete puzzle piece — not an empty folder:

```
components/sample_normalize/
├── step.yaml         # params_schema, outputs, requirements, verify
├── run.sh            # execution script — carries an honest-failure sentinel
├── provision.sh      # idempotent setup for declared requirements
├── README.md         # documents its own contract from day one
└── test-chain.yaml   # minimal single-step chain to exercise it
```

`--kind light|heavy|api` shapes the requirements block (PATH commands only / a Python venv / an
external API). Light is right here: the component needs only ffmpeg and ffprobe.

## 2. The scaffold fails on purpose

The generated `run.sh` carries a sentinel that breaks the component until you have actually
implemented it:

```bash
WORKCHAIN_NOT_IMPLEMENTED=1
if [[ "${WORKCHAIN_NOT_IMPLEMENTED:-0}" == "1" ]]; then
    log_error "$COMPONENT_NAME is an unimplemented scaffold."
    ...
    register_output ... "not_implemented"
    return 1
fi
```

Run the untouched scaffold and it fails — loudly, honestly, with the dependencies already
proven present:

```
$ workchain run-component sample_normalize tone.wav -o ./out
✓ sample_normalize — dependencies satisfied (2/2 checks)
[07:00:00] ERROR: sample_normalize is an unimplemented scaffold.
[07:00:00] ERROR: Add processing in components/sample_normalize/run.sh, then remove the 'WORKCHAIN_NOT_IMPLEMENTED=1' line.
...
"status": "failed", "exit_code": 1
```

Preflight passed (`requirements:` satisfied); the component still refused to pretend. **Do not
delete the `WORKCHAIN_NOT_IMPLEMENTED=1` line until `run.sh` genuinely produces its primary
output — and never before the `verify:` block is real.** The sentinel is what stops a scaffold
from being mistaken for a working component.

## 3. Write `run.sh`

The engine **sources** the script — so the rules that keep the engine alive:

- **`return`, never `exit`.** `exit` takes down the entire engine with you.
- **stdout is the final JSON; all logging goes to stderr** via the `log_*` helpers
  (`log_info`, `log_warn`, `log_error`, `log_step`). Never pollute stdout.
- **Never overwrite `WORKCHAIN_ROOT`, `LIB_DIR`, `COMPONENTS_DIR`** — the script sources its
  helpers from `lib/common-utils.sh` and `lib/constants.sh` when they are not already set.
- Read the context through the **special-char-safe helpers** (`ctx_get_abs`, `ctx_get`,
  `ctx_get_json`). Real paths contain apostrophes and spaces; never shell-interpolate them into
  one-liners.
- Read parameters with `get_param` — the engine has already resolved precedence (step `params`
  > chain `globals` > schema `default`). Never re-implement precedence.
- **Guard mandatory parameters explicitly.** The schema has no `required` key, so a missing
  mandatory param is caught by your guard or not at all.
- Register every output with `register_output`, and register `failed` / `not_implemented` plus
  `return 1` when you could not produce one. Never report `completed` for an output you did not
  write.

The core of our implementation:

```bash
INPUT_FILE=$(ctx_get_abs "$CONTEXT_FILE" input_file)
OUTPUT_DIR=$(ctx_get_abs "$CONTEXT_FILE" output_dir)
INPUT_NAME=$(ctx_get "$CONTEXT_FILE" input_name)
INPUT_EXT=$(ctx_get "$CONTEXT_FILE" input_ext)

TARGET_LUFS=$(get_param "target_lufs" "")          # schema default -16
[[ -z "$TARGET_LUFS" ]] && TARGET_LUFS="-16"       # overt guard for a mandatory param

OUTPUT_FILE="$OUTPUT_DIR/${INPUT_NAME}_${COMPONENT_NAME}.$INPUT_EXT"

# Two-pass loudnorm: measure first, then correct with measured values.
LOUDNESS_INFO=$(ffmpeg -i "$INPUT_FILE" -af "loudnorm=I=$TARGET_LUFS:LRA=7:TP=-1.5:print_format=json" -f null - 2>&1)
INPUT_I=$(echo "$LOUDNESS_INFO" | grep "input_i" | head -1 | cut -d'"' -f4)
if [[ -z "$INPUT_I" || "$INPUT_I" == "-inf" ]]; then
    log_error "Could not measure input loudness (silent or unreadable)"
    register_output "$CONTEXT_FILE" "$COMPONENT_NAME" "primary_output" "$OUTPUT_FILE" "file" \
        "{\"error\": \"unmeasurable_input\"}" "failed"
    return 1
fi

ffmpeg -i "$INPUT_FILE" -af "loudnorm=I=$TARGET_LUFS:LRA=7:TP=-1.5:measured_I=$INPUT_I:linear=true" \
    -y "$OUTPUT_FILE" >> "$LOG_FILE" 2>&1

if [[ ! -f "$OUTPUT_FILE" ]]; then
    log_error "$COMPONENT_NAME did not produce its primary output: $OUTPUT_FILE"
    register_output ... "failed"
    return 1
fi

register_output "$CONTEXT_FILE" "$COMPONENT_NAME" "primary_output" "$OUTPUT_FILE" "file" \
    "{\"target_lufs\": $TARGET_LUFS}" "completed"
return 0
```

Everything after the register-output call is the engine's problem, not yours: after your
`return 0`, `lib/workchain_verify.py` enforces the `verify:` block.

## 4. Declare `verify:` — the outbound contract

The scaffold already ships a structural assert (`assert: [exists, non_empty, audio_valid]`).
**For an audio output, always keep `audio_valid`.** `non_empty` only asks whether the file has
bytes — a 44-byte WAV header with zero samples has bytes. `audio_valid` re-probes with ffprobe
and demands a real audio stream and positive duration. That one word is the difference between
a filesystem question and an audio question.

The scaffold cannot know what your component *guarantees*, so the part that proves correctness
is yours: a post-condition that **re-measures the output** against the numeric target. Here is
the one we add (the same gate `normalization` ships with):

```yaml
verify:
  schema_version: "1.0"
  outputs:
    - name: primary_output
      assert: [exists, non_empty, audio_valid]
  post_conditions:
    - id: integrated_loudness_on_target
      check: audio_lufs_within
      output: primary_output
      target_param: target_lufs
      tolerance: 1.0
      description: "Re-measures the integrated LUFS of the output and fails the step if it missed the requested target by more than 1.0 LU."
```

The point of the post-condition is that it is **independent**: `audio_lufs_within` re-measures
the output's loudness with `ffmpeg loudnorm` rather than trusting a number the component wrote
about itself. The target resolves through the full precedence chain — the params the step
actually ran with — so a `--params-json '{"target_lufs":-14}'` run is checked against −14, not
the schema default. Registering output metadata (as our `register_output` call does) is **not**
verification; verification is the separate check that confirms what you registered holds up.

### The `params_schema` four keys

A param definition supports exactly four keys: `type`, `default`, `description`, `range` —
nothing else. **There is no `required` key.** Anything outside those four is silently discarded
by every layer, and a `required: true` only *documents* a param that was already mandatory.
A param is mandatory by convention: no `default` in the schema, plus an explicit guard in
`run.sh`. `format_conversion`'s `target_format` is the reference:

```yaml
params_schema:
  target_format:
    type: string
    # No default — this param is mandatory. run.sh errors: "target_format parameter is required"
    description: "Target format: wav, flac, aiff, alac, tta, wv, mka (lossless) | ..."
```

Bump `version` when you change a schema, and keep changes backwards-compatible.

## 5. Run it — and watch the contract prove the output

With the sentinel removed, the run both executes *and* verifies:

```
$ workchain run-component sample_normalize tone.wav -o ./out
✓ sample_normalize — dependencies satisfied (2/2 checks)
... verifier, after a clean exit ...
"tier": "verified", "verified": true,
  primary_output.exists -> true                 path=.../tone_sample_normalize.wav
  primary_output.non_empty -> true              1152102 bytes
  primary_output.audio_valid -> true            audio_stream=True duration=3.000s
  integrated_loudness_on_target -> true         measured -15.95 LUFS vs target -16.0 (±1.0) → off by 0.05 LU
```

`tier: verified` is the whole point of the system: the component said it hit −16 LUFS, and the
verifier independently measured −15.95.

## 6. Prove the test can fail

A check nobody has watched fail is decoration that manufactures confidence. **Break it on
purpose before calling it done.** Two ways we broke `sample_normalize` in the sandbox:

**Break A — a 44-byte WAV header, zero samples** (replace the ffmpeg call with a header-only
write). The component exits 0, `non_empty` passes — 44 bytes — and the verifier still fails it:

```
✗ sample_normalize — verification FAILED (2 of 4 checks)
    primary_output.audio_valid: audio_stream=True duration=0.000s
    integrated_loudness_on_target: measured -inf LUFS vs target -16.0 (±1.0) → off by inf LU
```

This is the exact "44-byte header has bytes" trap: `non_empty` is a filesystem question,
`audio_valid` is an audio question.

**Break B — copy the input through without normalizing.** The output is a real, valid, 3-second
WAV — every structural check passes — and the component's claim is still a lie the verifier
catches:

```
✗ sample_normalize — verification FAILED (1 of 4 checks)
    primary_output.exists      -> true     path=.../tone_sample_normalize.wav
    primary_output.non_empty   -> true     264678 bytes
    primary_output.audio_valid -> true     audio_stream=True duration=3.000s
    integrated_loudness_on_target -> false  measured -21.75 LUFS vs target -16.0 (±1.0) → off by 5.75 LU
```

The component exits 0. The audio is fine. The output is *wrong* — and the contract says so.
This is the failure mode the repo exists to eliminate; `chains/tests/normalization_offtarget.yaml`
is the standing fixture for it.

## 7. Write the README — then ship

Follow the format of `normalization` and `format_conversion` with a "Verified OUT" section:
**What it does · Parameters (name | type | default | range | meaning) · Inputs / Outputs ·
Verified IN · Verified OUT · Usage · Edge cases · Tier.**

Document honestly. If the contract is structural-only because no numeric post-condition exists
yet, say so out loud rather than implying coverage. Never write a measured claim you did not
measure, and never re-round or extrapolate one someone else measured. The generator's scaffold
README even tells you which parts are still scaffolding.

## Recap — the checklist

- [ ] `requirements:` declares every external binary and dependency (checked *before* the run)
- [ ] `WORKCHAIN_NOT_IMPLEMENTED=1` removed only once `run.sh` really produces its output
- [ ] `run.sh`: `return` never `exit`; logging to stderr; safe `ctx_get_*` helpers;
      `register_output` for everything produced; `failed`/`not_implemented` when not
- [ ] `params_schema` uses only `type`/`default`/`description`/`range`; mandatory params guarded
      in `run.sh`
- [ ] `verify:` is real — `audio_valid` on audio outputs; an independent post-condition for the
      numeric claim
- [ ] The contract has been **broken on purpose** and seen to fail
- [ ] README documents the contract and its limits honestly

Next: choosing the right checks is its own guide —
[`write-a-verify-block.md`](write-a-verify-block.md).