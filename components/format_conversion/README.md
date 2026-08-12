# format_conversion

Converts audio between formats via FFmpeg, with sensible encoder fallback chains baked in.

## What it does

`format_conversion` probes the input file (codec, sample rate, channels, bit depth) with `ffprobe`, then builds an FFmpeg command tailored to the requested `target_format`. Lossless targets (wav, aiff, flac, alac, tta, wv, mka, au, caf) preserve the source's sample rate/channel count and pick the matching PCM or native lossless codec. Lossy targets (mp3, m4a/aac, ogg, opus, wma, ac3, amr, spx) pick the best available encoder — e.g. `libmp3lame` before falling back to `libshine`, `libfdk_aac` before native `aac` — and apply the requested bitrate. If a target format has no usable encoder installed, the step fails loudly rather than silently downgrading. This logic is lifted from `audioconv-cli`, so the fallback behavior is proven outside the workchain too.

## Parameters

| Name | Type | Default | Range | Meaning |
|---|---|---|---|---|
| `target_format` | string | — (required) | — | Target format: `wav`, `flac`, `aiff`, `alac`, `tta`, `wv`, `mka` (lossless) \| `mp3`, `m4a`, `ogg`, `opus`, `aac`, `wma`, `ac3`, `amr`, `spx` (lossy) |
| `preserve_quality` | boolean | `true` | — | Preserve sample rate, channels, bit depth (for lossless formats) |
| `bitrate` | string | `"320k"` | — | Bitrate for lossy formats (e.g., 320k, 256k, 192k) |

Note: `target_format` has no schema default — `run.sh` errors out early ("target_format parameter is required") if it's omitted.

## Inputs / Outputs

- `input_types`: wav, mp3, aiff, aif, flac, m4a, m4b, ogg, oga, opus, aac, wma, ac3, amr, au, caf, mka, spx, tta, wv (anything the declared list covers — matches what FFmpeg can decode).
- Output (`outputs.items`, schema v1.0):

| Name | Type | Path template | Required |
|---|---|---|---|
| `primary_output` | file | `{input_name}_converted.{target_format}` | yes |

## Verified IN (inbound contract)

```yaml
requirements:
  commands:
    - ffmpeg
    - ffprobe
```

Just the two binaries — no python venv, node, models, or env vars declared. `lib/workchain_preflight.py` confirms both are on `PATH` before `run.sh` runs; missing either one blocks the step outright.

## Verified OUT (outbound contract)

```yaml
verify:
  schema_version: "1.0"
  outputs:
    - name: primary_output
      assert: [exists, non_empty, audio_valid]
```

`lib/workchain_verify.py` checks the output file exists, is non-empty, and decodes as valid audio (real duration, not a corrupt/zero-length file) after a clean exit — that's "proven correct," not just "ffmpeg returned 0." No `post_conditions` are declared, so this is structural-only: the contract doesn't (yet) assert that the output's codec/sample-rate/channel-count actually match what you asked for. The step.yaml comment flags this explicitly as a known gap — a future `audio_format_matches` post-condition could close it.

## Usage

```bash
workchain run-component format_conversion input.wav --params-json '{"target_format": "mp3", "bitrate": "256k"}'
```

In a chain:

```yaml
steps:
  - name: format_conversion
    enabled: true
    params:
      target_format: "mp3"
      preserve_quality: false
      bitrate: "320k"
```

## Tier

Light. No python venv, no models — ffmpeg/ffprobe on the command line.
