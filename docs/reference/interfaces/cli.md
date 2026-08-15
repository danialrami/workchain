---
title: CLI Reference
description: Complete command reference for the workchain CLI — all commands, flags, exit codes, and JSON output shapes.
type: reference
---

# CLI Reference

The `workchain` binary (`@lufs-audio/workchain`, Node 18+) is the primary human and agent interface to the LUFS Workchain engine. Every command delegates to a single shared YAML parser (`lib/workchain_yaml.py`) so the CLI, Bash engine, and MCP server agree on chain structure, parameter resolution, and validation semantics.

## Global options

These flags are accepted before any subcommand and affect the entire invocation:

| Flag | Description |
|---|---|
| `-V, --version` | Print version and exit |
| `--json` | Output raw JSON (machine mode). Human-friendly text otherwise. |
| `--no-color` | Disable coloured terminal output |
| `--verbose` | Verbose logging to stderr (raw engine output, NDJSON progress stream) |
| `-h, --help` | Display help for the current command |

## Exit codes

Every command uses a consistent exit-code contract:

| Code | Meaning | Typical cause |
|---|---|---|
| `0` | Success | Command completed (or dry-run plan generated, or validation passed) |
| `1` | Execution error | Component failed, chain halted, batch had failures |
| `2` | Input error | File not found, unsupported format, bad chain/component name |
| `3` | Configuration error | Workchain root not found (missing `engine/workchain-engine.sh`) |

## `workchain run`

Execute a processing chain on an audio file.

```bash
workchain run <chain> <input> [options]
```

**Arguments:**

| Arg | Description |
|---|---|
| `<chain>` | Chain name (resolved against `chains/<name>.yaml`) or path to a chain YAML file |
| `<input>` | Input audio file path |

**Options:**

| Flag | Description | Default |
|---|---|---|
| `-o, --output <dir>` | Output directory | `./output_YYYYMMDD_HHMMSS` |
| `--timeout <seconds>` | Max execution time in seconds | `3600` |
| `--dry-run` | Preview chain execution without running it | — |
| `--report` | Generate HTML report after chain completes | — |

**Examples:**

```bash
workchain run deliverable-voice song.wav -o ./output
workchain run deliverable-voice song.wav --dry-run --json
workchain run simple-test input.wav -o /tmp/out --json --report
workchain run ./my-chain.yaml /path/to/input.mp3 -o /tmp/out --timeout 7200
```

**Exit codes:** `0` (completed or dry-run), `1` (execution failed), `2` (bad input), `3` (no root).

### JSON output shape (annotated)

The following is a real captured run of `workchain run simple-test /tmp/test_tone.wav -o /tmp/wc-out --json` on a 5-second 440 Hz sine tone:

```json
{
  "status": "completed",
  "chain": "simple-test",
  "input_file": "/tmp/test_tone.wav",
  "input_name": "test_tone",
  "input_ext": "wav",
  "output_dir": "/tmp/wc-out",
  "duration_ms": 4437,
  "steps": {
    "normalization": {
      "preflight": {
        "satisfied": true,
        "checks": [
          {"name": "command:ffmpeg", "ok": true},
          {"name": "command:ffprobe", "ok": true}
        ],
        "resolved_params": {
          "target_lufs": -14,
          "two_pass": true,
          "lra": 7,
          "true_peak": -1.5
        }
      },
      "outputs": {
        "primary_output": {
          "path": "/tmp/wc-out/test_tone_normalized.wav",
          "type": "file",
          "measured_lufs": "-14.04"
        }
      },
      "verification": {
        "tier": "verified",
        "verified": true,
        "checks": [
          {"name": "primary_output.exists", "ok": true},
          {"name": "primary_output.audio_valid", "ok": true, "detail": "audio_stream=True duration=5.000s"},
          {"name": "integrated_loudness_on_target", "ok": true, "detail": "measured -14.04 LUFS vs target -14.0 (+/-1.0)"}
        ],
        "failures": []
      }
    }
  }
}
```

