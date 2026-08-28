# protection

Local psychoacoustic perturbation intended to resist AI-training use of the audio.

## Roadmap note — read this first

`step.yaml`'s description flags this component as **slated for rewrite** as the workchain's first
API-calling component, delegating to **Artyshield.ai**. The reason: the current local-DSP approach
below doesn't reliably defeat modern AI training. This README documents the *current* implementation
as it exists in the repo today — there is no Artyshield integration wired up yet (no credentials, no
HTTP client). When the rewrite lands, the inbound contract simplifies to `env: [ARTYSHIELD_API_KEY]`
plus an HTTP client, and the heavy numpy/scipy stack documented below goes away entirely. The
outbound contract — valid audio out, duration preserved — does not change; it's the same
metamorphic guarantee either way. See the KB roadmap doc
(`docs/product/workchain/07-roadmap`, Phase D — "The protection component reborn") for the full plan
and where it sits relative to the rest of the workchain's phased rollout.

## What it does (current implementation)

Applies psychoacoustic-masking-based perturbations to the audio samples — small enough to stay
perceptually transparent to a human listener, aimed at degrading how well an AI model can train on
the track. It runs on normalized audio when available (falling back to the original audio otherwise)
and also emits an HTML analysis report alongside the protected file. If the DSP step itself fails,
`run.sh` falls back to copying the unprotected input through as the "protected" output rather than
breaking the chain — worth knowing if you're auditing why a protected file looks identical to its
input.

## Parameters

| Parameter | Type | Default | Range | Description |
|---|---|---|---|---|
| `strength` | number | `0.4` | 0.01–1.0 | Protection strength |

## Inputs / Outputs

- **Input types:** `wav`, `mp3`, `aiff`, `aif`, `flac`, `m4a`, `ogg`
- **Output type:** `audio`

| Output | Type | Required | MIME | Path |
|---|---|---|---|---|
| `protected_audio` | file | yes | `audio/wav` | `protected/{input_name}_protected.{input_ext}` |
| `protection_report` | file | no | `text/html` | `protected/protection_report.html` |

## Verified IN (inbound contract)

Heavy component today — numpy/scipy against the repo-root Python stack. The exact `requirements:`
block in `step.yaml`:

```yaml
requirements:
  commands:
    - python3
  python:
    venv: "../../.venv"
    python_version: ">=3.10"
    packages:
      - { import: "numpy" }
      - { import: "scipy" }
      - { import: "soundfile" }
    provision: "uv sync   (run from the repo root; creates .venv)"
```

`soundfile` is declared here because `run.sh` imports it at runtime — preflight now checks it
alongside numpy/scipy, so a missing `soundfile` fails at the gate instead of mid-script. Same
repo-root `.venv` as `artwork_01`/`canvas_01`, provisioned by one `uv sync`. `lib/workchain_preflight.py`
enforces the venv and both imports before `run.sh` runs, failing honestly rather than letting a
missing dependency surface as a confusing mid-script crash. This DSP stack is exactly what the
Artyshield rewrite (see above) sheds — the future API-backed version drops numpy/scipy for an
`env` var and an HTTP client, which is a much lighter inbound contract than what's declared today.

## Verified OUT (outbound contract)

```yaml
verify:
  schema_version: "1.0"
  outputs:
    - name: protected_audio
      assert: [exists, non_empty, audio_valid]
  post_conditions:
    - id: duration_preserved
      check: audio_duration_matches
      outputs: [protected_audio]
      tolerance_s: 0.2
      description: "Protected audio must preserve the source duration (±0.2s)."
```

This is the component's one real metamorphic guarantee: `protected_audio` must be structurally
valid audio (`audio_valid`) **and** its duration must match the source within ±0.2s
(`audio_duration_matches`). Samples are expected to change — that's the point of a perturbation —
but the file has to still decode cleanly and run the same length as what went in.
`lib/workchain_verify.py` enforces both the per-output asserts and the post-condition after `run.sh`
exits cleanly. Notably, this same outbound contract is what the planned Artyshield rewrite keeps
unchanged — valid audio out, duration preserved — even though the inbound contract and internals
will look completely different.

## Usage

Run standalone:

```bash
workchain run-component protection track_normalized.wav --params-json '{"strength":0.4}'
```

In a chain, typically after `normalization`:

```yaml
steps:
  - name: normalization
    enabled: true
  - name: protection
    enabled: true
    params:
      strength: 0.4
```

## Tier

**Heavy.** Declares a Python venv (numpy/scipy), provisioned via `uv sync` at the repo root, not
the lean npm core. Runnable server-side via the hosted MCP tier once that venv is provisioned there
— though per the roadmap note above, expect this component's tier shape to change once the
Artyshield API rewrite lands (heavy DSP tier today, thin API-client tier tomorrow).
