# normalization

LUFS audio normalization using FFmpeg's `loudnorm` filter with true-peak limiting. The canonical
worked example for the component contract — small, deterministic, and fully contracted.

## What it does

Measures a track's integrated loudness and normalizes it to a target LUFS (two-pass by default, so
`loudnorm` computes the exact gain rather than estimating it), then writes the normalized audio plus
a JSON sidecar of the loudness measurements. Streaming platforms sit around −14 LUFS; the schema
default is −11.

## Parameters

| Name | Type | Default | Range | Meaning |
|---|---|---|---|---|
| `target_lufs` | number | `-11` | −60 to 0 | Target **integrated** loudness in LUFS — LUFS-I, not momentary or short-term |
| `two_pass` | boolean | `true` | — | Two-pass normalization: measure, then correct. More accurate than a single pass |
| `lra` | number | `7` | 1–20 | Loudness Range (LRA) in LU |
| `true_peak` | number | `-1.5` | −10 to 0 | True-peak ceiling in dB |
| `offset` | number | `0` | −6 to 6 | LU offset applied after two-pass correction (positive = hotter) |

### The `offset` knob

`loudnorm`'s two-pass mode already computes the exact gain to hit `target_lufs`, so the **default is
`0`** — the output lands on target. `offset` is an intentional post-correction nudge (in LU) for the
rare case you want the result deliberately hotter (`+`) or quieter (`-`) than target; it is *not* a
fudge factor for normal use.

> Historical note: this was previously hardcoded to `0.6`, which silently pushed every normalize
> +0.6 LU hot and made the combined `stem_separation → normalization` chain overshoot target — the
> verifier's ±1.0 LU gate caught it. It is now `0` by default and configurable. Keep it at `0`
> unless you specifically want a bias.

## Inputs / Outputs

- **Input types:** `wav`, `mp3`, `aiff`, `aif`, `flac`, `m4a`, `ogg`
- **Output type:** `audio`

| Name | Type | Required | MIME | Path | Meaning |
|---|---|---|---|---|---|
| `primary_output` | file | yes | `audio/wav` *(declared — see below)* | `{input_name}_normalized.{input_ext}` | Normalized audio file. Its format follows the **input**, not WAV |
| `loudness_metadata` | json | no | — | `logs/normalization.json` | LUFS values, LRA, True Peak measurements |

> **Known schema defect — declared, not behavioural.** `step.yaml` declares
> `mime_type: "audio/wav"` and describes `primary_output` as "Normalized audio file (WAV format)",
> but `path_template` is `{input_name}_normalized.{input_ext}`: the output preserves the input's
> format, so normalizing an `.mp3` yields an `.mp3`. **The declaration is wrong, not the code.** It
> is not patched here because the same defect exists in `format_conversion` (`alac` → `.m4a`, which
> no template over `{target_format}` can express) and `stem_separation` (every stem hardcodes
> `.wav` against the `output_format` param). One family, one fix, tracked together.

## Verified IN (inbound contract)

Light component — just shell binaries, no Python venv:

```yaml
requirements:
  commands:
    - ffmpeg
    - ffprobe
```

`lib/workchain_preflight.py` confirms both are on `PATH` *before* `run.sh` runs. That's the whole
inbound contract — this is exactly the kind of stdlib+ffmpeg component that ships in the lean npm
core and needs no `uv sync`.

## Verified OUT (outbound contract)

```yaml
verify:
  schema_version: "1.0"
  outputs:
    - name: primary_output
      assert: [exists, non_empty, audio_valid]
    - name: loudness_metadata
      assert: [exists, non_empty, json_valid]
      json_has: [target_lufs, final_lufs]
  post_conditions:
    - id: integrated_loudness_on_target
      check: audio_lufs_within
      output: primary_output
      target_param: target_lufs
      tolerance: 1.0
      description: "Measured integrated LUFS of the normalized output must be within tolerance (LU) of the requested target. This is the gate that closes the 'measured but never compared' bug: the component recorded final_lufs and exited 0 regardless; the verifier independently re-measures and fails the step if it missed target."
```

This is the reference example of "proven correct, not exited 0." The structural asserts guarantee a
decodable audio file and a well-formed metadata JSON, but the real gate is `integrated_loudness_on_target`:
`lib/workchain_verify.py` **independently re-measures** the output's integrated LUFS and fails the
step if it's more than ±1.0 LU off the requested `target_lufs`. The component itself recorded
`final_lufs` and exited 0 regardless — the verifier is what closes the "measured but never compared"
gap. The target is resolved from the params the step actually ran with (params > chain globals >
schema default), so a `--params-json '{"target_lufs":-16}'` run is checked against −16, not the
default.

## Usage

Run standalone:

```bash
workchain run-component normalization track.wav --params-json '{"target_lufs":-14}'
```

In a chain:

```yaml
steps:
  - name: normalization
    enabled: true
    params:
      target_lufs: -14
      two_pass: true
      lra: 7
      true_peak: -1.5
      offset: 0
```

`target_lufs` can also come from the chain's `globals` (as `lufs_target`, folded in by the resolver):

```yaml
globals:
  lufs_target: -14
steps:
  - name: normalization
```

## Edge cases

**Silent input.** If the input is pure silence (measured LUFS = `-inf`), two-pass normalization
detects it, copies the input through unchanged, and registers the step as `skipped` with a
`silent_input_skipped` note in the metadata. The chain continues without failing.

## Tier

**Light.** Declares only `commands:` (ffmpeg/ffprobe) — no Python venv, no models — so it ships in
the lean npm core and runs anywhere ffmpeg is installed.