**Key fields:**
- `duration_ms` — wall-clock time (includes verification)
- `steps.<name>.preflight.resolved_params` — parameters the component actually ran with, after resolving globals and defaults
- `steps.<name>.verification.tier` — `"verified"` (contract declared and passed), `"unverified"` (no contract)
- `steps.<name>.verification.checks[]` — every structural and numeric assert with pass/fail
- `steps.<name>.verification.failures[]` — any failed checks (empty = all passed)

### Dry-run JSON output

The `--dry-run` flag previews the chain without executing components:

```json
{
  "status": "dry_run",
  "mode": "dry-run",
  "chain": "Simple Test Chain",
  "step_count": 2,
  "steps": [
    {"name": "normalization", "outputs": ["primary_output", "loudness_metadata"]},
    {"name": "audio_benchmark", "outputs": ["benchmark_report", "primary_output"]}
  ]
}
```

The dry run parses the chain and component schemas but never touches the input — valid even before the input exists.

## `workchain run-component`

Run a component standalone, outside of a chain.

```bash
workchain run-component <component> <input> [options]
```

**Arguments:**

| Arg | Description |
|---|---|
| `<component>` | Component directory name under `components/` |
| `<input>` | Input audio file or directory (for batch mode) |

**Options:**

| Flag | Description | Default |
|---|---|---|
| `-o, --output <dir>` | Output directory | `./output_YYYYMMDD_HHMMSS` |
| `--timeout <seconds>` | Max execution time in seconds | `3600` |
| `--params-json <json>` | Component parameters as JSON string | — |
| `-r, --recursive` | Recursively scan directories for audio files (batch mode) | — |
| `-e, --extensions <list>` | Comma-separated list of extensions | `mp3,wav,flac,...` |

**Examples:**

```bash
workchain run-component normalization input.wav -o ./output
workchain run-component normalization input.wav --params-json '{"target_lufs":-14}'
workchain run-component audio_benchmark /path/to/folder --json -r -e mp3,wav
```

**Exit codes:** `0`, `1`, `2`, `3` (same as `run`).

**Verification:** When run directly, `run-component` still runs inbound preflight and outbound verification — a standalone "ran" becomes "proven correct."

## `workchain chains`

List available processing chains.

```bash
workchain chains [options]
```

**Options:**

| Flag | Description |
|---|---|
| `--filter <pattern>` | Case-insensitive substring filter by name |

**Examples:**

```bash
workchain chains                 # human-readable table
workchain chains --json          # machine-readable array
workchain chains --filter astro  # filter by name
```

**JSON output:** Array of `{name, description, version, steps, components[], path}`.

## `workchain chain`

Show a single chain definition.

```bash
workchain chain <name>
```

**Arguments:**

| Arg | Description |
|---|---|
| `<name>` | Chain name (or `tests/<name>` for test chains) |

**JSON output shape:**

```json
{
  "name": "Simple Test Chain",
  "version": "1.0",
  "engineVersion": "2.0",
  "globals": {"test_param": "value"},
  "steps": [
    {"name": "normalization", "enabled": true, "params": {"target_lufs": -14}},
    {"name": "audio_benchmark", "enabled": true, "params": {}}
  ]
}
```

## `workchain components`

List available processing components.

```bash
workchain components [options]
```

**Options:**

| Flag | Description |
|---|---|
| `--filter <pattern>` | Case-insensitive substring filter by name |

**JSON output:** Array of `{name, description, version, type, param_count}`.

## `workchain component`

Show a component's full schema.

```bash
workchain component <name>
```

**Arguments:**

| Arg | Description |
|---|---|
| `<name>` | Component directory name under `components/` |

**JSON output:** Full schema with `name`, `description`, `version`, `type`, `input_types[]`, `outputs` (with `items[]` each having `name`, `type`, `description`, `required`, `path_template`), `params[]` (each with `name`, `type`, `default`, `description`, `range`), and `requirements`.

