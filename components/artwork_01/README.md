# artwork_01

Album artwork generated from an audio file's spectrogram, blended with a jdenticon identity pattern.

## What it does

Takes the track at whatever point it enters the chain (protected audio if `protection` ran,
normalized audio if not, otherwise the original) and renders a spectrogram of it, layers a
jdenticon-derived identity pattern on top, and composites a square PNG. The spectrogram layer and
the identicon layer are also written out separately so downstream steps (or a human) can inspect
or recombine them.

## Parameters

| Parameter | Type | Default | Range | Description |
|---|---|---|---|---|
| `saturation` | number | `0.5` | 0.0–2.0 | Spectrogram saturation |
| `width` | number | `1000` | — | Output image width in pixels |
| `height` | number | `1000` | — | Output image height in pixels |

## Inputs / Outputs

- **Input types:** `wav`, `mp3`, `aiff`, `aif`, `flac`, `m4a`, `ogg`
- **Output type:** `image`

| Output | Type | Required | MIME | Path |
|---|---|---|---|---|
| `primary_output` | file | yes | `image/png` | `artwork/{input_name}_artwork.png` |
| `components` | directory | no | — | `artwork/components` |

## Verified IN (inbound contract)

This is a **heavy** component — it needs the scientific Python stack, not just a shell binary.
The exact `requirements:` block in `step.yaml`:

```yaml
requirements:
  commands:
    - python3
    - node
  python:
    venv: "../../.venv"
    python_version: ">=3.10"
    packages:
      - { import: "numpy" }
      - { import: "scipy" }
      - { import: "matplotlib" }
    provision: "uv sync   (run from the repo root; creates .venv)"
  node:
    packages:
      - { require: "jdenticon" }
```

That's numpy/scipy/matplotlib for the spectrogram render, plus the root `jdenticon` node package
for the identity pattern — all resolved against the repo-root `.venv` created by `uv sync`, not a
component-local venv. `lib/workchain_preflight.py` checks every one of these — commands, the venv,
each Python import, the node package — *before* `run.sh` is invoked, and fails honestly (never a
silent skip masquerading as success) if `uv sync` hasn't been run. This is exactly why heavy
components like this one are provisioned separately from the lean npm core: the core CLI doesn't
need numpy, so it doesn't carry it, but `artwork_01` declares what it actually needs and preflight
enforces it.

## Verified OUT (outbound contract)

```yaml
verify:
  schema_version: "1.0"
  outputs:
    - name: primary_output
      assert: [exists, non_empty]
```

Conservative on purpose: for a PNG, the contract only asserts the file exists and isn't empty.
There's no pixel-level or dimension check yet (a future `image_valid` primitive could assert a
decodable image at the declared width/height). `lib/workchain_verify.py` runs this after `run.sh`
exits cleanly — a green exit code alone doesn't mean the step passes.

## Usage

Run standalone:

```bash
workchain run-component artwork_01 track.wav --params-json '{"saturation":0.7}'
```

In a chain:

```yaml
steps:
  - name: artwork_01
    enabled: true
    params:
      saturation: 0.5
      width: 1000
      height: 1000
```

Typically follows `normalization` and/or `protection` in a chain — it will pick up whichever of
those ran, in that priority order, before falling back to the original input.

## Tier

**Heavy.** Declares a Python venv and a node package, so it's provisioned separately from the lean
core (`uv sync` at the repo root, not `npm install`). Runnable server-side via the hosted MCP tier
once the venv is provisioned there.
