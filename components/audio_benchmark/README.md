# audio_benchmark

Runs the LUFS Workchain quality-benchmark suite against an audio file and files a JSON report — it measures, it doesn't gatekeep.

## What it does

`audio_benchmark` is the workchain's diagnostic pass. It sources seven independent check scripts (format, loudness, DC offset, noise floor, spectral, phase, dynamics) against the input file, runs whichever subset you ask for, and combines the results into a single JSON report via a small python3 helper. Each check writes to a temp file; if a check's output fails to parse, the run still completes but is honestly marked `completed_with_errors` rather than papering over it as clean. This is a report, not a gate — it tells you things, it doesn't fail your chain because loudness came in hot.

## Parameters

| Name | Type | Default | Description |
|---|---|---|---|
| `checks` | array | `["format", "loudness", "dc_offset", "noise_floor", "spectral", "phase", "dynamics"]` | Which checks to run (format, loudness, dc_offset, noise_floor, spectral, phase, dynamics, or `"all"`) |
| `expected_spec` | string | `""` | Expected format spec for the format check (e.g. `"24/48000/2"` for 24-bit, 48kHz, stereo) |

## Inputs / Outputs

- Input: `type: text` — takes the input audio from context (`input_file`); no `input_types` restriction is declared.
- Outputs (`outputs.items`, schema v1.0):

| Name | Type | Path template | Required |
|---|---|---|---|
| `benchmark_report` | json | `logs/audio_benchmark.json` | yes |
| `primary_output` | file | `logs/audio_benchmark.json` | yes |

(Both point at the same combined report — `primary_output` is the conventional alias.)

## Verified IN (inbound contract)

step.yaml declares exactly one requirements class:

```yaml
requirements:
  commands:
    - ffmpeg
    - ffprobe
    - python3
```

That's it — no python venv/packages, no node, no models, no env vars declared. `lib/workchain_preflight.py` checks these three commands are on `PATH` before `run.sh` is ever invoked. If any are missing, the component never runs — you get a preflight failure, not a partial benchmark.

## Verified OUT (outbound contract)

```yaml
verify:
  schema_version: "1.0"
  outputs:
    - name: benchmark_report
      assert: [exists, non_empty, json_valid]
      json_has: [checks, benchmark_count]
    - name: primary_output
      assert: [exists, non_empty, json_valid]
```

`lib/workchain_verify.py` runs these asserts after `run.sh` exits cleanly. `benchmark_report` must exist, be non-empty, parse as valid JSON, and contain the keys `checks` and `benchmark_count`. `primary_output` gets the same existence/non-empty/valid-JSON treatment. No `post_conditions` are declared — the contract is purely structural (a well-formed report), not a numeric assertion on any individual check's values. That's deliberate: this component reports, it doesn't judge. Passing verify means the report is trustworthy shape, not that the audio "sounds good" — exit 0 alone proves nothing here; verify is what proves the report is real.

## Usage

```bash
workchain run-component audio_benchmark input.wav --params-json '{"checks": ["loudness", "phase"], "expected_spec": "24/48000/2"}'
```

In a chain:

```yaml
steps:
  - name: audio_benchmark
    enabled: true
    params:
      checks: ["format", "loudness", "dc_offset", "noise_floor", "spectral", "phase", "dynamics"]
      expected_spec: ""
```

## Tier

Light. No python venv, no models — just ffmpeg/ffprobe/python3 on the command line. All arithmetic uses stdlib python3 (replacing `bc`, which is absent from minimal containers).
