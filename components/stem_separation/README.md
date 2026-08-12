# stem_separation

**Source separation** for Workchain, powered by
[`python-audio-separator`](https://github.com/nomadkaraoke/python-audio-separator) (the
headless UVR model runner: MDX-Net / RoFormer / Demucs over ONNX Runtime + PyTorch).

This is the reference example of two advanced contracts:
- `requirements.python` preflight class (venv, python_version, packages with import/dist, provision command)
- **metamorphic verification** — its `verify:` block uses `audio_duration_matches` and `stems_recombine`, the canonical pattern for an operation with no single correct output

## What it does

Separates a mixed audio file into individual stems (vocals, drums, bass, other, or
combinations thereof), selectable by a single `preset` knob. The default `hybrid` preset
runs a two-stage pipeline: BS-RoFormer isolates vocals first, then Demucs splits the
remaining instrumental into drums, bass, and other — giving the best available 4-stem
quality. Other presets trade stems or speed as needed.

The hybrid's stage-2 residual vocal bleed is **folded into `other`** (nothing discarded),
so the four stems still recombine exactly to the source:
`vocals + drums + bass + other == mix`. That is what the metamorphic `stems_recombine`
contract verifies.

Separation quality cannot be asserted — there is no single correct answer — but
"the stems must sum back to the source within a residual tolerance" can be, and is.

## Parameters

| Name | Type | Default | Range | Meaning |
|---|---|---|---|---|
| `preset` | string | `"hybrid"` | — | Quality preset: `hybrid` (default) = RoFormer vocals + Demucs drums/bass/other (best 4-stem); `demucs` = htdemucs_ft 4-stem; `demucs6` = htdemucs_6s 6-stem; `roformer` = BS-RoFormer 2-stem (best vocals); `mdx` = MDX Inst_HQ_3 2-stem (fast); `custom` = set `model`. |
| `model` | string | `""` | — | Single-model override (for demucs/demucs6/roformer/mdx/custom). Any `audio-separator --list_models` filename. Empty = use the preset's default model. |
| `vocal_model` | string | `""` | — | hybrid stage-1 model (vocal isolation). Empty = preset default (`model_bs_roformer_ep_317_sdr_12.9755.ckpt`). |
| `instrumental_model` | string | `""` | — | hybrid stage-2 model (splits the instrumental into drums/bass/other). Empty = preset default (`htdemucs_ft.yaml`). |
| `primary_stem` | string | `"vocals"` | — | Which produced stem becomes `primary_output` (the file the chain advances to). Falls back to the first stem if absent. |
| `output_format` | string | `"wav"` | — | Output audio format for the stems. `wav` keeps lossless intermediates for downstream mastering and exact recombination checks. |

### One knob: `preset`

Pick quality with a single setting.

| `preset` | Pipeline | Stems | Notes |
|---|---|---|---|
| **`hybrid`** (default) | RoFormer → Demucs (2 stages) | vocals, drums, bass, other | Best 4-stem: BS-RoFormer isolates vocals, Demucs splits the leftover instrumental. |
| `demucs` | single htdemucs_ft | vocals, drums, bass, other | Fine-tuned Demucs v4, one pass. |
| `demucs6` | single htdemucs_6s | + guitar, piano | 6 stems. |
| `roformer` | single BS-RoFormer | vocals, instrumental | 2-stem, best vocal isolation. |
| `mdx` | single MDX Inst_HQ_3 | vocals, instrumental | 2-stem, fastest. |
| `custom` | single model you name | model-defined | Set `model`. |

Override a preset's model(s) without leaving the preset:
- single presets / `custom`: `model: <any audio-separator --list_models filename>`
- `hybrid`: `vocal_model:` (stage 1) and/or `instrumental_model:` (stage 2)

> **Note on inline comments:** the engine's dependency-free YAML parser (used when PyYAML
> is not present) does not strip `#` comments that follow a value on the same line — keep
> chain `params:` values comment-free.

## Inputs / Outputs

**Inputs:** `wav`, `mp3`, `aiff`, `aif`, `flac`, `m4a`, `ogg`

