# fx_with_params

A parameterized FX slot — the scaffold is real, the processing isn't wired up yet.

## What it does

`fx_with_params` is a component template: it reads `preset` and `strength` from step config and resolves the input/output paths from context. The executable contains a `WORKCHAIN_NOT_IMPLEMENTED=1` sentinel and fails before producing an output. Treat this as an honest scaffold, not a working effect; the sentinel must be removed only when real DSP and a meaningful contract are shipped.

## Parameters

| Name | Type | Default | Description |
|---|---|---|---|
| `preset` | string | `default_preset` | FX preset |
| `strength` | number | `0.5` | Effect strength (declared range: `min: 0`, `max: 1`) |

## Inputs / Outputs

- `input_types`: wav, mp3, aiff, aif, flac, m4a, ogg
- `output_type`: audio
- Output (`outputs.items`, schema v1.0):

| Name | Type | Path template | Required |
|---|---|---|---|
| `primary_output` | file | `{input_name}_fx_with_params.{input_ext}` | yes |

## Verified IN (inbound contract)

step.yaml declares **no `requirements:` block at all** — no commands, no python, no node, no models, no env vars. `lib/workchain_preflight.py` therefore has nothing to check before `run.sh` runs; the step is unconstrained by design (and by the fact that it doesn't call any external tool yet).

## Verified OUT (outbound contract)

step.yaml declares a structural `verify:` contract for `primary_output` (`exists`, `non_empty`, `audio_valid`). The current run path deliberately fails on the `WORKCHAIN_NOT_IMPLEMENTED=1` sentinel, so the verifier never turns a scaffold into a false success. Removing the sentinel requires replacing the stub with real DSP and keeping this contract truthful.

## Usage

```bash
workchain run-component fx_with_params input.wav --params-json '{"preset": "default_preset", "strength": 0.5}'
```

In a chain:

```yaml
steps:
  - name: fx_with_params
    enabled: true
    params:
      preset: default_preset
      strength: 0.5
```

## Tier

Light. No python venv, no models — presently no external tool invocation at all.
