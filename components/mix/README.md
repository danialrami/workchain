# mix

Two-input audio mix via ffmpeg `amix` — the demo consumer of the two-input
(`in2:`) channel from [issue #10](https://github.com/lufs-audio/workchain/issues/10).
It sums the step's **primary input** (the chain input, via the existing
`context.json` mechanism) with a **second input** the chain declares with `in2:`,
into one stereo 44.1 kHz / 16-bit WAV.

This is deliberately the smallest real two-input component: it exists so a sample
chain has a path that actually consumes two inputs, and so the two-input contract —
staging, routing, provenance, verification — is exercised end to end.

## What it does

1. Reads the primary input from `context.json` (`input_file`) — unchanged from
   every single-input component.
2. Reads the second input from `WORKCHAIN_INPUT_2` — the **one documented channel**
   for the second input (see `docs/format.md` → *Second input (`in2:`)*). The engine
   exports it after staging; a run without it is an authoring error and fails closed.
3. Measures both inputs (duration, sha256, mean volume) and writes them to a JSON
   sidecar.
4. Mixes with `ffmpeg amix` (inputs forced to stereo / 44.1 kHz so a format
   mismatch never surfaces only on certain input pairs).

## Parameters

| name | type | default | range | meaning |
|------|------|---------|-------|---------|
| `duration_mode` | string | `longest` | `longest` \| `first` | amix duration policy. `longest` spans the longer of the two inputs; `first` ends with the primary input. |
| `normalize` | boolean | `true` | — | amix `normalize`: scale each input before summing (`true` protects against clipping; `false` keeps raw levels). |

## Inputs / Outputs

- **Inputs:** the step's primary input (any supported audio format) plus the
  `in2:` file — a path or glob resolving to exactly one supported audio file.
- **Outputs**
  - `primary_output` — `{input_name}_mixed.wav` (stereo, 44.1 kHz, 16-bit).
  - `mix_metadata` — `logs/mix_metadata.json` with `in_a` / `in_b` / `output`
    entries: resolved paths, `duration_s`, `sha256`, `mean_volume_db`.

## Verified IN — `requirements:`

`ffmpeg` + `ffprobe` (already required by the engine and every light component).

The component also declares `accepts_second_input: true`. This is not a preflight
class — it is the schema gate that makes `validate` refuse any chain that declares
`in2:` against a component which would silently drop the second input.

## Verified OUT — `verify:`

| Check | What it proves | Independent? |
|---|---|---|
| `primary_output` `[exists, non_empty, audio_valid]` | the mix is a real, decodable audio file with positive duration | re-measures (ffprobe) |
| `mix_metadata` `[exists, non_empty, json_valid]` + `json_has [in_a, in_b]` | the sidecar exists and names both inputs | structural |
| `mix_preserves_primary_duration` (`audio_duration_matches`, ±0.2 s) | the mix keeps the **primary** input's timeline | **independent re-measurement** |
| `both_inputs_provenanced` (`json_fields_within`) | sidecar facts about **both** inputs: durations are numbers, mean levels are numbers, sha256s non-empty, `in_b.path` non-empty | **component-written** (weaker) |

The honesty split, stated plainly:

- The duration check **re-measures** the mix output and the primary input with
  ffprobe. It is the independent half of the contract — and with
  `duration_mode: longest`, a second input **longer** than the primary stretches
  the mix past the primary's timeline, so this check fails. That is the
  two-input *prove-it-can-fail* path: the second input's wrongness surfaces as a
  re-measured fact, not a component claim.
- The `json_fields_within` check reads the sidecar the component wrote about
  itself — the *two-input post-condition model* (a fact about the second input,
  nameable because the run records `in2` provenance). It is **weaker** than a
  re-measurement and is documented as such: a component that wrote plausible
  numbers would pass. The independent two-input re-measurement class is a
  follow-up unit (POST_CHECKS owner), not this one.

**Gaps, honestly:** nothing independently re-measures a fact of the *second*
input in this contract (the duration check measures the *output* against the
*primary*). A second input that is merely quieter (but not silent) mixes to a
valid, quieter file and passes. The `both_inputs_provenanced` check proves each
input was *measurable* — duration and mean level are real numbers, digests
non-empty — but digital silence measures at the PCM floor (~-91 dBFS), which is
a number, so a genuinely silent second input still satisfies it. Silence in the
second input is not independently caught by this contract; that is a documented
gap, not a claim.

## Usage

```bash
# two real inputs
ffmpeg -f lavfi -i sine=frequency=440:duration=2 inA.wav
ffmpeg -f lavfi -i sine=frequency=880:duration=2 inB.wav

# chain declares in2: for the mix step — e.g. chains/examples/two-input.yaml
./engine/workchain-engine.sh -c chains/examples/two-input.yaml inA.wav -o out
# or, with the second input staged from the chain's declared path:
node cli/bin/workchain.js run two-input inA.wav -o out
```

`in2:` is resolved against the engine's working directory (same rule as every
engine path). The committed sample chain uses
`in2: "chains/examples/fixtures/in_b.wav"` — regenerable with
`ffmpeg -f lavfi -i sine=frequency=880:duration=2 -ac 1 -c:a pcm_s16le chains/examples/fixtures/in_b.wav`.

## Edge cases

- **Missing `WORKCHAIN_INPUT_2`** → run.sh fails closed (authoring error, not a
  silent single-input mix).
- **`in2:` path/glob with zero matches or several matches** → the engine refuses
  the step before `run.sh` runs (fail closed; a glob must match exactly one).
- **`in2:` same file as the primary input** → the engine refuses (self-reference).
- **Second input longer than the primary** (with `duration_mode: longest`) → the
  verify contract fails: the mix exceeds the primary timeline (re-measured).
- **Second input that cannot be measured** (ffmpeg/ffprobe fail) → sidecar
  records `mean_volume_db: null` / `duration_s: null`; the component-written
  check fails. Note digital silence is *measurable* (~-91 dBFS) and passes —
  silence is not independently caught (see Verified OUT).
- **Non-audio second input** → engine stage-time refusal via `is_audio_file`.

## Tier

`light` — stdlib + ffmpeg only, same as `normalization` / `format_conversion`.
