# Component Template

The canonical scaffold for a new workchain component. Copy it, don't retype it — `components/_template/step.yaml` is the live contract schema, not a description of one. This README is a pointer, not the guide; see `docs/component-development.md` for the full walkthrough.

## Structure

```
my_component/
├── step.yaml       # Definition: params, outputs, requirements, verify
├── run.sh          # Execution script
├── provision.sh    # Idempotent setup for declared requirements (even light components ship one — it just says "nothing to provision")
└── README.md       # Component documentation — every component ships one, no exceptions
```

## step.yaml

`step.yaml` has two halves: the familiar part (name, params, outputs) and the contract (`requirements:` / `verify:`). Both halves ship on every component — a scaffold with no `verify:` block hasn't shipped.

```yaml
name: my_component
description: "What this component does"
version: "1.0"

type: audio  # audio, image, video, data, reporting, system

input_types: ["wav", "mp3", "aiff", "aif", "flac", "m4a", "ogg"]
output_type: audio

params_schema:
  param_name:
    type: number  # number, string, boolean
    default: 100
    description: "Parameter description"
    range:
      min: 0
      max: 200

# outputs: uses the schema_version/items form — not a bare list.
outputs:
  schema_version: "1.0"
  description: "Standardized output definitions for this component"
  items:
    - name: primary_output
      type: file                  # file, directory, json, number, string, boolean
      description: "Primary output file"
      required: true               # step fails if this is not created
      mime_type: "audio/wav"       # optional, for file outputs
      path_template: "output/{input_name}_template.{input_ext}"

    - name: metadata
      type: json
      description: "Processing metadata (LUFS values, etc.)"
      required: false
      path_template: "logs/template_metadata.json"

# ── Inbound contract (verified IN) ── what this component NEEDS.
# Enforced BEFORE run.sh by lib/workchain_preflight.py — a missing dependency
# fails honestly, never a fake success. Declare only the classes you use.
requirements:
  commands:                        # PATH binaries (checked via `which`)
    - ffmpeg
  # python:                        # a component-local (or shared) venv — heavy components only
  #   venv: ".venv"
  #   python_version: ">=3.10"
  #   packages:
  #     - { import: "numpy", dist: "numpy", version: ">=1.26" }
  #     - "soundfile"              # shorthand: import name only
  #   provision: "python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  # node:                          # node packages (checked via require.resolve)
  #   packages: [ { require: "jdenticon", version: "^3" } ]
  # models:                        # heavy artifacts (exists+size every run; sha256 only --deep)
  #   - { name: "weights", path: "models/weights.bin", bytes: 12345678, sha256: "…" }
  # env:                           # required env vars — presence only, never the value
  #   - SOME_API_KEY

# ── Outbound contract (verified OUT) ── what this component GUARANTEES.
# Enforced AFTER run.sh exits 0, by lib/workchain_verify.py. Structural
# asserts per output, plus optional component-level post-conditions
# (metamorphic checks — right level of specificity for creative/perceptual ops).
verify:
  schema_version: "1.0"
  outputs:
    - name: primary_output
      assert: [exists, non_empty, audio_valid]
    - name: metadata
      assert: [exists, non_empty, json_valid]
      json_has: [example_param]
  # post_conditions:
  #   - id: duration_preserved
  #     check: audio_duration_matches      # metamorphic: output duration ≈ source
  #     outputs: [primary_output]
  #     tolerance_s: 0.2
```

Full spec for both contract halves: `docs/component-development.md`, and `docs/product/workchain/03-component-contract` in the knowledge base for the *why*.

## run.sh

Receives `$1` (context JSON file path) and `$2` (step config YAML), and is **sourced** by the engine — not subprocessed. Always `return 0` / `return 1`; never `exit`, or you take the whole engine down with you.

### Reading and writing context — always through the helpers

Never shell-interpolate a context path into a `python3 -c "...open('$CONTEXT_FILE')..."` one-liner. Real input/output paths contain apostrophes and spaces (`Here's The Song.wav`), and naive string interpolation breaks on them — or worse, gets read as shell syntax. Use the safe helpers from `lib/common-utils.sh` instead, which pass every value through environment variables into a quoted heredoc:

```bash
INPUT_FILE=$(ctx_get_abs "$CONTEXT_FILE" input_file)   # absolute path, empty if missing
OUTPUT_DIR=$(ctx_get_abs "$CONTEXT_FILE" output_dir)
INPUT_NAME=$(ctx_get "$CONTEXT_FILE" input_name)        # scalar value (json for list/dict)
INPUT_EXT=$(ctx_get "$CONTEXT_FILE" input_ext)
```

After processing, register what you produced with `register_output` — it writes into `context.json['steps'][component]['outputs']`, sets the backward-compatible `output`/`output_dir` fields, and can set step status in the same call:

```bash
# register_output <context_file> <component> <output_name> <path> [type] [metadata_json] [status]
register_output "$CONTEXT_FILE" "my_component" "primary_output" "$OUTPUT_FILE" "file" \
    "{\"example_param\": $EXAMPLE_PARAM}" \
    "completed"
```

`register_output` records what the component *did*; it is not `verify:`. `verify:` is the separate, later check that confirms what you registered actually holds up.

### Fail honestly if unimplemented

A freshly copied scaffold must **fail** until you've actually implemented it. `_template/run.sh` already produces real output and calls `register_output()`, which means copying it verbatim gives you a component that "succeeds" at doing nothing useful — drop a sentinel that actively breaks (`return 1` plus `log_error`, or an assertion your `verify:` block is guaranteed to fail) until the real logic replaces it. A component that reports success it hasn't earned is worse than one that visibly hasn't been written yet.

## Creating a New Component

1. Copy the template directory:
   ```bash
   cp -r components/_template components/my_new_component
   ```
2. Edit `step.yaml` — params, outputs, requirements, verify.
3. Edit `run.sh` with your component's logic.
4. Write `provision.sh` if you declared a `python`/`node`/`models` requirement (light components with `commands:` only can leave the "nothing to provision" default).
5. Write `README.md` — every component ships one; it is not optional.
6. Regenerate the registry: `workchain registry generate`. `components/index.json` is **generated**, never hand-edited — `registry check` diffs it against what's committed and fails CI if it's stale.
7. Run `workchain doctor` to preflight the new component's inbound contract before running anything for real.
8. Add the component to a signal-chain:
   ```yaml
   steps:
     - name: my_new_component
       enabled: true
       params:
         param_name: 50
   ```

## Available Helper Functions

From `lib/common-utils.sh`:
- `log_info`, `log_warn`, `log_error`, `log_debug`, `log_step`
- `command_exists` — check if a command is available
- `error_exit` — log and exit with a message
- `ensure_dir` — create a directory if needed
- `is_audio_file` — check if a file is audio
- `ctx_get`, `ctx_get_abs`, `ctx_get_json` — safe context.json reads
- `get_global` — read `globals.<key>` with a default
- `register_output`, `ctx_set_status` — safe context.json writes

## Where to Go Deeper

- `docs/component-development.md` — the full guide: contract details, verify assert primitives, post-conditions, registry hashing/tiering.
- `components/_template/step.yaml` — the canonical, always-current schema. If a guide and the template disagree, the template wins.

lufs.
