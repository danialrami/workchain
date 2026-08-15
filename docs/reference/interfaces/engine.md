---
title: Engine Reference
description: Complete reference for the Bash engine — invocation, environment contracts, parameter resolution, stderr/stdout discipline, and built-in helpers.
type: reference
---

# Bash Engine Reference

The Bash engine (`engine/workchain-engine.sh`) is the lowest-level interface. The Node CLI and MCP server both delegate to it. It can be invoked directly for advanced use cases, debugging, or environments where Node is unavailable.

## Invocation

```bash
./engine/workchain-engine.sh -c <chain> <input> [options]
```

**Options:**

| Flag | Description |
|---|---|
| `-c, --chain <file>` | Chain YAML file (required). Resolved against `chains/` if not an absolute path. |
| `-o, --output <dir>` | Output directory (default: `./output_YYYYMMDD_HHMMSS`) |
| `-d, --debug` | Enable debug logging (verbose output to console) |
| `-h, --help` | Show usage |

**Examples:**

```bash
# Basic usage
./engine/workchain-engine.sh -c chains/deliverable-voice.yaml input.wav

# Custom output
./engine/workchain-engine.sh -c chains/deliverable-voice.yaml -o ./results input.wav

# Debug mode
./engine/workchain-engine.sh -c chains/deliverable-voice.yaml -d input.wav
```

**Preconditions** (enforced at startup):

- `-c` chain file exists and is a valid YAML chain
- `<input>` exists, is a file, and is in a supported audio format
- `python3` and `ffmpeg` are on `PATH`

## stdout / stderr discipline

- **stdout is the final JSON.** The engine writes structured progress markers (running/completed per step) to stdout during execution. The CLI parses these for its NDJSON progress stream. No component or engine log output should appear on stdout.
- **All logging goes to stderr.** Human-readable status messages (`log_info`, `log_warn`, `log_error`, `log_step`, `log_debug`) are written to stderr via the helpers in `lib/common-utils.sh`.
- **Run log** (when `WORKCHAIN_RUNLOG` is set): every `log_*` line is also appended verbatim to that file — uncolored, with full ISO-8601 timestamps. This is done with a bare `printf >>` (no subprocess per line) for performance at scale.

## Engine flow

1. **`parse_arguments`** — parse flags, validate input files exist and are audio, resolve chain path.
2. **`validate_chain`** — delegate to `lib/workchain_yaml.py validate` (the single parser). Exit 1 on invalid YAML.
3. **`initialize_context`** — create `context.json` in the output directory with `input_file`, `input_name`, `input_ext`, `output_dir`, `chain_file`, `chain_name`, `start_time`.
4. **`load_globals`** — read chain-level `globals:` from the YAML and write them into `context.json`.
5. **`run_steps`** — iterate the engine plan (base64-encoded `STEP_CONFIG` lines). For each step:
   a. **`record_step_params`** — persist resolved params to context.json (params > globals > default).
   b. **`preflight_step`** — run `lib/workchain_preflight.py` (Verified IN). Reject if dependencies missing.
   c. **`source <component>/run.sh`** — execute the component. Components `return`, never `exit`.
   d. **`verify_step`** — run `lib/workchain_verify.py` (Verified OUT). Halt chain if contract fails.
   e. **`update_input_file`** — set `input_file` to the step's primary output for the next step.
6. **`finalize`** — write `end_time` and `status: completed` to context.json.

If any step fails preflight, execution, or verification, the chain halts immediately and context.json records `status: failed`.

## Environment contracts

### Internal environment variables

These are exported by the engine and available to all components:

| Variable | Source | Description |
|---|---|---|
| `WORKCHAIN_ROOT` | `lib/constants.sh` | Absolute path to the workchain repository root |
| `LIB_DIR` | `lib/constants.sh` | Absolute path to `lib/` directory |
| `COMPONENTS_DIR` | `lib/constants.sh` | Absolute path to `components/` directory |
| `ENGINE_DIR` | `lib/constants.sh` | Absolute path to `engine/` directory |
| `CHAINS_DIR` | `lib/constants.sh` | Absolute path to `chains/` directory |
| `CONTEXT_FILE` | `init_step_runner` | Path to `context.json` for the current run |
| `CURRENT_STEP` | `init_step_runner` | Name of the currently executing component |
| `STEP_CONFIG` | Engine plan (resolved) | YAML block with the step's resolved configuration (params > globals > default) |
| `WORKCHAIN_RUNLOG` | `runlog_open` | Path to the run log file (inherited by child processes) |

### Run log environment

| Variable | Description |
|---|---|
| `WORKCHAIN_RUNLOG` | Path to the active run log file. When set, all `log_*` calls append to it. Children inherit it — at scale (e.g. 259k files), all engine invocations append to the same file. |
| `WORKCHAIN_RUNLOG_DISABLE` | Set to `1` to suppress run log creation entirely. |

### Component parameter overrides

Heavy components may read additional environment variables to locate external resources:

| Variable | Used by | Description |
|---|---|---|
| `WORKCHAIN_AUDIO_SEPARATOR_BIN` | `stem_separation` | Path to the audio-separator binary (overrides PATH lookup) |
| `WORKCHAIN_AUDIO_SEPARATOR_MODELS` | `stem_separation` | Path to model weights directory |
| `LUFS_WORKCHAIN_ROOT` | CLI | Override workchain root directory (CLI only, not the engine) |

### Requirements classes

Components declare inbound requirements in `step.yaml` under `requirements:`. The preflight (`lib/workchain_preflight.py`) checks these before running:

| Class | step.yaml | Checked |
|---|---|---|
| `commands` | `commands: [ffmpeg, ffprobe]` | On `PATH` via `shutil.which()` |
| `python` | `python: { venv: ".venv", packages: [numpy] }` | Venv exists, Python version matches, packages importable |
| `node` | `node: [tsx]` | On `PATH` (future; currently planned) |
| `models` | `models: [{path: "models/foo.pt"}]` | File exists; `--deep` also verifies sha256 |
| `env` | `env: [ARTYSHIELD_API_KEY]` | Environment variable is set (presence only, never value) |

## `return` vs `exit` in component scripts

Components are **sourced** (not executed as subprocesses): `source "$COMPONENTS_DIR/$step_name/run.sh"`. This means:

- **Use `return`, never `exit`.** A component that calls `exit` will terminate the entire engine process, not just the component.
- Use `return 0` for success, `return 1` (or any non-zero) for failure.
- The engine checks the return code immediately and halts the chain on failure.

## `STEP_CONFIG` resolution

Each step receives a resolved `STEP_CONFIG` YAML block as its second argument (`$2`). The resolution follows a strict precedence:

```
step params > chain globals > component schema default
```

1. **Step params** (from the chain YAML `steps[].params`) take highest priority.
2. **Chain globals** (from the chain YAML `globals:`) override schema defaults.
3. **Component schema defaults** (from `step.yaml` `params_schema[].default`) are the base.

The resolution is performed by `lib/workchain_yaml.py resolve-steps` / `engine-plan`. Components read resolved params by grepping `STEP_CONFIG`:

```bash
local value=$(echo "$STEP_CONFIG" | grep -E "^\s+${param_name}:" | sed "s/.*${param_name}: *//" | head -1)
```

## The `WORKCHAIN_NOT_IMPLEMENTED` sentinel

Generated component scaffolds include `WORKCHAIN_NOT_IMPLEMENTED=1` in `run.sh`. This sentinel causes a deliberate failure when the component is run before its implementation is complete. Remove this line only when the component actually produces its output — and fill in a real `verify:` block first.

## Built-in helpers (`lib/common-utils.sh`)

The engine sources `lib/common-utils.sh`, which provides:

### Logging

| Function | Level | Output |
|---|---|---|
| `log_info "message"` | INFO | Green `[HH:MM:SS] message` to stderr + run log |
| `log_warn "message"` | WARN | Yellow `[HH:MM:SS] WARNING: message` to stderr + run log |
| `log_error "message"` | ERROR | Red `[HH:MM:SS] ERROR: message` to stderr + run log |
| `log_debug "message"` | DEBUG | Blue to stderr (only when `DEBUG=1`); always to run log |
| `log_step "message"` | STEP | Cyan `[HH:MM:SS] STEP: message` to stderr + run log |
| `runlog "LEVEL" "message"` | — | Appends to run log only, no console output |

### Context JSON access (special-char-safe)

Every value is passed to Python via **environment variables inside a quoted heredoc** (`<< 'PYEOF'`), never shell-interpolated into Python source. This makes them robust to apostrophes, spaces, quotes, and backslashes in file paths.

| Function | Returns | Description |
|---|---|---|
| `ctx_get <cf> <dotted.key>` | scalar | Get a value from context.json by dotted key |
| `ctx_get_abs <cf> <dotted.key>` | absolute path | Get a value and resolve it to an absolute path |
| `ctx_get_json <cf> <dotted.key>` | JSON string | Get a dict/list value as JSON |
| `get_global <cf> <key> <default>` | scalar | Shorthand for `globals.<key>` with a fallback |
| `ctx_set_status <cf> <component> <status> [reason] [error]` | — | Set a step's status in context.json |

### Output registration

| Function | Description |
|---|---|
| `register_output <cf> <component> <name> <path> [type] [metadata_json] [status]` | Register an output in context.json with metadata, description, and path_template from `step.yaml` |

### Utility

| Function | Description |
|---|---|
| `command_exists <cmd>` | Check if a command is on PATH |
| `ensure_dir <dir>` | Create directory if it doesn't exist |
| `is_audio_file <file>` | Check if a file has a supported audio extension |
| `get_audio_extension <file>` | Get lowercase extension |
| `timestamp` | Get `YYYYMMDD_HHMMSS` timestamp |
| `error_exit <message>` | Log error and exit |
| `runlog_open <label> [key=value...]` | Start or inherit a run log |

## Chain validator (`engine/chain-validator.sh`)

This script used to be a second, independent, grep-based validator — it disagreed with the Python parser. It is now a thin delegate to `lib/workchain_yaml.py` and holds no validation logic of its own.

```bash
# Standalone usage
./engine/chain-validator.sh chains/my-chain.yaml
```

Validation now happens in exactly one place: `lib/workchain_yaml.py`. Two implementations of "is this chain valid?" is the same defect class as a component that exits 0 while producing silence: a check that can disagree with the truth is worse than no check.

## Step runner (`engine/step-runner.sh`)

Provides the `init_step_runner` function that sets up `CONTEXT_FILE` and `CURRENT_STEP`, plus helpers:

| Function | Description |
|---|---|
| `init_step_runner <context_file>` | Initialize the step runner with a context file |
| `get_context_value <dotted.key>` | Read a value from context.json |
| `set_context_value <dotted.key> <value>` | Write a value to context.json |
| `run_step <name> <step_config> <context_file>` | Execute a step by sourcing its `run.sh` |
| `get_step_param <config> <name> [default]` | Grep a param from the STEP_CONFIG YAML block |
| `get_input_file` | Shorthand for `input_file` from context |
| `get_output_dir` | Shorthand for `output_dir` from context |
| `get_previous_step_output <step>` | Read a previous step's output from context