---
title: Provision Heavy Components
description: How to provision the heavy tier — stem_separation's Python venv with audio-separator, the Python 3.10 pin, the uv fallback, model downloads and cache location, and the WORKCHAIN_AUDIO_SEPARATOR_BIN / _MODELS env overrides.
type: how-to
---

# Provision Heavy Components

The registry splits components into two tiers. **Light** components (`normalization`,
`format_conversion`, `audio_benchmark`, `content_hash`, `cdp_transform`) need only ffmpeg
+ system python3 and work the moment the CLI is installed. **Heavy** components declare
`python`/`models` requirements in `step.yaml` and must be provisioned separately — the
registry marks them `tier: heavy`, and `workchain doctor` reports them `missing` until
you do.

**`stem_separation` is the only heavy component today**, and this page is its provisioning
guide, reproduced from
[components/stem_separation/README.md](../../../components/stem_separation/README.md).

## What stem_separation needs

1. **A Python venv** at `components/stem_separation/.venv/` (or pointed to by
   `$WORKCHAIN_AUDIO_SEPARATOR_BIN`).
2. **A model download** — `audio-separator` fetches weights on first use and caches them to
   `components/stem_separation/models/` (or `$WORKCHAIN_AUDIO_SEPARATOR_MODELS`). The
   hybrid preset needs both the BS-RoFormer checkpoint and the Demucs model; `mdx` needs
   only a single ONNX file.
3. **The install command** — run once from the repo root:

```bash
python3.10 -m venv components/stem_separation/.venv
components/stem_separation/.venv/bin/pip install "audio-separator[cpu]"
# Linux + NVIDIA GPU: use "audio-separator[gpu]" and a matching CUDA torch build instead.
```

Use **Python 3.10** for the venv. Demucs `diffq` has no cp311 wheel (and the requirement's
`python_version` floor is `>=3.10`, so a newer interpreter would *pass preflight* and then
fail to build — pin the venv to 3.10).

## If python3.10 is not on PATH

macOS and minimal distros often ship only a newer CPython. Get a 3.10 via `uv`, then build
the venv from it:

```bash
uv python install 3.10                       # fetches a standalone CPython 3.10
uv venv --python 3.10 components/stem_separation/.venv
components/stem_separation/.venv/bin/pip install "audio-separator[cpu]"
# Linux + NVIDIA GPU: use "audio-separator[gpu]" and a matching CUDA torch build instead.
```

## The contract you are satisfying

The `step.yaml` inbound contract (Verified IN) declares:

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

Preflight checks these before `run.sh` runs. If `audio-separator` is not installed the
step fails honestly (`status: failed`, `reason: audio_separator_not_found`) — never a
faked success. Model weights are auto-provisioned on first use and are preset-dependent,
so they are intentionally not a hard preflight gate.

## After provisioning, confirm

```bash
workchain doctor
```

`stem_separation` flips from `missing  missing: python:venv` to `ok`.

## First run downloads models

Models are fetched on first use and cached under `components/stem_separation/models/`.
Overrides, honored by the component's `run.sh`:

| Env var | What it points at |
|---------|-------------------|
| `WORKCHAIN_AUDIO_SEPARATOR_BIN` | the `audio-separator` binary (venv layout equivalent) |
| `WORKCHAIN_AUDIO_SEPARATOR_MODELS` | the model cache directory |

## Usage

Run standalone after provisioning:

```bash
workchain run-component stem_separation track.wav -o ./out \
  --params-json '{"preset":"demucs","primary_stem":"drums"}' --json
```

```bash
workchain run chains/tests/stem_separation_test.yaml track.wav -o ./out --json
```

## GPU and CPU expectations

These are GPU models. On CPU they are slow (BS-RoFormer takes minutes for tens of seconds
of audio; the hybrid runs RoFormer *and* a 4-model Demucs bag). On a machine with a GPU or
Apple MPS they are far faster. Quality is a function of the model, not the clip length.

Unlike light components, this one does not ship in the lean npm core and requires explicit
provisioning before first use.