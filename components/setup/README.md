# setup

The prerequisite checker. Run this first, or don't be surprised when everything downstream fails.

## What it does

`setup` verifies the runtime environment has what the workchain needs: Python 3, `uv`, FFmpeg, and npm. It logs versions found for each, and — unless `check_only` is set — runs `uv sync` at the project root to make sure the declared python environment is actually installed (failing loudly if `uv sync` errors, telling you to run `uv lock` to update the lockfile). Missing `ffmpeg` or `npm` produce warnings rather than hard failures on their own, but missing `python3` or `uv` count toward a failure tally; if that tally is non-zero at the end, the step returns non-zero. If `npm` is present but `node` isn't, it also runs `npm install` at the project root. This is a system-type component — it verifies and prepares the environment, it doesn't touch or produce audio.

## Parameters

| Name | Type | Default | Description |
|---|---|---|---|
| `check_only` | boolean | `false` | Only check prerequisites without running `uv sync` |

## Inputs / Outputs

- `type: system` — no `input_types` declared; this step doesn't operate on an audio file.
- Output (`outputs.items`, schema v1.0):

| Name | Type | Path template | Required |
|---|---|---|---|
| `environment` | json | `logs/setup.json` | yes |

`run.sh` writes `logs/setup.json` with `status`, `failures`, and `check_only`, then registers that file as the component output. A failed prerequisite writes a failed record and returns non-zero; it is never reported as ready.

## Verified IN (inbound contract)

```yaml
requirements:
  commands:
    - python3
    - uv
```

Just those two. No node, python-venv/package requirements, models, or env vars are declared — even though `run.sh` also checks for `ffmpeg` and `npm` at runtime, those checks are the component's own internal logic, not part of the declared inbound contract, so `lib/workchain_preflight.py` doesn't gate on them before invoking `run.sh`. Preflight only confirms `python3` and `uv` are on `PATH`.

## Verified OUT (outbound contract)

step.yaml declares a contract for the persisted `logs/setup.json`: it must exist, be non-empty and valid JSON, and carry `status`, `failures`, and `check_only`. The component writes a failed record before returning non-zero when prerequisites are missing; a clean run is therefore backed by a concrete status artifact, not only an exit code.

## Usage

```bash
workchain run-component setup . --params-json '{"check_only": true}'
```

In a chain, typically first:

```yaml
steps:
  - name: setup
    enabled: true
    params:
      check_only: false
```

## Tier

Light. No models — just checking for and (optionally) installing python/node dependencies via `uv sync` / `npm install`.