**Outputs:**

| Name | Type | Required | MIME | Path | Meaning |
|---|---|---|---|---|---|
| `primary_output` | file | yes | `audio/wav` | `{input_name}_vocals.wav` | The stem selected by `primary_stem` (what the chain advances to) |
| `vocals` | file | no | `audio/wav` | `{input_name}_vocals.wav` | Isolated vocal stem |
| `drums` | file | no | `audio/wav` | `{input_name}_drums.wav` | Isolated drums stem |
| `bass` | file | no | `audio/wav` | `{input_name}_bass.wav` | Isolated bass stem |
| `other` | file | no | `audio/wav` | `{input_name}_other.wav` | Isolated "other" stem (everything not vocals/drums/bass) |
| `instrumental` | file | no | `audio/wav` | `{input_name}_instrumental.wav` | Isolated instrumental stem (2-stem presets only) |
| `separation_metadata` | json | no | — | `logs/stem_separation.json` | Preset, mode, model(s)/stages, stems, source input, measurements |

Unlisted stems (guitar, piano) are registered dynamically by `run.sh` when produced.

## Verified IN (inbound contract)

Heavy component — requires a Python venv with `audio-separator`:

```yaml
requirements:
  commands:
    - ffmpeg
    - ffprobe
  python:
    venv: ".venv"
    python_version: ">=3.10"
    packages:
      - { import: "audio_separator", dist: "audio-separator" }
    provision: "python3 -m venv .venv && .venv/bin/pip install 'audio-separator[cpu]' (use Python 3.10 — Demucs diffq has no cp311 wheel)"
```

`lib/workchain_preflight.py` checks all of these before `run.sh` runs. If `audio-separator`
is not installed the step fails honestly (`status: failed`, `reason: audio_separator_not_found`)
— never a faked success.

Model weights are auto-provisioned on first use by `audio-separator` and are preset-dependent
(hybrid needs RoFormer + Demucs; mdx needs only the MDX .onnx), so they are intentionally not
a hard preflight gate. Exact-weights pinning is a certified-tier concern.

## Verified OUT (outbound contract)

```yaml
verify:
  schema_version: "1.0"
  outputs:
    - name: primary_output
      assert: [exists, non_empty, audio_valid]
    - name: separation_metadata
      assert: [exists, non_empty, json_valid]
      json_has: [preset, stems, source_input]
  post_conditions:
    - id: stems_preserve_duration
      check: audio_duration_matches
      outputs: auto
      tolerance_s: 0.2
      description: "Every produced stem must preserve the source duration (±0.2s). Guards silent/truncated/padded outputs a green exit would hide."
    - id: stems_recombine_to_source
      check: stems_recombine
      stems: auto
      max_residual_db: -9.0
      description: "The stems must decompose the input: summing all stems must leave a residual at least 9 dB below the source. In hybrid mode the stage-2 residual vocals are folded into 'other' so this holds exactly. Catches a silent/duplicated/garbage/mismatched stem even though separation has no single right answer."
```

Separation is a canonical "exit 0 but wrong" operator. The `verify:` contract (enforced
by `lib/workchain_verify.py` right after the step) is **metamorphic and stem-count-agnostic**
(`stems: auto` = every registered stem file, so one contract covers hybrid / 2 / 4 / 6):

- **structural** — `primary_output` exists/non_empty/audio_valid; metadata JSON valid with preset/stems/source_input.
- **`stems_preserve_duration`** — every stem within ±0.2 s of the source.
- **`stems_recombine_to_source`** — all stems summed leave a residual ≥ 9 dB below source (catches a silent/duplicated/truncated/mismatched stem).

### Measured verification (12 s excerpt, CPU)

- **hybrid** → `vocals, drums, bass, other`; `verified`; recombination residual ≈ **−27.6 dB**; durations preserved.
- **handoff** — hybrid → `normalization`: the vocals stem mastered to **−13.9 LUFS** (target −14), both contracts pass, chain `completed`.
- **preset switch** — `demucs` preset → single htdemucs_ft, `primary_stem: drums` honored, `verified` (−24.1 dB). Proves the knob.

