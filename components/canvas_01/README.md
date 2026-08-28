# canvas_01

Spotify Canvas (animated GIF/MP4) generated from album artwork.

## What it does

Takes the PNG that `artwork_01` produced and turns it into a looping Canvas asset for Spotify: an
animated GIF (the primary output), plus an MP4 loop and a static preview PNG alongside it. It has
a hard dependency on `artwork_01` having already run in the chain — there's no fallback input path,
unlike `artwork_01` itself.

## Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `loop_count` | number | `8` | Number of frames in the canvas loop |

## Inputs / Outputs

- **Input types:** `png`, `jpg`, `jpeg`
- **Output type:** `image`

| Output | Type | Required | MIME | Path |
|---|---|---|---|---|
| `primary_output` | file | yes | `image/gif` | `canvas/{input_name}_canvas.gif` |

The canvas directory also contains `canvas.mp4` (web-friendly loop) and `canvas_static.png`
(preview frame) — not part of the declared `outputs.items` in `step.yaml` yet, but written by
`run.sh` and registered as `mp4_version` / `static_preview` when present.

## Verified IN (inbound contract)

Heavy component — needs Pillow from the project's Python stack, not a shell tool. The exact
`requirements:` block in `step.yaml`:

```yaml
requirements:
  commands:
    - python3
  python:
    venv: "../../.venv"
    python_version: ">=3.10"
    packages:
      - { import: "PIL", dist: "Pillow" }
    provision: "uv sync   (run from the repo root; creates .venv)"
```

Same repo-root `.venv` as `artwork_01` — one `uv sync` provisions both. `lib/workchain_preflight.py`
checks the venv and the `PIL` import before `run.sh` runs, so a missing Pillow install fails at the
gate with an actionable message instead of an opaque crash mid-script. This is the same reason
`canvas_01` sits in the heavy tier rather than the lean npm core: it needs a real Python
environment, and that's provisioned once at the repo root, not per-component.

## Verified OUT (outbound contract)

```yaml
verify:
  schema_version: "1.0"
  outputs:
    - name: primary_output
      assert: [exists, non_empty]
```

Conservative, same as `artwork_01`: exists and non-empty on the GIF, nothing deeper (no frame-count
or dimension check yet). `lib/workchain_verify.py` enforces this after `run.sh` exits cleanly, so a
zero exit code by itself still isn't proof of a valid deliverable.

## Usage

Run standalone (requires artwork already produced):

```bash
workchain run-component canvas_01 artwork/track_artwork.png --params-json '{"loop_count":8}'
```

In a chain, always after `artwork_01`:

```yaml
steps:
  - name: artwork_01
    enabled: true
  - name: canvas_01
    enabled: true
    params:
      loop_count: 8
```

## Tier

**Heavy.** Declares a Python venv (Pillow), provisioned via `uv sync` at the repo root alongside
`artwork_01`, not the lean npm core. Runnable server-side via the hosted MCP tier once that venv is
provisioned there.