## `workchain validate`

Validate chain YAML files against the single shared parser.

```bash
workchain validate <chain> [options]
```

**Arguments:**

| Arg | Description |
|---|---|
| `<chain>` | Chain name, or `"all"` to validate every chain |

**Options:**

| Flag | Description |
|---|---|
| `--strict` | Schema-aware checks: param types, numeric ranges, unknown params; reports missing commands |
| `--require-commands` | Also **fail** when a declared command is missing from PATH |

**Exit codes:** `0` (valid), `1` (invalid), `2` (not found).

`--strict` checks every step's params against the component schema. Missing commands are reported as `environment` findings, not errors — a machine fact, not a file fact. Use `--require-commands` to gate on them before execution.

## `workchain doctor`

Check every component's inbound dependency contract (preflight-all).

```bash
workchain doctor [options]
```

**Options:**

| Flag | Description |
|---|---|
| `--deep` | Also verify model content hashes (slow — sha256 of model weights) |

**JSON output:**

```json
{
  "summary": {"total": 6, "ok": 5, "missing_deps": 1},
  "components": [
    {"component": "normalization", "state": "ok", "failures": []},
    {"component": "stem_separation", "state": "missing", "failures": ["python:venv"]}
  ]
}
```

## `workchain registry`

Manage the generated component index.

```bash
workchain registry [action]
```

**Arguments:**

| Arg | Description | Default |
|---|---|---|
| `[action]` | `generate` or `check` | `generate` |

- **`generate`** — (re)writes `components/index.json` with manifests, tier, definition hashes
- **`check`** — exits 1 if the index is missing or stale (for CI gates)

The index is **generated**, never hand-edited.

## `workchain generate`

Scaffold a new component.

```bash
workchain generate component [options]
```

**Options:**

| Flag | Description |
|---|---|
| `--name <name>` | Component name (snake_case, lowercase) |
| `--description <text>` | Component description |
| `--type <type>` | Component type: `audio`, `image`, `video`, `data`, `text` |
| `--kind <kind>` | Component kind: `light`, `heavy`, `api` (default: inferred from deps) |
| `--params <json>` | Parameter definitions as JSON array |
| `--commands <list>` | Required system commands (comma-separated) |
| `--python-packages <list>` | Required Python packages (implies `heavy`) |
| `--node-packages <list>` | Required Node packages (comma-separated) |
| `--dependency <name>` | Previous step component name |
| `--output-subdir <path>` | Output subdirectory name |

The generated component includes `step.yaml` (with `requirements` + `verify`), `run.sh` (fails until implemented via `WORKCHAIN_NOT_IMPLEMENTED=1` sentinel), `provision.sh`, `test-chain.yaml`, and `README.md`.

## `workchain config`

Manage persistent configuration.

```bash
workchain config <subcommand> [key] [value]
```

**Valid keys:** `workchainRoot`, `server` (default: `local`), `defaultChain` (default: `deliverable-voice`), `outputDir` (default: `./output`), `concurrency` (default: CPU-1).

**Subcommands:** `set`, `get`, `list [--json]`, `delete`, `reset`.

**Environment variable overrides:** `LUFS_WORKCHAIN_ROOT`, `LUFS_WORKCHAIN_SERVER`, `LUFS_WORKCHAIN_DEFAULT_CHAIN`, `LUFS_WORKCHAIN_CONCURRENCY` take precedence over persistent config.

## NDJSON progress stream (stderr)

While a chain runs, the CLI emits NDJSON to stderr:

```
{"progress":{"step":"normalization","status":"running"}}
{"progress":{"step":"normalization","status":"completed"}}
{"progress":{"step":"audio_benchmark","status":"running"}}
{"progress":{"step":"audio_benchmark","status":"completed"}}
{"progress":{"status":"workchain_completed"}}
```

This is always produced with `--json`; with `--verbose`, raw engine stderr is also forwarded. The progress stream is best-effort — the authoritative result comes from the final JSON on stdout.