> The track used for measurement above was a private catalog excerpt. The measured values
> (residual dB, LUFS, duration) are provenance claims about real audio; they have not been
> altered. The specific track title is not reproduced here.

## Usage

Run standalone:

```bash
workchain run-component stem_separation track.wav -o ./out \
  --params-json '{"preset":"demucs","primary_stem":"drums"}' --json
```

In a chain:

```yaml
steps:
  - name: stem_separation
    enabled: true
    params:
      preset: hybrid          # or demucs / demucs6 / roformer / mdx / custom
      primary_stem: vocals    # which stem the chain advances on
```

Combine with normalization for a complete stem-and-master chain:

```yaml
globals:
  lufs_target: -14

steps:
  - name: stem_separation
    enabled: true
    params:
      preset: hybrid
      primary_stem: vocals
      output_format: wav

  - name: normalization
    enabled: true
    params:
      target_lufs: -14
      two_pass: true
```

## Edge cases

**Binary not found.** If `audio-separator` is not on `PATH`, `$WORKCHAIN_AUDIO_SEPARATOR_BIN`, or
`components/stem_separation/.venv/bin/`, the step fails with `audio_separator_not_found` and prints
install instructions. It never fakes a success.

**Custom preset with no model.** `preset: custom` requires an explicit `model:` param; omitting it
fails with `model_required`.

**Unknown preset.** Any value other than `hybrid`, `demucs`, `demucs6`, `roformer`, `mdx`, `custom`
fails with `unknown_preset`.

**Fewer than 2 stems produced.** If the separator returns fewer than 2 output files the step fails with
`too_few_stems`.

**primary_stem not in output.** If the requested `primary_stem` was not produced, the step falls back
to the first stem and logs a warning (does not fail).

**Silent input.** The separator will run; the output stems may be near-silent. The
`stems_recombine_to_source` contract will still pass (silence + silence = silence), but
`stems_preserve_duration` will still catch a truncated output.

## Tier

**heavy**

This component requires:

1. **A Python venv** at `components/stem_separation/.venv/` (or pointed to by
   `$WORKCHAIN_AUDIO_SEPARATOR_BIN`).
2. **A model download** — `audio-separator` fetches weights on first use and caches them to
   `components/stem_separation/models/` (or `$WORKCHAIN_AUDIO_SEPARATOR_MODELS`). The hybrid
   preset needs both the BS-RoFormer checkpoint and the Demucs model; `mdx` needs only a
   single ONNX file.
3. **The install command** — run once from the repo root:

```bash
python3.10 -m venv components/stem_separation/.venv
components/stem_separation/.venv/bin/pip install "audio-separator[cpu]"
# Linux + NVIDIA GPU: use "audio-separator[gpu]" and a matching CUDA torch build instead.
```

Use **Python 3.10** for the venv. Demucs `diffq` has no cp311 wheel (and the requirement's
`python_version` floor is `>=3.10`, so a newer interpreter would *pass preflight* and then
fail to build — pin the venv to 3.10).

If `python3.10` is not on PATH (macOS and minimal distros often ship only a newer CPython),
get a 3.10 via `uv`, then build the venv from it:

```bash
uv python install 3.10                       # fetches a standalone CPython 3.10
uv venv --python 3.10 components/stem_separation/.venv
components/stem_separation/.venv/bin/pip install "audio-separator[cpu]"
# Linux + NVIDIA GPU: use "audio-separator[gpu]" and a matching CUDA torch build instead.
```

Model weights are fetched on first use and cached under `components/stem_separation/models/`.

`ffmpeg` and `ffprobe` are also required and preflighted by the engine.

> These are GPU models. On CPU they are slow (BS-RoFormer takes minutes for tens of
> seconds of audio; the hybrid runs RoFormer *and* a 4-model Demucs bag). On a machine
> with a GPU or Apple MPS they are far faster. Quality is a function of the model, not
> the clip length.

Unlike light components, this one does not ship in the lean npm core and requires explicit
provisioning before first use.
