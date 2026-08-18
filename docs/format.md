# Workchain Chain and Component File Format

This document specifies the file format for LUFS Workchain chains and components. The format is declared unencumbered; this specification is the reference a competing engine implementation should follow. Where the existing engine's behaviour is a wart, it is noted plainly. Where something is genuinely unspecified, "unspecified" is written rather than invented.

**Source of truth**: `lib/workchain_yaml.py` (Python parser/validator/resolver), `engine/chain-validator.sh` (Bash validation), `lib/workchain_preflight.py` (requirement checking), `lib/workchain_verify.py` (output verification).

---

## Table of Contents

1. [Overview](#overview)
2. [Chain File](#chain-file)
3. [Parameter Precedence](#parameter-precedence)
4. [Component File (step.yaml)](#component-file-stepyaml)
5. [params\_schema](#params_schema)
6. [outputs](#outputs)
7. [requirements](#requirements)
8. [verify](#verify)
9. [Known Limitations and Parser Gotchas](#known-limitations-and-parser-gotchas)
10. [Annotated Working Example](#annotated-working-example)

---

## Overview

A Workchain **chain** is a YAML file that sequences named **components** against an input file. Each component is a directory under `components/` containing a `step.yaml` (the component contract) and a `run.sh` (the implementation). The engine resolves parameters, calls `lib/workchain_preflight.py` to verify inbound dependencies, executes `run.sh`, and then calls `lib/workchain_verify.py` to enforce the outbound contract.

---

## Chain File

A chain file is a YAML mapping at the top level. File extension must be `.yaml` or `.yml`.

### Required Fields

The Python validator (`workchain_yaml.py validate`) rejects a chain missing any of these three fields:

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Human-readable chain name. |
| `version` | string or number | Chain version. No format is enforced; use semver strings by convention (e.g. `"1.0"`). |
| `steps` | list | One or more step entries (see below). Must be non-empty. |

The Bash validator (`engine/chain-validator.sh`) checks the same three fields using `grep -qE "^name:"` etc., so fields that appear below a block scalar (see [Limitations](#known-limitations-and-parser-gotchas)) will be missed by the Bash validator even though the Python validator correctly reports them missing.

### Optional Fields

| Field | Type | Description |
|-------|------|-------------|
| `description` | string | Human-readable description. No effect on execution. Must be a single-line quoted string — do not use block scalars (see Limitations). |
| `engine_version` | string | Declares the minimum engine version required. Read and stored for documentation purposes; **not validated or enforced by any current engine code**. |
| `globals` | mapping | Key/value pairs made available to all steps as lower-precedence parameters. Keys that match a component's `params_schema` entry are passed through; others are ignored by the resolver. See [Parameter Precedence](#parameter-precedence). |

### Steps

`steps` is a YAML list of mappings. Each step mapping has:

| Key | Type | Required | Description |
|-----|------|----------|-------------|
| `name` | string | yes | Must match the name of a subdirectory under `components/`. The validator checks that the directory exists and contains both `step.yaml` and `run.sh`. **`name` is what gets executed** — the component resolved, its `run.sh` sourced, its `step.yaml` contract loaded. |
| `id` | string | no | **The step's record identity.** Defaults to the step `name`. See [Step identity (`id`)](#step-identity-id). |
| `in2` | string | no | Declares a **second audio input** for this step: a path or glob to a file on disk. See [Second input (`in2:`)](#second-input-in2). The component must declare `accepts_second_input: true` or validation refuses the step. |
| `enabled` | boolean | no | Default `true`. Set to `false` to skip this step. The engine logs "Skipping disabled step" and moves on without executing or verifying it. |
| `params` | mapping | no | Per-step parameter overrides. See [Parameter Precedence](#parameter-precedence). |

**Minimal valid chain:**

```yaml
name: "My Chain"
version: "1.0"
steps:
  - name: normalization
```

**Step with all keys:**

```yaml
steps:
  - name: format_conversion
    enabled: true
    params:
      target_format: wav
      sample_rate: 48000
```

---

## Step identity (`id`)

Each step may declare an optional `id:`. The **effective id** is the `id` value when it
is present and non-empty, otherwise the step's `name` (the component name). The effective
id is the key the step's record lives under in `context.json`'s `steps` map — nothing
else.

`name` and `id` are deliberately two different things:

| | `name` | `id` |
|---|--------|------|
| Resolves | the component: `components/<name>/` dir, `run.sh`, `step.yaml` contract | nothing — a pure record key |
| Used by | execution, file resolution, preflight, contract loading | `context.json` `steps` keying, the `__WC_STEP` env, `steps.<id>.*` lookups |
| Identical? | — | only when `id:` is absent (the default) |

The engine keys `context.json`'s `steps` on the effective id, so every write and read
for one step touches the same record:

- `record_step_params` writes `steps.<id>.params` before the step runs;
- `register_output` / `ctx_set_status` write `steps.<id>.outputs` / status while it runs;
- `lib/workchain_preflight.py` writes `steps.<id>.preflight`;
- `lib/workchain_verify.py` writes `steps.<id>.verification` afterwards.

A chain may therefore run two steps of the same component and each keeps its own record
under its own key — neither overwrites the other:

```yaml
steps:
  - name: cdp_transform
    id: trace
    params:
      effect: hilite.trace
  - name: cdp_transform
    id: blur
    params:
      effect: blur.blur
```

`context.json` then holds `steps.trace` and `steps.blur`, each with its own `params`,
`outputs`, and `verification` — instead of the second silently deleting the first's proof.

**Uniqueness is enforced.** Validation rejects a chain in which two steps resolve to the
same effective id (`workchain validate`, and the engine's own validation path, in both
strict and non-strict mode), with an error naming both steps and the colliding id. The
`steps` map must be a faithful per-step record; a chain the engine cannot record honestly
is refused rather than recorded wrongly. This includes disabled steps.

`id:` must be a single-line scalar — block scalars are not supported, see
[Known Limitations](#known-limitations-and-parser-gotchas).

---

## Second input (`in2:`)

A step may declare a second audio input with `in2:`. This is the first prerequisite
of chain topology beyond strict linear: a step can consume one extra file alongside
the chain input. The design and its scope are explained in
`docs/product/workchain/08-chain-topology.md`. `in2:` is a **single-line string** — a
path or glob to a file on disk. It is resolved and staged by the engine; the component
receives it through exactly one documented channel. There is deliberately **no second
declaration channel**: `in2:` in the chain is the only way to supply a second input.

### Accepted form

`in2:` must be a non-empty string naming a file, or a glob naming files:

```yaml
steps:
  - name: mix             # a component that declares accepts_second_input: true
    in2: "chains/examples/fixtures/in_b.wav"   # exact path
    params: { duration_mode: longest }
```

A **glob** (containing `* ? [`) is expanded and must match **exactly one** file — zero
matches (nothing to stage) or several (ambiguous) both fail closed at stage time.
Resolution base is the **engine's working directory** — the same rule as every other
engine path (`-c`/chain, the input, `-o`/output). A reference to *another step's
output* is **not** accepted: outputs-as-inputs and graph topology beyond two inputs are
explicitly out of scope for this unit (see the topology doc).

### Component requirement

A component that consumes a second input must declare it in its `step.yaml`:

```yaml
accepts_second_input: true
```

Validation **refuses** a chain step that declares `in2:` against a component without
this declaration — so a second input can never be silently dropped by a component that
does not know what to do with it.

### Staging and routing

1. **Validation** (`lib/workchain_yaml.py validate`) checks the syntax and the
   `accepts_second_input` gate. It does **not** touch the filesystem — whether the
   `in2:` path exists is a runtime fact of the machine running the chain.
2. **Staging** (`engine/workchain-engine.sh` `stage_second_input`), before `run.sh`:
   expands the glob, requires exactly one real audio file (`is_audio_file`), refuses a
   self-reference (`in2:` resolving to the step's own primary input), and computes the
   file's sha256. Fail closed at any point — the step never runs on a bad spec.
3. **Routing**: the resolved path is exported as **`WORKCHAIN_INPUT_2`** — the ONE
   documented channel. The component reads the primary input through the existing
   mechanism (`context.json` `input_file`) and the second through this env var. For a
   single-input step the env var is exported empty, and nothing else changes (byte-
   identical behaviour).
4. **Provenance**: the run JSON records both inputs' resolved paths (and the second
   input's sha256) under the step's effective id:

   ```json
   "steps": {
     "mix": {
       "inputs": {
         "in":  { "path": "<primary input>" },
         "in2": { "path": "<second input>", "sha256": "<hex>" }
       }
     }
   }
   ```

   This is what lets a two-input post-condition name *which* input's fact it measured.
   Keys recorded only when the step declares `in2:`; single-input steps gain nothing.

### Verification model

`lib/workchain_verify.py` resolves two-input records: `resolve_input_path(ctx,
step_key, "in"|"in2")` reads the recorded provenance, and the primary-input resolution
(`_resolve_source`) falls back to it. Post-condition classes are **not** added in this
unit (the POST_CHECKS owner does that); the model is that a two-input post-condition
names an input (`in`/`in2`) and measures a fact about it. The demo `mix` component
shows both halves available today: an **independent** re-measurement of the primary
timeline (`audio_duration_matches`) and a **component-written** fact sidecar about
both inputs (`json_fields_within`) — see `components/mix/README.md` for the honesty
split.

---

## Parameter Precedence

The engine resolves the effective parameter set for each step from three sources, in ascending priority:

1. **Schema default** — the `default` value declared in the component's `params_schema` entry.
2. **Chain globals** — values from the chain's `globals` mapping, filtered to keys that are known params of this component. A key in `globals` that does not match any param in the component's `params_schema` is silently dropped.
3. **Step `params`** — values in the step's own `params` mapping. These win over globals and defaults unconditionally.

The resolver (`workchain_yaml.resolve_params`) applies this precedence and passes the merged result to the component as the `STEP_CONFIG` environment block (a flat YAML mapping that `run.sh` reads via `get_param`). The verifier sees the same resolved params via `context.json` under `steps.<id>.params` — `id` being the step's effective id (its `id:`, defaulting to its `name`). For chains written before `id:` existed the key is the component name, unchanged.

**Legacy alias (normalization only):** if `globals.lufs_target` is set and the step is `normalization` and `target_lufs` is not in the step's own `params`, the resolver copies `globals.lufs_target` to `resolved.target_lufs`. This alias exists for backward compatibility with chains written before the param was renamed.

---

## Component File (step.yaml)

Each component directory must contain a `step.yaml` file. The file is a YAML mapping. All fields are optional unless marked required by the engine's validation path.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | no | Component display name. Defaults to the directory name if absent. |
| `description` | string | no | Human-readable description. No execution effect. |
| `version` | string or number | no | Component version. No format enforced. |
| `type` | string | no | Component category (e.g. `audio`, `image`, `data`). Informational only; the engine does not enforce type compatibility between steps. |
| `input_types` | list of strings | no | File extensions this component accepts (e.g. `[wav, mp3, flac]`). Informational; the engine does not currently gate execution on this. |
| `output_type` | string | no | Primary output type (e.g. `audio`). Informational only. |
| `params_schema` | mapping | no | Parameter definitions. See [`params_schema`](#params_schema). |
| `outputs` | mapping | no | Declared output artifacts. See [`outputs`](#outputs). |
| `requirements` | mapping | no | Inbound dependency declarations. See [`requirements`](#requirements). |
| `verify` | mapping | no | Outbound contract declarations. See [`verify`](#verify). |
| `accepts_second_input` | boolean | no | Declares the component consumes a **second input** via the `in2:` channel (issue #10). Validation rejects any chain step that declares `in2:` on a component without this. See [Second input (`in2:`)](#second-input-in2). |

---

## params\_schema

`params_schema` is a mapping from parameter name to a parameter definition mapping. The four keys the engine reads from each definition are:

| Key | Type | Description |
|-----|------|-------------|
| `type` | string | Data type: `string`, `number`, or `boolean`. Defaults to `string` if absent. Used for type-checking and range enforcement in strict validation mode. |
| `default` | scalar | Default value applied when neither globals nor step params supply a value. A param with no `default` key has no default. |
| `description` | string | Human-readable description of the parameter. No execution effect. |
| `range` | mapping | Numeric bounds: `{min: N, max: N}`. Both keys are optional. Checked in strict validation mode only (`--strict` flag). |

**There is no `required` key in `params_schema`.** The schema has no mechanism to declare a parameter mandatory. Making a parameter mandatory is done by convention: omit `default` from the schema entry and add an explicit guard in `run.sh` that errors out when the value is absent. Example from `format_conversion`:

```yaml
params_schema:
  target_format:
    type: string
    description: "Target format: wav, mp3, flac, ..."
    # no default — run.sh errors: "target_format parameter is required"
  preserve_quality:
    type: boolean
    default: true
    description: "Preserve sample rate, channels, bit depth"
```

Any keys in a param definition other than `type`, `default`, `description`, and `range` are silently discarded by `component_schema()`.

---

## outputs

`outputs` declares the artifacts a component produces. The engine's `register_output` helper reads `path_template` and `description` from this section and stores them in `context.json`; the verifier uses the names to resolve paths for assertion checks.

### Top-level structure

```yaml
outputs:
  schema_version: "1.0"   # string; currently only "1.0" is defined
  description: "..."       # optional human-readable summary
  items:                   # list of output item mappings
    - ...
```

`schema_version` and `description` are stored for documentation; `schema_version` is not validated against any allowed set.

### Output item fields

Each entry in `items` is a mapping with these keys:

| Key | Type | Required | Description |
|-----|------|----------|-------------|
| `name` | string | yes | Identifier used in `verify:` contracts and `context.json`. Use valid identifier characters (letters, digits, underscore). |
| `type` | string | yes | Artifact kind: `file`, `directory`, `json`, `number`, `string`, or `boolean`. |
| `description` | string | no | Human-readable description. Stored in `context.json` by `register_output`. |
| `required` | boolean | no | Declarative annotation. The engine does not currently enforce this automatically — whether a missing required output causes failure depends on the `verify:` contract's `assert` primitives. |
| `mime_type` | string | no | MIME type for file outputs. Stored as metadata; not validated. |
| `path_template` | string | no | Documentation of the output's expected path relative to the output directory. See below. |

### path\_template

`path_template` is a **documentation convention**, not an evaluated template. The engine's `register_output` reads the string from `step.yaml` and stores it verbatim in `context.json` as metadata. It does not substitute placeholders.

The placeholders used in existing components are:

| Placeholder | Meaning |
|-------------|---------|
| `{input_name}` | Base name of the current input file, without extension. Resolved from `context.json.input_name` by `run.sh`. |
| `{input_ext}` | Extension of the current input file, without leading dot. Resolved from `context.json.input_ext` by `run.sh`. |
| `{target_format}` | The `target_format` parameter value, used in `format_conversion` to express that the output extension follows the requested format. |

These placeholders have no defined substitution mechanism in the engine. Their meaning is purely documentary: each `run.sh` constructs the actual output path itself (typically with Bash variable expansion) and passes the concrete path to `register_output`. A competing implementation may choose to evaluate `path_template` and derive the output path from it, but the current engine does not.

The template path is relative to the output directory (`context.json.output_dir`). A path beginning with `logs/` (e.g. `logs/normalization.json`) conventionally indicates a sidecar file rather than a primary artifact.

---

## requirements

`requirements` is the inbound dependency contract. It is checked by `lib/workchain_preflight.py` before `run.sh` executes. A component with no `requirements` key passes preflight unconditionally.

All dependency classes are optional. A component declares only those it needs.

```yaml
requirements:
  commands: [...]
  python:
    ...
  node:
    ...
  models:
    - ...
  env: [...]
```

### commands

A list of command names. Each is checked with `shutil.which`. Failure halts the step before `run.sh` is called.

```yaml
requirements:
  commands:
    - ffmpeg
    - ffprobe
```

**Note on validation vs. runtime**: In strict validation mode without `--require-commands`, missing commands are reported as `environment` findings rather than errors. A chain is not considered _authoring-invalid_ merely because a required tool is absent from the validating machine. At runtime the engine calls `workchain_preflight.py` unconditionally before each step, and a missing command fails the step.

### python

Declares a component-local Python virtual environment.

| Key | Type | Description |
|-----|------|-------------|
| `venv` | string | Path to the venv directory, relative to the component directory. Default `.venv`. |
| `python_version` | string | Minimum Python version floor, e.g. `">=3.10"` or `"^3.11"`. Optional. |
| `packages` | list | Python packages to verify by import. Each entry is either a string (import name) or a mapping. |
| `provision` | string | Hint shown to the operator when preflight fails. Not executed automatically. |
| `when` | mapping | Guard: `{param_name: [value, ...]}`. The group is only required when the resolved param matches. Fails closed: if the param cannot be resolved, the group is treated as required. |

Each entry in `packages` is either:
- A plain string: the import module name (e.g. `"soundfile"`).
- A mapping with keys: `import` (module name), `dist` (distribution name for version lookup, defaults to `import` with underscores replaced by hyphens), `version` (version floor, e.g. `">=0.44"`).

Verification imports the module inside the declared venv's Python binary and reads the version via `importlib.metadata`.

```yaml
requirements:
  python:
    venv: ".venv"
    python_version: ">=3.10"
    packages:
      - { import: "audio_separator", dist: "audio-separator", version: ">=0.44" }
      - "soundfile"
    provision: "python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
    when:
      backend: [local, auto]
```

### node

Declares Node.js packages, checked via `require.resolve` in the component directory.

| Key | Type | Description |
|-----|------|-------------|
| `packages` | list | Node packages to verify. Each is a string or a mapping. |
| `when` | mapping | Same guard semantics as `python.when`. |

Each entry in `packages` is either:
- A plain string: the package require name.
- A mapping with keys: `require` (package name) and optionally `version` (version floor).

```yaml
requirements:
  node:
    packages:
      - { require: "jdenticon", version: "^3" }
      - "some-pkg"
```

### models

A list of model artifact declarations. Each entry is a mapping:

| Key | Type | Description |
|-----|------|-------------|
| `name` | string | Identifier for logging. |
| `path` | string | Path to the model file. If relative, resolved against the component directory unless `WORKCHAIN_AUDIO_SEPARATOR_MODELS` env var is set, in which case the basename is resolved there. |
| `bytes` | number | Expected file size in bytes. Checked with a 2% tolerance (minimum 1024 bytes). Optional. |
| `sha256` | string | Expected SHA-256 hex digest. Only checked when `--deep` is passed or `always_hash: true` is set. Optional. |
| `optional` | boolean | If `true`, an absent model is a passing check (the model is assumed to be auto-provisioned on first use). Default `false`. |
| `always_hash` | boolean | If `true`, the sha256 is verified on every preflight run, not only with `--deep`. |
| `provision` | string | Hint shown when the model is missing and not optional. |
| `when` | mapping | Same guard semantics as `python.when`. |

### env

A list of environment variable names. Checked for presence only (empty string counts as absent). Values are never read or logged.

```yaml
requirements:
  env:
    - ARTYSHIELD_API_KEY
```

---

## verify

`verify` is the outbound contract. It is enforced by `lib/workchain_verify.py` after `run.sh` exits 0, before the step's output becomes the next step's input. A component with no `verify` key is reported as "unverified" (tier `unverified`) and passes non-blockingly.

```yaml
verify:
  schema_version: "1.0"
  outputs:
    - name: primary_output
      assert: [exists, non_empty, audio_valid]
      json_has: [key1, key2]
  post_conditions:
    - id: my_check_id
      check: audio_lufs_within
      ...
```

### verify.outputs\[\]

Each entry names an output (by the same name used in `outputs.items[].name`) and declares structural assertions against it.

| Key | Type | Description |
|-----|------|-------------|
| `name` | string | Output name to check. Must match a registered output in context.json. |
| `assert` | list of strings | Structural assertions to run. |
| `json_has` | list of strings | Required top-level keys in a JSON output. Runs after `assert`. |

#### Structural assert primitives (STRUCTURAL dict)

| Assert name | What it checks |
|-------------|---------------|
| `exists` | Path is non-null and `os.path.exists(path)` is true. |
| `non_empty` | File is non-zero bytes; directory has at least one entry. |
| `audio_valid` | `ffprobe` reports at least one audio stream and a positive duration. Requires `ffprobe` on PATH. |
| `json_valid` | File can be parsed as JSON by `json.load`. |

#### json\_has

`json_has` takes a list of key names and fails if any key is absent from the JSON root object. It does not check values; use `json_fields_within` post-condition for value constraints.

### verify.post\_conditions\[\]

Post-conditions are component-level numeric or relational checks. Each entry is a mapping with at minimum:

| Key | Type | Description |
|-----|------|-------------|
| `id` | string | Identifier used in the verification report. Falls back to the `check` value if absent. |
| `check` | string | Name of the registered check function (see POST\_CHECKS below). |

Additional keys are specific to each check. The registered checks are:

---

#### audio\_lufs\_within

Re-measures the integrated LUFS of an audio output with `ffmpeg loudnorm` and fails if the measured value is more than `tolerance` LU from the target.

| Key | Default | Description |
|-----|---------|-------------|
| `output` | `"primary_output"` | Output name to measure. |
| `target_param` | `"target_lufs"` | Component param name that carries the target LUFS value. Resolved via the full precedence chain (recorded output metadata > step params > globals > schema default). |
| `tolerance` | `1.0` | Maximum allowed delta in LU (absolute value). |

---

#### audio\_format\_matches

Re-probes an audio output with `ffprobe` and confirms its sample rate, channel count, and/or bit depth match what the step was asked to produce. Fails if no format dimension resolves (empty contract proves nothing).

| Key | Default | Description |
|-----|---------|-------------|
| `output` | `"primary_output"` | Output name to probe. |
| `sample_rate_param` | — | Component param name that carries the target sample rate. Only asserted if the param resolves to a value. |
| `channels_param` | — | Component param name that carries the target channel count. |
| `bit_depth_param` | — | Component param name that carries the target bit depth. |

Bit depth is read from `bits_per_raw_sample` (authoritative for PCM), with fallback to sample format mapping for codecs that omit it.

---

#### audio\_duration\_matches

Metamorphic invariant: each listed audio output preserves the source file's duration within a tolerance. Intended for separation, denoise, and restoration components where there is no single correct output.

| Key | Default | Description |
|-----|---------|-------------|
| `outputs` | `"auto"` | Output name(s) to check. A string names one output; a list names several; `"auto"` resolves to all file-type outputs except `primary_output`. |
| `exclude` | `["primary_output"]` | Output names excluded from `auto` resolution. |
| `tolerance_s` (also `tolerance`) | `0.1` | Maximum allowed duration difference in seconds. |

Source duration is resolved from recorded output metadata, then from a JSON sidecar's `source_input` field, then from `context.json.input_file`.

---

#### stems\_recombine

Metamorphic relation for source separation: the stems must decompose the input such that their sum reconstructs the source within a residual level threshold.

| Key | Default | Description |
|-----|---------|-------------|
| `stems` | `"auto"` | Stem output names. Same resolution as `audio_duration_matches.outputs`. |
| `exclude` | `["primary_output"]` | Excluded from auto resolution. |
| `max_residual_db` | `-10.0` | The residual (source minus reconstructed mix) must sit at least this many dB below the source mean level. |

---

#### acoustic\_roundtrip

Decodes the output audio with the `audioqr` tool and requires the decoded text to match the source text the step was asked to encode. The decoder is resolved from `WORKCHAIN_AUDIOQR_BIN` env var or `audioqr` on PATH.

| Key | Default | Description |
|-----|---------|-------------|
| `output` | `"primary_output"` | Output name containing the encoded audio. |
| `target_param` | `"text"` | Component param name carrying the source text to recover. |

---

#### seed\_record\_verifies

Runs `lufs-seed verify` against the produced seed record and optionally against the source recording. The verifier is resolved from `WORKCHAIN_LUFS_SEED_BIN` env var or `lufs-seed` on PATH.

| Key | Default | Description |
|-----|---------|-------------|
| `output` | `"primary_output"` | Output name to verify. |
| `require_tier` | `"verified"` | Minimum tier the seed must reach: `"unverified"`, `"verified"`, or `"certified"`. |

---

#### embedding\_wellformed

Checks that a JSON embedding sidecar contains a real, usable vector: declared length, finite values, non-zero, and L2-normed (recomputed, not trusting the stored `l2norm`).

| Key | Default | Description |
|-----|---------|-------------|
| `output` | `"embedding"` | Output name to inspect. |
| `expect_dim` | — | Required vector dimensionality. If set, fails if the model changed embedding space. |
| `l2_tolerance` | `0.001` | Maximum allowed `|recomputed_norm - 1.0|`. |
| `require_served_by` | — | If set, the record's `served_by` field must equal this value. |

---

#### json\_fields\_within

Declarative value constraint check. Reads a JSON output and evaluates a list of constraint expressions against its fields. Fails on any violation; an empty `require` list fails rather than passing vacuously.

| Key | Default | Description |
|-----|---------|-------------|
| `output` | — (required) | Output name to inspect. |
| `require` | — (required) | List of constraint strings (see grammar below). A single string is also accepted. |

**Constraint grammar:**

Each constraint is a space-separated string of exactly three tokens: `FIELD OP VALUE`.

```
FIELD   ::= dotted.path.to.key    # supports nested JSON objects via dot-separated path
OP      ::= > | >= | < | <= | == | != | is | one_of
VALUE   ::= (depends on OP, see below)
```

Operators and their value forms:

| OP | VALUE | Semantics |
|----|-------|-----------|
| `>` `>=` `<` `<=` | numeric literal | Numeric comparison. The field must be a number. Null fields fail. |
| `==` `!=` | numeric literal or string | Numeric comparison if parseable as float; string comparison otherwise. |
| `is` | kind name | Type/emptiness check. See kinds below. |
| `one_of` | `A\|B\|C` | `str(field_value)` must be in the pipe-separated set. Pipe is used as separator so commas remain legal inside values. |

`is` kind names:

| Kind | Passes when |
|------|-------------|
| `number` | Value is int or float and not a boolean. |
| `string` | Value is a string. |
| `bool` | Value is a boolean. |
| `array` | Value is a list. |
| `object` | Value is a dict. |
| `non_empty` | Value is non-null; for strings, not blank; for lists/dicts, not empty. |
| `not_null` | Value is not None. |

An unparsable constraint is a failure, never a skip (fail-closed). A field absent from the record is a failure.

Example:

```yaml
verify:
  post_conditions:
    - id: probe_plausible
      check: json_fields_within
      output: probe_data
      require:
        - "duration_s > 0"
        - "samplerate >= 2000"
        - "codec is non_empty"
        - "decoder one_of ffmpeg|salvaged-riff"
        - "metadata.channels >= 1"
```

---

## Known Limitations and Parser Gotchas

The engine runs without PyYAML on a bare system. When PyYAML is unavailable, `workchain_yaml.py` uses a hand-written subset parser (`_MiniYAML`). The Bash validator uses `grep`-based field detection. The following divergences from standard YAML have been reproduced experimentally.

### 1. Block scalars (folded `>` and literal `|`) — stdlib parser silently corrupts the document

**Affected layer:** `_MiniYAML` (Python stdlib fallback). Not affected when PyYAML is installed. The Bash validator is unaffected but gives a false positive (see below).

**Symptom:** Any chain that uses a folded or literal block scalar — for example:

```yaml
# THIS FAILS on a bare system (no PyYAML)
name: my-chain
description: >
  A long description
  spanning multiple lines.
version: "1.0"
steps:
  - name: normalization
```

The `_MiniYAML` parser strips the indented continuation lines as comments or blank lines. The `description` key receives the bare `>` character as its value. The parser then sees `version:` and `steps:` at the correct indent level, so those keys ARE parsed correctly — but `python3 lib/workchain_yaml.py validate` still reports `Missing required field: version` and `Missing required field: steps`.

The error is misleading: the fields are present and syntactically valid, but the `_MiniYAML` parser consumed the block scalar marker `>` as the description value and then — on the engine-plan path — the resulting `data` dict does not pass the validator's `isinstance(data, dict)` check because of how the continuation lines are misinterpreted. The exact failure depends on the indentation structure.

**False positive in Bash validator:** `engine/chain-validator.sh` uses `grep -qE "^version:"` and `grep -qE "^steps:"` to check for required fields. These greps succeed regardless of block scalar usage, so the Bash validator reports "Chain validation passed" for a chain that the Python engine would reject.

**Fix:** Use single-line quoted strings for all `description` fields:

```yaml
description: "A long description spanning multiple lines."
```

This applies to chain files and `step.yaml` files alike.

### 2. YAML anchors (`&`) and aliases (`*`) — not supported by `_MiniYAML`

**Affected layer:** `_MiniYAML` (Python stdlib fallback). PyYAML handles these correctly.

`&anchor` is included verbatim as part of the scalar value. `*alias` is treated as a literal string, not dereferenced. A chain using anchors/aliases on a bare system will silently produce wrong parameter values — for example, `target_lufs: *tgt` becomes the string `"*tgt"` rather than the anchored value.

**Reproduced output:**

```json
{"globals": {"target_lufs": "&tgt -21"}, "steps": [{"params": {"target_lufs": "*tgt"}}]}
```

**Fix:** Do not use anchors or aliases. Repeat values explicitly.

### 3. Inline comments — not stripped by `_MiniYAML` or the Bash parser

**Affected layer:** Both `_MiniYAML` and `engine/yaml-parser.sh`.

A comment that appears after a value on the same line is included in the value string:

```yaml
name: my-chain  # inline comment
```

`_MiniYAML` parses `name` as `"my-chain  # inline comment"`. The Bash `yaml_get_value` function (`grep | sed`) has the same behaviour. Full-line comments (lines where the first non-whitespace character is `#`) are correctly stripped.

**Fix:** Put all comments on their own lines.

### 4. Multiline flow collections — not supported by `_MiniYAML`

**Affected layer:** `_MiniYAML` (Python stdlib fallback).

A flow sequence or mapping that spans multiple lines is not parsed correctly:

```yaml
# WRONG on bare system
params:
  checks: [
    "format",
    "loudness"
  ]
```

`_MiniYAML` sees `checks: [` as a value of `"["` and interprets `"format",` and `"loudness"` and `]` as additional map entries, producing a broken structure. Flow collections must open and close on the same line:

```yaml
# Correct
params:
  checks: ["format", "loudness"]
```

### 5. Colon in unquoted values — handled correctly (not a limitation)

`_MiniYAML`'s `_parse_map` splits on the **first** colon only (`content.partition(":")`), so `description: Audio: a description` correctly yields `description = "Audio: a description"`. This is safe. Only anchors and block scalars require workarounds.

### Summary table

| Feature | PyYAML | `_MiniYAML` (stdlib) | Bash `chain-validator.sh` |
|---------|--------|----------------------|---------------------------|
| Block scalars (`>`, `\|`) | Supported | **Silently broken** — misleading errors | **False positive** (passes incorrectly) |
| Anchors & aliases | Supported | **Silently wrong values** | Not applicable (field-presence only) |
| Inline comments | Stripped | **Included in value** | **Included in value** |
| Multiline flow `[...]` | Supported | **Broken** | Not applicable |
| Full-line comments | Stripped | Stripped | Not applicable |
| Tabs (converted to 2 spaces) | Handled | Handled | Not applicable |
| Unquoted values with colons | Correct | Correct | Not applicable |

---

## Annotated Working Example

The following example uses `chains/deliverable-voice.yaml` (a known-working chain) and `components/format_conversion/step.yaml` (a known-working component).

### Chain: chains/deliverable-voice.yaml

```yaml
name: "Deliverable: Voice / Dialogue"
description: "Prep a finished recording to a dialogue/VO spec: WAV, 48 kHz, 24-bit, true mono, -22 to -20 LUFS integrated, true peak below -3 dBFS. Conform first so loudness is measured on the audio that actually ships, then normalize, then audit against the spec."
version: "1.0"

globals:
  # -21 with a +/-1.0 LU tolerance covers the -22..-20 LUFS delivery window exactly.
  # This value is also available to normalization via the legacy 'lufs_target' alias.
  lufs_target: -21

steps:
  # Step 1: Convert and conform to the delivery format first.
  # The normalization step that follows will then see 48 kHz / 24-bit / mono,
  # so its LUFS measurement is made on audio that matches the final spec.
  - name: format_conversion
    enabled: true
    params:
      target_format: wav      # string; no default in schema — this is mandatory
      sample_rate: 48000      # number; verify: contract will re-probe and fail if missed
      bit_depth: 24           # number; same
      channels: 1             # number; 1 = true mono

  # Step 2: Normalize loudness.
  # Step params win over globals, so 'target_lufs: -21' here shadows 'lufs_target: -21'
  # from globals (they resolve to the same value; the step param is explicit for clarity).
  - name: normalization
    enabled: true
    params:
      target_lufs: -21
      two_pass: true
      lra: 7
      true_peak: -3.0

  # Step 3: Audit the finished file against the delivery spec.
  # 'checks' is a flow list — must be on one line (see Limitations, gotcha 4).
  - name: audio_benchmark
    enabled: true
    params:
      checks: ["format", "loudness", "dc_offset", "noise_floor", "phase", "dynamics"]
      expected_spec: "24/48000/1"
```

### Component: components/format\_conversion/step.yaml

```yaml
name: format_conversion
description: "Audio format conversion using FFmpeg (powered by audioconv-cli logic)"
version: "1.1"

type: audio

input_types:
  - wav
  - mp3
  - aiff
  - aif
  - flac
  - m4a
  - m4b
  - ogg
  - oga
  - opus
  - aac
  - wma
  - ac3
  - amr
  - au
  - caf
  - mka
  - spx
  - tta
  - wv

params_schema:
  target_format:
    type: string
    # No 'default' key — this param is mandatory. run.sh errors: "target_format parameter is required"
    description: "Target format: wav, flac, aiff, alac, tta, wv, mka (lossless) | mp3, m4a, ogg, opus, aac, wma, ac3, amr, spx (lossy)"
  preserve_quality:
    type: boolean
    default: true
    description: "Preserve sample rate, channels, bit depth (for lossless formats)"
  bitrate:
    type: string
    default: "320k"
    description: "Bitrate for lossy formats (e.g., 320k, 256k, 192k)"
  sample_rate:
    type: number
    # No default — omit to preserve source rate. Verifier only asserts this if it resolves.
    description: "Conform the output to this sample rate in Hz (e.g. 48000)."
    range:
      min: 8000
      max: 384000
  bit_depth:
    type: number
    description: "Conform the output to this bit depth (8, 16, 24, 32)."
    range:
      min: 8
      max: 32
  channels:
    type: number
    description: "Conform the output to this channel count (1 = true mono, 2 = stereo)."
    range:
      min: 1
      max: 8

outputs:
  schema_version: "1.0"
  description: "Converted audio file in target format"
  items:
    - name: primary_output
      type: file
      description: "Converted audio file"
      required: true
      mime_type: "audio/wav"
      # path_template is documentation only — run.sh constructs the actual path itself
      path_template: "{input_name}_converted.{target_format}"

requirements:
  commands:
    - ffmpeg
    - ffprobe

verify:
  schema_version: "1.0"
  outputs:
    - name: primary_output
      assert: [exists, non_empty, audio_valid]
      # No json_has — this is a file output, not JSON
  post_conditions:
    - id: output_conforms_to_requested_format
      check: audio_format_matches
      output: primary_output
      # Each *_param key names the component param that carries that dimension's target value.
      # A dimension whose param resolves to nothing is not asserted (component was asked to preserve it).
      # If none resolve, the check fails rather than passing vacuously.
      sample_rate_param: sample_rate
      bit_depth_param: bit_depth
      channels_param: channels
      description: "Re-probes the converted file and proves its sample rate, bit depth and channel count are the ones the step requested."
```

---

*The format is declared unencumbered; third-party implementations are welcome. Implementations should prefer the Python path (`lib/workchain_yaml.py`) as the authoritative parser specification. The Bash components are provided for runtime portability, not as the format reference.*
